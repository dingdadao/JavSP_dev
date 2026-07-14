"""JavSP Web Application - Flask + SocketIO 主应用"""

import os
import sys
import logging
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

from javsp.webapp.database import init_db, seed_default_config, migrate_config, DB_PATH

logger = logging.getLogger('javsp.webapp')

# 前端构建产物目录
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend', 'dist')


def create_app():
    """创建 Flask 应用"""
    app = Flask(__name__, static_folder=None)
    CORS(app)

    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', logger=False,
                        engineio_logger=False)

    # 初始化数据库
    init_db()
    seed_default_config()
    migrate_config()

    # 注册 API 蓝图
    from javsp.webapp.routes import register_routes
    register_routes(app, socketio)

    # 注册文件监控
    from javsp.webapp.watcher import setup_watcher
    setup_watcher(socketio)

    # 前端静态文件服务
    if os.path.isdir(FRONTEND_DIST):
        @app.route('/')
        def serve_index():
            return send_from_directory(FRONTEND_DIST, 'index.html')

        @app.route('/<path:path>')
        def serve_static(path):
            file_path = os.path.join(FRONTEND_DIST, path)
            if os.path.isfile(file_path):
                return send_from_directory(FRONTEND_DIST, path)
            return send_from_directory(FRONTEND_DIST, 'index.html')
    else:
        @app.route('/')
        def no_frontend():
            return jsonify({
                'message': 'JavSP Web API 已运行，但前端未构建',
                'hint': '请运行: cd javsp/webapp/frontend && npm install && npm run build'
            })

    return app, socketio


def run_web_server(host='0.0.0.0', port=5001, debug=False):
    """启动 Web 服务器"""
    app, socketio = create_app()
    logger.info(f"JavSP Web 启动: http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
