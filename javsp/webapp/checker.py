"""命名检查器 - 扫描目录检查影片文件命名一致性"""

import os
import re
import shutil
import subprocess
import logging
import threading
import time
from pathlib import Path
from typing import List, Dict, Optional

from javsp.avid import get_id, get_cid
from javsp.config import Cfg, ByteSize
from javsp.webapp.database import add_log, get_config

logger = logging.getLogger('javsp.webapp.checker')

# 扫描结果缓存: {path: scan_data}
_scan_cache: Dict[str, dict] = {}
_scan_cache_lock = threading.Lock()

# 视频扩展名
VIDEO_EXTENSIONS = {
    '.3gp', '.avi', '.f4v', '.flv', '.iso', '.m2ts', '.m4v', '.mkv',
    '.mov', '.mp4', '.mpeg', '.rm', '.rmvb', '.ts', '.vob', '.webm',
    '.wmv', '.strm', '.mpg',
}

# 图片扩展名
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


def _extract_avid(filepath: str) -> tuple[str, str]:
    """从文件路径提取番号，返回 (avid, source)"""
    dvdid = get_id(filepath)
    cid = get_cid(filepath)
    if cid:
        return cid, 'filename'
    if dvdid:
        return dvdid, 'filename'
    # 尝试从 nfo 文件提取
    parent = os.path.dirname(filepath)
    for f in os.listdir(parent):
        if f.lower().endswith('.nfo'):
            nfo_path = os.path.join(parent, f)
            nfo_dvdid = get_id(nfo_path)
            if nfo_dvdid:
                return nfo_dvdid, 'nfo'
    return '', ''


def _get_variant_suffix(filepath: str) -> str:
    """提取文件名中的变体后缀 (-UC, -C, -U, 空)"""
    basename = os.path.basename(filepath).upper()
    # 匹配番号后面的变体后缀，如 ABC-123-UC, [ABC-123-C], ABC-123-U.mp4
    if re.search(r'[-_.]UC(?:[-_.\s\]\)]|$)', basename):
        return 'UC'
    if re.search(r'[-_.]C(?:[-_.\s\]\)]|$)', basename) and not re.search(r'[-_.]CID', basename):
        return 'C'
    if re.search(r'[-_.]U(?:[-_.\s\]\)]|$)', basename):
        return 'U'
    return ''


def _get_nfo_basename_pattern() -> str:
    """获取 NFO 文件名模式（优先从数据库读取）"""
    try:
        config = get_config('summarizer')
        val = config.get('summarizer', {}).get('nfo_basename', '')
        if val:
            return val
    except Exception:
        pass
    return Cfg().summarizer.nfo.basename_pattern


def _get_minimum_size() -> int:
    """获取最小文件大小配置（字节）"""
    try:
        return int(Cfg().scanner.minimum_size)
    except Exception:
        try:
            config = get_config('scanner')
            raw = config.get('scanner', {}).get('minimum_size', '232MiB')
            return int(ByteSize(raw))
        except Exception:
            return 232 * 1024 * 1024  # 默认 232MiB


def _find_companion_files(video_path: str) -> dict:
    """查找视频文件的配套文件（nfo, poster, fanart）"""
    parent = os.path.dirname(video_path)
    video_stem = os.path.splitext(os.path.basename(video_path))[0]
    
    result = {
        'nfo_path': None,
        'nfo_basename': None,
        'poster_path': None,
        'poster_basename': None,
        'fanart_path': None,
        'fanart_basename': None,
    }
    
    for f in os.listdir(parent):
        f_lower = f.lower()
        f_path = os.path.join(parent, f)
        f_stem = os.path.splitext(f)[0].lower()
        f_ext = os.path.splitext(f)[1].lower()
        
        # NFO 文件
        if f_ext == '.nfo':
            result['nfo_path'] = f_path
            result['nfo_basename'] = os.path.splitext(f)[0]
        
        # Poster 文件 (poster.jpg, {num}-poster.jpg, etc.)
        if f_ext in IMAGE_EXTENSIONS:
            # 检查是否是 poster
            if f_stem == 'poster' or f_stem.endswith('-poster'):
                result['poster_path'] = f_path
                result['poster_basename'] = f
            # 检查是否是 fanart
            elif f_stem == 'fanart' or f_stem.endswith('-fanart'):
                result['fanart_path'] = f_path
                result['fanart_basename'] = f
    
    return result


def _get_expected_names(avid: str, convention: str, nfo_basename_pattern: str = None) -> dict:
    """根据命名约定生成期望的文件名"""
    num = avid
    
    # NFO 文件名
    if nfo_basename_pattern:
        nfo_name = nfo_basename_pattern.format(num=num)
    else:
        nfo_name = f'[{num}]'
    
    # Poster 和 Fanart 文件名（在视频同目录下）
    poster_name = 'poster'
    fanart_name = 'fanart'
    
    return {
        'expected_nfo': f'{nfo_name}.nfo',
        'expected_nfo_name': f'{nfo_name}.nfo',
        'expected_poster': f'{poster_name}.jpg',
        'expected_poster_name': f'{poster_name}.jpg',
        'expected_fanart': f'{fanart_name}.jpg',
        'expected_fanart_name': f'{fanart_name}.jpg',
        'expected_video_name': f'[{num}].mkv',  # 通用期望
    }


def _check_mismatches(companions: dict, expected: dict, video_basename: str, avid: str) -> list:
    """检查命名不一致的字段"""
    issues = []
    mismatch_fields = []
    
    # 检查 NFO
    nfo_actual = companions['nfo_basename']
    nfo_expected = expected['expected_nfo_name'].replace('.nfo', '')
    if not nfo_actual:
        mismatch_fields.append('nfo')
        issues.append('缺少 NFO 文件')
    elif nfo_actual != nfo_expected:
        mismatch_fields.append('nfo')
        issues.append(f'NFO 命名不一致: {nfo_actual} → {nfo_expected}')
    
    # 检查 Poster
    poster_actual = companions['poster_basename']
    poster_expected = expected['expected_poster_name']
    if not poster_actual:
        mismatch_fields.append('poster')
        issues.append('缺少 Poster 文件')
    elif poster_actual != poster_expected:
        mismatch_fields.append('poster')
        issues.append(f'Poster 命名不一致: {poster_actual} → {poster_expected}')
    
    # 检查 Fanart
    fanart_actual = companions['fanart_basename']
    fanart_expected = expected['expected_fanart_name']
    if not fanart_actual:
        mismatch_fields.append('fanart')
        issues.append('缺少 Fanart 文件')
    elif fanart_actual != fanart_expected:
        mismatch_fields.append('fanart')
        issues.append(f'Fanart 命名不一致: {fanart_actual} → {fanart_expected}')
    
    return mismatch_fields, issues


def scan_directory(path: str, convention: str = 'avid',
                   modified_after: str = None, modified_before: str = None,
                   created_after: str = None, created_before: str = None,
                   socketio=None, task_id: str = None) -> dict:
    """扫描目录，检查影片文件命名一致性"""
    if not os.path.isdir(path):
        return {'error': f'目录不存在: {path}'}
    
    # 获取 NFO 命名模式（优先从数据库读取用户配置）
    nfo_basename_pattern = _get_nfo_basename_pattern()
    
    results = []
    ok_count = 0
    mismatch_count = 0
    skipped_small = 0

    # 获取最小文件大小
    minimum_size = _get_minimum_size()

    dir_idx = 0
    for dirpath, dirnames, filenames_in_dir in os.walk(path):
        # 推送扫描进度（不含总数，因为无法预知）
        if socketio and task_id:
            try:
                socketio.emit('scan_progress', {
                    'task_id': task_id,
                    'status': 'running',
                    'dirs_scanned': dir_idx,
                    'total_dirs': 0,
                    'current': os.path.basename(dirpath),
                }, namespace='/')
            except Exception:
                pass
        dir_idx += 1

        try:
            filenames = os.listdir(dirpath)
        except PermissionError:
            continue
        
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in VIDEO_EXTENSIONS:
                continue
            
            filepath = os.path.join(dirpath, filename)

            # 过滤小文件
            try:
                if os.path.getsize(filepath) < minimum_size:
                    skipped_small += 1
                    continue
            except OSError:
                continue

            # 时间筛选
            if modified_after or modified_before:
                mtime = os.path.getmtime(filepath)
                if modified_after:
                    try:
                        from datetime import datetime
                        threshold = datetime.fromisoformat(modified_after.replace('Z', '+00:00')).timestamp()
                        if mtime < threshold:
                            continue
                    except:
                        pass
                if modified_before:
                    try:
                        from datetime import datetime
                        threshold = datetime.fromisoformat(modified_before.replace('Z', '+00:00')).timestamp()
                        if mtime > threshold:
                            continue
                    except:
                        pass
            
            if created_after or created_before:
                ctime = os.path.getctime(filepath)
                if created_after:
                    try:
                        from datetime import datetime
                        threshold = datetime.fromisoformat(created_after.replace('Z', '+00:00')).timestamp()
                        if ctime < threshold:
                            continue
                    except:
                        pass
                if created_before:
                    try:
                        from datetime import datetime
                        threshold = datetime.fromisoformat(created_before.replace('Z', '+00:00')).timestamp()
                        if ctime > threshold:
                            continue
                    except:
                        pass
            
            # 提取番号
            avid, avid_source = _extract_avid(filepath)
            variant = _get_variant_suffix(filepath) if avid else ''
            
            # 查找配套文件
            companions = _find_companion_files(filepath)
            
            # 获取期望命名
            expected = _get_expected_names(avid, convention, nfo_basename_pattern)
            
            # 检查不一致
            if avid:
                mismatch_fields, issues = _check_mismatches(
                    companions, expected, filename, avid)
            else:
                mismatch_fields = []
                issues = ['无法识别番号']
            
            # 获取文件创建时间
            try:
                created_time = os.path.getctime(filepath)
            except:
                created_time = None
            
            result = {
                'video_path': filepath,
                'video_basename': filename,
                'expected_video_name': expected.get('expected_video_name'),
                'video_needs_rename': False,
                'nfo_path': companions['nfo_path'],
                'nfo_basename': companions['nfo_basename'],
                'expected_nfo': expected['expected_nfo'],
                'expected_nfo_name': expected['expected_nfo_name'],
                'poster_path': companions['poster_path'],
                'poster_basename': companions['poster_basename'] or '',
                'expected_poster': expected['expected_poster'],
                'expected_poster_name': expected['expected_poster_name'],
                'fanart_path': companions['fanart_path'],
                'fanart_basename': companions['fanart_basename'] or '',
                'expected_fanart': expected['expected_fanart'],
                'expected_fanart_name': expected['expected_fanart_name'],
                'avid': avid,
                'avid_source': avid_source,
                'variant': variant,
                'issues': issues,
                'mismatch_fields': mismatch_fields,
                'has_poster': companions['poster_path'] is not None,
                'has_fanart': companions['fanart_path'] is not None,
                'convention': convention,
                'created_time': created_time,
                'image_orientation_issue': None,
            }
            
            results.append(result)
            if mismatch_fields:
                mismatch_count += 1
            else:
                ok_count += 1
    
    scan_data = {
        'path': path,
        'total': len(results),
        'ok_count': ok_count,
        'mismatch_count': mismatch_count,
        'skipped_small': skipped_small,
        'results': results,
        'convention': convention,
    }
    
    # 缓存结果
    with _scan_cache_lock:
        _scan_cache[path] = scan_data
    
    return scan_data


def get_scan_cache(path: str) -> Optional[dict]:
    """获取扫描缓存"""
    with _scan_cache_lock:
        return _scan_cache.get(path)


def fix_naming_issues(items: list, convention: str = 'avid', socketio=None, task_id: str = None) -> dict:
    """修复命名问题"""
    from javsp.webapp.database import get_config
    
    nfo_basename_pattern = _get_nfo_basename_pattern()
    
    success_list = []
    failed_list = []
    
    total = len(items)
    
    for idx, item in enumerate(items):
        if socketio and task_id:
            try:
                socketio.emit('fix_progress', {
                    'task_id': task_id,
                    'status': 'running',
                    'completed': idx,
                    'total': total,
                    'current': os.path.basename(item.get('video_path', '')),
                }, namespace='/')
            except Exception:
                pass
        
        try:
            video_path = item.get('video_path')
            if not video_path or not os.path.exists(video_path):
                failed_list.append({'video_path': video_path, 'error': '文件不存在'})
                continue
            
            # 提取番号
            avid, _ = _extract_avid(video_path)
            if not avid:
                failed_list.append({'video_path': video_path, 'error': '无法识别番号'})
                continue
            
            expected = _get_expected_names(avid, convention, nfo_basename_pattern)
            parent = os.path.dirname(video_path)
            renamed_files = []
            
            # 重命名 NFO
            nfo_path = item.get('nfo_path')
            if nfo_path and os.path.exists(nfo_path):
                new_nfo = os.path.join(parent, expected['expected_nfo'])
                if nfo_path != new_nfo:
                    os.rename(nfo_path, new_nfo)
                    renamed_files.append(('nfo', os.path.basename(nfo_path), expected['expected_nfo']))
            
            # 重命名 Poster
            poster_path = item.get('poster_path')
            if poster_path and os.path.exists(poster_path):
                new_poster = os.path.join(parent, expected['expected_poster'])
                if poster_path != new_poster:
                    os.rename(poster_path, new_poster)
                    renamed_files.append(('poster', os.path.basename(poster_path), expected['expected_poster']))
            
            # 重命名 Fanart
            fanart_path = item.get('fanart_path')
            if fanart_path and os.path.exists(fanart_path):
                new_fanart = os.path.join(parent, expected['expected_fanart'])
                if fanart_path != new_fanart:
                    os.rename(fanart_path, new_fanart)
                    renamed_files.append(('fanart', os.path.basename(fanart_path), expected['expected_fanart']))
            
            success_list.append({
                'video_path': video_path,
                'avid': avid,
                'renamed': renamed_files,
            })
            
            if renamed_files:
                add_log('INFO', 'checker', f'修复命名: {avid} - {len(renamed_files)} 个文件')
        
        except Exception as e:
            logger.exception(f"修复命名失败: {item}")
            failed_list.append({'video_path': item.get('video_path'), 'error': str(e)})
    
    result = {
        'success': success_list,
        'failed': failed_list,
    }
    
    # 推送完成
    if socketio and task_id:
        try:
            socketio.emit('fix_progress', {
                'task_id': task_id,
                'status': 'completed',
                'completed': total,
                'total': total,
                'success': len(success_list),
                'failed': len(failed_list),
            }, namespace='/')
        except Exception:
            pass
    
    return result


def repair_videos(video_paths: list, socketio=None, task_id: str = None) -> dict:
    """重新刮削视频（复用 scraper 逻辑）"""
    from javsp.webapp.scraper import run_scrape_task
    from javsp.webapp.database import get_config, create_task, update_task
    
    if not video_paths:
        return {'error': '未指定视频文件'}
    
    config = get_config()
    summarizer_cfg = config.get('summarizer', {})
    dest = summarizer_cfg.get('output_folder_pattern', '')
    
    if not dest:
        return {'error': '未配置输出路径'}
    
    # 创建任务
    repair_task_id = f'repair-{int(time.time())}'
    create_task(repair_task_id, video_paths[0], dest, len(video_paths), 'repair')
    
    # 启动异步线程
    thread = threading.Thread(
        target=_run_repair_task,
        args=(repair_task_id, video_paths, dest, socketio),
        daemon=True
    )
    thread.start()
    
    return {'task_id': repair_task_id, 'total': len(video_paths)}


def _run_repair_task(task_id: str, video_paths: list, dest: str, socketio):
    """异步执行修复任务"""
    from javsp.webapp.scraper import _scrape_single, apply_web_config, clear_stop
    from javsp.webapp.database import update_task, add_task_item, update_task_item, add_log
    from javsp.datatype import Movie
    from javsp import __main__ as main_module
    
    try:
        apply_web_config()
        main_module.load_actress_alias()
        main_module.import_crawlers()
        
        clear_stop()
        
        success_count = 0
        failed_count = 0
        
        for idx, video_path in enumerate(video_paths):
            try:
                # 创建 Movie 对象
                movie = Movie(os.path.basename(video_path))
                movie.files = [video_path]
                movie.data_src = 'normal'
                
                dvdid = movie.dvdid or movie.cid or f'unknown_{idx}'
                item_id = add_task_item(task_id, dvdid, video_path)
                
                if socketio:
                    try:
                        socketio.emit('repair_progress', {
                            'task_id': task_id,
                            'status': 'running',
                            'completed': idx,
                            'total': len(video_paths),
                            'current': dvdid,
                        }, namespace='/')
                    except Exception:
                        pass
                
                result = _scrape_single(movie, True, dest, True, main_module)
                
                if result['success']:
                    update_task_item(item_id, status='success',
                                     dest_path=result['dest_path'],
                                     scraped_data=result.get('data'),
                                     finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                    success_count += 1
                else:
                    update_task_item(item_id, status='failed',
                                     message=result['message'],
                                     finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                    failed_count += 1
            
            except Exception as e:
                logger.exception(f"修复视频失败: {video_path}")
                failed_count += 1
        
        final_status = 'completed' if failed_count == 0 else ('partial' if success_count > 0 else 'failed')
        update_task(task_id, status=final_status,
                    completed=len(video_paths),
                    success_count=success_count,
                    failed_count=failed_count,
                    finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
        
        if socketio:
            try:
                socketio.emit('repair_progress', {
                    'task_id': task_id,
                    'status': 'completed',
                    'completed': len(video_paths),
                    'total': len(video_paths),
                    'success': success_count,
                    'failed': failed_count,
                }, namespace='/')
            except Exception:
                pass
        
        add_log('INFO', 'checker', f'修复任务 {task_id[:8]} 完成: 成功 {success_count}, 失败 {failed_count}')
    
    except Exception as e:
        logger.exception("修复任务异常")
        update_task(task_id, status='error',
                    finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
        if socketio:
            try:
                socketio.emit('repair_progress', {
                    'task_id': task_id,
                    'status': 'error',
                    'message': str(e),
                }, namespace='/')
            except Exception:
                pass


def merge_duplicates(video_paths: list) -> dict:
    """合并重复番号的文件，保留最佳版本"""
    if len(video_paths) < 2:
        return {'error': '需要至少 2 个文件'}
    
    # 优先级: -UC(无修正) > -C(字幕) > -U(普通) > 文件大小
    def _score(path: str) -> tuple:
        basename = os.path.basename(path).upper()
        if '-UC' in basename or '_UC' in basename:
            return (0,)  # 最高优先级
        if '-C' in basename or '_C' in basename:
            return (1,)
        if '-U' in basename or '_U' in basename:
            return (2,)
        # 按文件大小降序
        try:
            return (3, -os.path.getsize(path))
        except:
            return (3, 0)
    
    sorted_paths = sorted(video_paths, key=_score)
    kept = sorted_paths[0]
    to_delete = sorted_paths[1:]
    
    deleted = []
    for path in to_delete:
        try:
            if os.path.exists(path):
                os.remove(path)
                # 同时删除配套文件
                parent = os.path.dirname(path)
                stem = os.path.splitext(os.path.basename(path))[0]
                for f in os.listdir(parent):
                    f_path = os.path.join(parent, f)
                    f_stem = os.path.splitext(f)[0]
                    f_ext = os.path.splitext(f)[1].lower()
                    if f_ext in {'.nfo', '.jpg', '.jpeg', '.png'} and f_stem in ('poster', 'fanart', f'[{stem}]'):
                        # 只删除被删视频的配套文件（同目录下有多个视频时不能乱删）
                        pass
                deleted.append({'path': os.path.basename(path), 'status': 'deleted'})
                add_log('INFO', 'checker', f'合并删除: {os.path.basename(path)}')
        except Exception as e:
            deleted.append({'path': os.path.basename(path), 'status': 'error', 'error': str(e)})
    
    return {
        'kept': kept,
        'deleted': deleted,
    }


# ==================== 视频完整性检查 ====================

_integrity_stop_flags: Dict[str, bool] = {}
_integrity_stop_lock = threading.Lock()


def _check_single_file(filepath: str) -> dict:
    """用 ffprobe 检查单个视频文件完整性（只读容器头，不解码帧，速度快）"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries',
             'format=format_name,duration:stream=codec_name,codec_type',
             '-of', 'json', filepath],
            capture_output=True, text=True, timeout=30
        )
        errors = result.stderr.strip()
        if result.returncode != 0 or errors:
            return {'ok': False, 'errors': errors or 'ffprobe 返回错误'}
        # 检查是否解析到了视频流
        try:
            import json as _json
            info = _json.loads(result.stdout)
            streams = info.get('streams', [])
            has_video = any(s.get('codec_type') == 'video' for s in streams)
            if not has_video:
                return {'ok': False, 'errors': '未找到视频流'}
        except Exception:
            pass  # JSON 解析失败不影响，只要 ffprobe 返回 0 就算正常
        return {'ok': True, 'errors': None}
    except FileNotFoundError:
        return {'ok': True, 'errors': None}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'errors': '检查超时 (>30s)'}
    except Exception as e:
        return {'ok': False, 'errors': str(e)}


def _format_size(size_bytes: int) -> str:
    for unit in ['B', 'KiB', 'MiB', 'GiB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != 'B' else f"{size_bytes} B"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TiB"


def request_integrity_stop(task_id: str):
    with _integrity_stop_lock:
        _integrity_stop_flags[task_id] = True


def is_integrity_stop_requested(task_id: str) -> bool:
    with _integrity_stop_lock:
        return _integrity_stop_flags.get(task_id, False)


def clear_integrity_stop(task_id: str):
    with _integrity_stop_lock:
        _integrity_stop_flags.pop(task_id, None)


def start_integrity_check(path: str, socketio=None) -> dict:
    """创建完整性检查任务并启动后台线程"""
    from javsp.webapp.database import (
        create_integrity_task, update_integrity_task_status,
        get_integrity_task, get_next_pending_integrity_item,
        update_integrity_item_status, update_integrity_task_progress,
        add_log
    )
    if not os.path.isdir(path):
        return {'error': f'目录不存在: {path}'}

    try:
        subprocess.run(['ffprobe', '-version'], capture_output=True, timeout=5)
    except FileNotFoundError:
        return {'error': 'ffprobe 未安装，请先安装 ffmpeg'}

    minimum_size = _get_minimum_size()
    files = []
    for dirpath, _, filenames_in_dir in os.walk(path):
        for filename in filenames_in_dir:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in VIDEO_EXTENSIONS:
                continue
            filepath = os.path.join(dirpath, filename)
            try:
                fsize = os.path.getsize(filepath)
                if fsize < minimum_size:
                    continue
                files.append({'path': filepath, 'basename': filename, 'size': fsize})
            except OSError:
                continue

    task_id = f'integrity-{int(time.time())}'
    create_integrity_task(task_id, path, files)
    add_log('INFO', 'integrity', f'开始完整性检查: {path} ({len(files)} 个文件)')

    def _run():
        try:
            while True:
                if is_integrity_stop_requested(task_id):
                    update_integrity_task_status(task_id, 'stopped')
                    if socketio:
                        socketio.emit('integrity_progress', {
                            'task_id': task_id, 'status': 'stopped',
                        }, namespace='/')
                    add_log('INFO', 'integrity', f'完整性检查已停止: {task_id[:8]}')
                    clear_integrity_stop(task_id)
                    return

                item = get_next_pending_integrity_item(task_id)
                if not item:
                    break

                if socketio:
                    try:
                        socketio.emit('integrity_progress', {
                            'task_id': task_id,
                            'status': 'running',
                            'current': item['video_basename'],
                        }, namespace='/')
                    except Exception:
                        pass

                result = _check_single_file(item['video_path'])
                new_status = 'ok' if result['ok'] else 'error'
                update_integrity_item_status(item['id'], new_status, result['errors'])
                update_integrity_task_progress(task_id)

            # 读取最终状态
            from javsp.webapp.database import get_integrity_task as _get_task
            final = _get_task(task_id)
            final_status = 'completed'
            if final and final.get('error_count', 0) > 0:
                final_status = 'completed'
            update_integrity_task_status(task_id, final_status)

            if socketio:
                socketio.emit('integrity_progress', {
                    'task_id': task_id,
                    'status': 'completed',
                    'ok_count': final['ok_count'] if final else 0,
                    'error_count': final['error_count'] if final else 0,
                }, namespace='/')

            add_log('INFO', 'integrity',
                     f'完整性检查完成: {final["total"] if final else 0} 个文件, '
                     f'{final["error_count"] if final else 0} 个损坏')
            clear_integrity_stop(task_id)

        except Exception as e:
            logger.exception("完整性检查异常")
            update_integrity_task_status(task_id, 'failed')
            if socketio:
                socketio.emit('integrity_progress', {
                    'task_id': task_id, 'status': 'failed', 'message': str(e),
                }, namespace='/')
            clear_integrity_stop(task_id)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {'task_id': task_id, 'total': len(files)}


def resume_integrity_check(task_id: str, socketio=None) -> dict:
    """恢复被停止的完整性检查任务"""
    from javsp.webapp.database import (
        get_integrity_task, update_integrity_task_status, add_log,
        get_next_pending_integrity_item, update_integrity_item_status,
        update_integrity_task_progress
    )
    task = get_integrity_task(task_id)
    if not task:
        return {'error': '任务不存在'}
    if task['status'] == 'running':
        return {'error': '任务正在运行中'}

    clear_integrity_stop(task_id)
    update_integrity_task_status(task_id, 'running')
    add_log('INFO', 'integrity', f'恢复完整性检查: {task_id[:8]}')

    def _run():
        try:
            while True:
                if is_integrity_stop_requested(task_id):
                    update_integrity_task_status(task_id, 'stopped')
                    if socketio:
                        socketio.emit('integrity_progress', {
                            'task_id': task_id, 'status': 'stopped',
                        }, namespace='/')
                    add_log('INFO', 'integrity', f'完整性检查已停止: {task_id[:8]}')
                    clear_integrity_stop(task_id)
                    return

                item = get_next_pending_integrity_item(task_id)
                if not item:
                    break

                if socketio:
                    try:
                        socketio.emit('integrity_progress', {
                            'task_id': task_id,
                            'status': 'running',
                            'current': item['video_basename'],
                        }, namespace='/')
                    except Exception:
                        pass

                result = _check_single_file(item['video_path'])
                new_status = 'ok' if result['ok'] else 'error'
                update_integrity_item_status(item['id'], new_status, result['errors'])
                update_integrity_task_progress(task_id)

            final = get_integrity_task(task_id)
            update_integrity_task_status(task_id, 'completed')

            if socketio:
                socketio.emit('integrity_progress', {
                    'task_id': task_id,
                    'status': 'completed',
                    'ok_count': final['ok_count'] if final else 0,
                    'error_count': final['error_count'] if final else 0,
                }, namespace='/')

            add_log('INFO', 'integrity',
                     f'完整性检查完成: {final["total"] if final else 0} 个文件, '
                     f'{final["error_count"] if final else 0} 个损坏')
            clear_integrity_stop(task_id)

        except Exception as e:
            logger.exception("完整性检查恢复异常")
            update_integrity_task_status(task_id, 'failed')
            if socketio:
                socketio.emit('integrity_progress', {
                    'task_id': task_id, 'status': 'failed', 'message': str(e),
                }, namespace='/')
            clear_integrity_stop(task_id)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {'task_id': task_id}


def _get_video_extensions() -> set:
    """获取视频文件扩展名（优先从数据库读取）"""
    try:
        from javsp.webapp.database import get_config as _get_config
        config = _get_config('scanner')
        exts = config.get('scanner', {}).get('filename_extensions', [])
        if exts:
            return {e.lower() if e.startswith('.') else f'.{e.lower()}' for e in exts}
    except Exception:
        pass
    return VIDEO_EXTENSIONS


def _has_other_media_files(directory: str, exclude_path: str) -> bool:
    """检查目录下是否还有其他媒体文件（排除指定文件）"""
    exts = _get_video_extensions()
    try:
        for f in os.listdir(directory):
            fpath = os.path.join(directory, f)
            if fpath == exclude_path:
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext in exts:
                return True
    except OSError:
        pass
    return False


def delete_videos(video_paths: list) -> dict:
    """批量删除视频文件，若同目录无其他媒体文件则一并删除该目录"""
    deleted = []
    failed = []
    # 记录已处理过的目录，避免重复检查
    processed_dirs = set()
    for path in video_paths:
        try:
            parent = os.path.dirname(path)
            if os.path.exists(path):
                has_others = _has_other_media_files(parent, path)
                os.remove(path)
                result = {'path': path, 'has_other_media': has_others}
            else:
                # 文件已不在磁盘上，视为已清理成功
                has_others = _has_other_media_files(parent, path)
                result = {'path': path, 'has_other_media': has_others, 'already_gone': True}

            # 如果同目录下无其他媒体文件，删除整个目录
            if not has_others and parent not in processed_dirs:
                processed_dirs.add(parent)
                if os.path.isdir(parent):
                    import shutil
                    shutil.rmtree(parent)
                    result['dir_deleted'] = parent

            deleted.append(result)
        except Exception as e:
            failed.append({'path': path, 'error': str(e)})
    return {'deleted': deleted, 'failed': failed}
