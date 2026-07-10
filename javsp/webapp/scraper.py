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
    if 'hardworking' in crawler_cfg:
        _override(cfg.crawler, 'hardworking', bool(crawler_cfg['hardworking']))
    if 'sleep_after_scraping' in crawler_cfg:
        import pendulum
        val = crawler_cfg['sleep_after_scraping']
        if isinstance(val, str):
            _override(cfg.crawler, 'sleep_after_scraping', pendulum.parse(val) if val else cfg.crawler.sleep_after_scraping)
        else:
            _override(cfg.crawler, 'sleep_after_scraping', val)
    if 'required_keys' in crawler_cfg:
        _override(cfg.crawler, 'required_keys', crawler_cfg['required_keys'] if isinstance(crawler_cfg['required_keys'], list) else json.loads(crawler_cfg['required_keys']))
    if 'respect_site_avid' in crawler_cfg:
        _override(cfg.crawler, 'respect_site_avid', bool(crawler_cfg['respect_site_avid']))
    if 'use_javdb_cover' in crawler_cfg:
        _override(cfg.crawler, 'use_javdb_cover', crawler_cfg['use_javdb_cover'])
    if 'normalize_actress_name' in crawler_cfg:
        _override(cfg.crawler, 'normalize_actress_name', bool(crawler_cfg['normalize_actress_name']))

    # 爬虫镜像地址
    network_cfg = db_config.get('network', {})
    if 'crawler_mirror' in network_cfg and isinstance(network_cfg['crawler_mirror'], dict):
        _override(cfg.network, 'crawler_mirror', {CrawlerID(k): v for k, v in network_cfg['crawler_mirror'].items()})
    if 'proxy_server' in network_cfg:
        _override(cfg.network, 'proxy_server', network_cfg['proxy_server'] or None)
    if 'retry' in network_cfg:
        _override(cfg.network, 'retry', network_cfg['retry'])
    if 'timeout' in network_cfg:
        import pendulum
        val = network_cfg['timeout']
        if isinstance(val, str):
            _override(cfg.network, 'timeout', pendulum.parse(val) if val else cfg.network.timeout)
        else:
            _override(cfg.network, 'timeout', val)
    if 'ssl_verification' in network_cfg:
        _override(cfg.network, 'ssl_verification', bool(network_cfg['ssl_verification']))

    # 整理/命名设置
    summarizer_cfg = db_config.get('summarizer', {})
    if 'output_folder_pattern' in summarizer_cfg and summarizer_cfg['output_folder_pattern']:
        _override(cfg.summarizer.path, 'output_folder_pattern', summarizer_cfg['output_folder_pattern'])
    if 'basename_pattern' in summarizer_cfg and summarizer_cfg['basename_pattern']:
        _override(cfg.summarizer.path, 'basename_pattern', summarizer_cfg['basename_pattern'])
    if 'file_basename_pattern' in summarizer_cfg and summarizer_cfg['file_basename_pattern']:
        _override(cfg.summarizer.path, 'file_basename_pattern', summarizer_cfg['file_basename_pattern'])
    if 'nfo_title_pattern' in summarizer_cfg and summarizer_cfg['nfo_title_pattern']:
        _override(cfg.summarizer.nfo, 'title_pattern', summarizer_cfg['nfo_title_pattern'])
    if 'nfo_basename' in summarizer_cfg and summarizer_cfg['nfo_basename']:
        _override(cfg.summarizer.nfo, 'basename_pattern', summarizer_cfg['nfo_basename'])
    if 'move_files' in summarizer_cfg:
        _override(cfg.summarizer, 'move_files', bool(summarizer_cfg['move_files']))
    if 'hard_link' in summarizer_cfg:
        _override(cfg.summarizer.path, 'hard_link', bool(summarizer_cfg['hard_link']))
    if 'length_maximum' in summarizer_cfg:
        _override(cfg.summarizer.path, 'length_maximum', int(summarizer_cfg['length_maximum']))
    if 'max_actress_count' in summarizer_cfg:
        _override(cfg.summarizer.path, 'max_actress_count', int(summarizer_cfg['max_actress_count']))
    if 'remove_trailing_actor_name' in summarizer_cfg:
        _override(cfg.summarizer.title, 'remove_trailing_actor_name', bool(summarizer_cfg['remove_trailing_actor_name']))
    if 'cover_basename' in summarizer_cfg and summarizer_cfg['cover_basename']:
        _override(cfg.summarizer.cover, 'basename_pattern', summarizer_cfg['cover_basename'])
    if 'fanart_basename' in summarizer_cfg and summarizer_cfg['fanart_basename']:
        _override(cfg.summarizer.fanart, 'basename_pattern', summarizer_cfg['fanart_basename'])
    if 'extra_fanarts_enabled' in summarizer_cfg:
        _override(cfg.summarizer.extra_fanarts, 'enabled', bool(summarizer_cfg['extra_fanarts_enabled']))
    if 'extra_fanarts_concurrent' in summarizer_cfg:
        _override(cfg.summarizer.extra_fanarts, 'concurrent_downloads', int(summarizer_cfg['extra_fanarts_concurrent']))
    if 'extra_fanarts_max' in summarizer_cfg:
        _override(cfg.summarizer.extra_fanarts, 'max_download_count', int(summarizer_cfg['extra_fanarts_max']))
    if 'censor_repr_0' in summarizer_cfg:
        cfg.summarizer.censor_options_representation[0] = summarizer_cfg['censor_repr_0']
    if 'censor_repr_1' in summarizer_cfg:
        cfg.summarizer.censor_options_representation[1] = summarizer_cfg['censor_repr_1']
    if 'censor_repr_2' in summarizer_cfg:
        cfg.summarizer.censor_options_representation[2] = summarizer_cfg['censor_repr_2']

    # 封面设置
    cover_cfg = db_config.get('cover', {})
    if 'highres' in cover_cfg:
        _override(cfg.summarizer.cover, 'highres', bool(cover_cfg['highres']))
    if 'add_label' in cover_cfg:
        _override(cfg.summarizer.cover, 'add_label', bool(cover_cfg['add_label']))

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

    logger.debug(f"Web 配置已应用")


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

        # 生成命名（output_folder_pattern 已由 apply_web_config 从数据库同步）
        cfg = Cfg()
        main_module.generate_names(movie)

        if not movie.save_dir:
            result['message'] = '无法生成目标路径'
            return result

        os.makedirs(movie.save_dir, exist_ok=True)

        # 下载封面图片
        try:
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

        # 写入 NFO
        write_nfo(movie.info, movie.nfo_file)

        # 使用 movie.rename_files 移动/重命名文件（与命令行逻辑一致）
        root = os.path.dirname(movie.files[0]) if movie.files else None
        if move_files:
            movie.rename_files(cfg.summarizer.path.hard_link, root=root)
        else:
            # 复制模式：手动复制并重命名
            new_files = []
            for file_path in movie.files:
                basename = movie.basename or os.path.splitext(os.path.basename(file_path))[0]
                ext = os.path.splitext(file_path)[1]
                dest_file = os.path.join(movie.save_dir, basename + ext)
                shutil.copy2(file_path, dest_file)
                new_files.append(dest_file)
            movie.files = new_files

        result['dest_path'] = movie.save_dir
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
