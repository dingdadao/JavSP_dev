# """从missav.ai抓取数据"""
# import logging
#
# from javsp.chromium import get_browsers_cookies
# from javsp.web.base import resp2html, Request
# from javsp.datatype import MovieInfo
# from javsp.web.exceptions import SiteBlocked
# from javsp.web.javdb import get_valid_cookies
#
# logger = logging.getLogger(__name__)
# base_url = 'https://missav.ai/dm15/ja'
# logger = logging.getLogger(__name__)
# request = Request(use_scraper=True)
# request.headers['Accept-Language'] = 'zh-CN,zh;q=0.9,zh-TW;q=0.8,en-US;q=0.7,en;q=0.6,ja;q=0.5'
#
#
# def get_html_wrapper(url):
#     global request
#     try:
#         response = request.get(url)
#         if response.status_code == 200:
#             return response
#         else: raise SiteBlocked(f'禁止访问，状态码: {response.status_code}，错误码: 500')
#     except Exception as e:
#         logger.error(f"请求失败: {url}，错误: {e}", exc_info=True)
#         raise SiteBlocked(f'禁止访问，错误状态: {e}，错误码: 500')
#
#
# def parse_data(movie: MovieInfo):
#     """抓取并解析指定番号的影片信息"""
#     html = get_html_wrapper(f'{base_url}/search/{movie.dvdid}')
#     logger.info(html,"----------------------------获取下问题")
#
#
# if __name__ == "__main__":
#     cookies_pool = get_browsers_cookies()
#     valid_cookies = get_valid_cookies()
#     if valid_cookies:
#         request.cookies = valid_cookies
#
#     movie = MovieInfo('NKMTNDVAJ-331')
#     parse_data(movie)
