from argparse import ArgumentParser, RawTextHelpFormatter
from enum import Enum
from typing import Dict, List, Literal, TypeAlias, Union, Optional
from confz import BaseConfig, CLArgSource, EnvSource, FileSource
from pydantic import ByteSize, Field, NonNegativeInt, PositiveInt
from pydantic_extra_types.pendulum_dt import Duration
from pydantic_core import Url
from pathlib import Path
import os

from javsp.lib import resource_path


class Scanner(BaseConfig):
    ignored_id_pattern: List[str]
    input_directory: Path | None = None
    filename_extensions: List[str]
    ignored_folder_name_pattern: List[str]
    minimum_size: ByteSize
    skip_nfo_dir: bool
    manual: bool
    clear_skipped_on_rescan: bool = False  # 重新扫描时是否清理 .skipped 文件


class CrawlerID(str, Enum):
    airav = 'airav'
    avsox = 'avsox'
    avwiki = 'avwiki'
    dl_getchu = 'dl_getchu'
    fanza = 'fanza'
    fc2 = 'fc2'
    fc2fan = 'fc2fan'
    fc2ppvdb = 'fc2ppvdb'
    gyutto = 'gyutto'
    jav321 = 'jav321'
    javbus = 'javbus'
    javdb = 'javdb'
    javlib = 'javlib'
    javmenu = 'javmenu'
    mgstage = 'mgstage'
    njav = 'njav'
    prestige = 'prestige'
    arzon = 'arzon'
    arzon_iv = 'arzon_iv'
    missav = 'missav'


class Network(BaseConfig):
    proxy_server: Url | None
    retry: NonNegativeInt = 3
    timeout: Duration
    proxy_free: Dict[CrawlerID, Url]
    # 爬虫镜像地址，配置后优先使用镜像地址
    crawler_mirror: Dict[CrawlerID, str] = {}
    ssl_verification: bool = True

    def get_crawler_url(self, crawler_id: CrawlerID, permanent_url: str) -> str:
        """获取爬虫的实际访问地址，优先使用镜像地址"""
        mirror = self.crawler_mirror.get(crawler_id)
        if mirror and mirror.strip():
            return mirror.rstrip('/')
        if self.proxy_server:
            return permanent_url
        free_url = self.proxy_free.get(crawler_id)
        return str(free_url) if free_url else permanent_url
    # 连接池配置
    pool_connections: int = 20
    pool_maxsize: int = 20
    pool_block: bool = False
    # 重试配置
    retry_total: int = 3
    retry_backoff_factor: float = 1.0
    retry_status_forcelist: list[int] = [429, 500, 502, 503, 504, 521]  # 521: CloudFlare Web Server Is Down
    # 站点 Cookie 配置（可选，用于需要登录的站点）
    # 格式: JSON 字符串或键值对，例如: '{"javdb": {"cookie1": "value1", "cookie2": "value2"}}'
    site_cookies: Dict[str, Dict[str, str]] = {}


class CrawlerSelect(BaseConfig):
    def items(self) -> List[tuple[str, list[CrawlerID]]]:
        return [
            ('normal', self.normal),
            ('fc2', self.fc2),
            ('cid', self.cid),
            ('getchu', self.getchu),
            ('gyutto', self.gyutto),
        ]

    def __getitem__(self, index) -> list[CrawlerID]:
        if index == 'normal':
            return self.normal
        elif index == 'fc2':
            return self.fc2
        elif index == 'cid':
            return self.cid
        elif index == 'getchu':
            return self.getchu
        elif index == 'gyutto':
            return self.gyutto
        else:
            raise Exception("Unknown crawler type")

    normal: list[CrawlerID]
    fc2: list[CrawlerID]
    cid: list[CrawlerID]
    getchu: list[CrawlerID]
    gyutto: list[CrawlerID]


class MovieInfoField(str, Enum):
    dvdid = 'dvdid'
    cid = 'cid'
    url = 'url'
    plot = 'plot'
    cover = 'cover'
    big_cover = 'big_cover'
    genre = 'genre'
    genre_id = 'genre_id'
    genre_norm = 'genre_norm'
    score = 'score'
    title = 'title'
    ori_title = 'ori_title'
    magnet = 'magnet'
    serial = 'serial'
    actress = 'actress'
    actress_pics = 'actress_pics'
    director = 'director'
    duration = 'duration'
    producer = 'producer'
    publisher = 'publisher'
    uncensored = 'uncensored'
    publish_date = 'publish_date'
    preview_pics = 'preview_pics'
    preview_video = 'preview_video'


class UseJavDBCover(str, Enum):
    yes = "yes"
    no = "no"
    fallback = "fallback"


class Crawler(BaseConfig):
    selection: CrawlerSelect
    required_keys: list[MovieInfoField]
    hardworking: bool
    respect_site_avid: bool
    fc2fan_local_path: Path | None
    sleep_after_scraping: Duration
    use_javdb_cover: UseJavDBCover
    normalize_actress_name: bool


class MovieDefault(BaseConfig):
    title: str
    actress: str
    series: str
    director: str
    producer: str
    publisher: str


class PathSummarize(BaseConfig):
    output_folder_pattern: str
    basename_pattern: str
    file_basename_pattern: str = ''  # 影片文件名的命名规则，为空时使用 basename_pattern
    length_maximum: PositiveInt
    length_by_byte: bool
    max_actress_count: PositiveInt = 10
    hard_link: bool


class TitleSummarize(BaseConfig):
    remove_trailing_actor_name: bool


class DuplicateFilePolicy(BaseConfig):
    """重复文件处理策略"""
    # 处理策略: auto_select(自动选择大文件), manual(手动选择), skip(跳过)
    strategy: str = 'auto_select'
    # 自动选择时，文件大小差异阈值（字节），小于此值则跳过
    size_threshold: int = 1024 * 1024  # 1MB
    # 自动解决重复文件冲突 (0=关闭, 1=开启)
    # 开启后，当同一番号有多个文件时，自动按优先级选择：-C(字幕) > -UC(无修正) > -U(普通)
    auto_resolve_duplicate: int = 0


class NFOSummarize(BaseConfig):
    basename_pattern: str
    title_pattern: str
    custom_genres_fields: list[str]
    custom_tags_fields: list[str]
    # 飞牛 NAS 兼容模式：添加飞牛特定的字段和格式
    fnos_compatible: bool = False


class ExtraFanartSummarize(BaseConfig):
    enabled: bool
    concurrent_downloads: int = 3  # 并发下载数量
    max_download_count: int = 6  # 最大下载剧照数量


class SlimefaceEngine(BaseConfig):
    name: Literal['slimeface']


class CoverCrop(BaseConfig):
    engine: SlimefaceEngine | None
    on_id_pattern: list[str]


class CoverSummarize(BaseConfig):
    basename_pattern: str
    highres: bool
    add_label: bool
    crop: CoverCrop


class FanartSummarize(BaseConfig):
    basename_pattern: str


class Summarizer(BaseConfig):
    default: MovieDefault
    censor_options_representation: list[str]
    title: TitleSummarize
    move_files: bool = True
    path: PathSummarize
    nfo: NFOSummarize
    cover: CoverSummarize
    fanart: FanartSummarize
    extra_fanarts: ExtraFanartSummarize
    duplicate_file: DuplicateFilePolicy = DuplicateFilePolicy()


class BaiduTranslateEngine(BaseConfig):
    name: Literal['baidu']
    app_id: str
    api_key: str
    max_retry: int = 3
    retry_delay: int = 1


class BingTranslateEngine(BaseConfig):
    name: Literal['bing']
    api_key: str
    max_retry: int = 3
    retry_delay: int = 1


class ClaudeTranslateEngine(BaseConfig):
    name: Literal['claude']
    api_key: str
    max_retry: int = 3
    retry_delay: int = 1


class OpenAITranslateEngine(BaseConfig):
    name: Literal['openai']
    url: Url
    api_key: str
    model: str
    max_retry: int = 3
    retry_delay: int = 1


class LocalAITranslateEngine(BaseConfig):
    name: Literal['localai']
    url: Url
    api_key: str = ''
    model: str
    context_window: int = 2048
    max_retry: int = 3
    retry_delay: int = 1


class GoogleTranslateEngine(BaseConfig):
    name: Literal['google']
    max_retry: int = 3
    retry_delay: int = 1


class GoogleAITranslateEngine(BaseConfig):
    name: Literal['googleai']
    url: Url
    api_key: str
    model: str
    max_retry: int = 3
    retry_delay: int = 1


TranslateEngine: TypeAlias = Union[
    BaiduTranslateEngine,
    BingTranslateEngine,
    ClaudeTranslateEngine,
    OpenAITranslateEngine,
    LocalAITranslateEngine,
    GoogleTranslateEngine,
    GoogleAITranslateEngine,
    None]


class TranslateField(BaseConfig):
    title: bool
    plot: bool


class Translator(BaseConfig):
    engine: TranslateEngine = Field(..., discriminator='name')
    fields: TranslateField

    def __init__(self, **data):
        super().__init__(**data)
        # 从环境变量读取API密钥
        if self.engine and self.engine.api_key is None:
            if self.engine.name == 'openai':
                self.engine.api_key = os.getenv('JAVSP_OPENAI_API_KEY')
            elif self.engine.name == 'baidu':
                self.engine.app_id = os.getenv('JAVSP_BAIDU_APP_ID')
                self.engine.api_key = os.getenv('JAVSP_BAIDU_API_KEY')
            elif self.engine.name == 'bing':
                self.engine.api_key = os.getenv('JAVSP_BING_API_KEY')
            elif self.engine.name == 'claude':
                self.engine.api_key = os.getenv('JAVSP_CLAUDE_API_KEY')


class Other(BaseConfig):
    interactive: bool
    check_update: bool
    auto_update: bool


def get_config_source():
    parser = ArgumentParser(
        prog='dingdadaoSp', description='汇总多站点数据的AV元数据刮削器', formatter_class=RawTextHelpFormatter)
    parser.add_argument('-c', '--config', help='使用指定的配置文件')
    args, _ = parser.parse_known_args()
    sources = []
    if args.config is None:
        args.config = resource_path('config.yml')
    sources.append(FileSource(file=args.config))
    sources.append(EnvSource(prefix='JAVSP_', allow_all=True))
    sources.append(CLArgSource(prefix='o'))
    return sources


class Cfg(BaseConfig):
    scanner: Scanner
    network: Network
    crawler: Crawler
    summarizer: Summarizer
    translator: Translator
    other: Other
    CONFIG_SOURCES = get_config_source()
