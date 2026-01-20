"""爬虫管理器 - 负责并发抓取和数据汇总"""
import sys
import threading
import logging
from typing import Dict, List
from tqdm import tqdm
import requests

from javsp.datatype import Movie, MovieInfo
from javsp.web.exceptions import *
from javsp.config import Cfg, CrawlerID
from javsp.web.base import set_ssl_verification

logger = logging.getLogger(__name__)


class CrawlerManager:
    """管理多线程爬虫抓取和数据汇总"""

    def __init__(self):
        self.config = Cfg()

    def parallel_crawler(self, movie: Movie, tqdm_bar=None) -> Dict[str, MovieInfo]:
        """使用多线程抓取不同网站的数据"""
        def wrapper(parser, info: MovieInfo, retry):
            """对抓取器函数进行包装，便于更新提示信息和自动重试"""
            crawler_name = threading.current_thread().name
            task_info = f'Crawler: {crawler_name}: {info.dvdid}'

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
                    logger.exception(e)
                    break
                except (SiteBlocked, SitePermissionError, CredentialError) as e:
                    logger.error(e)
                    break
                except requests.exceptions.SSLError as e:
                    logger.warning(f'{crawler_name}: SSL证书验证失败: {repr(e)}')
                    # 检查是否是特定的SSL错误类型
                    error_msg = str(e).lower()
                    if cnt == 0 and ('eof occurred in violation of protocol' in error_msg or 'ssl' in error_msg):
                        # 第一次失败时尝试关闭SSL验证
                        logger.info(f'{crawler_name}: 尝试关闭SSL验证重新连接')
                        set_ssl_verification(False)
                    logger.debug(
                        f'{crawler_name}: SSL错误，正在重试 ({cnt+1}/{retry}): \n{repr(e)}')
                    if isinstance(tqdm_bar, tqdm):
                        tqdm_bar.set_description(f'{crawler_name}: SSL错误，正在重试')
                except requests.exceptions.ConnectionError as e:
                    logger.warning(f'{crawler_name}: 连接错误: {repr(e)}')
                    logger.debug(
                        f'{crawler_name}: 连接错误，正在重试 ({cnt+1}/{retry}): \n{repr(e)}')
                    if isinstance(tqdm_bar, tqdm):
                        tqdm_bar.set_description(f'{crawler_name}: 连接错误，正在重试')
                except requests.exceptions.RequestException as e:
                    logger.debug(
                        f'{crawler_name}: 网络错误，正在重试 ({cnt+1}/{retry}): \n{repr(e)}')
                    if isinstance(tqdm_bar, tqdm):
                        tqdm_bar.set_description(f'{crawler_name}: 网络错误，正在重试')
                except Exception as e:
                    logger.exception(e)
            else:
                # 如果所有重试都失败，恢复SSL验证设置
                if retry > 0:
                    set_ssl_verification(True)  # 恢复SSL验证设置

        # 根据影片的数据源获取对应的抓取器
        crawler_mods: List[CrawlerID] = self.config.crawler.selection[movie.data_src]

        all_info = {i.value: MovieInfo(movie) for i in crawler_mods}

        # 番号为cid但同时也有有效的dvdid时，也尝试使用普通模式进行抓取
        if movie.data_src == 'cid' and movie.dvdid:
            crawler_mods = crawler_mods + self.config.crawler.selection.normal
            for i in all_info.values():
                i.dvdid = None
            for i in self.config.crawler.selection.normal:
                all_info[i.value] = MovieInfo(movie.dvdid)

        thread_pool = []
        for mod_partial, info in all_info.items():
            mod = f"javsp.web.{mod_partial}"
            parser = getattr(sys.modules[mod], 'parse_data')

            # 抓取器如果带有parse_data_raw，说明它已经自行进行了重试处理
            if hasattr(sys.modules[mod], 'parse_data_raw'):
                th = threading.Thread(
                    target=wrapper, name=mod, args=(parser, info, 1))
            else:
                th = threading.Thread(target=wrapper, name=mod, args=(
                    parser, info, self.config.network.retry))
            th.start()
            thread_pool.append(th)

        # 等待所有线程结束
        timeout = self.config.network.retry * self.config.network.timeout.total_seconds()
        for th in thread_pool:
            th: threading.Thread
            th.join(timeout=timeout)

        # 根据抓取结果更新影片类型判定
        if movie.data_src == 'cid' and movie.dvdid:
            titles = [
                all_info[i].title for i in self.config.crawler.selection[movie.data_src]]
            if any(titles):
                movie.dvdid = None
                all_info = {k: v for k, v in all_info.items(
                ) if k in self.config.crawler.selection['cid']}
            else:
                logger.debug(
                    f'自动更正影片数据源类型: {movie.dvdid} ({movie.cid}): normal')
                movie.data_src = 'normal'
                movie.cid = None
                all_info = {k: v for k, v in all_info.items(
                ) if k not in self.config.crawler.selection['cid']}

        # 删除抓取失败的站点对应的数据
        all_info = {k: v for k, v in all_info.items() if hasattr(v, 'success')}
        for info in all_info.values():
            del info.success

        # 删除all_info中键名中的'web.'
        all_info = {k[4:]: v for k, v in all_info.items()}
        return all_info

    def summarize_info(self, movie: Movie, all_info: Dict[str, MovieInfo]) -> bool:
        """汇总多个来源的在线数据生成最终数据"""
        if not all_info:
            logger.error("没有找到任何来源的数据")
            return False

        final_info = MovieInfo(movie)

        # 部分字段配置了专门的选取逻辑，先处理这些字段
        if 'javdb' in all_info and all_info['javdb'].genre:
            final_info.genre = all_info['javdb'].genre

        # 移除所有抓取器数据中，标题尾部的女优名
        if self.config.summarizer.title.remove_trailing_actor_name:
            for name, data in all_info.items():
                data.title = self._remove_trail_actor_in_title(
                    data.title, data.actress)

        # 然后检查所有字段，如果某个字段还是默认值，则按照优先级选取数据
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
                else:
                    if not current and incoming:
                        setattr(final_info, attr, incoming)
                        absorbed.append(attr)

            if absorbed:
                logger.debug(f"从'{name}'中获取了字段: " + ' '.join(absorbed))

        # 使用网站的番号作为最终番号
        if self.config.crawler.respect_site_avid:
            id_weight = {}
            for name, data in all_info.items():
                id_key = data.dvdid if data.dvdid else data.cid
                if id_key:
                    id_weight.setdefault(id_key, []).append(name)

            # 根据权重选择最终番号
            if id_weight:
                sorted_id_weight = {k: v for k, v in sorted(
                    id_weight.items(), key=lambda x: len(x[1]), reverse=True)}
                final_id = list(sorted_id_weight.keys())[0]
                if movie.dvdid:
                    final_info.dvdid = final_id
                else:
                    final_info.cid = final_id

        # 优先处理 javdb 的封面
        javdb_cover = getattr(all_info.get('javdb'), 'cover', None)
        if javdb_cover is not None:
            use_javdb_cover_setting = self.config.crawler.use_javdb_cover
            if use_javdb_cover_setting == 'fallback':
                if javdb_cover not in covers:
                    covers.append(javdb_cover)
            elif use_javdb_cover_setting == 'no':
                if javdb_cover in covers:
                    covers.remove(javdb_cover)

        setattr(final_info, 'covers', covers)
        setattr(final_info, 'big_covers', big_covers)

        # 对cover和big_cover赋值，避免后续检查必须字段时出错
        if covers:
            final_info.cover = covers[0]
        if big_covers:
            final_info.big_cover = big_covers[0]

        # 特殊的 genre 处理
        if final_info.genre is None:
            final_info.genre = []
        if movie.hard_sub:
            final_info.genre.append('内嵌字幕')
        if movie.uncensored:
            final_info.genre.append('无码流出/破解')

        # 检查必需字段
        for attr in self.config.crawler.required_keys:
            if not getattr(final_info, attr, None):
                logger.error(f"所有抓取器均未获取到字段: '{attr}'，抓取失败")
                return False

        # 将最终数据附加到电影对象
        movie.info = final_info
        return True

    def _remove_trail_actor_in_title(self, title: str, actress: List[str]) -> str:
        """移除标题尾部的女优名"""
        if not title or not actress:
            return title

        for actor in actress:
            if title.endswith(actor):
                title = title[:-len(actor)].rstrip()
                break
        return title
