"""统一错误处理模块"""
import logging
import traceback
from typing import Optional, Callable, Any
from functools import wraps
from tqdm import tqdm

from javsp.web.exceptions import *

logger = logging.getLogger(__name__)


class ErrorHandler:
    """统一错误处理器"""
    
    @staticmethod
    def handle_crawler_error(error: Exception, crawler_name: str, movie_id: str) -> bool:
        """处理爬虫错误，返回是否应该继续重试"""
        if isinstance(error, MovieNotFoundError):
            logger.debug(f"{crawler_name}: 未找到影片 {movie_id}")
            return False
        elif isinstance(error, MovieDuplicateError):
            logger.error(f"{crawler_name}: 影片 {movie_id} 存在重复")
            return False
        elif isinstance(error, (SiteBlocked, SitePermissionError, CredentialError)):
            logger.error(f"{crawler_name}: 站点访问受限 - {error}")
            return False
        elif isinstance(error, requests.exceptions.RequestException):
            logger.debug(f"{crawler_name}: 网络错误 - {error}")
            return True  # 网络错误可以重试
        else:
            logger.exception(f"{crawler_name}: 未知错误")
            return False
    
    @staticmethod
    def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
        """重试装饰器"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                last_error = None
                for attempt in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            logger.debug(f"第{attempt + 1}次尝试失败，{delay}秒后重试: {e}")
                            time.sleep(delay)
                        else:
                            logger.error(f"所有{max_retries}次尝试都失败了")
                raise last_error
            return wrapper
        return decorator
    
    @staticmethod
    def safe_execute(func: Callable, *args, **kwargs) -> Optional[Any]:
        """安全执行函数，捕获所有异常"""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.exception(f"执行函数 {func.__name__} 时发生错误")
            return None


class ProgressTracker:
    """进度跟踪器，统一管理tqdm进度条"""
    
    def __init__(self, total: int, desc: str = "处理中"):
        self.total = total
        self.desc = desc
        self.current = 0
        self.bar: Optional[tqdm] = None
    
    def __enter__(self):
        self.bar = tqdm(total=self.total, desc=self.desc, ascii=True, leave=False)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.bar:
            self.bar.close()
    
    def update(self, n: int = 1, description: str = None):
        """更新进度"""
        if self.bar:
            if description:
                self.bar.set_description(description)
            self.bar.update(n)
            self.current += n
    
    def set_description(self, description: str):
        """设置描述"""
        if self.bar:
            self.bar.set_description(description) 