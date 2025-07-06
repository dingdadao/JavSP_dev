import os
import re
import time
import random
import logging
import json

from javsp.web.base import Request, resp2html
from javsp.web.exceptions import *
from javsp.func import *
from javsp.avid import guess_av_type
from javsp.config import Cfg, CrawlerID
from javsp.datatype import MovieInfo, GenreMap
from javsp.chromium import get_browsers_cookies


logger = logging.getLogger(__name__)

# 全局变量
cookies_pool = []
request = Request(use_scraper=True)
request.headers['Accept-Language'] = 'zh-CN,zh;q=0.9,zh-TW;q=0.8,en-US;q=0.7,en;q=0.6,ja;q=0.5'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# genre_map = GenreMap(os.path.join(DATA_DIR, 'genre_javdb.csv'))
permanent_url = 'https://javdb.com'
base_url = (
    permanent_url
    if Cfg().network.proxy_server
    else str(Cfg().network.proxy_free[CrawlerID.javdb])
)


def retry_request(url, max_retries=3, delay=3):
    """带重试的请求封装"""
    for attempt in range(max_retries):
        try:
            response = request.get(url, delay_raise=True)
            if response.status_code == 200:
                return response
            elif response.status_code in (403, 503):
                html = resp2html(response)
                code_tag = html.xpath("//span[@class='code-label']/span")
                error_code = code_tag[0].text if code_tag else None
                if error_code == '1020':
                    raise SiteBlocked(f'禁止访问: 站点屏蔽了来自日本地区的IP')
                else:
                    raise SiteBlocked(f'禁止访问，状态码: {response.status_code}，错误码: {error_code}')
            else:
                raise WebsiteError(f'非预期状态码: {response.status_code}')
        except Exception as e:
            logger.warning(f"请求失败，第{attempt + 1}次重试，错误: {e}")
            time.sleep(delay)
    raise WebsiteError(f"请求失败，超过最大重试次数: {url}")


def get_html_wrapper(url):
    """
    使用提供的 Cookies 请求网页，处理 Cloudflare、登录重定向、VIP 限制。
    """
    global request

    # 固定 Cookie 值（你 curl 的那段复制过来）
    JAVDB_COOKIES = {
        "list_mode": "h",
        "theme": "auto",
        "locale": "zh",
        "over18": "1",
        "cf_clearance": "PqwcU16z0mfu5TGFYHTlHYcCFS5aYgK5isXQVfBzATk-1751812866-1.2.1.1-BXv0Fbiug.S_Qgxv2tkk3VuKXZqTWDsR1gcg3zLr2o3cYGCkL1JGkPeMnHWKKvRHEvPT7tQNeGNMW3a732IbhsJgVAm7cD2Z4Sm.XjsogXlq_zTN4PbfElORbi24b9hXHaFEqK03ce3UCF1m2Kuhh06rZHiixAExXrxuQ0Da8MmKe80hE__fu58SFzUAqZ_ZocZtnuD9UZd4r9cpo7uErG2174hzHUWYkegokqjXZjE",
        "_ym_uid": "1751812866757350996",
        "_ym_d": "1751812866",
        "_ym_isad": "2",
        "_jdb_session": "/OD1/kRpJxsURHEtKBkClNdK5xs4GPrkaz/RuKCs3ny5OJO7l9lOcRAlfaHLv2MpNumBqfjQJUtucs4G8wmCmO2GV4BlxlpviEPUdYK+ORnchrf3qbT2iKo3ZLT5EBLtWjBHIFHvmJmYw2OnixhylYfbkn0duHzxGcjxkfNX12EwqHOB4RxIYhiV4kWy3ULi5EragdfYzrlVHfCsgTBOdLj05x3lpgalQtePfGWGNIgCtOZroCsUMnf22Pgu3QoLFE2BTCILszLfOikk6zm5ZOMdOKYzoWy/6j0N5rCG95JcDZi/qg3FBcwF--O94QVEMoOpRsLv2v--NT2KQBmTgWmpev/6PyelAA=="
    }

    try:
        # request.cookies = JAVDB_COOKIES
        response = request.get(url)
        # print(response.text)
    except Exception as e:
        logger.error(f"请求失败: {url}，错误: {e}", exc_info=True)
        raise

    # 登录重定向检测
    if response.history and '/login' in response.url:
        raise CredentialError("JavDB: 提供的 Cookies 已失效，页面跳转至登录页")

    # VIP资源页面检测
    if response.history and 'pay' in response.url.split('/')[-1]:
        raise SitePermissionError(f"JavDB: 资源仅 VIP 可见: '{response.history[0].url}'")

    try:
        html = resp2html(response)
        return html
    except Exception as e:
        logger.error(f"HTML 解析失败: {e}", exc_info=True)
        raise



def get_user_info(site, cookies):
    """通过Cookies获取JavDB用户信息"""
    try:
        request.cookies = cookies
        html = request.get_html(f'https://{site}/users/profile')
    except Exception as e:
        logger.info('获取用户信息时出错', exc_info=True)
        return None

    if 'JavDB' in html.text:
        email = html.xpath("//div[@class='user-profile']/ul/li[1]/span/following-sibling::text()")[0].strip()
        username = html.xpath("//div[@class='user-profile']/ul/li[2]/span/following-sibling::text()")[0].strip()
        return email, username
    else:
        logger.debug('域名已过期: ' + site)
        return None


def get_valid_cookies():
    """返回第一个有效的cookies"""
    for item in cookies_pool:
        info = get_user_info(item['site'], item['cookies'])
        if info:
            logger.info(f"找到有效Cookies，用户: {info[1]}")
            return item['cookies']
        else:
            logger.debug(f"{item['profile']}, {item['site']} Cookies无效")
    return None

def normalize_id(s):
    return s.strip().lower().replace(' ', '').replace('\u3000', '')

def parse_data(movie: MovieInfo):
    """抓取并解析指定番号的影片信息"""
    print(movie.dvdid,"------movie.dvdid")
    html = get_html_wrapper(f'{base_url}/search?q={movie.dvdid}')
    logger.info(html,"----------------------------获取下问题")
    ids = [i.lower() for i in html.xpath("//div[@class='video-title']/strong/text()")]
    movie_urls = html.xpath("//a[@class='box']/@href")
    print(movie_urls,"-------movie_urls------")

    target_id = normalize_id(movie.dvdid)
    print(ids,"idddddddssss")
    print("-----------",target_id,"target_idtarget_id")
    matches = [i for i in ids if i == target_id]
    print(matches,"matchesmatchesmatchesmatches")
    if len(matches) == 0:
        raise MovieNotFoundError(__name__, movie.dvdid, ids)
    elif len(matches) > 1:
        raise MovieDuplicateError(__name__, movie.dvdid, len(matches))

    index = ids.index(target_id)
    print(index,"indexindexindexindexindex")
    new_url = movie_urls[index]
    print(new_url,"new_urlnew_urlnew_urlnew_urlnew_urlnew_url")

    try:
        html2 = get_html_wrapper(new_url)
        print(html2.text_content(),"=============222222")
    except (SitePermissionError, CredentialError):
        # VIP限制，取搜索页的部分信息
        box = html.xpath("//a[@class='box']")[index]
        movie.url = new_url
        movie.title = box.get('title')
        movie.cover = box.xpath("div/img/@src")[0]
        score_str = box.xpath("div[@class='score']/span/span")[0].tail
        score = re.search(r'([\d.]+)分', score_str).group(1)
        movie.score = "{:.2f}".format(float(score)*2)
        movie.publish_date = box.xpath("div[@class='meta']/text()")[0].strip()
        return

    container = html2.xpath("/html/body/section/div/div[@class='video-detail']")[0]
    info = container.xpath("//nav[@class='panel movie-panel-info']")[0]

    movie.dvdid = info.xpath("div/span")[0].text_content()
    movie.url = new_url.replace(base_url, permanent_url)
    movie.title = container.xpath("h2/strong[@class='current-title']/text()")[0].replace(movie.dvdid, '').strip()
    movie.ori_title = container.xpath("h2/span[@class='origin-title']/text()")[0] if container.xpath("//a[contains(@class, 'meta-link') and not(contains(@style, 'display: none'))]") else None
    movie.cover = container.xpath("//img[@class='video-cover']/@src")[0]
    movie.preview_pics = container.xpath("//a[@class='tile-item'][@data-fancybox='gallery']/@href")
    preview_video_tag = container.xpath("//video[@id='preview-video']/source/@src")
    if preview_video_tag:
        movie.preview_video = preview_video_tag[0] if not preview_video_tag[0].startswith('//') else 'https:' + preview_video_tag[0]

    movie.publish_date = info.xpath("div/strong[text()='日期:']")[0].getnext().text
    movie.duration = info.xpath("div/strong[text()='時長:']")[0].getnext().text.replace('分鍾', '').strip()
    movie.director = info.xpath("div/strong[text()='導演:']")[0].getnext().text_content().strip() if info.xpath("div/strong[text()='導演:']") else None

    av_type = guess_av_type(movie.dvdid)
    producer_tag = info.xpath("div/strong[text()='片商:']")[0].getnext().text_content().strip() if av_type != 'fc2' else info.xpath("div/strong[text()='賣家:']")[0].getnext().text_content().strip()
    movie.producer = producer_tag if producer_tag else None

    movie.publisher = info.xpath("div/strong[text()='發行:']")[0].getnext().text_content().strip() if info.xpath("div/strong[text()='發行:']") else None
    movie.serial = info.xpath("div/strong[text()='系列:']")[0].getnext().text_content().strip() if info.xpath("div/strong[text()='系列:']") else None

    score_tag = html2.xpath("//span[@class='score-stars']")
    if score_tag:
        score_str = score_tag[0].tail
        score = re.search(r'([\d.]+)分', score_str).group(1)
        movie.score = "{:.2f}".format(float(score)*2)

    # 解析类别及有码/无码状态
    genre_tags = info.xpath("//strong[text()='類別:']/../span/a")
    genre, genre_id = [], []
    for tag in genre_tags:
        pre_id = tag.get('href').split('/')[-1]
        genre.append(tag.text)
        genre_id.append(pre_id)
        movie.uncensored = {'uncensored': True, 'tags': False}.get(pre_id.split('?')[0])

    movie.genre = genre
    movie.genre_id = genre_id

    # 演员和女优筛选
    actors_tag = info.xpath("//strong[text()='演員:']/../span")[0]
    all_actors = actors_tag.xpath("a/text()")
    genders = actors_tag.xpath("strong/text()")
    actress = [a for a in all_actors if genders[all_actors.index(a)] == '♀']
    movie.actress = actress

    magnet = container.xpath("//div[@class='magnet-name column is-four-fifths']/a/@href")
    movie.magnet = [m.replace('[javdb.com]', '') for m in magnet]


def parse_clean_data(movie: MovieInfo):
    """解析并清洗影片数据"""
    try:
        parse_data(movie)
        # 校验封面是否有效
        if movie.cover:
            r = request.head(movie.cover)
            if r.status_code != 200:
                movie.cover = None
    except SiteBlocked as e:
        logger.error('JavDB: 可能触发了反爬虫机制，请稍后再试')
        raise e


def save_actress_aliases(data: dict, filepath: str):
    """保存女优别名到JSON"""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            existing = json.load(f)
    else:
        existing = {}

    existing.update(data)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def fetch_actor_alias(actor_url: str, use_original: bool):
    """抓取单个女优详细别名信息"""
    html = get_html_wrapper(actor_url)
    names_span = html.xpath("//span[@class='actor-section-name']")[0]
    aliases_span_list = html.xpath("//span[@class='section-meta']")

    names_list = [name.strip() for name in names_span.text.split(",")]
    aliases_list = []
    if len(aliases_span_list) > 1:
        aliases_list = [alias.strip() for alias in aliases_span_list[0].text.split(",")]

    key_name = names_list[-1 if use_original else 0]
    return key_name, names_list + aliases_list


def collect_actress_alias(type_: int = 0, use_original: bool = True):
    """
    爬取女优别名
    type_: 0-有码, 1-无码, 2-欧美
    use_original: True使用原名，False使用译名
    """
    type_list = ["censored", "uncensored", "western"]
    page_url = f"{base_url}/actors/{type_list[type_]}"

    actress_alias_map = {}
    alias_file_path = os.path.join(DATA_DIR, "actress_alias.json")
    os.makedirs(DATA_DIR, exist_ok=True)

    count = 0
    while True:
        html = get_html_wrapper(page_url)
        actors = html.xpath("//div[@class='box actor-box']/a")
        for actor in actors:
            count += 1
            actor_name = actor.xpath("strong/text()")[0].strip()
            actor_url = actor.xpath("@href")[0]

            try:
                key_name, all_names = fetch_actor_alias(actor_url, use_original)
                actress_alias_map[key_name] = all_names
                logger.info(f"爬取女优: {key_name} 别名: {all_names}")
            except Exception as e:
                logger.warning(f"爬取女优详细信息失败: {actor_name} - {e}")

            # 批量保存，避免数据丢失
            if count % 10 == 0:
                save_actress_aliases(actress_alias_map, alias_file_path)
                actress_alias_map.clear()
                logger.info(f"已爬取 {count} 个女优，保存到文件")

            time.sleep(max(1, random.uniform(1, 10)))

        next_page_link = html.xpath("//a[@rel='next' and @class='pagination-next']/@href")
        if not next_page_link:
            break
        page_url = next_page_link[0]

    # 保存剩余数据
    if actress_alias_map:
        save_actress_aliases(actress_alias_map, alias_file_path)
        logger.info(f"爬取完成，共爬取 {count} 个女优，保存到文件")


if __name__ == "__main__":
    cookies_pool = get_browsers_cookies()
    valid_cookies = get_valid_cookies()
    if valid_cookies:
        request.cookies = valid_cookies

    movie = MovieInfo('NKMTNDVAJ-331')
    try:
        parse_clean_data(movie)
        print(movie)
    except CrawlerError as e:
        logger.error(repr(e))
