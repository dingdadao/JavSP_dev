from javsp.config import Cfg, CrawlerID, UseJavDBCover
from javsp.web.exceptions import *
from javsp.web.base import download
from javsp.datatype import Movie, MovieInfo
from javsp.image import *
from javsp.func import *
from javsp.file import *
from javsp.lib import resource_path
from javsp.cropper import get_cropper
from tqdm import tqdm
import os
import re
import sys
import json
import time
import logging
from PIL import Image
import requests
import threading
from typing import Dict, List

logger = logging.getLogger('main')

# 全局锁，保护curl_cffi session的并发访问
download_lock = threading.Lock()

actressAliasMap = {}


def resolve_alias(name):
    """将别名解析为固定的名字"""
    for fixedName, aliases in actressAliasMap.items():
        if name in aliases:
            return fixedName
    return name


def load_actress_alias():
    """加载女优别名数据"""
    global actressAliasMap
    if Cfg().crawler.normalize_actress_name:
        actressAliasFilePath = resource_path("data/actress_alias.json")
        with open(actressAliasFilePath, "r", encoding="utf-8") as file:
            actressAliasMap = json.load(file)


def import_crawlers():
    """按配置文件的抓取器顺序将该字段转换为抓取器的函数列表"""
    unknown_mods = []
    for _, mods in Cfg().crawler.selection.items():
        valid_mods = []
        for name in mods:
            try:
                import_name = 'javsp.web.' + name
                __import__(import_name)
                valid_mods.append(import_name)
            except ModuleNotFoundError:
                unknown_mods.append(name)
    if unknown_mods:
        logger.warning('配置的抓取器无效: ' + ', '.join(unknown_mods))


def parallel_crawler(movie: Movie, tqdm_bar=None):
    """使用多线程抓取不同网站的数据"""
    def wrapper(parser, info: MovieInfo, retry):
        """对抓取器函数进行包装，便于更新提示信息和自动重试"""
        crawler_name = threading.current_thread().name
        for cnt in range(retry):
            try:
                parser(info)
                movie_id = info.dvdid or info.cid
                logger.debug(
                    f"{crawler_name}: 抓取成功: '{movie_id}': '{info.url}'")
                setattr(info, 'success', True)
                if isinstance(tqdm_bar, tqdm):
                    tqdm_bar.set_description(f'{crawler_name}: 抓取完成')
                break
            except MovieNotFoundError as e:
                logger.debug(e)
                break
            except MovieDuplicateError as e:
                logger.error(f"{crawler_name}: {str(e)}")
                break
            except (SiteBlocked, SitePermissionError, CredentialError) as e:
                logger.error(f"{crawler_name}: {str(e)}")
                break
            except requests.exceptions.RequestException as e:
                logger.debug(
                    f'{crawler_name}: 网络错误，正在重试 ({cnt+1}/{retry}): \n{repr(e)}')
                if isinstance(tqdm_bar, tqdm):
                    tqdm_bar.set_description(f'{crawler_name}: 网络错误，正在重试')
            except Exception as e:
                logger.debug(f"{crawler_name}: 发生异常: {str(e)}")

    # 根据影片的数据源获取对应的抓取器
    crawler_mods: List[CrawlerID] = Cfg().crawler.selection[movie.data_src]

    all_info = {i.value: MovieInfo(movie) for i in crawler_mods}
    # 番号为cid但同时也有有效的dvdid时，也尝试使用普通模式进行抓取
    if movie.data_src == 'cid' and movie.dvdid:
        crawler_mods = crawler_mods + Cfg().crawler.selection.normal
        for i in all_info.values():
            i.dvdid = None
        for i in Cfg().crawler.selection.normal:
            all_info[i.value] = MovieInfo(movie.dvdid)
    thread_pool = []
    for mod_partial, info in all_info.items():
        mod = f"javsp.web.{mod_partial}"
        parser = getattr(sys.modules[mod], 'parse_data')
        if hasattr(sys.modules[mod], 'parse_data_raw'):
            th = threading.Thread(target=wrapper, name=mod,
                                  args=(parser, info, 1))
        else:
            th = threading.Thread(target=wrapper, name=mod, args=(
                parser, info, Cfg().network.retry))
        th.start()
        thread_pool.append(th)
    # 等待所有线程结束
    timeout = Cfg().network.retry * Cfg().network.timeout.total_seconds()
    for th in thread_pool:
        th: threading.Thread
        th.join(timeout=timeout)
    # 根据抓取结果更新影片类型判定
    if movie.data_src == 'cid' and movie.dvdid:
        titles = [all_info[i].title for i in Cfg(
        ).crawler.selection[movie.data_src]]
        if any(titles):
            movie.dvdid = None
            all_info = {k: v for k, v in all_info.items(
            ) if k in Cfg().crawler.selection['cid']}
        else:
            logger.debug(f'自动更正影片数据源类型: {movie.dvdid} ({movie.cid}): normal')
            movie.data_src = 'normal'
            movie.cid = None
            all_info = {k: v for k, v in all_info.items(
            ) if k not in Cfg().crawler.selection['cid']}
    # 删除抓取失败的站点对应的数据
    all_info = {k: v for k, v in all_info.items() if hasattr(v, 'success')}
    for info in all_info.values():
        del info.success
    # 删除all_info中键名中的'web.'
    all_info = {k[4:]: v for k, v in all_info.items()}
    return all_info


def info_summary(movie: Movie, all_info: Dict[str, MovieInfo]):
    """汇总多个来源的在线数据生成最终数据"""
    if not all_info:
        logger.error("没有找到任何来源的数据")
        return False

    final_info = MovieInfo(movie)
    ########## 部分字段配置了专门的选取逻辑，先处理这些字段 ##########
    # genre
    if 'javdb' in all_info and all_info['javdb'].genre:
        final_info.genre = all_info['javdb'].genre

    ########## 移除所有抓取器数据中，标题尾部的女优名 ##########
    if Cfg().summarizer.title.remove_trailing_actor_name:
        for name, data in all_info.items():
            data.title = remove_trail_actor_in_title(data.title, data.actress)

    ########## 然后检查所有字段，如果某个字段还是默认值，则按照优先级选取数据 ##########
    attrs = [i for i in dir(final_info) if not i.startswith('_')]
    covers, big_covers = [], []

    # 遍历并吸收各个来源的数据
    for name, data in all_info.items():
        absorbed = []
        for attr in attrs:
            incoming = getattr(data, attr)
            current = getattr(final_info, attr)

            if attr == 'cover' or attr == 'big_cover':
                target_list = covers if attr == 'cover' else big_covers
                if incoming and (incoming not in target_list):
                    target_list.append(incoming)
                    absorbed.append(attr)
            elif attr == 'uncensored':
                if current is None and incoming is not None:
                    setattr(final_info, attr, incoming)
                    absorbed.append(attr)
            elif attr == 'plot':
                if incoming and (not current or len(incoming) > len(current)):
                    logger.debug(f"从'{name}'获取简介: {incoming[:50]}...")
                    setattr(final_info, attr, incoming)
                    absorbed.append(attr)
                elif incoming:
                    logger.debug(f"'{name}'有简介但已存在更长的，跳过")
            else:
                if not current and incoming:
                    setattr(final_info, attr, incoming)
                    absorbed.append(attr)

        if absorbed:
            logger.debug(f"从'{name}'中获取了字段: " + ' '.join(absorbed))

    ########## 使用网站的番号作为最终番号 ##########
    if Cfg().crawler.respect_site_avid:
        id_weight = {}
        for name, data in all_info.items():
            id_key = data.dvdid if data.dvdid else data.cid
            if id_key:
                id_weight.setdefault(id_key, []).append(name)

        if id_weight:
            sorted_id_weight = {k: v for k, v in sorted(
                id_weight.items(), key=lambda x: len(x[1]), reverse=True)}
            final_id = list(sorted_id_weight.keys())[0]
            if movie.dvdid:
                final_info.dvdid = final_id
            else:
                final_info.cid = final_id

    ########## 优先处理 javdb 的封面 ##########
    javdb_cover = getattr(all_info.get('javdb'), 'cover', None)
    if javdb_cover is not None:
        use_javdb_cover_setting = Cfg().crawler.use_javdb_cover
        if use_javdb_cover_setting == UseJavDBCover.fallback:
            if javdb_cover not in covers:
                covers.append(javdb_cover)
        elif use_javdb_cover_setting == UseJavDBCover.no:
            if javdb_cover in covers:
                covers.remove(javdb_cover)

    setattr(final_info, 'covers', covers)
    setattr(final_info, 'big_covers', big_covers)

    if covers:
        final_info.cover = covers[0]
    if big_covers:
        final_info.big_cover = big_covers[0]

    ########## 特殊的 genre 处理 ##########
    if final_info.genre is None:
        final_info.genre = []
    if movie.hard_sub:
        final_info.genre.append('内嵌字幕')
    if movie.uncensored:
        final_info.genre.append('无码流出/破解')

    ########## 女优别名处理 ##########
    if Cfg().crawler.normalize_actress_name and final_info.actress_pics:
        final_info.actress = [resolve_alias(i) for i in final_info.actress]
        if final_info.actress_pics:
            final_info.actress_pics = {
                resolve_alias(key): value for key, value in final_info.actress_pics.items()
            }

    ########## 检查必需字段 ##########
    for attr in Cfg().crawler.required_keys:
        if not getattr(final_info, attr, None):
            logger.error(f"所有抓取器均未获取到字段: '{attr}'，抓取失败")
            return False

    ########## 将最终数据附加到电影对象 ##########
    movie.info = final_info

    if final_info.plot:
        logger.debug(f"最终简介: {final_info.plot[:50]}...")
    else:
        logger.debug("最终简介为空")

    return True


def generate_names(movie: Movie):
    """按照模板生成相关文件的文件名"""

    def legalize_path(path: str):
        return ''.join(c for c in path if c not in {'\n'})

    info = movie.info
    d = info.get_info_dic()

    if info.actress and len(info.actress) > Cfg().summarizer.path.max_actress_count:
        logging.debug('女优人数过多，按配置保留了其中的前n个: ' + ','.join(info.actress))
        actress = info.actress[:Cfg(
        ).summarizer.path.max_actress_count] + ['…']
    else:
        actress = info.actress
    d['actress'] = ','.join(
        actress) if actress else Cfg().summarizer.default.actress

    setattr(info, 'label', d['label'].upper())
    for k, v in d.items():
        d[k] = replace_illegal_chars(v.strip())

    nfo_title = Cfg().summarizer.nfo.title_pattern.format(**d)
    setattr(info, 'nfo_title', nfo_title)

    cdx = '' if len(movie.files) <= 1 else '-CD1'
    if hasattr(info, 'title_break'):
        title_break = info.title_break
    else:
        title_break = split_by_punc(d['title'])
    if hasattr(info, 'ori_title_break'):
        ori_title_break = info.ori_title_break
    else:
        ori_title_break = split_by_punc(d['rawtitle'])
    copyd = d.copy()

    def legalize_info():
        if movie.save_dir != None:
            movie.save_dir = legalize_path(movie.save_dir)
        if movie.nfo_file != None:
            movie.nfo_file = legalize_path(movie.nfo_file)
        if movie.fanart_file != None:
            movie.fanart_file = legalize_path(movie.fanart_file)
        if movie.poster_file != None:
            movie.poster_file = legalize_path(movie.poster_file)
        if d['title'] != copyd['title']:
            logger.info(f"自动截短标题为:\n{copyd['title']}")
        if d['rawtitle'] != copyd['rawtitle']:
            logger.info(f"自动截短原始标题为:\n{copyd['rawtitle']}")
        return

    copyd['num'] = copyd['num'] + movie.attr_str
    longest_ext = max((os.path.splitext(i)[1] for i in movie.files), key=len)

    file_basename_pattern = Cfg().summarizer.path.file_basename_pattern or Cfg().summarizer.path.basename_pattern

    # 飞牛 NAS 兼容模式：图片必须命名为 {视频同名}-poster / {视频同名}-fanart
    fnos_mode = Cfg().summarizer.nfo.fnos_compatible
    
    for end in range(len(ori_title_break), 0, -1):
        copyd['rawtitle'] = replace_illegal_chars(
            ''.join(ori_title_break[:end]).strip())
        for sub_end in range(len(title_break), 0, -1):
            copyd['title'] = replace_illegal_chars(
                ''.join(title_break[:sub_end]).strip())
            if Cfg().summarizer.move_files:
                save_dir = os.path.normpath(
                    Cfg().summarizer.path.output_folder_pattern.format(**copyd)).strip()
                file_basename = os.path.normpath(
                    file_basename_pattern.format(**copyd)).strip()
                basename = os.path.normpath(
                    Cfg().summarizer.path.basename_pattern.format(**copyd)).strip()
            else:
                save_dir = os.path.dirname(movie.files[0])
                filebasename = os.path.basename(movie.files[0])
                ext = os.path.splitext(filebasename)[1]
                file_basename = filebasename.replace(ext, '')
                basename = file_basename
            long_path = os.path.join(save_dir, file_basename+longest_ext)
            remaining = get_remaining_path_len(os.path.abspath(long_path))
            if remaining > 0:
                movie.save_dir = save_dir
                movie.basename = file_basename
                movie.nfo_file = os.path.join(
                    save_dir, file_basename + '.nfo')
                if fnos_mode:
                    movie.fanart_file = os.path.join(save_dir, file_basename + '-fanart.jpg')
                    movie.poster_file = os.path.join(save_dir, file_basename + '-poster.jpg')
                else:
                    movie.fanart_file = os.path.join(
                        save_dir, Cfg().summarizer.fanart.basename_pattern.format(**copyd) + '.jpg')
                    movie.poster_file = os.path.join(
                        save_dir, Cfg().summarizer.cover.basename_pattern.format(**copyd) + '.jpg')
                return legalize_info()
    else:
        copyd['title'] = copyd['title'][:remaining]
        copyd['rawtitle'] = copyd['rawtitle'][:remaining]
        if not Cfg().summarizer.move_files:
            save_dir = os.path.dirname(movie.files[0])
            filebasename = os.path.basename(movie.files[0])
            ext = os.path.splitext(filebasename)[1]
            file_basename = filebasename.replace(ext, '')
            basename = file_basename
        else:
            save_dir = os.path.normpath(
                Cfg().summarizer.path.output_folder_pattern.format(**copyd)).strip()
            file_basename = os.path.normpath(
                file_basename_pattern.format(**copyd)).strip()
            basename = os.path.normpath(
                Cfg().summarizer.path.basename_pattern.format(**copyd)).strip()
        movie.save_dir = save_dir
        movie.basename = file_basename

        movie.nfo_file = os.path.join(
            save_dir, file_basename + '.nfo')
        if fnos_mode:
            movie.fanart_file = os.path.join(save_dir, file_basename + '-fanart.jpg')
            movie.poster_file = os.path.join(save_dir, file_basename + '-poster.jpg')
        else:
            movie.fanart_file = os.path.join(
                save_dir, Cfg().summarizer.fanart.basename_pattern.format(**copyd) + '.jpg')
            movie.poster_file = os.path.join(
                save_dir, Cfg().summarizer.cover.basename_pattern.format(**copyd) + '.jpg')

        return legalize_info()


SUBTITLE_MARK_FILE = Image.open(
    os.path.abspath(resource_path('image/sub_mark.png')))
UNCENSORED_MARK_FILE = Image.open(
    os.path.abspath(resource_path('image/unc_mark.png')))


def process_poster(movie: Movie):
    def should_use_ai_crop_match(label):
        for r in Cfg().summarizer.cover.crop.on_id_pattern:
            if re.match(r, label):
                return True
        return False
    crop_engine = None
    if (movie.info.uncensored or
       movie.data_src == 'fc2' or
       (movie.dvdid and should_use_ai_crop_match(movie.dvdid.upper()))):
        crop_engine = Cfg().summarizer.cover.crop.engine
    cropper = get_cropper(crop_engine)
    fanart_image = Image.open(movie.fanart_file)
    fanart_cropped = cropper.crop(fanart_image)

    if Cfg().summarizer.cover.add_label:
        if movie.hard_sub:
            fanart_cropped = add_label_to_poster(
                fanart_cropped, SUBTITLE_MARK_FILE, LabelPostion.BOTTOM_RIGHT)
        if movie.uncensored:
            fanart_cropped = add_label_to_poster(
                fanart_cropped, UNCENSORED_MARK_FILE, LabelPostion.BOTTOM_LEFT)
    fanart_cropped.save(movie.poster_file)


def download_cover(covers, fanart_path, big_covers=[]):
    """下载封面图片"""
    # 优先下载高清封面
    for url in big_covers:
        pic_path = get_pic_path(fanart_path, url)
        for _ in range(Cfg().network.retry):
            try:
                info = download(url, pic_path)
                if valid_pic(pic_path):
                    filesize = get_fmt_size(pic_path)
                    width, height = get_pic_size(pic_path)
                    elapsed = time.strftime(
                        "%M:%S", time.gmtime(info['elapsed']))
                    speed = get_fmt_size(info['rate']) + '/s'
                    logger.info(
                        f"已下载高清封面: {width}x{height}, {filesize} [{elapsed}, {speed}]")
                    return (url, pic_path)
            except requests.exceptions.HTTPError:
                break
    # 如果没有高清封面或高清封面下载失败
    for url in covers:
        pic_path = get_pic_path(fanart_path, url)
        for _ in range(Cfg().network.retry):
            try:
                download(url, pic_path)
                if valid_pic(pic_path):
                    logger.debug(f"已下载封面: '{url}'")
                    return (url, pic_path)
                else:
                    logger.debug(f"图片无效或已损坏: '{url}'，尝试更换下载地址")
                    break
            except Exception as e:
                logger.debug(e, exc_info=True)
    logger.error(f"下载封面图片失败")
    logger.debug('big_covers:'+str(big_covers) + ', covers'+str(covers))
    return None


def get_pic_path(fanart_path, url):
    fanart_base = os.path.splitext(fanart_path)[0]
    pic_extend = url.split('.')[-1]
    if '?' in pic_extend:
        pic_extend = pic_extend.split('?')[0]

    pic_path = fanart_base + "." + pic_extend
    return pic_path


def error_exit(success, err_info):
    """检查业务逻辑是否成功完成，如果失败则报错退出程序"""
    if not success:
        logger.error(err_info)
        sys.exit(1)


def download_extrafanart_concurrent(movie, extrafanartdir, progress_bar):
    """并发下载extrafanart图片"""
    import concurrent.futures

    concurrent_downloads = Cfg().summarizer.extra_fanarts.concurrent_downloads
    max_download_count = Cfg().summarizer.extra_fanarts.max_download_count

    def download_single_image(args):
        id, pic_url = args
        fanart_destination = f"{extrafanartdir}/{id}.png"

        try:
            if progress_bar is not None:
                progress_bar.set_description(
                    f"Downloading extrafanart {id} from url: {pic_url}")

            with download_lock:
                info = download(pic_url, fanart_destination)
            if valid_pic(fanart_destination):
                filesize = get_fmt_size(fanart_destination)
                width, height = get_pic_size(fanart_destination)
                elapsed = time.strftime("%M:%S", time.gmtime(info['elapsed']))
                speed = get_fmt_size(info['rate']) + '/s'
                logger.info(
                    f"已下载剧照{pic_url} {id}.png: {width}x{height}, {filesize} [{elapsed}, {speed}]")
                return (id, True, None)
            else:
                return (id, False, f"图片无效或已损坏: {pic_url}")
        except Exception as e:
            return (id, False, f"下载失败: {str(e)}")

    # 准备下载任务，根据max_download_count限制数量
    if max_download_count > 0:
        download_tasks = [(id, pic_url)
                          for id, pic_url in enumerate(movie.info.preview_pics[:max_download_count])]
        logger.info(f"限制下载前{max_download_count}张剧照")
    else:
        download_tasks = [(id, pic_url)
                          for id, pic_url in enumerate(movie.info.preview_pics)]

    logger.info(f"开始并发下载，最大并发数: {concurrent_downloads}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_downloads) as executor:
        future_to_id = {executor.submit(download_single_image, task): task[0]
                        for task in download_tasks}

        completed_count = 0
        for future in concurrent.futures.as_completed(future_to_id):
            id = future_to_id[future]
            try:
                result_id, success, error_msg = future.result()
                if success:
                    completed_count += 1
                else:
                    logger.error(f"下载剧照{id}失败: {error_msg}")
            except Exception as e:
                logger.error(f"处理下载结果时出错: {e}")

        logger.info(f"并发下载完成，成功下载 {completed_count}/{len(download_tasks)} 张剧照")
