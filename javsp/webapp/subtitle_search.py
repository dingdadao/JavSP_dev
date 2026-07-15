"""字幕搜索模块 - 通过迅雷看看和射手网 API 搜索字幕"""

import os
import re
import json
import zlib
import struct
import hashlib
import logging
from urllib import request, parse
from pathlib import Path

logger = logging.getLogger('javsp.webapp.subtitle_search')

XUNLEI_API_URL = 'http://api.sub.sandai.net:8000/subxl'
SHOOTER_API_URL = 'https://www.shooter.cn/api/subapi.php'


def compute_video_hash(filepath: str) -> tuple[str, str, int]:
    """计算视频文件的 Hash 值，用于字幕搜索匹配
    
    Returns:
        tuple: (filehash, crc32, filesize)
    """
    if not os.path.exists(filepath):
        return '', '', 0
    
    filesize = os.path.getsize(filepath)
    
    try:
        with open(filepath, 'rb') as f:
            # 文件头 64KB
            head = f.read(65536)
            
            # 文件末尾 64KB
            if filesize > 65536:
                f.seek(-65536, os.SEEK_END)
                tail = f.read(65536)
            else:
                tail = b''
            
            # 文件中间 64KB（如果文件足够大）
            if filesize > 196608:
                mid_pos = filesize // 2 - 32768
                f.seek(mid_pos)
                middle = f.read(65536)
            else:
                middle = b''
        
        # 计算 CRC32
        crc = zlib.crc32(head) & 0xffffffff
        crc = zlib.crc32(middle, crc) & 0xffffffff
        crc = zlib.crc32(tail, crc) & 0xffffffff
        
        # 计算 MD5（用于射手网）
        md5_hash = hashlib.md5()
        md5_hash.update(head)
        md5_hash.update(middle)
        md5_hash.update(tail)
        filehash = md5_hash.hexdigest().upper()
        
        return filehash, f"{crc:08x}".upper(), filesize
    
    except Exception as e:
        logger.error(f"计算视频 Hash 失败: {filepath} - {e}")
        return '', '', 0


def search_xunlei_subtitle(filepath: str) -> list[dict]:
    """通过迅雷看看 API 搜索字幕
    
    Args:
        filepath: 视频文件路径
    
    Returns:
        list: 字幕搜索结果列表
            [{
                'source': 'xunlei',
                'id': str,
                'language': str,
                'filename': str,
                'url': str,
                'encoding': str,
            }]
    """
    results = []
    filehash, crc32, filesize = compute_video_hash(filepath)
    
    if not filehash:
        return results
    
    try:
        params = {
            'q': filehash,
            'crc32': crc32,
            'fs': filesize,
            'l': '',
            's': 1,
        }
        url = f"{XUNLEI_API_URL}?{parse.urlencode(params)}"
        
        with request.urlopen(url, timeout=10) as resp:
            data = resp.read().decode('utf-8', errors='replace')
        
        if not data or data == '{}':
            return results
        
        try:
            json_data = json.loads(data)
        except json.JSONDecodeError:
            return results
        
        for item in json_data.get('data', []):
            for sub in item.get('subs', []):
                lang_map = {
                    'zh': '中文',
                    'zh-CN': '中文',
                    'zh-TW': '繁体',
                    'en': '英文',
                    'ja': '日文',
                }
                results.append({
                    'source': 'xunlei',
                    'id': f"xunlei_{sub.get('id', '')}",
                    'language': lang_map.get(sub.get('l'), sub.get('l', '未知')),
                    'filename': sub.get('sname', ''),
                    'url': sub.get('url', ''),
                    'encoding': sub.get('charset', 'utf-8'),
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
            [{
                'source': 'shooter',
                'id': str,
                'language': str,
                'filename': str,
                'url': str,
                'encoding': str,
            }]
    """
    results = []
    filehash, _, filesize = compute_video_hash(filepath)
    
    if not filehash:
        return results
    
    try:
        params = {
            'filehash': filehash,
            'pathinfo': parse.quote(os.path.basename(filepath)),
            'format': 'json',
            'lang': 'Chn',
        }
        url = f"{SHOOTER_API_URL}?{parse.urlencode(params)}"
        
        req = request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json',
        })
        
        with request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode('utf-8', errors='replace')
        
        if not data:
            return results
        
        try:
            json_data = json.loads(data)
        except json.JSONDecodeError:
            return results
        
        for item in json_data:
            for sub in item.get('Subtitles', []):
                lang_map = {
                    'Chn': '中文',
                    'Eng': '英文',
                    'Jpn': '日文',
                }
                results.append({
                    'source': 'shooter',
                    'id': f"shooter_{sub.get('ID', '')}",
                    'language': lang_map.get(sub.get('Language', ''), sub.get('Language', '未知')),
                    'filename': sub.get('FileName', ''),
                    'url': sub.get('DownloadLink', ''),
                    'encoding': sub.get('Encoding', 'utf-8'),
                })
        
        logger.info(f"射手网搜索完成: {filepath} -> {len(results)} 条结果")
        
    except Exception as e:
        logger.error(f"射手网字幕搜索失败: {filepath} - {e}")
    
    return results


def search_subtitle(filepath: str, prefer_xunlei: bool = True) -> list[dict]:
    """搜索字幕，优先迅雷，然后射手网
    
    Args:
        filepath: 视频文件路径
        prefer_xunlei: 是否优先迅雷搜索
    
    Returns:
        list: 合并后的字幕搜索结果，按优先级排序
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
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
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
                    with open(save_path, 'wb') as f:
                        f.write(sub_content)
            except Exception as e:
                logger.error(f"解压字幕失败: {e}")
                return {'ok': False, 'path': '', 'errors': f'解压失败: {e}'}
        else:
            with open(save_path, 'wb') as f:
                f.write(content)
        
        if os.path.getsize(save_path) == 0:
            os.remove(save_path)
            return {'ok': False, 'path': '', 'errors': '下载的字幕文件为空'}
        
        logger.info(f"字幕下载成功: {save_path}")
        return {'ok': True, 'path': save_path, 'errors': None}
    
    except Exception as e:
        logger.error(f"字幕下载失败: {url} -> {save_path} - {e}")
        return {'ok': False, 'path': '', 'errors': str(e)}