"""刮削任务执行器 - 将现有刮削逻辑封装为异步任务"""

import os
import sys
import json
import time
import shutil
import logging
import threading
from pathlib import Path
from typing import List

from javsp.webapp.database import (
    create_task, update_task, add_task_item, update_task_item,
    get_config, add_log
)

logger = logging.getLogger('javsp.webapp.scraper')

# 全局停止信号
_stop_event = threading.Event()


def request_stop():
    """请求停止当前刮削任务"""
    _stop_event.set()


def clear_stop():
    """清除停止信号（新任务开始前调用）"""
    _stop_event.clear()


def is_stop_requested() -> bool:
    return _stop_event.is_set()


def _override(obj, attr, value):
    """绕过 pydantic frozen 限制设置属性"""
    object.__setattr__(obj, attr, value)


def apply_web_config():
    """从数据库读取 Web 配置，覆盖 Cfg() 中对应的值"""
    from javsp.config import Cfg, CrawlerID
    cfg = Cfg()
    db_config = get_config()

    # 爬虫列表
    crawler_cfg = db_config.get('crawler', {})
    if 'selection_normal' in crawler_cfg:
        _override(cfg.crawler.selection, 'normal', [CrawlerID(c) for c in crawler_cfg['selection_normal']])
    if 'selection_fc2' in crawler_cfg:
        _override(cfg.crawler.selection, 'fc2', [CrawlerID(c) for c in crawler_cfg['selection_fc2']])

    # 爬虫镜像地址
    network_cfg = db_config.get('network', {})
    if 'crawler_mirror' in network_cfg and isinstance(network_cfg['crawler_mirror'], dict):
        _override(cfg.network, 'crawler_mirror', {CrawlerID(k): v for k, v in network_cfg['crawler_mirror'].items()})

    # 翻译设置
    translator_cfg = db_config.get('translator', {})
    if 'engine' in translator_cfg:
        engine_name = translator_cfg['engine']
        if not engine_name:
            _override(cfg.translator, 'engine', None)
    if 'translate_title' in translator_cfg:
        _override(cfg.translator.fields, 'title', bool(translator_cfg['translate_title']))
    if 'translate_plot' in translator_cfg:
        _override(cfg.translator.fields, 'plot', bool(translator_cfg['translate_plot']))

    logger.debug(f"Web 配置已应用: 爬虫列表={[c.value for c in cfg.crawler.selection.normal]}")


def run_scrape_task(task_id: str, source: str, dest: str,
                    translate: bool, move_files: bool, socketio):
    """异步执行刮削任务，通过 SocketIO 实时推送进度"""
    from javsp.datatype import Movie, MovieInfo
    from javsp.web.base import close_global_session
    from javsp.web.translate import translate_movie_info
    from javsp.file import scan_movies, replace_illegal_chars
    from javsp.nfo import write_nfo
    from javsp import __main__ as main_module
    # 应用 Web 配置覆盖 Cfg()
    apply_web_config()
    main_module.import_crawlers()

    def emit_progress(data):
        """推送实时进度到前端"""
        try:
            socketio.emit('scrape_progress', data, namespace='/')
        except Exception as e:
            logger.debug(f"SocketIO 推送失败: {e}")

    try:
        clear_stop()

        # 扫描影片文件
        emit_progress({'task_id': task_id, 'status': 'scanning', 'message': '正在扫描影片文件...'})
        movies = scan_movies(source)

        if not movies:
            update_task(task_id, status='failed', finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
            emit_progress({'task_id': task_id, 'status': 'failed', 'message': '未找到影片文件'})
            add_log('WARNING', 'scraper', f'任务 {task_id[:8]}: 未找到影片文件')
            return

        total = len(movies)
        update_task(task_id, status='running', completed=0)
        # 这里需要更新 total（create_task 时传的是 0，现在知道了实际数量）
        from javsp.webapp.database import get_db
        with get_db() as conn:
            conn.execute("UPDATE tasks SET total = ? WHERE id = ?", (total, task_id))

        add_log('INFO', 'scraper', f'任务 {task_id[:8]}: 找到 {total} 部影片')
        emit_progress({
            'task_id': task_id, 'status': 'running',
            'total': total, 'completed': 0, 'message': f'找到 {total} 部影片，开始刮削...'
        })

        success_count = 0
        failed_count = 0

        for idx, movie in enumerate(movies):
            # 检查是否收到停止信号
            if is_stop_requested():
                logger.info(f"任务 {task_id[:8]}: 收到停止请求，中断刮削")
                update_task(task_id, status='stopped', finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                emit_progress({
                    'task_id': task_id, 'status': 'stopped',
                    'total': total, 'completed': idx,
                    'success': success_count, 'failed': failed_count,
                    'message': f'任务已停止: 已完成 {idx}/{total}'
                })
                add_log('INFO', 'scraper', f'任务 {task_id[:8]}: 用户停止，已完成 {idx}/{total}')
                return

            dvdid = movie.dvdid or movie.cid or f'unknown_{idx}'
            item_id = add_task_item(task_id, dvdid, movie.files[0] if movie.files else '')

            emit_progress({
                'task_id': task_id, 'status': 'running',
                'total': total, 'completed': idx,
                'current': dvdid, 'message': f'正在刮削: {dvdid}'
            })

            try:
                result = _scrape_single(movie, translate, dest, move_files, main_module)

                if result['success']:
                    update_task_item(item_id, status='success', dest_path=result['dest_path'],
                                     scraped_data=result.get('data'), finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                    success_count += 1
                else:
                    update_task_item(item_id, status='failed', message=result['message'],
                                     finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                    failed_count += 1

            except Exception as e:
                logger.exception(f"刮削 {dvdid} 异常")
                update_task_item(item_id, status='failed', message=str(e),
                                 finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                failed_count += 1

            completed = idx + 1
            update_task(task_id, completed=completed, success_count=success_count, failed_count=failed_count)
            emit_progress({
                'task_id': task_id, 'status': 'running',
                'total': total, 'completed': completed,
                'success': success_count, 'failed': failed_count,
                'current': dvdid,
                'message': f'进度: {completed}/{total} (成功:{success_count} 失败:{failed_count})'
            })

        # 标记任务完成
        final_status = 'completed' if failed_count == 0 else ('partial' if success_count > 0 else 'failed')
        update_task(task_id, status=final_status, finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))

        emit_progress({
            'task_id': task_id, 'status': final_status,
            'total': total, 'completed': total,
            'success': success_count, 'failed': failed_count,
            'message': f'任务完成: 成功 {success_count}/{total}, 失败 {failed_count}/{total}'
        })

        add_log('INFO', 'scraper',
                f'任务 {task_id[:8]} 完成: 成功 {success_count}, 失败 {failed_count}')

        # 清理全局会话
        try:
            close_global_session()
        except Exception:
            pass

    except Exception as e:
        logger.exception("刮削任务执行异常")
        update_task(task_id, status='error', finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
        emit_progress({'task_id': task_id, 'status': 'error', 'message': f'任务异常: {str(e)}'})
        add_log('ERROR', 'scraper', f'任务 {task_id[:8]} 异常: {str(e)}')


def _scrape_single(movie, translate: bool, dest_path: str, move_files: bool, main_module) -> dict:
    """刮削单部影片，复用 __main__ 中的核心逻辑"""
    from javsp.datatype import MovieInfo
    from javsp.web.translate import translate_movie_info
    from javsp.config import Cfg
    from javsp.file import replace_illegal_chars
    from javsp.nfo import write_nfo

    result = {
        'dvdid': movie.dvdid or movie.cid,
        'success': False,
        'message': '',
        'dest_path': None,
        'data': None
    }

    try:
        # 并行抓取数据
        all_info = main_module.parallel_crawler(movie)
        if not all_info:
            result['message'] = '无法获取影片信息，所有爬虫均失败'
            return result

        # 汇总数据
        success = main_module.info_summary(movie, all_info)
        if not success:
            result['message'] = '数据汇总失败'
            return result

        # 翻译
        if translate:
            cfg = Cfg()
            if cfg.translator.engine:
                try:
                    translate_movie_info(movie.info)
                except Exception as e:
                    logger.warning(f"翻译失败 {movie.dvdid}: {e}")

        # 生成文件名和路径
        main_module.generate_names(movie)

        # 创建输出目录
        movie_save_dir = os.path.join(dest_path, replace_illegal_chars(movie.dvdid or movie.cid))
        os.makedirs(movie_save_dir, exist_ok=True)
        movie.save_dir = movie_save_dir

        # 下载封面图片
        try:
            cfg = Cfg()
            big_covers = movie.info.big_covers if cfg.summarizer.cover.highres else None
            cover_dl = main_module.download_cover(movie.info.covers, movie.fanart_file, big_covers)
            if cover_dl is None:
                logger.warning(f"封面下载失败: {movie.dvdid or movie.cid}")
            else:
                cover, pic_path = cover_dl
                if cover != movie.info.cover:
                    movie.info.cover = cover
                if pic_path != movie.fanart_file:
                    movie.fanart_file = pic_path
                    actual_ext = os.path.splitext(pic_path)[1]
                    movie.poster_file = os.path.splitext(movie.poster_file)[0] + actual_ext
                main_module.process_poster(movie)
        except Exception as e:
            logger.warning(f"封面处理异常 {movie.dvdid}: {e}")

        # 下载剧照
        cfg = Cfg()
        if cfg.summarizer.extra_fanarts.enabled and getattr(movie.info, 'preview_pics', None):
            try:
                extrafanartdir = movie.save_dir + '/extrafanart'
                os.makedirs(extrafanartdir, exist_ok=True)
                concurrent = cfg.summarizer.extra_fanarts.concurrent_downloads
                if concurrent > 0:
                    main_module.download_extrafanart_concurrent(movie, extrafanartdir, None)
                else:
                    max_count = cfg.summarizer.extra_fanarts.max_download_count
                    pics = movie.info.preview_pics[:max_count] if max_count > 0 else movie.info.preview_pics
                    for id, pic_url in enumerate(pics):
                        fanart_dest = f"{extrafanartdir}/{id}.png"
                        try:
                            main_module.download(pic_url, fanart_dest)
                        except Exception as e:
                            logger.warning(f"剧照下载失败 {pic_url}: {e}")
            except Exception as e:
                logger.warning(f"剧照处理异常 {movie.dvdid}: {e}")

        # 保存 NFO
        nfo_path = os.path.join(movie_save_dir, f"{movie.dvdid or movie.cid}.nfo")
        write_nfo(movie.info, nfo_path)

        # 移动或复制文件
        new_files = []
        for file_path in movie.files:
            file_name = os.path.basename(file_path)
            dest_file = os.path.join(movie_save_dir, file_name)
            if move_files:
                os.rename(file_path, dest_file)
            else:
                shutil.copy2(file_path, dest_file)
            new_files.append(dest_file)

        movie.files = new_files
        result['dest_path'] = movie_save_dir
        result['success'] = True
        result['message'] = '刮削成功'

        # 收集元数据
        info = movie.info
        result['data'] = {
            'title': info.title,
            'actress': info.actress,
            'genre': info.genre,
            'cover': info.cover,
            'publish_date': info.publish_date,
            'director': info.director,
            'producer': info.producer,
            'publisher': info.publisher,
            'score': info.score,
        }

    except Exception as e:
        logger.exception(f"刮削 {movie.dvdid} 异常")
        result['message'] = str(e)

    return result
