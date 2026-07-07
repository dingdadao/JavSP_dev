"""文件监控模块 - 使用 watchdog 监控目录变动，自动触发刮削"""

import os
import time
import uuid
import logging
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from javsp.webapp.database import get_config, get_watch_paths, add_log

logger = logging.getLogger('javsp.webapp.watcher')

# 全局观察者
_observer = None
_observer_lock = threading.Lock()

# 视频文件后缀（与 scanner 配置一致）
DEFAULT_VIDEO_EXTENSIONS = {
    '.3gp', '.avi', '.f4v', '.flv', '.iso', '.m2ts', '.m4v', '.mkv',
    '.mov', '.mp4', '.mpeg', '.rm', '.rmvb', '.ts', '.vob', '.webm',
    '.wmv', '.strm', '.mpg'
}

# 防抖：新文件创建后等待一段时间再触发刮削（文件可能还在复制中）
DEBOUNCE_SECONDS = 30


class ScrapeEventHandler(FileSystemEventHandler):
    """监控文件变动，新视频文件创建后自动触发刮削"""

    def __init__(self, socketio):
        super().__init__()
        self.socketio = socketio
        self._pending = {}  # path -> timestamp
        self._debounce_timer = None
        self._lock = threading.Lock()

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle_file(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        self._handle_file(event.dest_path)

    def _handle_file(self, filepath: str):
        """处理新出现的文件"""
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in self._get_video_extensions():
            return

        logger.info(f"检测到新视频文件: {filepath}")
        add_log('INFO', 'watcher', f'检测到新文件: {os.path.basename(filepath)}')

        with self._lock:
            self._pending[filepath] = time.time()

        # 启动防抖定时器
        if self._debounce_timer:
            self._debounce_timer.cancel()
        self._debounce_timer = threading.Timer(DEBOUNCE_SECONDS, self._process_pending)
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

    def _get_video_extensions(self) -> set:
        """从配置获取视频文件后缀"""
        try:
            config = get_config('scanner')
            extensions = config.get('scanner', {}).get('filename_extensions', [])
            if extensions:
                return set(e.lower() if e.startswith('.') else f'.{e.lower()}' for e in extensions)
        except Exception:
            pass
        return DEFAULT_VIDEO_EXTENSIONS

    def _process_pending(self):
        """处理待刮削的文件"""
        with self._lock:
            pending = self._pending.copy()
            self._pending.clear()

        if not pending:
            return

        # 按目录分组（同一目录下的文件只触发一次刮削）
        dirs_to_scrape = set()
        for filepath in pending:
            dirs_to_scrape.add(os.path.dirname(filepath))

        for dir_path in dirs_to_scrape:
            logger.info(f"自动触发刮削: {dir_path}")
            add_log('INFO', 'watcher', f'自动触发刮削: {dir_path}')
            self.socketio.emit('watcher_event', {
                'type': 'auto_scrape',
                'path': dir_path,
                'files': [os.path.basename(f) for f in pending if os.path.dirname(f) == dir_path],
                'message': f'检测到新文件，自动触发刮削: {dir_path}'
            }, namespace='/')

            # 异步触发刮削
            self._trigger_scrape(dir_path)

    def _trigger_scrape(self, source_dir: str):
        """触发异步刮削任务"""
        from javsp.webapp.scraper import run_scrape_task

        config = get_config()
        scanner_cfg = config.get('scanner', {})
        summarizer_cfg = config.get('summarizer', {})

        dest = summarizer_cfg.get('output_folder_pattern', '')
        if not dest:
            logger.warning("未配置输出路径，跳过自动刮削")
            add_log('WARNING', 'watcher', '未配置输出路径，跳过自动刮削')
            return

        translate = config.get('translator', {}).get('translate_title', True)
        move_files = summarizer_cfg.get('move_files', True)

        task_id = str(uuid.uuid4())
        thread = threading.Thread(
            target=run_scrape_task,
            args=(task_id, source_dir, dest, translate, move_files, self.socketio),
            daemon=True
        )
        thread.start()


def setup_watcher(socketio):
    """设置并启动文件监控"""
    global _observer

    config = get_config('watcher')
    watcher_cfg = config.get('watcher', {})

    if not watcher_cfg.get('enabled', False):
        logger.info("文件监控未启用")
        return

    watch_paths = get_watch_paths(enabled_only=True)
    if not watch_paths:
        logger.info("没有配置监控路径")
        return

    with _observer_lock:
        if _observer:
            _observer.stop()
            _observer.join(timeout=5)

        handler = ScrapeEventHandler(socketio)
        _observer = Observer()
        _observer.daemon = True

        for wp in watch_paths:
            path = wp['path']
            if os.path.isdir(path):
                _observer.schedule(handler, path, recursive=True)
                logger.info(f"开始监控: {path}")
                add_log('INFO', 'watcher', f'开始监控: {path}')

        _observer.start()


def reload_watcher(socketio):
    """重新加载文件监控（配置变更后调用）"""
    setup_watcher(socketio)
