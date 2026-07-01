"""网络请求的统一接口"""
from javsp.web.exceptions import *
from javsp.config import Cfg
import os
import sys
import time
import logging
import webbrowser
import contextlib
import requests
import lxml.html
from curl_cffi import requests as curl_requests
from tqdm import tqdm
from lxml import etree
from lxml.html.clean import Cleaner
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


__all__ = ['Request', 'get_html', 'post_html', 'request_get', 'resp2html',
           'is_connectable', 'download', 'get_resp_text', 'read_proxy', 'set_ssl_verification',
           'close_global_session', 'reset_global_session']


headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}

# SSL验证设置
ssl_verify = Cfg().network.ssl_verification

logger = logging.getLogger(__name__)
# 删除js脚本相关的tag，避免网页检测到没有js运行环境时强行跳转，影响调试
cleaner = Cleaner(kill_tags=['script', 'noscript'])

# 全局 curl_cffi Session，用于复用连接
_global_curl_session = None


def _get_curl_session():
    """获取全局 curl_cffi Session"""
    global _global_curl_session
    if _global_curl_session is None:
        _global_curl_session = curl_requests.Session(
            impersonate="chrome120"
        )
    return _global_curl_session


def _close_curl_session():
    """关闭全局 curl_cffi Session"""
    global _global_curl_session
    if _global_curl_session:
        _global_curl_session.close()
        _global_curl_session = None


def read_proxy():
    if Cfg().network.proxy_server is None:
        return {}
    else:
        proxy = str(Cfg().network.proxy_server)
        return {'http': proxy, 'https': proxy}


def set_ssl_verification(verify):
    """设置SSL证书验证状态"""
    global ssl_verify
    ssl_verify = verify
    logger.info(f"SSL验证已设置为: {verify}")


def close_global_session():
    """关闭全局会话，清理连接池"""
    if hasattr(_global_session, 'close'):
        _global_session.close()
    _close_curl_session()
    logger.debug("全局会话已关闭，连接池已清理")


def reset_global_session():
    """重置全局会话，重新创建连接池"""
    global _global_session
    if hasattr(_global_session, 'close'):
        _global_session.close()
    _global_session = _create_global_session()
    _close_curl_session()
    logger.debug("全局会话已重置，连接池已重建")

# 与网络请求相关的功能汇总到一个模块中以方便处理，但是不同站点的抓取器又有自己的需求（针对不同网站
# 需要使用不同的UA、语言等）。每次都传递参数很麻烦，而且会面临函数参数越加越多的问题。因此添加这个
# 处理网络请求的类，它带有默认的属性，但是也可以在各个抓取器模块里进行进行定制


class Request():
    """作为网络请求出口并支持各个模块定制功能"""

    def __init__(self, use_scraper=False, cookies=None) -> None:
        # 必须使用copy()，否则各个模块对headers的修改都将会指向本模块中定义的headers变量，导致只有最后一个对headers的修改生效
        self.headers = headers.copy()
        self.cookies = cookies.copy() if cookies else {}

        self.proxies = read_proxy()
        self.timeout = Cfg().network.timeout.total_seconds()

        # 创建会话对象以支持连接池
        self.session = requests.Session()

        # 获取配置
        config = Cfg().network

        # 配置重试策略
        retry_strategy = Retry(
            total=config.retry_total,
            backoff_factor=config.retry_backoff_factor,
            status_forcelist=config.retry_status_forcelist,
        )
        adapter = HTTPAdapter(
            pool_connections=config.pool_connections,  # 连接池数量
            pool_maxsize=config.pool_maxsize,          # 最大连接数
            pool_block=config.pool_block,              # 是否阻塞等待连接
            max_retries=retry_strategy
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        if not use_scraper:
            self.scraper = None
            # 使用会话对象进行请求以支持连接复用
            self.__get = self._create_request_wrapper(self.session.get)
            self.__post = self._create_request_wrapper(self.session.post)
            self.__head = self._create_request_wrapper(self.session.head)
        else:
            # 使用全局 curl_cffi Session 以复用连接
            self.scraper = _get_curl_session()
            # 设置代理
            if self.proxies:
                proxy_url = self.proxies.get('http') or self.proxies.get('https')
                if proxy_url:
                    self.scraper.proxies = {'http': proxy_url, 'https': proxy_url}
            # 设置 SSL 验证
            self.scraper.verify = ssl_verify
            # 同步 Cookie 到 curl_cffi Session
            if self.cookies:
                self.scraper.cookies.update(self.cookies)
            self.__get = self._scraper_monitor(
                self._create_request_wrapper(self.scraper.get))
            self.__post = self._scraper_monitor(
                self._create_request_wrapper(self.scraper.post))
            self.__head = self._scraper_monitor(
                self._create_request_wrapper(self.scraper.head))

    def _scraper_monitor(self, func):
        """监控curl_cffi的工作状态，遇到403/521时尝试退回常规的requests请求"""
        def wrapper(*args, **kw):
            try:
                return func(*args, **kw)
            except Exception as e:
                error_msg = str(e).lower()
                # 如果是403/521错误，尝试退回常规requests请求
                if '403' in error_msg or 'forbidden' in error_msg or '521' in error_msg:
                    logger.debug(f"curl_cffi返回错误: '{e}', 尝试退回常规的requests请求")
                    # 根据函数名称判断是get还是post请求
                    if 'get' in str(func).lower():
                        kw_copy = kw.copy()
                        kw_copy.setdefault('verify', ssl_verify)
                        try:
                            return requests.get(*args, **kw_copy)
                        except Exception as fallback_error:
                            logger.debug(f"退回常规请求也失败: {fallback_error}")
                            raise
                    else:
                        kw_copy = kw.copy()
                        kw_copy.setdefault('verify', ssl_verify)
                        try:
                            return requests.post(*args, **kw_copy)
                        except Exception as fallback_error:
                            logger.debug(f"退回常规请求也失败: {fallback_error}")
                            raise
                else:
                    raise
        return wrapper

    def _create_request_wrapper(self, original_func):
        """创建请求包装器以支持SSL验证配置"""
        def wrapper(*args, **kwargs):
            # 确保请求使用当前的SSL验证设置
            kwargs.setdefault('verify', ssl_verify)
            return original_func(*args, **kwargs)
        return wrapper

    def get(self, url, delay_raise=False):
        # 对于scraper，verify参数已经在scraper实例中设置，不需要单独传递
        try:
            if self.scraper is not None:
                r = self.__get(url,
                               headers=self.headers,
                               proxies=self.proxies,
                               cookies=self.cookies,
                               timeout=self.timeout)
                # 检测 403 响应，curl_cffi 可能不会抛出异常
                if r.status_code == 403:
                    logger.debug(f"curl_cffi 返回 403，尝试退回常规 requests: {url}")
                    try:
                        r = requests.get(url,
                                        headers=self.headers,
                                        proxies=self.proxies,
                                        cookies=self.cookies,
                                        timeout=self.timeout,
                                        verify=ssl_verify)
                    except Exception as fallback_error:
                        logger.debug(f"退回常规请求也失败: {fallback_error}")
                        raise
            else:
                r = self.__get(url,
                               headers=self.headers,
                               proxies=self.proxies,
                               cookies=self.cookies,
                               timeout=self.timeout,
                               verify=ssl_verify)
        except requests.exceptions.SSLError as e:
            # 如果是SSL错误，尝试禁用SSL验证重试
            if ssl_verify and ('eof occurred in violation of protocol' in str(e).lower() or 'ssl' in str(e).lower()):
                logger.debug(f"SSL错误，尝试禁用SSL验证重试: {url}")
                if self.scraper is not None:
                    # 临时修改scraper的SSL验证设置
                    original_verify = self.scraper.verify
                    self.scraper.verify = False
                    try:
                        r = self.__get(url,
                                       headers=self.headers,
                                       proxies=self.proxies,
                                       cookies=self.cookies,
                                       timeout=self.timeout)
                    finally:
                        self.scraper.verify = original_verify
                else:
                    r = self.__get(url,
                                   headers=self.headers,
                                   proxies=self.proxies,
                                   cookies=self.cookies,
                                   timeout=self.timeout,
                                   verify=False)
            else:
                raise
        if not delay_raise:
            r.raise_for_status()
        return r

    def post(self, url, data, delay_raise=False):
        # 对于scraper，verify参数已经在scraper实例中设置，不需要单独传递
        try:
            if self.scraper is not None:
                r = self.__post(url,
                                data=data,
                                headers=self.headers,
                                proxies=self.proxies,
                                cookies=self.cookies,
                                timeout=self.timeout)
            else:
                r = self.__post(url,
                                data=data,
                                headers=self.headers,
                                proxies=self.proxies,
                                cookies=self.cookies,
                                timeout=self.timeout,
                                verify=ssl_verify)
        except requests.exceptions.SSLError as e:
            # 如果是SSL错误，尝试禁用SSL验证重试
            if ssl_verify and ('eof occurred in violation of protocol' in str(e).lower() or 'ssl' in str(e).lower()):
                logger.debug(f"SSL错误，尝试禁用SSL验证重试: {url}")
                if self.scraper is not None:
                    # 临时修改scraper的SSL验证设置
                    original_verify = self.scraper.verify
                    self.scraper.verify = False
                    try:
                        r = self.__post(url,
                                        data=data,
                                        headers=self.headers,
                                        proxies=self.proxies,
                                        cookies=self.cookies,
                                        timeout=self.timeout)
                    finally:
                        self.scraper.verify = original_verify
                else:
                    r = self.__post(url,
                                    data=data,
                                    headers=self.headers,
                                    proxies=self.proxies,
                                    cookies=self.cookies,
                                    timeout=self.timeout,
                                    verify=False)
            else:
                raise
        if not delay_raise:
            r.raise_for_status()
        return r

    def head(self, url, delay_raise=True):
        # 对于scraper，verify参数已经在scraper实例中设置，不需要单独传递
        try:
            if self.scraper is not None:
                r = self.__head(url,
                                headers=self.headers,
                                proxies=self.proxies,
                                cookies=self.cookies,
                                timeout=self.timeout)
            else:
                r = self.__head(url,
                                headers=self.headers,
                                proxies=self.proxies,
                                cookies=self.cookies,
                                timeout=self.timeout,
                                verify=ssl_verify)
        except requests.exceptions.SSLError as e:
            # 如果是SSL错误，尝试禁用SSL验证重试
            if ssl_verify and ('eof occurred in violation of protocol' in str(e).lower() or 'ssl' in str(e).lower()):
                logger.debug(f"SSL错误，尝试禁用SSL验证重试: {url}")
                if self.scraper is not None:
                    # 临时修改scraper的SSL验证设置
                    original_verify = self.scraper.verify
                    self.scraper.verify = False
                    try:
                        r = self.__head(url,
                                        headers=self.headers,
                                        proxies=self.proxies,
                                        cookies=self.cookies,
                                        timeout=self.timeout)
                    finally:
                        self.scraper.verify = original_verify
                else:
                    r = self.__head(url,
                                    headers=self.headers,
                                    proxies=self.proxies,
                                    cookies=self.cookies,
                                    timeout=self.timeout,
                                    verify=False)
            else:
                raise
        if not delay_raise:
            r.raise_for_status()
        return r

    def get_html(self, url):
        r = self.get(url)
        html = resp2html(r)
        return html


class DownloadProgressBar(tqdm):
    def update_to(self, b=1, bsize=1, tsize=None):
        if tsize is not None:
            self.total = tsize
        self.update(b * bsize - self.n)


# 创建全局会话对象以支持连接池
def _create_global_session():
    """创建全局会话，默认使用 curl_cffi 模拟浏览器 TLS 指纹"""
    # 优先使用 curl_cffi 来绕过 CloudFlare 等网站的 TLS 指纹检测
    try:
        session = curl_requests.Session(impersonate="chrome120")
        # 设置代理
        proxies = read_proxy()
        if proxies:
            proxy_url = proxies.get('http') or proxies.get('https')
            if proxy_url:
                session.proxies = {'http': proxy_url, 'https': proxy_url}
        # 设置 SSL 验证
        session.verify = ssl_verify
        logger.debug("使用 curl_cffi Session (chrome120)")
        return session
    except Exception as e:
        logger.warning(f"curl_cffi 初始化失败，回退到普通 requests: {e}")
        # 回退到普通 requests
        session = requests.Session()
        
        # 获取配置
        config = Cfg().network
        
        # 配置重试策略
        retry_strategy = Retry(
            total=config.retry_total,
            backoff_factor=config.retry_backoff_factor,
            status_forcelist=config.retry_status_forcelist,
        )
        adapter = HTTPAdapter(
            pool_connections=config.pool_connections,
            pool_maxsize=config.pool_maxsize,
            pool_block=config.pool_block,
            max_retries=retry_strategy
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session


_global_session = _create_global_session()

# 创建独立的下载session（使用普通requests，线程安全）
_download_session = requests.Session()
_download_session.headers.update(headers)
_download_proxies = read_proxy()
if _download_proxies:
    _download_session.proxies.update(_download_proxies)


def request_get(url, cookies={}, timeout=None, delay_raise=False, verify_ssl=None, use_scraper=False):
    """获取指定url的原始请求"""
    if timeout is None:
        timeout = Cfg().network.timeout.seconds

    # 使用全局SSL验证设置，除非特别指定了
    if verify_ssl is None:
        verify_ssl = ssl_verify

    # 如果全局会话已经是 curl_cffi，直接使用
    if hasattr(_global_session, 'impersonate'):
        try:
            r = _global_session.get(url, headers=headers, timeout=timeout)
            if not delay_raise:
                r.raise_for_status()
            return r
        except Exception as e:
            logger.debug(f"curl_cffi GET 失败: {e}")
            raise

    # 使用普通 requests
    try:
        r = _global_session.get(url, headers=headers, proxies=read_proxy(),
                                cookies=cookies, timeout=timeout, verify=verify_ssl)
    except requests.exceptions.SSLError as e:
        # 如果是SSL错误且当前启用了SSL验证，尝试禁用SSL验证重试
        if verify_ssl and ('eof occurred in violation of protocol' in str(e).lower() or 'ssl' in str(e).lower()):
            logger.debug(f"SSL错误，尝试禁用SSL验证重试: {url}")
            r = _global_session.get(url, headers=headers, proxies=read_proxy(),
                                    cookies=cookies, timeout=timeout, verify=False)
        else:
            raise

    if not delay_raise:
        if r.status_code == 403 and b'>Just a moment...<' in r.content:
            raise SiteBlocked(f"403 Forbidden: 无法通过CloudFlare检测: {url}")
        else:
            r.raise_for_status()
    return r


def request_post(url, data, cookies={}, timeout=None, delay_raise=False, verify_ssl=None, use_scraper=False):
    """向指定url发送post请求"""
    if timeout is None:
        timeout = Cfg().network.timeout.seconds

    # 使用全局SSL验证设置，除非特别指定了
    if verify_ssl is None:
        verify_ssl = ssl_verify

    # 如果指定使用 scraper (curl_cffi)，则使用 curl_cffi 发送请求
    if use_scraper:
        try:
            session = _get_curl_session()
            # 设置代理
            proxies = read_proxy()
            if proxies:
                proxy_url = proxies.get('http') or proxies.get('https')
                if proxy_url:
                    session.proxies = {'http': proxy_url, 'https': proxy_url}
            # 设置 SSL 验证
            session.verify = verify_ssl
            # 同步 Cookie
            if cookies:
                session.cookies.update(cookies)
            r = session.post(url, data=data, headers=headers, timeout=timeout)
            if not delay_raise:
                r.raise_for_status()
            return r
        except Exception as e:
            # curl_cffi 失败时回退到普通 requests
            logger.debug(f"curl_cffi POST 失败，回退到普通 requests: {e}")
    
    # 使用普通 requests
    try:
        r = _global_session.post(url, data=data, headers=headers, proxies=read_proxy(
        ), cookies=cookies, timeout=timeout, verify=verify_ssl)
    except requests.exceptions.SSLError as e:
        # 如果是SSL错误且当前启用了SSL验证，尝试禁用SSL验证重试
        if verify_ssl and ('eof occurred in violation of protocol' in str(e).lower() or 'ssl' in str(e).lower()):
            logger.debug(f"SSL错误，尝试禁用SSL验证重试: {url}")
            r = _global_session.post(url, data=data, headers=headers, proxies=read_proxy(
            ), cookies=cookies, timeout=timeout, verify=False)
        else:
            raise

    if not delay_raise:
        r.raise_for_status()
    return r


def get_resp_text(resp, encoding=None):
    """提取Response的文本"""
    if encoding:
        resp.encoding = encoding
    else:
        # 优先使用 apparent_encoding（requests）
        if hasattr(resp, 'apparent_encoding') and resp.apparent_encoding:
            resp.encoding = resp.apparent_encoding
        # curl_cffi 已自动检测编码
        elif resp.encoding:
            pass
        # 最后回退到 UTF-8
        else:
            resp.encoding = 'utf-8'
    return resp.text


def get_html(url, encoding='utf-8'):
    """使用get方法访问指定网页并返回经lxml解析后的document"""
    resp = request_get(url)
    text = get_resp_text(resp, encoding=encoding)
    html = lxml.html.fromstring(text)
    html.make_links_absolute(url, resolve_base_href=True)
    # 清理功能仅应在需要的时候用来调试网页（如prestige），否则可能反过来影响调试（如JavBus）
    # html = cleaner.clean_html(html)
    if hasattr(sys, 'javsp_debug_mode'):
        # for develop and debug
        lxml.html.open_in_browser(html, encoding=encoding)
    return html


def resp2html(resp, encoding='utf-8') -> lxml.html.HtmlComment:
    """将request返回的response转换为经lxml解析后的document"""
    text = get_resp_text(resp, encoding=encoding)
    html = lxml.html.fromstring(text)
    html.make_links_absolute(resp.url, resolve_base_href=True)
    # html = cleaner.clean_html(html)
    if hasattr(sys, 'javsp_debug_mode'):
        # for develop and debug
        lxml.html.open_in_browser(html, encoding=encoding)
    return html


def post_html(url, data, encoding='utf-8', cookies={}, use_scraper=True):
    """使用post方法访问指定网页并返回经lxml解析后的document"""
    resp = request_post(url, data, cookies=cookies, use_scraper=use_scraper)
    text = get_resp_text(resp, encoding=encoding)
    html = lxml.html.fromstring(text)
    # jav321提供ed2k形式的资源链接，其中的非ASCII字符可能导致转换失败，因此要先进行处理
    ed2k_tags = html.xpath("//a[starts-with(@href,'ed2k://')]")
    for tag in ed2k_tags:
        tag.attrib['ed2k'], tag.attrib['href'] = tag.attrib['href'], ''
    html.make_links_absolute(url, resolve_base_href=True)
    for tag in ed2k_tags:
        tag.attrib['href'] = tag.attrib['ed2k']
        tag.attrib.pop('ed2k')
    # html = cleaner.clean_html(html)
    # lxml.html.open_in_browser(html, encoding=encoding)  # for develop and debug
    return html


def dump_xpath_node(node, filename=None):
    """将xpath节点dump到文件"""
    if not filename:
        filename = node.tag + '.html'
    with open(filename, 'wt', encoding='utf-8') as f:
        content = etree.tostring(node, pretty_print=True).decode('utf-8')
        f.write(content)


def is_connectable(url, timeout=3):
    """测试与指定url的连接"""
    try:
        r = _global_session.get(url, headers=headers,
                                timeout=timeout, verify=ssl_verify)
        return True
    except requests.exceptions.RequestException as e:
        logger.debug(f"Not connectable: {url}\n" + repr(e))
        return False


def urlretrieve(url, filename=None, reporthook=None, headers=None, max_retry=3, retry_delay=1):
    if "arzon" in url:
        headers["Referer"] = "https://www.arzon.jp/"
    """使用requests实现urlretrieve，带重试机制"""
    # https://blog.csdn.net/qq_38282706/article/details/80253447
    
    for attempt in range(1, max_retry + 1):
        try:
            # 使用独立的下载session（普通requests，线程安全）
            with contextlib.closing(_download_session.get(url, headers=headers,
                                                        stream=True, verify=ssl_verify)) as r:
                header = r.headers
                with open(filename, 'wb+') as fp:
                    bs = 1024
                    size = -1
                    blocknum = 0
                    if "content-length" in header:
                        size = int(header["Content-Length"])    # 文件总大小（理论值）
                    if reporthook:                              # 写入前运行一次回调函数
                        reporthook(blocknum, bs, size)
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:
                            fp.write(chunk)
                            fp.flush()
                            blocknum += 1
                            if reporthook:
                                reporthook(blocknum, bs, size)  # 每写入一次运行一次回调函数
            return  # 成功则直接返回
        except requests.exceptions.SSLError as e:
            logger.debug(f"下载 {url} 第 {attempt} 次失败 (SSL错误): {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
                # 尝试禁用SSL验证重试
                logger.debug(f"尝试禁用SSL验证重试: {url}")
                try:
                    with contextlib.closing(_global_session.get(url, headers=headers,
                                                                proxies=read_proxy(), stream=True, verify=False)) as r:
                        header = r.headers
                        with open(filename, 'wb+') as fp:
                            bs = 1024
                            size = -1
                            blocknum = 0
                            if "content-length" in header:
                                size = int(header["Content-Length"])
                            if reporthook:
                                reporthook(blocknum, bs, size)
                            for chunk in r.iter_content(chunk_size=1024):
                                if chunk:
                                    fp.write(chunk)
                                    fp.flush()
                                    blocknum += 1
                                    if reporthook:
                                        reporthook(blocknum, bs, size)
                    return  # 成功则直接返回
                except Exception as e2:
                    logger.debug(f"禁用SSL验证重试也失败: {e2}")
                    if attempt < max_retry:
                        time.sleep(retry_delay)
            else:
                logger.error(f"下载 {url} 失败 (SSL错误): {e}")
                raise
        except Exception as e:
            logger.debug(f"下载 {url} 第 {attempt} 次失败: {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
            else:
                logger.error(f"下载 {url} 失败: {e}")
                raise


def download(url, output_path, desc=None):
    """下载指定url的资源"""
    # 支持“下载”本地资源，以供fc2fan的本地镜像所使用
    if not url.startswith('http'):
        start_time = time.time()
        shutil.copyfile(url, output_path)
        filesize = os.path.getsize(url)
        elapsed = time.time() - start_time
        info = {'total': filesize, 'elapsed': elapsed, 'rate': filesize/elapsed}
        return info
    if not desc:
        desc = url.split('/')[-1]
    referrer = headers.copy()
    referrer['referer'] = url[:url.find('/', 8)+1]  # 提取base_url部分
    with DownloadProgressBar(unit='B', unit_scale=True,
                             miniters=1, desc=desc, leave=False) as t:
        urlretrieve(url, filename=output_path,
                    reporthook=t.update_to, headers=referrer)
        info = {k: t.format_dict[k] for k in ('total', 'elapsed', 'rate')}
        return info


def open_in_chrome(url, new=0, autoraise=True):
    """使用指定的Chrome Profile打开url，便于调试"""
    import subprocess
    chrome = R'C:\Program Files\Google\Chrome\Application\chrome.exe'
    subprocess.run(
        f'"{chrome}" --profile-directory="Profile 2" {url}', shell=True)


webbrowser.open = open_in_chrome


if __name__ == "__main__":
    import pretty_errors
    pretty_errors.configure(display_link=True)
    download('https://www.javbus.com/pics/cover/6n54_b.jpg', 'cover.jpg')
