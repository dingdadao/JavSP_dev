"""
JavSP API 服务端
提供 HTTP 接口用于刮削影片信息
"""

import os
import sys
import json
import logging
import threading
import shutil
import uuid
import time
from typing import Dict, Any, List, Optional
from dataclasses import asdict
from flask import Flask, request, jsonify
from flask_cors import CORS
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from javsp.config import Cfg
from javsp.datatype import Movie, MovieInfo
from javsp.web.exceptions import *
from javsp.web.translate import translate_movie_info
from javsp.web.base import close_global_session
from javsp import __main__ as main_module
from javsp.file import scan_movies, replace_illegal_chars
from javsp.nfo import write_nfo
from javsp.func import split_by_punc

# 直接导入所有爬虫模块（All in）
from javsp.web import (
    airav, arzon, arzon_iv, avsox, avwiki, 
    fanza, fc2, fc2fan, javbus, javdb, 
    javlib, javmenu, jav321, mgstage, 
    prestige, dl_getchu, gyutto, njav, missav
)

# 爬虫模块映射表
CRAWLER_MODULES = {
    'airav': airav,
    'arzon': arzon,
    'arzon_iv': arzon_iv,
    'avsox': avsox,
    'avwiki': avwiki,
    'fanza': fanza,
    'fc2': fc2,
    'fc2fan': fc2fan,
    'javbus': javbus,
    'javdb': javdb,
    'javlib': javlib,
    'javmenu': javmenu,
    'jav321': jav321,
    'mgstage': mgstage,
    'prestige': prestige,
    'dl_getchu': dl_getchu,
    'gyutto': gyutto,
    'njav': njav,
    'missav': missav,
}

# 配置日志
logger = logging.getLogger('javsp.api')

# 创建 Flask 应用
app = Flask(__name__)
CORS(app)  # 启用跨域支持

# 当前任务存储（只保留最近一次任务）
current_task = None
task_lock = threading.Lock()


# 定义返回码
class ApiCode:
    SUCCESS = 0                    # 成功
    INVALID_PARAM = 1001          # 参数错误
    SOURCE_NOT_FOUND = 1002       # 源路径不存在
    DEST_NOT_FOUND = 1003         # 目标路径不存在
    CONFIG_SOURCE_INVALID = 1004  # 配置文件源路径无效
    CONFIG_DEST_INVALID = 1005    # 配置文件目标路径无效
    NO_MOVIE_FOUND = 1006         # 未找到影片文件
    TASK_RUNNING = 1007           # 已有任务进行中
    INTERNAL_ERROR = 9999         # 内部错误


def get_config_paths():
    """从配置文件获取路径"""
    cfg = Cfg()
    source = None
    dest = None
    
    # 尝试从 scanner 配置获取输入目录
    if hasattr(cfg.scanner, 'input_directory'):
        source = cfg.scanner.input_directory
    elif hasattr(cfg.scanner, 'scan_dir'):
        source = cfg.scanner.scan_dir
    
    # 尝试从 summarizer 配置获取输出目录
    if hasattr(cfg.summarizer, 'path') and hasattr(cfg.summarizer.path, 'output_folder_pattern'):
        output_pattern = cfg.summarizer.path.output_folder_pattern
        if '{' in output_pattern:
            dest = output_pattern.split('{')[0].rstrip('/')
        else:
            dest = output_pattern
    
    return source, dest


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return jsonify({
        'code': ApiCode.SUCCESS,
        'message': 'JavSP API 服务运行中',
        'data': None
    })


@app.route('/api/scrape', methods=['POST'])
def scrape():
    """
    创建刮削任务
    
    请求参数 (JSON):
    {
        "source": "/path/to/movies",      // 可选，源文件夹路径（不传则使用配置文件）
        "dest": "/path/to/output",        // 可选，输出文件夹路径（不传则使用配置文件）
        "translate": true,                 // 可选，是否翻译，默认 true
        "move_files": false                // 可选，是否移动文件，默认 false
    }
    
    返回结果（成功）:
    {
        "code": 0,
        "message": "任务创建成功"
    }
    
    返回结果（失败）:
    {
        "code": 1002,
        "message": "源路径不存在: /path/to/movies"
    }
    """
    global current_task
    
    try:
        with task_lock:
            # 检查是否已有任务进行中
            if current_task and current_task.get('status') == 'running':
                return jsonify({
                    'code': ApiCode.TASK_RUNNING,
                    'message': '已有任务进行中，请等待完成后再创建新任务',
                    'data': None
                }), 400
        
        data = request.get_json() or {}
        
        # 获取参数（优先使用传入的参数，否则使用配置文件）
        source = data.get('source')
        dest = data.get('dest')
        translate = data.get('translate', True)
        move_files = data.get('move_files', False)
        
        # 如果没有传入路径，从配置文件读取
        config_source, config_dest = get_config_paths()
        
        if not source:
            source = config_source
            if not source:
                return jsonify({
                    'code': ApiCode.CONFIG_SOURCE_INVALID,
                    'message': '未提供源路径，且配置文件中也未设置有效的源路径',
                    'data': None
                }), 400
        
        if not dest:
            dest = config_dest
            if not dest:
                return jsonify({
                    'code': ApiCode.CONFIG_DEST_INVALID,
                    'message': '未提供目标路径，且配置文件中也未设置有效的目标路径',
                    'data': None
                }), 400
        
        # 检查源路径是否存在
        source_path = Path(source)
        if not source_path.exists():
            return jsonify({
                'code': ApiCode.SOURCE_NOT_FOUND,
                'message': f'源路径不存在: {source}',
                'data': None
            }), 404
        
        # 检查目标路径是否存在（不存在则尝试创建）
        dest_path = Path(dest)
        if not dest_path.exists():
            try:
                dest_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"创建目标路径: {dest}")
            except Exception as e:
                return jsonify({
                    'code': ApiCode.DEST_NOT_FOUND,
                    'message': f'目标路径不存在且无法创建: {dest}, 错误: {str(e)}',
                    'data': None
                }), 404
        
        # 扫描影片文件
        movies = scan_movies(str(source_path))
        
        if not movies:
            return jsonify({
                'code': ApiCode.NO_MOVIE_FOUND,
                'message': f'未在路径 {source} 中找到任何影片文件',
                'data': None
            }), 404
        
        # 创建任务
        with task_lock:
            current_task = {
                'task_id': str(uuid.uuid4()),
                'status': 'running',
                'source': source,
                'dest': dest,
                'total': len(movies),
                'completed': 0,
                'success': [],
                'failed': [],
                'start_time': time.time()
            }
        
        logger.info(f"创建任务: 找到 {len(movies)} 部影片，开始异步刮削...")
        
        # 启动异步刮削线程
        thread = threading.Thread(
            target=async_scrape_task,
            args=(movies, translate, str(dest_path), move_files)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'code': ApiCode.SUCCESS,
            'message': f'任务创建成功，共 {len(movies)} 部影片',
            'data': {
                'total': len(movies)
            }
        })
        
    except Exception as e:
        logger.exception("创建任务失败")
        return jsonify({
            'code': ApiCode.INTERNAL_ERROR,
            'message': f'创建任务失败: {str(e)}',
            'data': None
        }), 500


def async_scrape_task(movies: List[Movie], translate: bool, dest_path: str, move_files: bool):
    """异步执行刮削任务"""
    global current_task
    
    try:
        for movie in movies:
            result = scrape_single_movie(movie, translate, dest_path, move_files)
            
            with task_lock:
                if current_task is None:
                    break
                
                if result['success']:
                    current_task['success'].append({
                        'dvdid': result['dvdid'],
                        'source_path': result['source_files'][0] if result['source_files'] else None,
                        'dest_path': result['dest_path']
                    })
                else:
                    current_task['failed'].append({
                        'dvdid': result['dvdid'],
                        'source_path': result['source_files'][0] if result['source_files'] else None,
                        'reason': result['message']
                    })
                
                current_task['completed'] += 1
        
        # 标记任务完成
        with task_lock:
            if current_task:
                success_count = len(current_task['success'])
                failed_count = len(current_task['failed'])
                total = current_task['total']
                
                if success_count == total:
                    current_task['status'] = 'completed'
                    logger.info(f"任务完成: 全部成功 {success_count}/{total}")
                elif success_count > 0:
                    current_task['status'] = 'partial'
                    logger.info(f"任务完成: 部分成功 {success_count}/{total}")
                else:
                    current_task['status'] = 'failed'
                    logger.info(f"任务完成: 全部失败 {failed_count}/{total}")
                
    except Exception as e:
        logger.exception("任务执行失败")
        with task_lock:
            if current_task:
                current_task['status'] = 'error'


def scrape_single_movie(movie: Movie, translate: bool, dest_path: str, move_files: bool) -> Dict[str, Any]:
    """刮削单部影片"""
    result = {
        'dvdid': movie.dvdid or movie.cid,
        'success': False,
        'message': '',
        'source_files': movie.files,
        'dest_path': None
    }
    
    try:
        # 并行抓取数据
        all_info = main_module.parallel_crawler(movie)
        
        if not all_info:
            result['message'] = '无法获取影片信息，所有爬虫均返回失败'
            return result
        
        # 汇总数据
        success = main_module.info_summary(movie, all_info)
        if not success:
            result['message'] = '数据汇总失败，缺少必需字段'
            return result
        
        # 翻译（如果启用）
        if translate and Cfg().translator.engine:
            try:
                translate_movie_info(movie.info)
            except Exception as e:
                logger.error(f"翻译失败 {movie.dvdid}: {e}")
        
        # 生成文件名和路径
        main_module.generate_names(movie)
        
        # 创建目标文件夹
        movie_save_dir = os.path.join(dest_path, replace_illegal_chars(movie.dvdid or movie.cid))
        os.makedirs(movie_save_dir, exist_ok=True)
        movie.save_dir = movie_save_dir
        
        # 保存 NFO 文件
        nfo_path = os.path.join(movie_save_dir, f"{movie.dvdid or movie.cid}.nfo")
        write_nfo(movie.info, nfo_path)
        
        # 移动或复制文件
        new_files = []
        for file_path in movie.files:
            file_name = os.path.basename(file_path)
            dest_file = os.path.join(movie_save_dir, file_name)
            
            if move_files:
                os.rename(file_path, dest_file)
            else:
                shutil.copy2(file_path, dest_file)
            new_files.append(dest_file)
        
        movie.files = new_files
        result['dest_path'] = movie_save_dir
        result['success'] = True
        result['message'] = '刮削成功'
        
    except Exception as e:
        logger.exception(f"刮削影片 {movie.dvdid} 时发生错误")
        result['message'] = f'刮削异常: {str(e)}'
    
    return result


@app.route('/api/scrape/status', methods=['GET'])
def get_task_status():
    """
    查询当前任务状态
    
    返回结果（进行中）:
    {
        "code": 0,
        "message": "任务进行中",
        "data": {
            "status": "running",
            "total": 10,
            "completed": 5,
            "progress": "5/10"
        }
    }
    
    返回结果（已完成）:
    {
        "code": 0,
        "message": "任务已完成",
        "data": {
            "status": "completed",      // completed, partial, failed, error
            "total": 10,
            "completed": 10,
            "progress": "10/10",
            "success_count": 8,
            "failed_count": 2,
            "success": [
                {
                    "dvdid": "SSIS-123",
                    "source_path": "/path/to/SSIS-123.mp4",
                    "dest_path": "/path/to/output/SSIS-123"
                }
            ],
            "failed": [
                {
                    "dvdid": "SSIS-999",
                    "source_path": "/path/to/SSIS-999.mp4",
                    "reason": "无法获取影片信息"
                }
            ]
        }
    }
    
    返回结果（无任务）:
    {
        "code": 0,
        "message": "当前无任务",
        "data": null
    }
    """
    global current_task
    
    try:
        with task_lock:
            if current_task is None:
                return jsonify({
                    'code': ApiCode.SUCCESS,
                    'message': '当前无任务',
                    'data': None
                })
            
            task = current_task.copy()
        
        # 构建返回数据
        data = {
            'status': task['status'],
            'total': task['total'],
            'completed': task['completed'],
            'progress': f"{task['completed']}/{task['total']}"
        }
        
        # 如果任务已完成，返回详细结果
        if task['status'] != 'running':
            data['success_count'] = len(task['success'])
            data['failed_count'] = len(task['failed'])
            data['success'] = task['success']
            data['failed'] = task['failed']
            message = '任务已完成'
        else:
            message = '任务进行中'
        
        return jsonify({
            'code': ApiCode.SUCCESS,
            'message': message,
            'data': data
        })
        
    except Exception as e:
        logger.exception("查询任务状态失败")
        return jsonify({
            'code': ApiCode.INTERNAL_ERROR,
            'message': f'查询失败: {str(e)}',
            'data': None
        }), 500


@app.route('/api/config', methods=['GET'])
def get_config():
    """获取当前配置信息"""
    try:
        cfg = Cfg()
        source, dest = get_config_paths()
        
        return jsonify({
            'code': ApiCode.SUCCESS,
            'message': '获取配置成功',
            'data': {
                'paths': {
                    'source': source,
                    'dest': dest
                },
                'crawler': {
                    'selection': cfg.crawler.selection,
                    'required_keys': cfg.crawler.required_keys,
                    'hardworking': cfg.crawler.hardworking,
                },
                'translator': {
                    'engine': cfg.translator.engine.name if cfg.translator.engine else None,
                    'fields': {
                        'title': cfg.translator.fields.title,
                        'plot': cfg.translator.fields.plot,
                    }
                }
            }
        })
    except Exception as e:
        return jsonify({
            'code': ApiCode.INTERNAL_ERROR,
            'message': f'获取配置失败: {str(e)}',
            'data': None
        }), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'code': ApiCode.INVALID_PARAM,
        'message': '接口不存在',
        'data': None
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'code': ApiCode.INTERNAL_ERROR,
        'message': '服务器内部错误',
        'data': None
    }), 500


def run_api_server(host='0.0.0.0', port=5000, debug=False):
    """运行 API 服务器"""
    logger.info(f"启动 JavSP API 服务器: http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 运行服务器
    run_api_server(debug=True)
