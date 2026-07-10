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
    add_media_library, update_media_library, delete_media_library
)
from javsp.webapp.scraper import run_scrape_task, request_stop, is_stop_requested

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

    # ==================== 系统信息 ====================
    @app.route('/api/system/info')
    def api_system_info():
        from javsp.webapp.database import DB_PATH
        import sqlite3
        try:
            with sqlite3.connect(DB_PATH) as conn:
                task_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
                success_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'").fetchone()[0]
                failed_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'failed'").fetchone()[0]

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
