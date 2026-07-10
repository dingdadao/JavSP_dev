"""SQLite 数据库模块 - 存储 Web 应用配置和任务历史"""

import os
import sqlite3
import json
import logging
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger('javsp.webapp.db')

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'javsp_web.db')


@contextmanager
def get_db():
    """获取数据库连接的上下文管理器"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化数据库表结构"""
    with get_db() as conn:
        conn.executescript("""
            -- 配置表：键值对存储，支持分组
            CREATE TABLE IF NOT EXISTS config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                key_name TEXT NOT NULL,
                value TEXT,
                value_type TEXT NOT NULL DEFAULT 'str',
                description TEXT,
                default_value TEXT,
                UNIQUE(group_name, key_name)
            );

            -- 刮削任务表
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                source_path TEXT NOT NULL,
                dest_path TEXT NOT NULL,
                total INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                task_type TEXT NOT NULL DEFAULT 'manual',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                config_snapshot TEXT
            );

            -- 任务详情表：每部影片的刮削结果
            CREATE TABLE IF NOT EXISTS task_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                dvdid TEXT,
                source_path TEXT,
                dest_path TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                message TEXT,
                scraped_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            -- 文件监控表
            CREATE TABLE IF NOT EXISTS watch_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 操作日志表
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                module TEXT,
                message TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 媒体库表
            CREATE TABLE IF NOT EXISTS media_library (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_task_items_task_id ON task_items(task_id);
            CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at);
        """)
    logger.info(f"数据库初始化完成: {DB_PATH}")


def seed_default_config():
    """从 config.yml 填充默认配置值到数据库"""
    config_defaults = [
        # scanner 配置
        ('scanner', 'input_directory', '', 'str', '扫描的源文件夹路径', ''),
        ('scanner', 'output_directory', '', 'str', '整理输出的目标文件夹路径', ''),
        ('scanner', 'minimum_size', '232MiB', 'str', '匹配番号时忽略小于指定大小的文件', '232MiB'),
        ('scanner', 'skip_nfo_dir', 'false', 'bool', '跳过已有NFO文件的目录', 'false'),
        ('scanner', 'clear_skipped_on_rescan', 'true', 'bool', '重新扫描时清理 .skipped 文件', 'true'),
        ('scanner', 'filename_extensions', json.dumps([
            '.3gp', '.avi', '.f4v', '.flv', '.iso', '.m2ts', '.m4v', '.mkv',
            '.mov', '.mp4', '.mpeg', '.rm', '.rmvb', '.ts', '.vob', '.webm',
            '.wmv', '.strm', '.mpg'
        ]), 'json', '视为影片的文件后缀', json.dumps(['.mkv', '.mp4', '.avi'])),
        ('scanner', 'ignored_folder_name_pattern', json.dumps([
            '^\\.', '^#recycle$', '^#整理完成$', '^#不要扫描$'
        ]), 'json', '扫描时忽略的文件夹名正则', json.dumps(['^\\.'])),

        # network 配置
        ('network', 'proxy_server', '', 'str', '代理服务器地址 (留空禁用)', ''),
        ('network', 'retry', '3', 'int', '抓取失败重试次数', '3'),
        ('network', 'timeout', 'PT10S', 'str', '网络请求超时 (ISO 8601 Duration)', 'PT10S'),
        ('network', 'ssl_verification', 'true', 'bool', '是否验证 SSL 证书', 'true'),
        ('network', 'crawler_mirror', '{}', 'json', '爬虫镜像地址 (JSON对象，配置后优先使用)', '{}'),

        # crawler 配置
        ('crawler', 'selection_normal', json.dumps(['javdb', 'arzon', 'airav', 'mgstage', 'prestige', 'javbus']),
         'json', '普通影片使用的爬虫列表', json.dumps(['javdb', 'arzon', 'airav', 'mgstage', 'prestige', 'javbus'])),
        ('crawler', 'selection_fc2', json.dumps(['fc2', 'avsox', 'javdb', 'javmenu', 'fc2ppvdb']),
         'json', 'FC2影片使用的爬虫列表', json.dumps(['fc2', 'avsox', 'javdb', 'javmenu'])),
        ('crawler', 'hardworking', 'true', 'bool', '努力爬取更丰富的信息', 'true'),
        ('crawler', 'sleep_after_scraping', 'PT1S', 'str', '刮削后等待时间 (ISO 8601)', 'PT1S'),

        # summarizer 配置
        ('summarizer', 'move_files', 'true', 'bool', '整理时是否移动文件', 'true'),
        ('summarizer', 'output_folder_pattern', '', 'str', '输出文件夹路径模式', ''),
        ('summarizer', 'basename_pattern', '{title}', 'str', '文件命名规则', '{title}'),
        ('summarizer', 'nfo_title_pattern', '{title}', 'str', 'NFO 中的标题格式', '{title}'),

        # translator 配置
        ('translator', 'engine', '', 'str', '翻译引擎 (google/bing/baidu/openai/localai)', ''),
        ('translator', 'translate_title', 'true', 'bool', '是否翻译标题', 'true'),
        ('translator', 'translate_plot', 'true', 'bool', '是否翻译剧情简介', 'true'),
        ('translator', 'api_url', '', 'str', '翻译API地址', ''),
        ('translator', 'api_key', '', 'str', '翻译API密钥', ''),
        ('translator', 'model', '', 'str', '翻译模型名称', ''),

        # cover 配置
        ('cover', 'highres', 'true', 'bool', '下载高清封面', 'true'),
        ('cover', 'add_label', 'false', 'bool', '在封面添加水印标签', 'false'),

        # 文件监控配置
        ('watcher', 'enabled', 'false', 'bool', '启用文件变动自动监控', 'false'),
        ('watcher', 'auto_scrape', 'true', 'bool', '检测到新文件后自动刮削', 'true'),
    ]

    with get_db() as conn:
        for group, key, value, vtype, desc, default in config_defaults:
            conn.execute("""
                INSERT OR IGNORE INTO config (group_name, key_name, value, value_type, description, default_value)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (group, key, value, vtype, desc, default))

    logger.info("默认配置已填充到数据库")


def get_config(group: str = None) -> dict:
    """获取配置，可按组筛选"""
    with get_db() as conn:
        if group:
            rows = conn.execute("SELECT * FROM config WHERE group_name = ?", (group,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM config ORDER BY group_name, key_name").fetchall()

        result = {}
        for row in rows:
            g = row['group_name']
            if g not in result:
                result[g] = {}
            value = row['value'] if row['value'] else row['default_value']
            # 类型转换
            if row['value_type'] == 'bool':
                value = value.lower() in ('true', '1', 'yes')
            elif row['value_type'] == 'int':
                value = int(value) if value else 0
            elif row['value_type'] == 'json':
                value = json.loads(value) if value else json.loads(row['default_value'] or '[]')
            result[g][row['key_name']] = value

        return result


def update_config(group: str, key: str, value):
    """更新配置项"""
    with get_db() as conn:
        if isinstance(value, bool):
            value = 'true' if value else 'false'
        elif isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, int):
            value = str(value)
        conn.execute("""
            UPDATE config SET value = ? WHERE group_name = ? AND key_name = ?
        """, (value, group, key))


def batch_update_config(updates: list[dict]):
    """批量更新配置项
    updates: [{'group': 'scanner', 'key': 'input_directory', 'value': '/path'}]
    """
    with get_db() as conn:
        for item in updates:
            value = item['value']
            if isinstance(value, bool):
                value = 'true' if value else 'false'
            elif isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, int):
                value = str(value)
            conn.execute("""
                UPDATE config SET value = ? WHERE group_name = ? AND key_name = ?
            """, (value, item['group'], item['key']))


# 任务相关操作
def create_task(task_id: str, source: str, dest: str, total: int, task_type: str = 'manual') -> dict:
    """创建新任务"""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO tasks (id, status, source_path, dest_path, total, task_type, started_at)
            VALUES (?, 'running', ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (task_id, source, dest, total, task_type))
    return {'id': task_id, 'status': 'running', 'total': total}


def update_task(task_id: str, **kwargs):
    """更新任务字段"""
    allowed = {'status', 'completed', 'success_count', 'failed_count', 'finished_at'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ', '.join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    with get_db() as conn:
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)


def add_task_item(task_id: str, dvdid: str, source_path: str, status: str = 'pending'):
    """添加任务项"""
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO task_items (task_id, dvdid, source_path, status)
            VALUES (?, ?, ?, ?)
        """, (task_id, dvdid, source_path, status))
        return cursor.lastrowid


def update_task_item(item_id: int, **kwargs):
    """更新任务项"""
    allowed = {'status', 'message', 'dest_path', 'scraped_data', 'finished_at'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    if 'scraped_data' in fields and isinstance(fields['scraped_data'], dict):
        fields['scraped_data'] = json.dumps(fields['scraped_data'], ensure_ascii=False)
    set_clause = ', '.join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [item_id]
    with get_db() as conn:
        conn.execute(f"UPDATE task_items SET {set_clause} WHERE id = ?", values)


def get_task(task_id: str) -> dict:
    """获取任务详情"""
    with get_db() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return None
        task = dict(task)
        items = conn.execute(
            "SELECT * FROM task_items WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
        task['items'] = [dict(i) for i in items]
        return task


def get_tasks(limit: int = 50, offset: int = 0, status: str = None) -> list:
    """获取任务列表"""
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
        return [dict(r) for r in rows]


def add_log(level: str, module: str, message: str, details: str = None):
    """添加操作日志"""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO logs (level, module, message, details) VALUES (?, ?, ?, ?)
        """, (level, module, message, details))


def get_logs(limit: int = 100, level: str = None) -> list:
    """获取日志"""
    with get_db() as conn:
        if level:
            rows = conn.execute(
                "SELECT * FROM logs WHERE level = ? ORDER BY created_at DESC LIMIT ?",
                (level, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


# 文件监控相关
def add_watch_path(path: str):
    """添加监控路径"""
    with get_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO watch_paths (path, enabled) VALUES (?, 1)
        """, (path,))


def remove_watch_path(path: str):
    """移除监控路径"""
    with get_db() as conn:
        conn.execute("DELETE FROM watch_paths WHERE path = ?", (path,))


def get_watch_paths(enabled_only: bool = True) -> list:
    """获取监控路径列表"""
    with get_db() as conn:
        if enabled_only:
            rows = conn.execute("SELECT * FROM watch_paths WHERE enabled = 1").fetchall()
        else:
            rows = conn.execute("SELECT * FROM watch_paths ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def toggle_watch_path(path: str, enabled: bool):
    """启用/禁用监控路径"""
    with get_db() as conn:
        conn.execute("UPDATE watch_paths SET enabled = ? WHERE path = ?", (1 if enabled else 0, path))


# 媒体库相关
def get_media_libraries() -> list:
    """获取所有媒体库"""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM media_library ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_default_media_library() -> dict:
    """获取默认媒体库"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM media_library WHERE is_default = 1 LIMIT 1").fetchone()
        if row:
            return dict(row)
        # 没有默认的，返回第一个
        row = conn.execute("SELECT * FROM media_library ORDER BY created_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def add_media_library(name: str, path: str, is_default: bool = False) -> int:
    """添加媒体库"""
    with get_db() as conn:
        # 如果设为默认，先取消其他默认
        if is_default:
            conn.execute("UPDATE media_library SET is_default = 0")
        # 如果是第一个库，自动设为默认
        count = conn.execute("SELECT COUNT(*) FROM media_library").fetchone()[0]
        if count == 0:
            is_default = True
        cursor = conn.execute(
            "INSERT INTO media_library (name, path, is_default) VALUES (?, ?, ?)",
            (name, path, 1 if is_default else 0)
        )
        return cursor.lastrowid


def update_media_library(lib_id: int, name: str = None, path: str = None, is_default: bool = None):
    """更新媒体库"""
    with get_db() as conn:
        if is_default is not None:
            conn.execute("UPDATE media_library SET is_default = 0")
            conn.execute("UPDATE media_library SET is_default = 1 WHERE id = ?", (lib_id,))
        if name is not None:
            conn.execute("UPDATE media_library SET name = ? WHERE id = ?", (name, lib_id))
        if path is not None:
            conn.execute("UPDATE media_library SET path = ? WHERE id = ?", (path, lib_id))


def delete_media_library(lib_id: int):
    """删除媒体库"""
    with get_db() as conn:
        was_default = conn.execute("SELECT is_default FROM media_library WHERE id = ?", (lib_id,)).fetchone()
        conn.execute("DELETE FROM media_library WHERE id = ?", (lib_id,))
        # 如果删的是默认库，把第一个设为默认
        if was_default and was_default[0]:
            first = conn.execute("SELECT id FROM media_library ORDER BY created_at LIMIT 1").fetchone()
            if first:
                conn.execute("UPDATE media_library SET is_default = 1 WHERE id = ?", (first[0],))
