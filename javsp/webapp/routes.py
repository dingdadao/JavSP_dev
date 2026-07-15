"""API 路由 - 配置管理、刮削任务、文件监控"""

import os
import json
import uuid
import time
import logging
import threading
from pathlib import Path
from flask import request, jsonify
from flask_socketio import SocketIO

from javsp.webapp.database import (
    get_config, update_config, batch_update_config,
    create_task, update_task, add_task_item, update_task_item,
    get_task, get_tasks, add_log, get_logs,
    add_watch_path, remove_watch_path, get_watch_paths, toggle_watch_path,
    get_media_libraries, get_default_media_library,
    add_media_library, update_media_library, delete_media_library,
    get_all_translate_models, get_active_translate_model,
    save_translate_model, update_translate_model, set_active_translate_model, delete_translate_model
)
from javsp.webapp.scraper import run_scrape_task, request_stop, is_stop_requested
from javsp.webapp.checker import (
    scan_directory, get_scan_cache, fix_naming_issues,
    repair_videos, merge_duplicates,
    start_integrity_check, resume_integrity_check, request_integrity_stop,
    delete_videos
)

logger = logging.getLogger('javsp.webapp.routes')

# 全局任务状态
_current_task_lock = threading.Lock()
_current_task_thread = None


def register_routes(app, socketio: SocketIO):
    """注册所有 API 路由"""

    # ==================== 健康检查 ====================
    @app.route('/api/health')
    def health():
        return jsonify({'code': 0, 'message': 'ok', 'data': {'status': 'running'}})

    # ==================== 配置管理 ====================
    @app.route('/api/config', methods=['GET'])
    def api_get_config():
        group = request.args.get('group')
        try:
            config = get_config(group)
            return jsonify({'code': 0, 'data': config})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/config', methods=['PUT'])
    def api_update_config():
        try:
            data = request.get_json()
            if not data:
                return jsonify({'code': 400, 'message': '请求体为空'}), 400

            # 支持单个更新和批量更新
            if isinstance(data, list):
                batch_update_config(data)
                add_log('INFO', 'config', f'批量更新 {len(data)} 项配置')
            else:
                update_config(data['group'], data['key'], data['value'])
                add_log('INFO', 'config', f'更新配置: {data["group"]}.{data["key"]}')

            return jsonify({'code': 0, 'message': '配置已更新'})
        except Exception as e:
            logger.exception("更新配置失败")
            return jsonify({'code': 500, 'message': str(e)}), 500

    # ==================== 刮削任务 ====================
    @app.route('/api/tasks', methods=['GET'])
    def api_list_tasks():
        try:
            limit = request.args.get('limit', 50, type=int)
            offset = request.args.get('offset', 0, type=int)
            status = request.args.get('status')
            tasks = get_tasks(limit, offset, status)
            return jsonify({'code': 0, 'data': tasks})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/tasks/<task_id>', methods=['GET'])
    def api_get_task(task_id):
        try:
            task = get_task(task_id)
            if not task:
                return jsonify({'code': 404, 'message': '任务不存在'}), 404
            return jsonify({'code': 0, 'data': task})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/scrape', methods=['POST'])
    def api_create_scrape():
        global _current_task_thread
        try:
            with _current_task_lock:
                if _current_task_thread and _current_task_thread.is_alive():
                    return jsonify({'code': 409, 'message': '已有任务进行中，请等待完成'}), 409

            data = request.get_json() or {}
            source = data.get('source')
            dest = data.get('dest')

            # 从数据库配置获取默认路径
            if not source or not dest:
                config = get_config()
                scanner_cfg = config.get('scanner', {})
                summarizer_cfg = config.get('summarizer', {})
                if not source:
                    source = scanner_cfg.get('input_directory', '')
                if not dest:
                    dest = summarizer_cfg.get('output_folder_pattern', '')

            if not source:
                return jsonify({'code': 400, 'message': '未配置源路径'}), 400
            if not dest:
                return jsonify({'code': 400, 'message': '未配置目标路径'}), 400

            source_path = Path(source)
            if not source_path.exists():
                return jsonify({'code': 404, 'message': f'源路径不存在: {source}'}), 404

            dest_path = Path(dest)
            dest_path.mkdir(parents=True, exist_ok=True)

            # 创建任务记录
            task_id = str(uuid.uuid4())
            create_task(task_id, str(source_path), str(dest_path), 0, data.get('type', 'manual'))
            add_log('INFO', 'scraper', f'创建刮削任务: {source} -> {dest}')

            # 启动异步线程
            translate = data.get('translate', True)
            move_files = data.get('move_files', get_config('summarizer').get('summarizer', {}).get('move_files', True))

            _current_task_thread = threading.Thread(
                target=run_scrape_task,
                args=(task_id, str(source_path), str(dest_path), translate, move_files, socketio),
                daemon=True
            )
            _current_task_thread.start()

            return jsonify({'code': 0, 'message': '任务已创建', 'data': {'task_id': task_id}})
        except Exception as e:
            logger.exception("创建任务失败")
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/scrape/status', methods=['GET'])
    def api_scrape_status():
        """兼容旧 API 的状态查询"""
        try:
            tasks = get_tasks(1)
            if not tasks:
                return jsonify({'code': 0, 'message': '当前无任务', 'data': None})
            latest = tasks[0]
            task_detail = get_task(latest['id'])
            return jsonify({'code': 0, 'data': task_detail})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/scrape/stop', methods=['POST'])
    def api_stop_scrape():
        """停止当前刮削任务"""
        try:
            with _current_task_lock:
                if not _current_task_thread or not _current_task_thread.is_alive():
                    return jsonify({'code': 0, 'message': '当前无运行中的任务'})
            request_stop()
            add_log('INFO', 'scraper', '请求停止刮削任务')
            return jsonify({'code': 0, 'message': '已发送停止信号'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    # ==================== 文件监控 ====================
    @app.route('/api/watcher', methods=['GET'])
    def api_get_watch_paths():
        try:
            paths = get_watch_paths(enabled_only=False)
            config = get_config('watcher')
            return jsonify({
                'code': 0,
                'data': {
                    'enabled': config.get('watcher', {}).get('enabled', False),
                    'paths': paths
                }
            })
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/watcher', methods=['POST'])
    def api_add_watch_path():
        try:
            data = request.get_json()
            path = data.get('path')
            if not path:
                return jsonify({'code': 400, 'message': '路径不能为空'}), 400
            if not os.path.isdir(path):
                return jsonify({'code': 404, 'message': f'目录不存在: {path}'}), 404
            add_watch_path(path)
            add_log('INFO', 'watcher', f'添加监控路径: {path}')
            return jsonify({'code': 0, 'message': '监控路径已添加'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/watcher', methods=['DELETE'])
    def api_remove_watch_path():
        try:
            data = request.get_json()
            path = data.get('path')
            if not path:
                return jsonify({'code': 400, 'message': '路径不能为空'}), 400
            remove_watch_path(path)
            add_log('INFO', 'watcher', f'移除监控路径: {path}')
            return jsonify({'code': 0, 'message': '监控路径已移除'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/watcher/toggle', methods=['POST'])
    def api_toggle_watch():
        try:
            data = request.get_json()
            path = data.get('path')
            enabled = data.get('enabled', True)
            if not path:
                return jsonify({'code': 400, 'message': '路径不能为空'}), 400
            toggle_watch_path(path, enabled)
            return jsonify({'code': 0, 'message': '已更新'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    # ==================== 媒体库管理 ====================
    @app.route('/api/media-libraries', methods=['GET'])
    def api_get_media_libraries():
        try:
            libs = get_media_libraries()
            return jsonify({'code': 0, 'data': libs})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/media-libraries', methods=['POST'])
    def api_create_media_library():
        try:
            data = request.get_json()
            name = data.get('name', '').strip()
            path = data.get('path', '').strip()
            is_default = data.get('is_default', False)
            if not name:
                return jsonify({'code': 400, 'message': '名称不能为空'}), 400
            if not path:
                return jsonify({'code': 400, 'message': '路径不能为空'}), 400
            if not os.path.isdir(path):
                return jsonify({'code': 404, 'message': f'目录不存在: {path}'}), 404
            lib_id = add_media_library(name, path, is_default)
            add_log('INFO', 'media_library', f'添加媒体库: {name} ({path})')
            return jsonify({'code': 0, 'message': '媒体库已添加', 'data': {'id': lib_id}})
        except Exception as e:
            if 'UNIQUE' in str(e):
                return jsonify({'code': 409, 'message': '该路径已存在于媒体库中'}), 409
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/media-libraries/<int:lib_id>', methods=['PUT'])
    def api_update_media_library(lib_id):
        try:
            data = request.get_json()
            name = data.get('name')
            path = data.get('path')
            is_default = data.get('is_default')
            if path and not os.path.isdir(path):
                return jsonify({'code': 404, 'message': f'目录不存在: {path}'}), 404
            update_media_library(lib_id, name=name, path=path, is_default=is_default)
            add_log('INFO', 'media_library', f'更新媒体库 #{lib_id}')
            return jsonify({'code': 0, 'message': '媒体库已更新'})
        except Exception as e:
            if 'UNIQUE' in str(e):
                return jsonify({'code': 409, 'message': '该路径已存在于媒体库中'}), 409
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/media-libraries/<int:lib_id>', methods=['DELETE'])
    def api_delete_media_library(lib_id):
        try:
            delete_media_library(lib_id)
            add_log('INFO', 'media_library', f'删除媒体库 #{lib_id}')
            return jsonify({'code': 0, 'message': '媒体库已删除'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    # ==================== 日志 ====================
    @app.route('/api/logs', methods=['GET'])
    def api_get_logs():
        try:
            limit = request.args.get('limit', 100, type=int)
            level = request.args.get('level')
            logs = get_logs(limit, level)
            return jsonify({'code': 0, 'data': logs})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/app-logs', methods=['GET'])
    def api_app_logs():
        """读取应用日志文件"""
        try:
            import re as _re
            log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'javsp_web.log')
            if not os.path.isfile(log_file):
                return jsonify({'code': 0, 'data': {'lines': [], 'total': 0}})

            level_filter = request.args.get('level', '').upper()
            search = request.args.get('search', '')
            limit = request.args.get('limit', 500, type=int)
            offset = request.args.get('offset', 0, type=int)

            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()

            # 解析日志行: "2026-07-11 00:00:27 [INFO] module: message"
            parsed = []
            pattern = _re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+(\S+):\s+(.*)')
            for line in all_lines:
                line = line.rstrip('\n')
                m = pattern.match(line)
                if m:
                    parsed.append({
                        'time': m.group(1),
                        'level': m.group(2),
                        'module': m.group(3),
                        'message': m.group(4),
                        'raw': line,
                    })
                else:
                    # 续行（上一条的详情）
                    if parsed:
                        parsed[-1]['message'] += '\n' + line
                        parsed[-1]['raw'] += '\n' + line

            # 筛选
            if level_filter:
                parsed = [p for p in parsed if p['level'] == level_filter]
            if search:
                search_lower = search.lower()
                parsed = [p for p in parsed if search_lower in p['message'].lower() or search_lower in p['module'].lower()]

            total = len(parsed)
            # 取最新的 offset 开始的 limit 条（从尾部往前）
            sliced = parsed[max(0, total - offset - limit):total - offset] if offset < total else []
            sliced.reverse()  # 保持最新的在前

            return jsonify({'code': 0, 'data': {'lines': sliced, 'total': total}})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    # ==================== 系统信息 ====================
    @app.route('/api/system/info')
    def api_system_info():
        from javsp.webapp.database import DB_PATH
        import sqlite3
        try:
            with sqlite3.connect(DB_PATH) as conn:
                task_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
                success_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'").fetchone()[0]
                failed_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('failed', 'stopped', 'error')").fetchone()[0]

            watch_paths = get_watch_paths(enabled_only=False)

            return jsonify({
                'code': 0,
                'data': {
                    'total_tasks': task_count,
                    'success_tasks': success_count,
                    'failed_tasks': failed_count,
                    'watch_paths_count': len(watch_paths),
                    'db_size': os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
                }
            })
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    # ==================== 命名检查器 ====================
    @app.route('/api/checker/default-path', methods=['GET'])
    def api_checker_default_path():
        try:
            config = get_config('checker')
            default_path = config.get('checker', {}).get('scan_path', '')
            return jsonify({'code': 0, 'data': {'default_path': default_path or ''}})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/scan', methods=['POST'])
    def api_checker_scan():
        try:
            data = request.get_json() or {}
            path = data.get('path')
            if not path:
                return jsonify({'code': 400, 'message': '路径不能为空'}), 400
            if not os.path.isdir(path):
                return jsonify({'code': 404, 'message': f'目录不存在: {path}'}), 404

            convention = data.get('convention', 'avid')
            task_id = str(uuid.uuid4())

            add_log('INFO', 'checker', f'开始扫描: {path}')

            def _run_scan():
                try:
                    result = scan_directory(
                        path, convention,
                        modified_after=data.get('modified_after'),
                        modified_before=data.get('modified_before'),
                        created_after=data.get('created_after'),
                        created_before=data.get('created_before'),
                        socketio=socketio, task_id=task_id
                    )
                    socketio.emit('scan_progress', {
                        'task_id': task_id,
                        'status': 'completed',
                        'data': result,
                        'message': f'扫描完成: {result["total"]} 个文件, {result["mismatch_count"]} 个有问题',
                    }, namespace='/')
                    add_log('INFO', 'checker', f'扫描完成: {result["total"]} 个文件')
                except Exception as e:
                    logger.exception("扫描失败")
                    socketio.emit('scan_progress', {
                        'task_id': task_id,
                        'status': 'failed',
                        'message': str(e),
                    }, namespace='/')

            thread = threading.Thread(target=_run_scan, daemon=True)
            thread.start()

            return jsonify({'code': 0, 'data': {'task_id': task_id}, 'message': '扫描任务已创建'})
        except Exception as e:
            logger.exception("创建扫描任务失败")
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/scan/cache', methods=['GET'])
    def api_checker_scan_cache():
        try:
            path = request.args.get('path')
            if not path:
                return jsonify({'code': 400, 'message': '路径不能为空'}), 400
            cached = get_scan_cache(path)
            if cached:
                return jsonify({'code': 0, 'data': cached})
            return jsonify({'code': 0, 'data': None})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/fix', methods=['POST'])
    def api_checker_fix():
        try:
            data = request.get_json() or {}
            items = data.get('items', [])
            convention = data.get('convention', 'avid')
            if not items:
                return jsonify({'code': 400, 'message': '未指定修复项'}), 400

            task_id = f'fix-{int(time.time())}'
            add_log('INFO', 'checker', f'开始修复命名: {len(items)} 项')

            def _run_fix():
                try:
                    result = fix_naming_issues(items, convention, socketio, task_id)
                    socketio.emit('fix_progress', {
                        'task_id': task_id,
                        'status': 'completed',
                        'completed': len(items),
                        'total': len(items),
                        'success': len(result.get('success', [])),
                        'failed': len(result.get('failed', [])),
                    }, namespace='/')
                    add_log('INFO', 'checker', f'修复完成: {len(result.get("success", []))} 成功')
                except Exception as e:
                    logger.exception("修复失败")
                    socketio.emit('fix_progress', {
                        'task_id': task_id,
                        'status': 'error',
                        'message': str(e),
                    }, namespace='/')

            thread = threading.Thread(target=_run_fix, daemon=True)
            thread.start()

            return jsonify({'code': 0, 'data': {'task_id': task_id}, 'message': f'修复任务已创建: {len(items)} 项'})
        except Exception as e:
            logger.exception("创建修复任务失败")
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/repair', methods=['POST'])
    def api_checker_repair():
        try:
            data = request.get_json() or {}
            video_paths = data.get('video_paths', [])
            if not video_paths:
                return jsonify({'code': 400, 'message': '未指定视频文件'}), 400

            result = repair_videos(video_paths, socketio)
            if 'error' in result:
                return jsonify({'code': 400, 'message': result['error']}), 400

            return jsonify({'code': 0, 'data': result, 'message': f'刮削任务已创建: {result["total"]} 个文件'})
        except Exception as e:
            logger.exception("创建刮削任务失败")
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/tasks', methods=['GET'])
    def api_checker_tasks():
        try:
            tasks = get_tasks(limit=50)
            return jsonify({'code': 0, 'data': {'history': tasks}})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/tasks/<task_id>', methods=['GET'])
    def api_checker_task_detail(task_id):
        try:
            task = get_task(task_id)
            if not task:
                return jsonify({'code': 404, 'message': '任务不存在'}), 404

            # 提取成功和失败的视频路径
            success = []
            for item in task.get('items', []):
                if item.get('status') == 'success':
                    success.append({
                        'video_path': item.get('source_path', ''),
                        'dest_path': item.get('dest_path', ''),
                    })

            return jsonify({'code': 0, 'data': {'success': success}})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/merge', methods=['POST'])
    def api_checker_merge():
        try:
            data = request.get_json() or {}
            video_paths = data.get('video_paths', [])
            if not video_paths or len(video_paths) < 2:
                return jsonify({'code': 400, 'message': '需要至少 2 个文件'}), 400

            result = merge_duplicates(video_paths)
            if 'error' in result:
                return jsonify({'code': 400, 'message': result['error']}), 400

            return jsonify({'code': 0, 'data': result, 'message': f'合并完成: 保留 {os.path.basename(result["kept"])}'})
        except Exception as e:
            logger.exception("合并失败")
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/logs', methods=['GET'])
    def api_checker_logs():
        try:
            logs = get_logs(limit=50, level=None)
            return jsonify({'code': 0, 'data': {'logs': logs}})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    # ==================== 完整性检查 ====================
    @app.route('/api/checker/integrity', methods=['POST'])
    def api_checker_integrity():
        try:
            data = request.get_json() or {}
            path = data.get('path')
            if not path:
                return jsonify({'code': 400, 'message': '路径不能为空'}), 400
            if not os.path.isdir(path):
                return jsonify({'code': 404, 'message': f'目录不存在: {path}'}), 404
            result = start_integrity_check(path, socketio)
            if 'error' in result:
                return jsonify({'code': 400, 'message': result['error']}), 400
            return jsonify({'code': 0, 'data': result, 'message': '完整性检查已启动'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/integrity/resume', methods=['POST'])
    def api_checker_integrity_resume():
        try:
            data = request.get_json() or {}
            task_id = data.get('task_id')
            if not task_id:
                return jsonify({'code': 400, 'message': '缺少 task_id'}), 400
            result = resume_integrity_check(task_id, socketio)
            if 'error' in result:
                return jsonify({'code': 400, 'message': result['error']}), 400
            return jsonify({'code': 0, 'data': result, 'message': '完整性检查已恢复'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/integrity/stop', methods=['POST'])
    def api_checker_integrity_stop():
        try:
            data = request.get_json() or {}
            task_id = data.get('task_id')
            if not task_id:
                return jsonify({'code': 400, 'message': '缺少 task_id'}), 400
            request_integrity_stop(task_id)
            return jsonify({'code': 0, 'message': '停止信号已发送'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/integrity/tasks', methods=['GET'])
    def api_checker_integrity_tasks():
        try:
            from javsp.webapp.database import get_integrity_tasks
            tasks = get_integrity_tasks(limit=20)
            return jsonify({'code': 0, 'data': tasks})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/integrity/tasks/<task_id>', methods=['GET'])
    def api_checker_integrity_task_detail(task_id):
        try:
            from javsp.webapp.database import get_integrity_task, get_integrity_items
            task = get_integrity_task(task_id)
            if not task:
                return jsonify({'code': 404, 'message': '任务不存在'}), 404
            items = get_integrity_items(task_id)
            task['items'] = items
            return jsonify({'code': 0, 'data': task})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/integrity/delete', methods=['POST'])
    def api_checker_integrity_delete():
        try:
            data = request.get_json() or {}
            video_paths = data.get('video_paths', [])
            item_ids = data.get('item_ids', [])
            if not video_paths:
                return jsonify({'code': 400, 'message': '未指定文件'}), 400
            result = delete_videos(video_paths)
            if result['deleted'] and item_ids:
                from javsp.webapp.database import delete_integrity_items
                delete_integrity_items(item_ids)
            return jsonify({'code': 0, 'data': result, 'message': f'已删除 {len(result["deleted"])} 个文件'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/checker/integrity/task/delete', methods=['POST'])
    def api_checker_integrity_task_delete():
        try:
            data = request.get_json() or {}
            task_id = data.get('task_id')
            if not task_id:
                return jsonify({'code': 400, 'message': '缺少 task_id'}), 400
            from javsp.webapp.database import delete_integrity_task, add_log
            delete_integrity_task(task_id)
            add_log('INFO', 'integrity', f'删除完整性检查任务: {task_id[:8]}')
            return jsonify({'code': 0, 'message': '任务已删除'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    # ==================== 翻译模型管理 ====================

    @app.route('/api/translate/models', methods=['GET'])
    def api_translate_models():
        """获取所有翻译模型配置"""
        try:
            models = get_all_translate_models()
            for m in models:
                m['config_json'] = json.loads(m['config_json'])
            return jsonify({'code': 0, 'data': models})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/translate/model/active', methods=['GET'])
    def api_translate_model_active():
        """获取当前激活的翻译模型"""
        try:
            model = get_active_translate_model()
            return jsonify({'code': 0, 'data': model})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/translate/model', methods=['POST', 'PUT'])
    def api_save_translate_model():
        """保存翻译模型配置（POST新增/PUT更新）"""
        try:
            data = request.get_json()
            name = data.get('name')
            engine = data.get('engine')
            config = data.get('config', {})
            is_active = data.get('is_active', False)
            model_id = data.get('id')
            
            if not name or not engine:
                return jsonify({'code': 400, 'message': '模型名称和引擎不能为空'}), 400
            
            if request.method == 'PUT' and model_id:
                update_translate_model(model_id, name, engine, config, is_active)
            else:
                save_translate_model(name, engine, config, is_active)
            
            if is_active:
                set_active_translate_model(name)
            return jsonify({'code': 0, 'message': '保存成功'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/translate/model/active', methods=['POST'])
    def api_set_active_translate_model():
        """设置激活的翻译模型"""
        try:
            data = request.get_json()
            name = data.get('name')
            if not name:
                return jsonify({'code': 400, 'message': '模型名称不能为空'}), 400
            set_active_translate_model(name)
            return jsonify({'code': 0, 'message': '切换成功'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/translate/model', methods=['DELETE'])
    def api_delete_translate_model():
        """删除翻译模型配置"""
        try:
            data = request.get_json()
            name = data.get('name')
            if not name:
                return jsonify({'code': 400, 'message': '模型名称不能为空'}), 400
            delete_translate_model(name)
            return jsonify({'code': 0, 'message': '删除成功'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    # ==================== 字幕生成 ====================

    @app.route('/api/subtitle/platform', methods=['GET'])
    def api_subtitle_platform():
        """检查平台是否支持字幕生成"""
        try:
            from javsp.webapp.subtitle import check_platform_support
            return jsonify({'code': 0, 'data': check_platform_support()})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/scan', methods=['POST'])
    def api_subtitle_scan():
        """扫描目录下的媒体文件并保存结果"""
        try:
            data = request.get_json() or {}
            path = data.get('path')
            if not path:
                return jsonify({'code': 400, 'message': '缺少路径'}), 400
            from javsp.webapp.subtitle import scan_media_files, refresh_scan_extracted_status
            from javsp.webapp.database import save_subtitle_scan_results, get_subtitle_scan_results
            files = scan_media_files(path)
            save_subtitle_scan_results(path, files)
            refresh_scan_extracted_status()
            results = get_subtitle_scan_results(path)
            return jsonify({'code': 0, 'data': {'files': results, 'total': len(results)}})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/scan_results', methods=['GET'])
    def api_subtitle_scan_results():
        """获取已保存的扫描结果"""
        try:
            path = request.args.get('path')
            if not path:
                return jsonify({'code': 400, 'message': '缺少路径'}), 400
            from javsp.webapp.database import get_subtitle_scan_results
            from javsp.webapp.subtitle import refresh_scan_extracted_status
            refresh_scan_extracted_status()
            results = get_subtitle_scan_results(path)
            return jsonify({'code': 0, 'data': {'files': results, 'total': len(results)}})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/start', methods=['POST'])
    def api_subtitle_start():
        """创建字幕任务（第一步：音频提取）"""
        try:
            data = request.get_json() or {}
            path = data.get('path')
            files = data.get('files')
            name = data.get('name', '')
            if not path:
                return jsonify({'code': 400, 'message': '缺少路径'}), 400

            # 校验文件存在性，丢失的文件从扫描结果中删除并返回错误
            from javsp.webapp.subtitle import validate_files_exist
            from javsp.webapp.database import delete_subtitle_scan_result
            valid_files, missing_files = validate_files_exist(files or [])
            if missing_files:
                for mf in missing_files:
                    p = mf.get('path') or mf.get('video_path')
                    if p:
                        delete_subtitle_scan_result(p)
            if not valid_files:
                return jsonify({'code': 400, 'message': '选中的文件已不存在，已从列表移除'}), 400

            from javsp.webapp.subtitle import start_subtitle_task
            import time as _time, datetime as _dt
            now = _dt.datetime.now()
            task_id = now.strftime('subtitle-%Y%m%d-%H%M%S')
            if not name:
                name = now.strftime('%Y-%m-%d %H:%M:%S')
            result = start_subtitle_task(task_id, name, path, files=valid_files, socketio=socketio)
            if 'error' in result:
                return jsonify({'code': 400, 'message': result['error']}), 400
            return jsonify({'code': 0, 'data': result})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/stop', methods=['POST'])
    def api_subtitle_stop():
        """停止字幕任务"""
        try:
            data = request.get_json() or {}
            task_id = data.get('task_id')
            if not task_id:
                return jsonify({'code': 400, 'message': '缺少 task_id'}), 400
            from javsp.webapp.subtitle import request_subtitle_stop
            request_subtitle_stop(task_id)
            return jsonify({'code': 0, 'message': '停止信号已发送'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/generate', methods=['POST'])
    def api_subtitle_generate():
        """启动字幕生成（第二步：音频 → 字幕）"""
        try:
            data = request.get_json() or {}
            task_id = data.get('task_id')
            if not task_id:
                return jsonify({'code': 400, 'message': '缺少 task_id'}), 400
            from javsp.webapp.subtitle import start_subtitle_generate
            result = start_subtitle_generate(task_id, socketio)
            if 'error' in result:
                return jsonify({'code': 400, 'message': result['error']}), 400
            return jsonify({'code': 0, 'data': result})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/generate_video', methods=['POST'])
    def api_subtitle_generate_video():
        """仅生成指定视频的字幕"""
        try:
            data = request.get_json() or {}
            task_id = data.get('task_id')
            video_path = data.get('video_path')
            if not task_id or not video_path:
                return jsonify({'code': 400, 'message': '缺少 task_id 或 video_path'}), 400
            from javsp.webapp.subtitle import start_subtitle_generate_for_video
            result = start_subtitle_generate_for_video(task_id, video_path, socketio)
            if 'error' in result:
                return jsonify({'code': 400, 'message': result['error']}), 400
            return jsonify({'code': 0, 'data': result})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/tasks', methods=['GET'])
    def api_subtitle_tasks():
        """获取字幕任务列表"""
        try:
            from javsp.webapp.database import get_subtitle_tasks
            tasks = get_subtitle_tasks()
            return jsonify({'code': 0, 'data': tasks})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/tasks/<task_id>', methods=['GET'])
    def api_subtitle_task_detail(task_id):
        """获取字幕任务详情"""
        try:
            from javsp.webapp.database import get_subtitle_task, get_subtitle_items
            task = get_subtitle_task(task_id)
            if not task:
                return jsonify({'code': 404, 'message': '任务不存在'}), 404
            items = get_subtitle_items(task_id)
            task['items'] = items
            return jsonify({'code': 0, 'data': task})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/task/delete', methods=['POST'])
    def api_subtitle_task_delete():
        """删除字幕任务"""
        try:
            data = request.get_json() or {}
            task_id = data.get('task_id')
            if not task_id:
                return jsonify({'code': 400, 'message': '缺少 task_id'}), 400
            from javsp.webapp.database import delete_subtitle_task, add_log
            delete_subtitle_task(task_id)
            add_log('INFO', 'subtitle', f'删除字幕任务: {task_id[:8]}')
            return jsonify({'code': 0, 'message': '任务已删除'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/regenerate', methods=['POST'])
    def api_subtitle_regenerate():
        """重新生成指定项的字幕（重置状态为 pending）"""
        try:
            data = request.get_json() or {}
            item_ids = data.get('item_ids', [])
            if not item_ids:
                return jsonify({'code': 400, 'message': '缺少 item_ids'}), 400
            from javsp.webapp.database import update_subtitle_item
            for item_id in item_ids:
                update_subtitle_item(item_id, subtitle_status='pending', subtitle_path=None,
                                     errors=None, subtitle_started_at=None, subtitle_finished_at=None)
            return jsonify({'code': 0, 'message': f'已重置 {len(item_ids)} 项，可重新生成字幕'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/delete-audio', methods=['POST'])
    def api_subtitle_delete_audio():
        """删除指定项的音轨文件"""
        try:
            data = request.get_json() or {}
            item_ids = data.get('item_ids', [])
            if not item_ids:
                return jsonify({'code': 400, 'message': '缺少 item_ids'}), 400
            from javsp.webapp.subtitle import delete_audio_files_for_items
            result = delete_audio_files_for_items(item_ids)
            return jsonify({'code': 0, 'data': result, 'message': f'已删除 {len(result["deleted"])} 个音轨文件'})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/audio-tracks', methods=['GET'])
    def api_subtitle_audio_tracks():
        """获取视频的音轨列表"""
        try:
            path = request.args.get('path')
            if not path:
                return jsonify({'code': 400, 'message': '缺少路径'}), 400
            from javsp.webapp.subtitle import get_audio_tracks
            tracks = get_audio_tracks(path)
            return jsonify({'code': 0, 'data': tracks})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/search', methods=['POST'])
    def api_subtitle_search():
        """搜索单个视频的字幕（优先迅雷，然后射手网）"""
        try:
            data = request.get_json() or {}
            video_path = data.get('video_path')
            if not video_path:
                return jsonify({'code': 400, 'message': '缺少 video_path'}), 400
            from javsp.webapp.subtitle import search_subtitle_for_video
            result = search_subtitle_for_video(video_path)
            if not result['ok']:
                return jsonify({'code': 400, 'message': result['errors']}), 400
            return jsonify({'code': 0, 'data': {'results': result['results'], 'count': result['count']}})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/batch_search', methods=['POST'])
    def api_subtitle_batch_search():
        """批量搜索字幕"""
        try:
            data = request.get_json() or {}
            files = data.get('files', [])
            if not files:
                return jsonify({'code': 400, 'message': '缺少文件列表'}), 400
            from javsp.webapp.subtitle import batch_search_subtitles
            result = batch_search_subtitles(files)
            return jsonify({'code': 0, 'data': result})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/download', methods=['POST'])
    def api_subtitle_download():
        """下载选中的字幕文件"""
        try:
            data = request.get_json() or {}
            video_path = data.get('video_path')
            video_dir = data.get('video_dir')
            video_basename = data.get('video_basename')
            subtitle_result = data.get('subtitle_result')
            if not video_path or not subtitle_result:
                return jsonify({'code': 400, 'message': '缺少必要参数'}), 400
            from javsp.webapp.subtitle import download_selected_subtitle
            result = download_selected_subtitle(video_path, video_dir, video_basename, subtitle_result)
            if not result['ok']:
                return jsonify({'code': 400, 'message': result['errors']}), 400
            return jsonify({'code': 0, 'data': result})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/batch_delete_audio', methods=['POST'])
    def api_subtitle_batch_delete_audio():
        """批量删除音轨文件"""
        try:
            data = request.get_json() or {}
            files = data.get('files', [])
            if not files:
                return jsonify({'code': 400, 'message': '缺少文件列表'}), 400
            from javsp.webapp.subtitle import batch_delete_audio
            result = batch_delete_audio(files)
            return jsonify({'code': 0, 'data': result})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500

    @app.route('/api/subtitle/batch_delete_subtitle', methods=['POST'])
    def api_subtitle_batch_delete_subtitle():
        """批量删除字幕文件"""
        try:
            data = request.get_json() or {}
            files = data.get('files', [])
            if not files:
                return jsonify({'code': 400, 'message': '缺少文件列表'}), 400
            from javsp.webapp.subtitle import batch_delete_subtitle
            result = batch_delete_subtitle(files)
            return jsonify({'code': 0, 'data': result})
        except Exception as e:
            return jsonify({'code': 500, 'message': str(e)}), 500
