"""爬虫管理器测试"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from javsp.core.crawler_manager import CrawlerManager
from javsp.datatype import Movie, MovieInfo
from javsp.web.exceptions import MovieNotFoundError, SiteBlocked


class TestCrawlerManager:
    """爬虫管理器测试类"""
    
    @pytest.fixture
    def crawler_manager(self):
        """创建爬虫管理器实例"""
        return CrawlerManager()
    
    @pytest.fixture
    def mock_movie(self):
        """创建模拟电影对象"""
        movie = Mock(spec=Movie)
        movie.dvdid = "TEST-001"
        movie.cid = None
        movie.data_src = "normal"
        return movie
    
    @pytest.fixture
    def mock_movie_info(self):
        """创建模拟电影信息对象"""
        info = Mock(spec=MovieInfo)
        info.dvdid = "TEST-001"
        info.title = "测试标题"
        info.cover = "http://example.com/cover.jpg"
        info.url = "http://example.com/movie"
        return info
    
    def test_remove_trail_actor_in_title(self, crawler_manager):
        """测试移除标题尾部女优名"""
        # 测试正常情况
        title = "测试标题 女优名"
        actress = ["女优名"]
        result = crawler_manager._remove_trail_actor_in_title(title, actress)
        assert result == "测试标题"
        
        # 测试没有匹配的情况
        title = "测试标题"
        actress = ["其他女优"]
        result = crawler_manager._remove_trail_actor_in_title(title, actress)
        assert result == "测试标题"
        
        # 测试空参数
        result = crawler_manager._remove_trail_actor_in_title("", [])
        assert result == ""
    
    @patch('javsp.core.crawler_manager.sys.modules')
    @patch('javsp.core.crawler_manager.threading.Thread')
    def test_parallel_crawler_success(self, mock_thread, mock_modules, 
                                    crawler_manager, mock_movie):
        """测试并发抓取成功情况"""
        # 模拟配置
        crawler_manager.config.crawler.selection = {
            "normal": ["airav", "javdb"]
        }
        crawler_manager.config.network.retry = 1
        crawler_manager.config.network.timeout.total_seconds.return_value = 10
        
        # 模拟模块和解析器
        mock_parser = Mock()
        mock_parser.return_value = None  # 成功执行
        
        mock_modules.__getitem__.return_value = Mock()
        mock_modules.__getitem__.return_value.parse_data = mock_parser
        
        # 模拟线程
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance
        
        # 执行测试
        result = crawler_manager.parallel_crawler(mock_movie)
        
        # 验证结果
        assert isinstance(result, dict)
        assert len(result) == 2  # 两个爬虫
        assert "airav" in result
        assert "javdb" in result
    
    @patch('javsp.core.crawler_manager.sys.modules')
    @patch('javsp.core.crawler_manager.threading.Thread')
    def test_parallel_crawler_with_errors(self, mock_thread, mock_modules,
                                        crawler_manager, mock_movie):
        """测试并发抓取包含错误的情况"""
        # 模拟配置
        crawler_manager.config.crawler.selection = {
            "normal": ["airav", "javdb"]
        }
        crawler_manager.config.network.retry = 1
        crawler_manager.config.network.timeout.total_seconds.return_value = 10
        
        # 模拟解析器抛出异常
        def mock_parser_with_error(info):
            if "airav" in str(info):
                raise MovieNotFoundError("airav", "TEST-001", [])
            else:
                raise SiteBlocked("站点被屏蔽")
        
        mock_modules.__getitem__.return_value = Mock()
        mock_modules.__getitem__.return_value.parse_data = mock_parser_with_error
        
        # 模拟线程
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance
        
        # 执行测试
        result = crawler_manager.parallel_crawler(mock_movie)
        
        # 验证结果 - 应该没有成功的爬虫
        assert isinstance(result, dict)
        assert len(result) == 0
    
    def test_summarize_info_success(self, crawler_manager, mock_movie):
        """测试数据汇总成功情况"""
        # 创建模拟数据
        all_info = {
            "airav": Mock(spec=MovieInfo),
            "javdb": Mock(spec=MovieInfo)
        }
        
        # 设置模拟数据
        all_info["airav"].title = "标题1"
        all_info["airav"].cover = "http://example.com/cover1.jpg"
        all_info["javdb"].title = "标题2"
        all_info["javdb"].cover = "http://example.com/cover2.jpg"
        all_info["javdb"].genre = ["动作", "剧情"]
        
        # 模拟配置
        crawler_manager.config.crawler.required_keys = ["cover", "title"]
        crawler_manager.config.summarizer.title.remove_trailing_actor_name = False
        crawler_manager.config.crawler.respect_site_avid = False
        crawler_manager.config.crawler.use_javdb_cover = "fallback"
        
        # 执行测试
        result = crawler_manager.summarize_info(mock_movie, all_info)
        
        # 验证结果
        assert result is True
        assert mock_movie.info is not None
        assert mock_movie.info.title == "标题1"  # 第一个非空标题
        assert mock_movie.info.genre == ["动作", "剧情"]  # javdb的genre
    
    def test_summarize_info_no_data(self, crawler_manager, mock_movie):
        """测试数据汇总无数据情况"""
        result = crawler_manager.summarize_info(mock_movie, {})
        assert result is False
    
    def test_summarize_info_missing_required_fields(self, crawler_manager, mock_movie):
        """测试数据汇总缺少必需字段情况"""
        # 创建模拟数据，但缺少必需字段
        all_info = {
            "airav": Mock(spec=MovieInfo)
        }
        all_info["airav"].title = None  # 缺少title
        all_info["airav"].cover = None  # 缺少cover
        
        # 模拟配置
        crawler_manager.config.crawler.required_keys = ["cover", "title"]
        
        # 执行测试
        result = crawler_manager.summarize_info(mock_movie, all_info)
        
        # 验证结果
        assert result is False 