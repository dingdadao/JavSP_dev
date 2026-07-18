"""字幕搜索模块 - 通过迅雷看看和射手网 API 搜索字幕"""

import os
import re
import json
import hashlib
import logging
from urllib import request, parse

logger = logging.getLogger('javsp.webapp.subtitle_search')

XUNLEI_API_URL_DEFAULT = 'https://api-shoulei-ssl.xunlei.com/oracle/subtitle'
SHOOTER_API_URL_DEFAULT = 'https://www.shooter.cn/api/subapi.php'


def _get_search_api_urls() -> tuple[str, str]:
    """从数据库读取字幕搜索 API 地址，未配置或为空则使用默认值"""
    try:
        from javsp.webapp.database import get_config
        cfg = get_config('subtitle')
        xunlei_url = cfg.get('subtitle_search_xunlei_api_url', '') or XUNLEI_API_URL_DEFAULT
        shooter_url = cfg.get('subtitle_search_shooter_api_url', '') or SHOOTER_API_URL_DEFAULT
        return xunlei_url, shooter_url
    except Exception as e:
        logger.warning(f"读取字幕搜索 API 配置失败，使用默认值: {e}")
        return XUNLEI_API_URL_DEFAULT, SHOOTER_API_URL_DEFAULT


def safe_write_file(path: str, content, mode: str = 'wb', encoding: str = None):
    """安全写入文件，兼容 SMB 等网络存储

    依次尝试：
    1. 先写临时文件，再原子替换；
    2. 删除目标后重命名；
    3. 直接覆盖写入。
    每步失败都记录日志，最后一步仍失败才抛出异常。
    """
    def _write(target_path: str):
        if encoding:
            with open(target_path, mode, encoding=encoding) as f:
                f.write(content)
        else:
            with open(target_path, mode) as f:
                f.write(content)

    tmp_path = path + '.tmp'

    # 方案 1：临时文件 + 原子替换
    try:
        _write(tmp_path)
        try:
            os.replace(tmp_path, path)
            return
        except (OSError, PermissionError) as e:
            logger.warning(f"safe_write_file replace 失败 ({path}): {e}")
    except Exception as e:
        logger.warning(f"safe_write_file 写临时文件失败 ({path}): {e}")

    # 方案 2：删除目标后重命名
    try:
        if os.path.exists(tmp_path):
            if os.path.exists(path):
                os.remove(path)
            os.rename(tmp_path, path)
            return
    except Exception as e:
        logger.warning(f"safe_write_file 删除+重命名失败 ({path}): {e}")

    # 方案 3：直接覆盖写入
    try:
        _write(path)
        logger.info(f"safe_write_file 已使用直接写入兜底 ({path})")
    except Exception as e:
        logger.error(f"safe_write_file 直接写入失败 ({path}): {e}")
        raise


def compute_shooter_hash(filepath: str) -> str:
    """计算射手网文件 Hash（4 段 4KB MD5）
    
    Returns:
        str: 4 段 MD5 hash，用分号连接
    """
    if not os.path.exists(filepath):
        return ''
    
    filesize = os.path.getsize(filepath)
    if filesize < 8 * 1024:
        return ''
    
    try:
        offsets = [
            4 * 1024,
            filesize // 3 * 2,
            filesize // 3,
            filesize - 8 * 1024,
        ]
        
        parts = []
        buf = bytearray(4096)
        
        with open(filepath, 'rb') as f:
            for offset in offsets:
                f.seek(offset)
                f.readinto(buf)
                parts.append(hashlib.md5(buf).hexdigest())
        
        return ';'.join(parts)
    
    except Exception as e:
        logger.error(f"计算射手网 Hash 失败: {filepath} - {e}")
        return ''


def compute_thunder_cid(filepath: str) -> str:
    """计算迅雷 CID（SHA1 三段算法）
    
    Returns:
        str: 大写 SHA1 hex
    """
    if not os.path.exists(filepath):
        return ''
    
    filesize = os.path.getsize(filepath)
    if filesize == 0:
        return ''
    
    try:
        buffer = bytearray(0xf000)
        
        with open(filepath, 'rb') as f:
            if filesize < 0xf000:
                n = f.readinto(buffer[:filesize])
                sha1_hash = hashlib.sha1(buffer[:n]).hexdigest().upper()
            else:
                f.readinto(buffer[:0x5000])
                f.seek(filesize // 3)
                f.readinto(buffer[0x5000:0xa000])
                f.seek(filesize - 0x5000)
                f.readinto(buffer[0xa000:0xf000])
                sha1_hash = hashlib.sha1(buffer).hexdigest().upper()
        
        return sha1_hash
    
    except Exception as e:
        logger.error(f"计算迅雷 CID 失败: {filepath} - {e}")
        return ''


def _get_json_key(data: dict, key: str, default=None):
    """兼容大小写的 JSON 字段读取"""
    if key in data:
        return data[key]
    lower_key = key.lower()
    if lower_key in data:
        return data[lower_key]
    return default


def search_xunlei_subtitle(filepath: str) -> list[dict]:
    """通过迅雷看看 API 搜索字幕
    
    Args:
        filepath: 视频文件路径
    
    Returns:
        list: 字幕搜索结果列表
    """
    results = []
    
    if not os.path.exists(filepath):
        return results
    
    try:
        filename = os.path.basename(filepath)
        cid = compute_thunder_cid(filepath)
        xunlei_api_url, _ = _get_search_api_urls()
        
        params = {'name': filename}
        url = f"{xunlei_api_url}?{parse.urlencode(params)}"
        
        req = request.Request(url, headers={
            'User-Agent': 'MeiamSub.Thunder',
            'Accept': '*/*',
        })
        
        with request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode('utf-8', errors='replace')
        
        if not data:
            return results
        
        try:
            json_data = json.loads(data)
        except json.JSONDecodeError:
            return results
        
        if _get_json_key(json_data, 'Code') != 0:
            return results
        
        for item in _get_json_key(json_data, 'Data', []):
            if not _get_json_key(item, 'Name'):
                continue
            
            languages = _get_json_key(item, 'Languages', [])
            lang = ', '.join(languages).strip() or '未知'
            item_cid = _get_json_key(item, 'Cid', '')
            sub_url = _get_json_key(item, 'Url', '')
            
            results.append({
                'source': 'xunlei',
                'id': f"xunlei_{sub_url}",
                'language': lang,
                'filename': _get_json_key(item, 'Name', ''),
                'url': sub_url,
                'encoding': 'utf-8',
                'is_hash_match': bool(cid and item_cid and cid.upper() == str(item_cid).upper()),
            })
        
        logger.info(f"迅雷搜索完成: {filepath} -> {len(results)} 条结果")
        
    except Exception as e:
        logger.error(f"迅雷字幕搜索失败: {filepath} - {e}")
    
    return results


def search_shooter_subtitle(filepath: str) -> list[dict]:
    """通过射手网 API 搜索字幕
    
    Args:
        filepath: 视频文件路径
    
    Returns:
        list: 字幕搜索结果列表
    """
    results = []
    
    filehash = compute_shooter_hash(filepath)
    if not filehash:
        return results
    
    try:
        _, shooter_api_url = _get_search_api_urls()
        form_data = {
            'filehash': filehash,
            'pathinfo': os.path.basename(filepath),
            'format': 'json',
            'lang': 'chn',
        }
        
        data = parse.urlencode(form_data).encode('utf-8')
        req = request.Request(shooter_api_url, data=data, headers={
            'User-Agent': 'MeiamSub.Shooter',
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
        })
        
        with request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
        
        if not raw or not raw.strip().startswith('['):
            return results
        
        try:
            json_data = json.loads(raw)
        except json.JSONDecodeError:
            return results
        
        for item in json_data:
            for sub in _get_json_key(item, 'Files', []):
                sub_url = _get_json_key(sub, 'Link', '')
                if not sub_url:
                    continue
                
                results.append({
                    'source': 'shooter',
                    'id': f"shooter_{sub_url}",
                    'language': '中文',
                    'filename': os.path.basename(filepath),
                    'url': sub_url,
                    'encoding': 'utf-8',
                    'is_hash_match': True,
                })
        
        logger.info(f"射手网搜索完成: {filepath} -> {len(results)} 条结果")
        
    except Exception as e:
        logger.error(f"射手网字幕搜索失败: {filepath} - {e}")
    
    return results


def _map_language_to_code(lang_str: str) -> str:
    """将字幕语言描述字符串映射为统一语言码

    支持：zh(中文/简体), cht(繁体), en(英文), jp(日文), ko(韩文) 等
    关键字按词边界匹配，避免在普通单词内部误识别。
    """
    if not lang_str:
        return ''
    text = lang_str.lower()

    # 按优先级排列：繁体 > 简体 > 通用中文 > 英文 > 日文 > 韩文
    mapping = [
        ('cht', ('繁体', '繁體', 'cht', 'tc', 'tw', 'hk', 'big5', 'traditional', 'zh-hant', 'zh-tw', 'zh-hk', 'zht')),
        ('zh', ('简体', '簡體', '简中', '簡中', 'gb', 'simplified', 'chs', 'sc', 'zh-hans', 'zh-cn', 'zhs')),
        ('zh', ('中文', 'chinese', 'chi', 'zho', 'zh', 'cn', 'cns', 'mandarin')),
        ('en', ('英文', '英语', 'english', 'en', 'eng')),
        ('jp', ('日文', '日语', 'japanese', 'jpn', 'jp', 'ja')),
        ('ko', ('韩文', '韩语', 'korean', 'kor', 'ko', 'kr')),
    ]

    for code, keys in mapping:
        for k in keys:
            pattern = rf'(?<![a-z]){re.escape(k.lower())}(?![a-z])'
            if re.search(pattern, text):
                return code
    return ''


def _detect_subtitle_language(result: dict) -> str:
    """综合 language 字段和 filename 字段识别字幕语言

    文件名中带有明确语言标记时优先使用文件名，因为部分 API 返回的 language 字段不准确。
    """
    lang_code = _map_language_to_code(result.get('language', ''))
    filename = result.get('filename', '')
    filename_code = _map_language_to_code(filename)

    # 文件名里有明确语言标记时，以文件名为准
    if filename_code and _has_language_marker_in_filename(filename, filename_code):
        return filename_code

    return lang_code


def _has_language_marker_in_filename(filename: str, lang_code: str) -> bool:
    """判断文件名中是否包含指定语言的明确标记

    支持 .zh.、_zh、-zh.、.chs.、.cn. 等形式；
    标记前/后只要有分隔符（点、下划线、横杠、空格）或位于文件头/尾即可；
    匹配不区分大小写。
    """
    if not filename or not lang_code:
        return False
    import re
    text = filename.lower()
    markers = {
        'zh': [
            'zh', 'zh-cn', 'zh-hans', 'zh-hant', 'chs', 'ch-s', 'ch', 'chi', 'zho',
            'cn', 'cns', 'sc', 'zhs', 'gb', 'simp', 'simplified', 'mandarin', 'chinese',
        ],
        'cht': [
            'cht', 'tc', 'zh-tw', 'zh-hk', 'zh-hant', 'zht', 'big5', 'trad',
            'traditional', 'tw', 'hk',
        ],
        'en': ['en', 'eng', 'english'],
        'jp': ['jp', 'ja', 'jpn', 'japanese'],
        'ko': ['ko', 'kor', 'korean'],
    }
    for m in markers.get(lang_code, []):
        # 标记不能嵌入在字母序列中；前后可以是数字、分隔符或开头/结尾
        pattern = rf'(?<![a-z]){re.escape(m)}(?![a-z])'
        if re.search(pattern, text):
            return True
    return False


def _get_preferred_languages() -> list[str]:
    """读取数据库中的字幕语言偏好设置，并规范化为标准语言码"""
    try:
        from javsp.webapp.database import get_config
        cfg = get_config('subtitle')
        langs = cfg.get('subtitle_search_preferred_languages', [])
        if isinstance(langs, list):
            normalized = []
            for l in langs:
                s = str(l).lower().strip()
                if not s:
                    continue
                # 把中文描述、ISO 代码等都映射为标准语言码
                code = _map_language_to_code(s)
                if code:
                    normalized.append(code)
                elif s in ('zh', 'cht', 'en', 'jp', 'ko'):
                    normalized.append(s)
            if normalized:
                return normalized
    except Exception as e:
        logger.warning(f"读取字幕语言偏好失败，使用默认值: {e}")
    return ['zh', 'cht', 'en']


def select_best_subtitle(results: list[dict], preferred_languages: list[str] = None) -> dict | None:
    """根据语言偏好从搜索结果中选择最佳字幕

    优先级：
    1. 与偏好语言匹配且 hash 匹配
    2. 与偏好语言匹配
    3. hash 匹配
    4. 第一条结果
    """
    if not results:
        return None

    if preferred_languages is None:
        preferred_languages = _get_preferred_languages()
    preferred_languages = [l.lower().strip() for l in preferred_languages if l]

    def _score(result: dict) -> tuple:
        lang_code = _detect_subtitle_language(result)
        is_hash_match = bool(result.get('is_hash_match'))
        has_lang_marker = _has_language_marker_in_filename(result.get('filename', ''), lang_code)
        if lang_code in preferred_languages:
            # 越靠前的偏好语言优先级越高（升序）
            lang_score = preferred_languages.index(lang_code)
        else:
            # 不在偏好列表中的语言排在后面
            lang_score = len(preferred_languages)
        # 返回 (语言匹配分, 文件名语言标记, hash 匹配分)
        # 优先级：偏好语言 > 文件名带语言标记 > hash 匹配
        return (lang_score, 0 if has_lang_marker else 1, 0 if is_hash_match else 1)

    sorted_results = sorted(results, key=_score)
    return sorted_results[0]


def search_subtitle(filepath: str, prefer_xunlei: bool = True) -> list[dict]:
    """搜索字幕，优先迅雷，然后射手网
    
    Args:
        filepath: 视频文件路径
        prefer_xunlei: 是否优先迅雷搜索
    
    Returns:
        list: 合并后的字幕搜索结果，按语言偏好和 hash 匹配排序
    """
    xunlei_results = []
    shooter_results = []
    
    if prefer_xunlei:
        xunlei_results = search_xunlei_subtitle(filepath)
        if not xunlei_results:
            shooter_results = search_shooter_subtitle(filepath)
    else:
        shooter_results = search_shooter_subtitle(filepath)
        if not shooter_results:
            xunlei_results = search_xunlei_subtitle(filepath)
    
    # 合并结果，迅雷在前
    all_results = []
    seen_ids = set()
    
    for r in xunlei_results:
        if r['id'] not in seen_ids:
            seen_ids.add(r['id'])
            all_results.append(r)
    
    for r in shooter_results:
        if r['id'] not in seen_ids:
            seen_ids.add(r['id'])
            all_results.append(r)
    
    # 按语言偏好、文件名语言标记、hash 匹配排序
    preferred_languages = _get_preferred_languages()
    all_results.sort(key=lambda r: (
        preferred_languages.index(_detect_subtitle_language(r))
        if _detect_subtitle_language(r) in preferred_languages
        else len(preferred_languages),
        0 if _has_language_marker_in_filename(r.get('filename', ''), _detect_subtitle_language(r)) else 1,
        0 if r.get('is_hash_match') else 1,
    ))

    return all_results


def download_subtitle(url: str, save_path: str) -> dict:
    """下载字幕文件
    
    Args:
        url: 字幕下载链接
        save_path: 保存路径
    
    Returns:
        dict: {'ok': bool, 'path': str, 'errors': str}
    """
    try:
        dir_name = os.path.dirname(save_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        
        req = request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        })
        
        with request.urlopen(req, timeout=30) as resp:
            content = resp.read()
        
        # 处理可能的压缩格式
        if save_path.endswith('.zip') or (len(content) > 0 and content[:2] == b'PK'):
            import zipfile
            from io import BytesIO
            try:
                with zipfile.ZipFile(BytesIO(content)) as zf:
                    names = zf.namelist()
                    # 优先选择 .srt 文件
                    srt_files = [n for n in names if n.lower().endswith('.srt')]
                    target = srt_files[0] if srt_files else names[0]
                    with zf.open(target) as f:
                        sub_content = f.read()
                    # 重命名为视频名称 + .srt
                    base_path = save_path.rsplit('.', 1)[0]
                    save_path = f"{base_path}.srt"
                    safe_write_file(save_path, sub_content, 'wb')
            except Exception as e:
                logger.error(f"解压字幕失败: {e}")
                return {'ok': False, 'path': '', 'errors': f'解压失败: {e}'}
        else:
            safe_write_file(save_path, content, 'wb')
        
        if os.path.getsize(save_path) == 0:
            os.remove(save_path)
            return {'ok': False, 'path': '', 'errors': '下载的字幕文件为空'}
        
        logger.info(f"字幕下载成功: {save_path}")
        return {'ok': True, 'path': save_path, 'errors': None}
    
    except Exception as e:
        logger.error(f"字幕下载失败: {url} -> {save_path} - {e}")
        err_msg = str(e)
        if 'Operation not permitted' in err_msg or 'Permission denied' in err_msg:
            err_msg += (
                '。提示：目标路径可能是 SMB/网络共享卷，当前进程没有写入权限。'
                '请尝试从系统终端手动启动服务（而非 IDE/Agent 后台），或检查应用对网络卷的写入权限。'
            )
        return {'ok': False, 'path': '', 'errors': err_msg}
