"""性能优化工具模块"""
import time
import logging
import functools
from typing import Callable, Any, Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """性能指标数据类"""
    total_time: float
    success_count: int
    failure_count: int
    avg_time_per_item: float
    
    def __str__(self):
        return (f"总耗时: {self.total_time:.2f}s, "
                f"成功: {self.success_count}, "
                f"失败: {self.failure_count}, "
                f"平均耗时: {self.avg_time_per_item:.2f}s")


def performance_monitor(func: Callable) -> Callable:
    """性能监控装饰器"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            logger.debug(f"{func.__name__} 执行耗时: {execution_time:.2f}s")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"{func.__name__} 执行失败，耗时: {execution_time:.2f}s, 错误: {e}")
            raise
    return wrapper


class BatchProcessor:
    """批量处理器，支持并发处理"""
    
    def __init__(self, max_workers: int = 10, batch_size: int = 50):
        self.max_workers = max_workers
        self.batch_size = batch_size
    
    def process_batch(self, items: List[Any], processor_func: Callable, 
                     desc: str = "处理中") -> PerformanceMetrics:
        """批量处理项目"""
        start_time = time.time()
        success_count = 0
        failure_count = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_item = {
                executor.submit(processor_func, item): item 
                for item in items
            }
            
            # 收集结果
            for future in as_completed(future_to_item):
                try:
                    result = future.result()
                    success_count += 1
                except Exception as e:
                    failure_count += 1
                    logger.error(f"处理项目失败: {e}")
        
        total_time = time.time() - start_time
        avg_time = total_time / len(items) if items else 0
        
        metrics = PerformanceMetrics(
            total_time=total_time,
            success_count=success_count,
            failure_count=failure_count,
            avg_time_per_item=avg_time
        )
        
        logger.info(f"{desc} - {metrics}")
        return metrics


class CacheManager:
    """简单的缓存管理器"""
    
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl
        self.cache: Dict[str, tuple] = {}
    
    def get(self, key: str) -> Any:
        """获取缓存值"""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, value: Any):
        """设置缓存值"""
        if len(self.cache) >= self.max_size:
            # 简单的LRU策略：删除最旧的项
            oldest_key = min(self.cache.keys(), 
                           key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]
        
        self.cache[key] = (value, time.time())
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()


class RateLimiter:
    """速率限制器"""
    
    def __init__(self, max_requests: int, time_window: float):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    def can_proceed(self) -> bool:
        """检查是否可以继续请求"""
        now = time.time()
        # 清理过期的请求记录
        self.requests = [req_time for req_time in self.requests 
                        if now - req_time < self.time_window]
        
        if len(self.requests) < self.max_requests:
            self.requests.append(now)
            return True
        return False
    
    def wait_if_needed(self):
        """如果需要则等待"""
        while not self.can_proceed():
            time.sleep(0.1) 