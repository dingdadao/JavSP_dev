# JavSP 优化指南

本文档提供了 JavSP 项目的优化建议和最佳实践。

## 架构优化

### 1. 模块化重构

**问题：** `__main__.py`文件过于庞大（848 行），承担了太多职责

**解决方案：**

- 将并发抓取逻辑分离到 `javsp/core/crawler_manager.py`
- 将错误处理逻辑分离到 `javsp/utils/error_handler.py`
- 将性能优化工具分离到 `javsp/utils/performance.py`

**优势：**

- 提高代码可读性和可维护性
- 便于单元测试
- 降低模块间耦合度

### 2. 配置管理优化

**问题：** 配置文件中存在硬编码的 API 密钥

**解决方案：**

- 使用环境变量存储敏感信息
- 支持的环境变量：
  - `JAVSP_OPENAI_API_KEY`: OpenAI API 密钥
  - `JAVSP_BAIDU_APP_ID`: 百度翻译 APP ID
  - `JAVSP_BAIDU_API_KEY`: 百度翻译 API 密钥
  - `JAVSP_BING_API_KEY`: 必应翻译 API 密钥
  - `JAVSP_CLAUDE_API_KEY`: Claude API 密钥

**使用示例：**

```bash
export JAVSP_OPENAI_API_KEY="your-api-key-here"
python -m javsp
```

## 性能优化

### 1. 缓存机制

**实现：** `CacheManager`类提供简单的内存缓存

**使用场景：**

- 缓存已抓取的电影信息
- 缓存翻译结果
- 缓存网络请求结果

**配置：**

```python
cache = CacheManager(max_size=1000, ttl=3600)  # 最大1000项，1小时过期
```

### 2. 速率限制

**实现：** `RateLimiter`类防止请求过于频繁

**使用场景：**

- 限制对同一站点的请求频率
- 避免被站点封禁 IP

**配置：**

```python
rate_limiter = RateLimiter(max_requests=10, time_window=60)  # 60秒内最多10次请求
```

### 3. 批量处理

**实现：** `BatchProcessor`类支持并发批量处理

**使用场景：**

- 批量下载封面图片
- 批量生成 NFO 文件
- 批量文件重命名

## 错误处理优化

### 1. 统一错误处理

**实现：** `ErrorHandler`类提供统一的错误处理策略

**功能：**

- 根据错误类型决定是否重试
- 提供重试装饰器
- 安全执行函数包装器

### 2. 进度跟踪

**实现：** `ProgressTracker`类统一管理进度条

**优势：**

- 避免进度条冲突
- 提供统一的进度更新接口
- 自动资源管理

## 测试优化

### 1. 单元测试覆盖

**新增测试：**

- `test_crawler_manager.py`: 爬虫管理器测试
- 模拟网络请求和异常情况
- 验证数据汇总逻辑

### 2. 性能测试

**指标：**

- 抓取成功率
- 平均响应时间
- 内存使用情况
- 并发处理能力

## 代码质量改进

### 1. 类型注解

**建议：** 为所有函数添加完整的类型注解

**示例：**

```python
def process_movie(movie: Movie, config: Config) -> bool:
    """处理单个电影文件"""
    pass
```

### 2. 文档字符串

**建议：** 为所有公共函数和类添加详细的文档字符串

**格式：**

```python
def function_name(param1: str, param2: int) -> bool:
    """函数功能描述

    Args:
        param1: 参数1的描述
        param2: 参数2的描述

    Returns:
        返回值的描述

    Raises:
        ValueError: 当参数无效时抛出
    """
    pass
```

### 3. 代码风格

**遵循 PEP 8 规范：**

- 使用 4 个空格缩进
- 行长度不超过 79 字符
- 使用有意义的变量名
- 添加适当的空行分隔

## 部署优化

### 1. Docker 优化

**当前 Dockerfile 优化建议：**

- 使用多阶段构建减少镜像大小
- 添加健康检查
- 优化依赖安装顺序

### 2. 环境配置

**建议：** 使用`.env`文件管理环境变量

**示例：**

```bash
# .env
JAVSP_OPENAI_API_KEY=your-api-key
JAVSP_INPUT_DIRECTORY=/path/to/videos
JAVSP_OUTPUT_DIRECTORY=/path/to/output
```

## 监控和日志

### 1. 性能监控

**实现：** `@performance_monitor`装饰器

**功能：**

- 记录函数执行时间
- 统计成功/失败次数
- 生成性能报告

### 2. 日志优化

**建议：**

- 使用结构化日志
- 添加日志轮转
- 区分不同级别的日志

## 未来优化方向

### 1. 异步处理

**计划：** 使用`asyncio`替代多线程

**优势：**

- 更好的并发性能
- 减少资源消耗
- 更简单的错误处理

### 2. 数据库支持

**计划：** 添加 SQLite/PostgreSQL 支持

**功能：**

- 缓存抓取结果
- 记录处理历史
- 支持增量更新

### 3. Web 界面

**计划：** 开发 Web 管理界面

**功能：**

- 可视化配置管理
- 实时处理状态
- 批量操作支持

## 贡献指南

### 1. 代码提交

**要求：**

- 通过所有单元测试
- 符合代码风格规范
- 添加适当的文档

### 2. 性能测试

**要求：**

- 新功能不降低整体性能
- 提供性能测试报告
- 优化关键路径

### 3. 错误处理

**要求：**

- 添加适当的异常处理
- 提供有意义的错误信息
- 记录详细的错误日志
