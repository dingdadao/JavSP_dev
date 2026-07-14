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

            -- 完整性检查任务表
            CREATE TABLE IF NOT EXISTS integrity_tasks (
                id TEXT PRIMARY KEY,
                scan_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                total INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                ok_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                finished_at TIMESTAMP
            );

            -- 完整性检查项表
            CREATE TABLE IF NOT EXISTS integrity_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                video_path TEXT NOT NULL,
                video_basename TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                errors TEXT,
                checked_at TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES integrity_tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_task_items_task_id ON task_items(task_id);
            CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_integrity_items_task_id ON integrity_items(task_id);

            -- 字幕生成任务表
            CREATE TABLE IF NOT EXISTS subtitle_tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                scan_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                total INTEGER NOT NULL DEFAULT 0,
                audio_completed INTEGER NOT NULL DEFAULT 0,
                subtitle_completed INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                finished_at TIMESTAMP
            );

            -- 字幕生成项表（每个音轨一条记录）
            CREATE TABLE IF NOT EXISTS subtitle_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                video_path TEXT NOT NULL,
                video_basename TEXT NOT NULL,
                video_dir TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                track_index INTEGER NOT NULL DEFAULT 0,
                track_language TEXT,
                track_title TEXT,
                track_codec TEXT,
                audio_path TEXT,
                audio_status TEXT NOT NULL DEFAULT 'pending',
                audio_duration REAL,
                subtitle_path TEXT,
                subtitle_status TEXT NOT NULL DEFAULT 'pending',
                subtitle_format TEXT DEFAULT 'srt',
                whisper_model TEXT,
                whisper_language TEXT,
                errors TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                audio_started_at TIMESTAMP,
                audio_finished_at TIMESTAMP,
                subtitle_started_at TIMESTAMP,
                subtitle_finished_at TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES subtitle_tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_subtitle_items_task_id ON subtitle_items(task_id);

            -- 字幕扫描结果表（缓存扫描到的视频文件，支持文件丢失检测）
            CREATE TABLE IF NOT EXISTS subtitle_scan_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_path TEXT NOT NULL,
                video_path TEXT NOT NULL,
                video_basename TEXT NOT NULL,
                video_dir TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                file_exists INTEGER NOT NULL DEFAULT 1,
                extracted INTEGER NOT NULL DEFAULT 0,
                scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scan_path, video_path)
            );

            CREATE INDEX IF NOT EXISTS idx_subtitle_scan_path ON subtitle_scan_results(scan_path);
            CREATE INDEX IF NOT EXISTS idx_subtitle_scan_video ON subtitle_scan_results(video_path);

            -- 翻译模型配置表：支持保存多个模型配置
            CREATE TABLE IF NOT EXISTS translate_models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                engine TEXT NOT NULL,
                config_json TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_translate_models_active ON translate_models(is_active);
        """)

    # 迁移：为旧表添加音轨字段
    with get_db() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(subtitle_items)").fetchall()]
        if 'track_index' not in cols:
            conn.execute("ALTER TABLE subtitle_items ADD COLUMN track_index INTEGER NOT NULL DEFAULT 0")
        if 'track_language' not in cols:
            conn.execute("ALTER TABLE subtitle_items ADD COLUMN track_language TEXT")
        if 'track_title' not in cols:
            conn.execute("ALTER TABLE subtitle_items ADD COLUMN track_title TEXT")
        if 'track_codec' not in cols:
            conn.execute("ALTER TABLE subtitle_items ADD COLUMN track_codec TEXT")

        # 迁移：添加扫描结果表字段
        cols_scan = [r[1] for r in conn.execute("PRAGMA table_info(subtitle_scan_results)").fetchall()]
        if 'file_exists' not in cols_scan:
            conn.execute("ALTER TABLE subtitle_scan_results ADD COLUMN file_exists INTEGER NOT NULL DEFAULT 1")
        if 'extracted' not in cols_scan:
            conn.execute("ALTER TABLE subtitle_scan_results ADD COLUMN extracted INTEGER NOT NULL DEFAULT 0")

        # 服务重启后，内存中的 stop_event 丢失，旧 running 状态的任务无法继续/停止，统一重置为 stopped
        conn.execute(
            "UPDATE subtitle_tasks SET status = 'stopped' WHERE status IN ('running', 'subtitle_running')"
        )

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
        ('scanner', 'check_file_integrity', 'true', 'bool', '刮削前使用 ffmpeg 检查视频文件完整性', 'true'),
        ('scanner', 'filename_extensions', json.dumps([
            '.3gp', '.avi', '.f4v', '.flv', '.iso', '.m2ts', '.m4v', '.mkv',
            '.mov', '.mp4', '.mpeg', '.rm', '.rmvb', '.ts', '.vob', '.webm',
            '.wmv', '.strm', '.mpg'
        ]), 'json', '视为影片的文件后缀', json.dumps(['.mkv', '.mp4', '.avi'])),
        ('scanner', 'ignored_folder_name_pattern', json.dumps([
            '^\\.', '^#recycle$', '^#整理完成$', '^#不要扫描$'
        ]), 'json', '扫描时忽略的文件夹名正则', json.dumps(['^\\.'])),
        ('scanner', 'ignored_id_pattern', json.dumps([
            '(144|240|360|480|720|1080)[Pp]',
            '[24][Kk]',
            '\\w+2048\\.com',
            'Carib(beancom)?',
            '[^a-z\\d](f?hd|lt)[^a-z\\d]',
        ]), 'json', '匹配番号时忽略的正则表达式', json.dumps([])),

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
        ('crawler', 'required_keys', json.dumps(['cover', 'title']),
         'json', '爬虫至少要获取到哪些字段才算抓取成功', json.dumps(['cover', 'title'])),
        ('crawler', 'respect_site_avid', 'true', 'bool', '使用网页番号作为最终番号（会对番号大小写进行更正）', 'true'),
        ('crawler', 'use_javdb_cover', 'fallback', 'str', '是否使用javdb的封面 (yes/no/fallback)', 'fallback'),
        ('crawler', 'normalize_actress_name', 'true', 'bool', '统一女优艺名（将多个艺名统一成一个）', 'true'),

        # summarizer 配置
        ('summarizer', 'move_files', 'true', 'bool', '整理时是否移动文件', 'true'),
        ('summarizer', 'output_folder_pattern', '', 'str', '输出文件夹路径模式', ''),
        ('summarizer', 'basename_pattern', '{title}', 'str', '文件命名规则（封面、NFO等）', '{title}'),
        ('summarizer', 'file_basename_pattern', '', 'str', '影片文件单独命名规则（留空则使用上方规则）', ''),
        ('summarizer', 'nfo_title_pattern', '{title}', 'str', 'NFO 中的标题格式', '{title}'),
        ('summarizer', 'hard_link', 'false', 'bool', '使用硬链接方式整理文件（节省空间）', 'false'),
        ('summarizer', 'length_maximum', '250', 'int', '允许的最长文件路径', '250'),
        ('summarizer', 'max_actress_count', '10', 'int', '路径中 {actress} 最多包含多少名女优', '10'),
        ('summarizer', 'remove_trailing_actor_name', 'true', 'bool', '删除标题尾部可能存在的女优名', 'true'),
        ('summarizer', 'cover_basename', 'poster', 'str', '封面文件名（不含扩展名）', 'poster'),
        ('summarizer', 'fanart_basename', 'fanart', 'str', '横版封面文件名（不含扩展名）', 'fanart'),
        ('summarizer', 'nfo_basename', '[{num}]', 'str', 'NFO文件名（不含扩展名）', '[{num}]'),
        ('summarizer', 'extra_fanarts_enabled', 'true', 'bool', '是否下载剧照', 'true'),
        ('summarizer', 'extra_fanarts_concurrent', '3', 'int', '并发下载剧照数量', '3'),
        ('summarizer', 'extra_fanarts_max', '6', 'int', '最大下载剧照数量（0=不限制）', '6'),
        ('summarizer', 'censor_repr_0', '无码', 'str', '已知无码时 {censor} 的文本', '无码'),
        ('summarizer', 'censor_repr_1', '有码', 'str', '已知有码时 {censor} 的文本', '有码'),
        ('summarizer', 'censor_repr_2', '打码情况未知', 'str', '不确定时 {censor} 的文本', '打码情况未知'),

        # translator 配置
        ('translator', 'translate_mode', 'normal', 'str', '翻译模式 (ai=使用AI翻译模型, normal=使用内置翻译器)', 'normal'),
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

        # 文件检查器配置
        ('checker', 'scan_path', '', 'str', '文件检查器默认扫描路径', ''),

        # 字幕生成配置
        ('subtitle', 'scan_path', '', 'str', '字幕生成默认扫描路径', ''),
        ('subtitle', 'audio_store_path', '', 'str', '音轨文件存放路径（留空则存放在视频同目录）', ''),
        ('subtitle', 'whisper_model', 'mlx-community/whisper-large-v3-turbo', 'str', 'Whisper 模型名称', 'mlx-community/whisper-large-v3-turbo'),
        ('subtitle', 'whisper_language', 'ja', 'str', '识别语言（ja/zh/en/auto）', 'ja'),
        ('subtitle', 'subtitle_format', 'srt', 'str', '字幕输出格式（srt/ass/vtt）', 'srt'),
        ('subtitle', 'subtitle_mode', 'original', 'str', '字幕模式（original=原语言, chinese=中文翻译, bilingual=双语）', 'original'),
        ('subtitle', 'translate_max_length', '1500', 'int', '单次翻译最大字符数（根据模型上下文窗口调整）', '1500'),
        ('subtitle', 'audio_concurrency', '2', 'int', '音轨提取并发数', '2'),
        ('subtitle', 'subtitle_concurrency', '1', 'int', '字幕生成并发数（受显存限制，建议1）', '1'),
        ('subtitle', 'delete_audio_after', 'false', 'bool', '生成字幕后删除音轨文件', 'false'),
        ('subtitle', 'segment_duration', '30', 'int', '语音分段时长（秒），用于大模型上下文限制', '30'),
        ('subtitle', 'filter_fillers', 'false', 'bool', '过滤语气词和拟声词（如ああ、ははは等）', 'false'),
    ]

    with get_db() as conn:
        for group, key, value, vtype, desc, default in config_defaults:
            conn.execute("""
                INSERT OR IGNORE INTO config (group_name, key_name, value, value_type, description, default_value)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (group, key, value, vtype, desc, default))

    logger.info("默认配置已填充到数据库")


def migrate_config():
    """迁移：为已有数据库补充新增的配置项"""
    migrations = [
        ('scanner', 'check_file_integrity', 'true', 'bool', '刮削前使用 ffmpeg 检查视频文件完整性', 'true'),
        ('checker', 'scan_path', '', 'str', '文件检查器默认扫描路径', ''),
    ]
    with get_db() as conn:
        for group, key, value, vtype, desc, default in migrations:
            exists = conn.execute(
                "SELECT 1 FROM config WHERE group_name = ? AND key_name = ?",
                (group, key)
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO config (group_name, key_name, value, value_type, description, default_value) VALUES (?, ?, ?, ?, ?, ?)",
                    (group, key, value, vtype, desc, default)
                )
                logger.info(f"迁移配置项: {group}.{key}")


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
            INSERT INTO config (group_name, key_name, value, value_type, description, default_value)
            VALUES (?, ?, ?, 'str', '', '')
            ON CONFLICT(group_name, key_name) DO UPDATE SET value = excluded.value
        """, (group, key, value))


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
                INSERT INTO config (group_name, key_name, value, value_type, description, default_value)
                VALUES (?, ?, ?, 'str', '', '')
                ON CONFLICT(group_name, key_name) DO UPDATE SET value = excluded.value
            """, (item['group'], item['key'], value))


def get_all_translate_models() -> list[dict]:
    """获取所有翻译模型配置"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, name, engine, config_json, is_active, created_at, updated_at
            FROM translate_models ORDER BY is_active DESC, name
        """).fetchall()
        return [dict(row) for row in rows]


def get_active_translate_model() -> dict | None:
    """获取当前激活的翻译模型"""
    with get_db() as conn:
        row = conn.execute("""
            SELECT id, name, engine, config_json
            FROM translate_models WHERE is_active = 1 LIMIT 1
        """).fetchone()
        if row:
            result = dict(row)
            result['config_json'] = json.loads(result['config_json'])
            return result
        return None


def save_translate_model(name: str, engine: str, config: dict, is_active: bool = False):
    """保存翻译模型配置"""
    config_json = json.dumps(config, ensure_ascii=False)
    with get_db() as conn:
        conn.execute("""
            INSERT INTO translate_models (name, engine, config_json, is_active, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET 
                engine = excluded.engine, 
                config_json = excluded.config_json, 
                is_active = excluded.is_active,
                updated_at = CURRENT_TIMESTAMP
        """, (name, engine, config_json, 1 if is_active else 0))


def update_translate_model(model_id: int, name: str, engine: str, config: dict, is_active: bool = False):
    """更新翻译模型配置"""
    config_json = json.dumps(config, ensure_ascii=False)
    with get_db() as conn:
        conn.execute("""
            UPDATE translate_models 
            SET name = ?, engine = ?, config_json = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (name, engine, config_json, 1 if is_active else 0, model_id))


def set_active_translate_model(name: str):
    """设置指定模型为激活状态，其他模型设为非激活"""
    with get_db() as conn:
        conn.execute("UPDATE translate_models SET is_active = 0")
        conn.execute("UPDATE translate_models SET is_active = 1 WHERE name = ?", (name,))


def delete_translate_model(name: str):
    """删除翻译模型配置"""
    with get_db() as conn:
        conn.execute("DELETE FROM translate_models WHERE name = ?", (name,))


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


# ==================== 完整性检查 ====================

def create_integrity_task(task_id: str, scan_path: str, files: list) -> dict:
    """创建完整性检查任务并批量插入待检查文件"""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO integrity_tasks (id, scan_path, status, total, started_at)
            VALUES (?, ?, 'running', ?, CURRENT_TIMESTAMP)
        """, (task_id, scan_path, len(files)))
        for f in files:
            conn.execute("""
                INSERT INTO integrity_items (task_id, video_path, video_basename, file_size, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (task_id, f['path'], f['basename'], f['size']))
    return {'id': task_id, 'status': 'running', 'total': len(files)}


def get_integrity_task(task_id: str) -> dict:
    """获取完整性检查任务详情"""
    with get_db() as conn:
        task = conn.execute("SELECT * FROM integrity_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return None
        return dict(task)


def get_integrity_tasks(limit: int = 20) -> list:
    """获取完整性检查任务列表"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM integrity_tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_integrity_items(task_id: str, status: str = None) -> list:
    """获取完整性检查项"""
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM integrity_items WHERE task_id = ? AND status = ? ORDER BY id",
                (task_id, status)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM integrity_items WHERE task_id = ? ORDER BY id", (task_id,)
            ).fetchall()
        return [dict(r) for r in rows]


def update_integrity_item_status(item_id: int, status: str, errors: str = None):
    """更新单个检查项的状态"""
    with get_db() as conn:
        conn.execute("""
            UPDATE integrity_items SET status = ?, errors = ?, checked_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, errors, item_id))


def update_integrity_task_progress(task_id: str):
    """根据 items 状态更新 task 的 completed/ok/error 计数"""
    with get_db() as conn:
        stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status != 'pending' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) as ok_count,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count
            FROM integrity_items WHERE task_id = ?
        """, (task_id,)).fetchone()
        conn.execute("""
            UPDATE integrity_tasks SET total = ?, completed = ?, ok_count = ?, error_count = ?
            WHERE id = ?
        """, (stats[0], stats[1], stats[2], stats[3], task_id))


def update_integrity_task_status(task_id: str, status: str):
    """更新完整性检查任务状态"""
    with get_db() as conn:
        if status in ('completed', 'stopped', 'failed'):
            conn.execute("""
                UPDATE integrity_tasks SET status = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?
            """, (status, task_id))
        else:
            conn.execute("""
                UPDATE integrity_tasks SET status = ? WHERE id = ?
            """, (status, task_id))


def get_next_pending_integrity_item(task_id: str) -> dict:
    """获取下一个待检查的文件"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM integrity_items WHERE task_id = ? AND status = 'pending' ORDER BY id LIMIT 1",
            (task_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_integrity_task(task_id: str):
    """删除完整性检查任务及关联项"""
    with get_db() as conn:
        conn.execute("DELETE FROM integrity_items WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM integrity_tasks WHERE id = ?", (task_id,))


def delete_integrity_items(item_ids: list):
    """删除指定的完整性检查项（从数据库中移除已删除的文件记录）"""
    if not item_ids:
        return
    with get_db() as conn:
        placeholders = ','.join('?' * len(item_ids))
        conn.execute(f"DELETE FROM integrity_items WHERE id IN ({placeholders})", item_ids)


# ==================== 字幕生成 ====================

def create_subtitle_task(task_id: str, name: str, scan_path: str, tracks: list) -> dict:
    """创建字幕生成任务并批量插入音轨记录
    tracks: [{path, basename, dir, size, track_index, track_language, track_title, track_codec}]
    """
    with get_db() as conn:
        conn.execute("""
            INSERT INTO subtitle_tasks (id, name, scan_path, status, total, started_at)
            VALUES (?, ?, ?, 'running', ?, CURRENT_TIMESTAMP)
        """, (task_id, name, scan_path, len(tracks)))
        for t in tracks:
            conn.execute("""
                INSERT INTO subtitle_items (
                    task_id, video_path, video_basename, video_dir, file_size,
                    track_index, track_language, track_title, track_codec,
                    audio_status, subtitle_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'pending')
            """, (task_id, t['path'], t['basename'], t['dir'], t['size'],
                  t['track_index'], t.get('track_language'), t.get('track_title'), t.get('track_codec')))
    return {'id': task_id, 'status': 'running', 'total': len(tracks)}


def get_subtitle_task(task_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM subtitle_tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def get_subtitle_tasks(limit: int = 20) -> list:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM subtitle_tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_subtitle_items(task_id: str, status: str = None) -> list:
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM subtitle_items WHERE task_id = ? AND (audio_status = ? OR subtitle_status = ?) ORDER BY id",
                (task_id, status, status)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM subtitle_items WHERE task_id = ? ORDER BY id", (task_id,)
            ).fetchall()
        return [dict(r) for r in rows]


def reset_subtitle_status_for_video(task_id: str, video_path: str) -> int:
    """重置指定影片的字幕状态为 pending，返回重置数量"""
    with get_db() as conn:
        cur = conn.execute(
            """UPDATE subtitle_items
               SET subtitle_status = 'pending', subtitle_path = NULL, errors = NULL,
                   subtitle_started_at = NULL, subtitle_finished_at = NULL
               WHERE task_id = ? AND video_path = ? AND audio_status = 'done'""",
            (task_id, video_path)
        )
        return cur.rowcount


def get_next_subtitle_item(task_id: str, phase: str = 'audio') -> dict:
    """获取下一个待处理的项。phase='audio' 或 'subtitle'"""
    with get_db() as conn:
        if phase == 'audio':
            row = conn.execute(
                "SELECT * FROM subtitle_items WHERE task_id = ? AND audio_status = 'pending' ORDER BY id LIMIT 1",
                (task_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM subtitle_items WHERE task_id = ? AND audio_status = 'done' AND subtitle_status = 'pending' ORDER BY id LIMIT 1",
                (task_id,)
            ).fetchone()
        return dict(row) if row else None


def get_pending_subtitle_items(task_id: str, phase: str = 'audio') -> list:
    """获取所有待处理的项，用于并发执行"""
    with get_db() as conn:
        if phase == 'audio':
            rows = conn.execute(
                "SELECT * FROM subtitle_items WHERE task_id = ? AND audio_status = 'pending' ORDER BY id",
                (task_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM subtitle_items WHERE task_id = ? AND audio_status = 'done' AND subtitle_status = 'pending' ORDER BY id",
                (task_id,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_pending_subtitle_items_by_video(task_id: str, video_path: str, phase: str = 'audio') -> list:
    """获取指定影片下所有待处理的项"""
    with get_db() as conn:
        if phase == 'audio':
            rows = conn.execute(
                "SELECT * FROM subtitle_items WHERE task_id = ? AND video_path = ? AND audio_status = 'pending' ORDER BY id",
                (task_id, video_path)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM subtitle_items WHERE task_id = ? AND video_path = ? AND audio_status = 'done' AND subtitle_status = 'pending' ORDER BY id",
                (task_id, video_path)
            ).fetchall()
        return [dict(r) for r in rows]


def update_subtitle_item(item_id: int, **kwargs):
    with get_db() as conn:
        allowed = {'audio_path', 'audio_status', 'audio_duration', 'audio_started_at', 'audio_finished_at',
                   'subtitle_path', 'subtitle_status', 'subtitle_format', 'whisper_model', 'whisper_language',
                   'subtitle_started_at', 'subtitle_finished_at', 'errors',
                   'track_index', 'track_language', 'track_title', 'track_codec'}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ', '.join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [item_id]
        conn.execute(f"UPDATE subtitle_items SET {set_clause} WHERE id = ?", values)


def update_subtitle_task_progress(task_id: str):
    with get_db() as conn:
        stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN audio_status != 'pending' THEN 1 ELSE 0 END) as audio_completed,
                SUM(CASE WHEN subtitle_status != 'pending' THEN 1 ELSE 0 END) as subtitle_completed
            FROM subtitle_items WHERE task_id = ?
        """, (task_id,)).fetchone()
        conn.execute("""
            UPDATE subtitle_tasks SET total = ?, audio_completed = ?, subtitle_completed = ? WHERE id = ?
        """, (stats[0], stats[1], stats[2], task_id))


def update_subtitle_task_status(task_id: str, status: str):
    with get_db() as conn:
        if status in ('completed', 'stopped', 'failed'):
            conn.execute("UPDATE subtitle_tasks SET status = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?", (status, task_id))
        else:
            conn.execute("UPDATE subtitle_tasks SET status = ? WHERE id = ?", (status, task_id))


def delete_subtitle_task(task_id: str):
    with get_db() as conn:
        conn.execute("DELETE FROM subtitle_items WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM subtitle_tasks WHERE id = ?", (task_id,))


def delete_subtitle_items(item_ids: list):
    if not item_ids:
        return
    with get_db() as conn:
        placeholders = ','.join('?' * len(item_ids))
        conn.execute(f"DELETE FROM subtitle_items WHERE id IN ({placeholders})", item_ids)


# ==================== 字幕扫描结果 ====================

def save_subtitle_scan_results(scan_path: str, files: list):
    """保存扫描结果，保留已提取状态"""
    with get_db() as conn:
        old_extracted = {}
        rows = conn.execute(
            "SELECT video_path, extracted FROM subtitle_scan_results WHERE scan_path = ?",
            (scan_path,)
        ).fetchall()
        for row in rows:
            old_extracted[row['video_path']] = row['extracted']
        
        conn.execute("DELETE FROM subtitle_scan_results WHERE scan_path = ?", (scan_path,))
        for f in files:
            video_path = f['path']
            extracted = old_extracted.get(video_path, 0)
            conn.execute("""
                INSERT INTO subtitle_scan_results (scan_path, video_path, video_basename, video_dir, file_size, file_exists, extracted)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (scan_path, video_path, f['basename'], f['dir'], f['size'], 1 if f.get('exists', True) else 0, extracted))


def get_subtitle_scan_results(scan_path: str) -> list:
    """获取某路径的扫描结果"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM subtitle_scan_results WHERE scan_path = ? ORDER BY id",
            (scan_path,)
        ).fetchall()
        return [dict(r) for r in rows]


def update_subtitle_scan_result_exists(video_path: str, exists: bool):
    """更新扫描结果中的文件存在状态"""
    with get_db() as conn:
        conn.execute(
            "UPDATE subtitle_scan_results SET file_exists = ? WHERE video_path = ?",
            (1 if exists else 0, video_path)
        )


def delete_subtitle_scan_result(video_path: str):
    """删除单条扫描结果"""
    with get_db() as conn:
        conn.execute("DELETE FROM subtitle_scan_results WHERE video_path = ?", (video_path,))


def update_subtitle_scan_result_extracted(video_path: str, extracted: bool):
    """标记某视频是否已提取过音轨"""
    with get_db() as conn:
        conn.execute(
            "UPDATE subtitle_scan_results SET extracted = ? WHERE video_path = ?",
            (1 if extracted else 0, video_path)
        )


def refresh_subtitle_scan_extracted_status():
    """根据 subtitle_items 中的成功记录，刷新扫描结果的 extracted 状态"""
    with get_db() as conn:
        conn.execute("""
            UPDATE subtitle_scan_results
            SET extracted = 1
            WHERE video_path IN (
                SELECT DISTINCT video_path FROM subtitle_items WHERE audio_status = 'done'
            )
        """)
