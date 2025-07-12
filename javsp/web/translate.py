"""网页翻译接口"""
# 由于翻译服务不走代理，而且需要自己的错误处理机制，因此不通过base.py来管理网络请求
import time
from typing import Union, re
import uuid
import random
import logging
from pydantic_core import Url
import requests
from hashlib import md5


__all__ = ['translate', 'translate_movie_info']


from javsp.config import BaiduTranslateEngine, BingTranslateEngine, Cfg, ClaudeTranslateEngine, GoogleTranslateEngine, OpenAITranslateEngine, TranslateEngine
from javsp.datatype import MovieInfo
from javsp.web.base import read_proxy


logger = logging.getLogger(__name__)

def translate_movie_info(info: MovieInfo):
    """根据配置翻译影片信息"""
    # 翻译标题
    if info.title and Cfg().translator.fields.title and info.ori_title is None:
        try:
            result = translate(info.title, Cfg().translator.engine, info.actress)
            if result and 'trans' in result:
                info.ori_title = info.title
                info.title = result['trans']

                # 如果有的话，附加断句信息
                if 'orig_break' in result:
                    setattr(info, 'ori_title_break', result['orig_break'])
                if 'trans_break' in result:
                    setattr(info, 'title_break', result['trans_break'])
            else:
                logger.error(f"翻译标题时出错: {result.get('error', '未知错误')}")
                return False
        except Exception as e:
            logger.error(f"调用翻译服务时出错: {str(e)}")
            return False

    # 翻译简介
    if info.plot and Cfg().translator.fields.plot:
        try:
            result = translate(info.plot, Cfg().translator.engine, info.actress)
            if result and 'trans' in result:
                # 只有翻译过plot的影片才可能需要ori_plot属性
                if not hasattr(info, 'ori_plot'):
                    setattr(info, 'ori_plot', info.plot)
                info.plot = result['trans']
            else:
                logger.error(f"翻译简介时出错: {result.get('error', '未知错误')}")
                return False
        except Exception as e:
            logger.error(f"调用翻译服务时出错: {str(e)}")
            return False

    return True


def translate(texts, engine: Union[
        BaiduTranslateEngine,
        BingTranslateEngine,
        ClaudeTranslateEngine,
        OpenAITranslateEngine,
        None
    ], actress=[]):
    """
    翻译入口：对错误进行处理并且统一返回格式

    Returns:
        dict: 翻译正常: {'trans': '译文', 'orig_break':['原句1', ...], 'trans_break': ['译句1', ...]}
              仅在能判断分句时有breaks字段，子句末尾可能有换行符\n
              翻译出错: {'error': 'baidu: 54000: PARAM_FROM_TO_OR_Q_EMPTY'}
    """
    rtn = {}
    err_msg = ''
    if engine.name == 'baidu':
        result = baidu_translate(texts, engine.app_id, engine.api_key)
        if 'error_code' not in result:
            # 百度翻译的结果中的组表示的是按换行符分隔的不同段落，而不是句子
            paragraphs = [i['dst'] for i in result['trans_result']]
            rtn = {'trans': '\n'.join(paragraphs)}
        else:
            err_msg = "{}: {}: {}".format(engine, result['error_code'], result['error_msg'])
    elif engine.name == 'bing':
        """主逻辑：使用 Bing 翻译，并对文本分句处理"""
        texts = protect_names(texts, actress)
        result = bing_translate(texts, api_key=api_key)

        if not result:
            print("翻译失败，返回为空")
            return None
        if isinstance(result, dict) and 'error' in result:
            print("翻译失败，错误信息:", result['error'])
            return None
        if not isinstance(result, list):
            print("翻译返回结构异常:", result)
            return None

        try:
            translation = result[0]['translations'][0]
            sentLen = translation.get('sentLen')
            orig_break, trans_break = [], []

            # 拆分原文
            remaining = texts
            for i in sentLen['srcSentLen']:
                orig_break.append(remaining[:i])
                remaining = remaining[i:]

            # 拆分译文（去除结尾空格）
            remaining = translation['text']
            for i in sentLen['transSentLen']:
                trans_break.append(remaining[:i].rstrip(' '))
                remaining = remaining[i:]

            trans = ''.join(trans_break)
            return {'trans': trans, 'orig_break': orig_break, 'trans_break': trans_break}
        except Exception as e:
            err_msg = "{}: {}: {}".format(engine, result['error']['code'], result['error']['message'])
    elif engine.name == 'claude':
        try:
            result = claude_translate(texts, engine.api_key)
            if 'error_code' not in result:
                rtn = {'trans': result}
            else:
                err_msg = "{}: {}: {}".format(engine, result['error_code'], result['error_msg'])
        except Exception as e:
            err_msg = "{}: {}: Exception: {}".format(engine, -2, repr(e))
    elif engine.name == 'openai':
        try:
            result = openai_translate(texts, engine.url, engine.api_key, engine.model)
            if 'error_code' not in result:
                rtn = {'trans': result}
            else:
                err_msg = "{}: {}: {}".format(engine, result['error_code'], result['error_msg'])
        except Exception as e:
            err_msg = "{}: {}: Exception: {}".format(engine, -2, repr(e))
    elif engine.name == 'google':
        try:
            result = google_trans(texts)
            # 经测试，翻译成功时会带有'sentences'字段；失败时不带，也没有故障码
            if 'sentences' in result:
                # Google会对句子分组，完整的译文需要自行拼接
                orig_break = [i['orig'] for i in result['sentences']]
                trans_break = [i['trans'] for i in result['sentences']]
                trans = ''.join(trans_break)
                rtn = {'trans': trans, 'orig_break': orig_break, 'trans_break': trans_break}
            else:
                err_msg = "{}: {}: {}".format(engine, result['error_code'], result['error_msg'])
        except Exception as e:
            err_msg = "{}: {}: Exception: {}".format(engine, -2, repr(e))
    elif engine.name == 'googleai':
        try:
            result = googleai_translate(texts, engine.url, engine.api_key, engine.model)
            if isinstance(result, str) and result:
                rtn = {'trans': result, 'orig_break': [texts], 'trans_break': [result]}
            elif isinstance(result, dict) and 'error_code' in result:
                err_msg = "{}: {}: {}".format(engine, result['error_code'], result['error_msg'])
            else:
                err_msg = "{}: Unknown error: {}".format(engine, repr(result))
        except Exception as e:
            err_msg = "{}: -2: Exception: {}".format(engine, repr(e))
    else:
        return {'trans': texts}

    if rtn == {}:
        rtn['error'] = err_msg

    return rtn

def baidu_translate(texts, app_id, api_key, to='zh'):
    """使用百度翻译文本（默认翻译为简体中文）"""
    api_url = "https://api.fanyi.baidu.com/api/trans/vip/translate"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    salt = random.randint(0, 0x7FFFFFFF)
    sign_input = app_id + texts + str(salt) + api_key
    sign = md5(sign_input.encode('utf-8')).hexdigest()
    payload = {'appid': app_id, 'q': texts, 'from': 'auto', 'to': to, 'salt': salt, 'sign': sign}
    # 由于百度标准版限制QPS为1，连续翻译标题和简介会超限，因此需要添加延时
    now = time.perf_counter()
    last_access = getattr(baidu_translate, '_last_access', -1)
    wait = 1.0 - (now - last_access)
    if wait > 0:
        time.sleep(wait)
    r = requests.post(api_url, params=payload, headers=headers)
    result = r.json()
    baidu_translate._last_access = time.perf_counter()
    return result

def protect_names(texts, names):
    """将女优名用 <mstrans:dictionary> 包裹防止翻译"""
    def repl(m):
        name = m.group(0)
        return f'<mstrans:dictionary translation="{name}">{name}</mstrans:dictionary>'
    pattern = '|'.join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    return re.sub(pattern, repl, texts)

def bing_translate(texts, api_key, to='zh-Hans', max_retry=3):
    """使用 Bing 翻译文本（默认翻译为简体中文），失败自动重试"""
    api_url = "https://api.cognitive.microsofttranslator.com/translate"
    params = {'api-version': '3.0', 'to': to, 'includeSentenceLength': True}
    headers = {
        'Ocp-Apim-Subscription-Key': api_key,
        'Ocp-Apim-Subscription-Region': 'global',
        'Content-type': 'application/json',
        'X-ClientTraceId': str(uuid.uuid4())
    }
    body = [{'text': texts}]

    for attempt in range(1, max_retry + 1):
        try:
            r = requests.post(api_url, params=params, headers=headers, json=body, timeout=10)
            r.raise_for_status()
            result = r.json()
            print(f"[Bing翻译第 {attempt} 次成功] 响应内容: {result}")
            return result
        except Exception as e:
            print(f"[Bing翻译第 {attempt} 次失败] 错误: {e}")
            if attempt < max_retry:
                time.sleep(2)
            else:
                print("[Bing翻译] 已达到最大重试次数，返回 None")
                return None


_google_trans_wait = 60
def google_trans(texts, to='zh_CN'):
    """使用Google翻译文本（默认翻译为简体中文）"""
    # API: https://www.jianshu.com/p/ce35d89c25c3
    # client参数的选择: https://github.com/lmk123/crx-selection-translate/issues/223#issue-184432017
    global _google_trans_wait
    url = f"https://translate.google.com.hk/translate_a/single?client=gtx&dt=t&dj=1&ie=UTF-8&sl=auto&tl={to}&q={texts}"
    proxies = read_proxy()
    r = requests.get(url, proxies=proxies)
    while r.status_code == 429:
        logger.warning(f"HTTP {r.status_code}: {r.reason}: Google翻译请求超限，将等待{_google_trans_wait}秒后重试")
        time.sleep(_google_trans_wait)
        r = requests.get(url, proxies=proxies)
        if r.status_code == 429:
            _google_trans_wait += random.randint(60, 90)
    if r.status_code == 200:
        result = r.json()
    else:
        result = {'error_code': r.status_code, 'error_msg': r.reason}
    time.sleep(4) # Google翻译的API有QPS限制，因此需要等待一段时间
    return result

def claude_translate(texts, api_key, to="zh_CN"):
    """使用Claude翻译文本（默认翻译为简体中文）"""
    api_url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "context-type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    data = {
        "model": "claude-3-haiku-20240307",
        "system": f"Translate the following Japanese paragraph into {to}, while leaving non-Japanese text, names, or text that does not look like Japanese untranslated. Reply with the translated text only, do not add any text that is not in the original content.",
        "max_completion_tokens": 1024,
        "messages": [{"role": "user", "content": texts}],
    }
    r = requests.post(api_url, headers=headers, json=data)
    if r.status_code == 200:
        result = r.json().get("content", [{}])[0].get("text", "").strip()
    else:
        result = {
            "error_code": r.status_code,
            "error_msg": r.json().get("error", {}).get("message", r.reason),
        }
    return result

import requests

def openai_translate(texts, url: str, api_key: str, model: str, to="zh_CN"):
    """
    兼容 OpenAI Chat API 和 Groq llama-3.1-70b-versatile 翻译接口的翻译函数
    """
    api_url = str(url)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"Translate the following Japanese paragraph into {to}, "
                    "while leaving non-Japanese text, names, or text that does not look like Japanese untranslated. "
                    "Reply with the translated text only, do not add any text that is not in the original content."
                )
            },
            {
                "role": "user",
                "content": texts
            }
        ],
        "temperature": 0,
        "max_tokens": 1024,
    }

    try:
        r = requests.post(api_url, headers=headers, json=data, timeout=15)
        r.raise_for_status()
        resp = r.json()

        # OpenAI 标准返回格式
        if "choices" in resp and len(resp["choices"]) > 0:
            choice = resp["choices"][0]
            # OpenAI 可能是 message.content
            if "message" in choice and "content" in choice["message"]:
                return choice["message"]["content"].strip()
            # Groq llama 可能直接是 text 字段
            elif "text" in choice:
                return choice["text"].strip()

        # 返回有 error 字段时
        if "error" in resp:
            return {
                "error_code": r.status_code,
                "error_msg": resp["error"].get("message", "")
            }

        # 无法解析，直接返回原始响应
        return {
            "error_code": -1,
            "error_msg": f"Unexpected response format: {resp}"
        }

    except requests.exceptions.RequestException as e:
        return {
            "error_code": -1,
            "error_msg": str(e),
        }


import requests

def googleai_translate(texts, url: Url, api_key: str, model:str, to="zh_CN"):
    """
    使用 Google Gemini 翻译文本（默认翻译为简体中文）
    仅翻译日文部分，保留非日文字符不变
    """
    api_url = f"{url}{model}:generateContent?key={api_key}"

    headers = {
        "Content-Type": "application/json"
    }

    system_prompt = (
        f"Translate the following Japanese text into {to}. "
        f"Do not translate any non-Japanese parts, such as English names or formatting. "
        f"Reply with only the translated version of the original content."
    )

    data = {
        "contents": [
            {
                "parts": [
                    {"text": system_prompt},
                    {"text": texts}
                ]
            }
        ]
    }

    try:
        r = requests.post(api_url, headers=headers, json=data, timeout=10)
        if r.status_code == 200:
            result_json = r.json()
            if "candidates" in result_json:
                content = (
                    result_json["candidates"][0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                    .strip()
                )
                return content
            else:
                return {
                    "error_code": r.status_code,
                    "error_msg": "No candidates in response"
                }
        else:
            return {
                "error_code": r.status_code,
                "error_msg": r.reason
            }
    except requests.exceptions.RequestException as e:
        return {
            "error_code": -1,
            "error_msg": str(e)
        }

import requests

def openai_translate(texts, url: str, api_key: str, model: str, to="zh_CN"):
    """
    兼容 OpenAI Chat API 和 Groq llama-3.1-70b-versatile 翻译接口的翻译函数
    """
    api_url = str(url)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"Translate the following Japanese paragraph into {to}, "
                    "while leaving non-Japanese text, names, or text that does not look like Japanese untranslated. "
                    "Reply with the translated text only, do not add any text that is not in the original content."
                )
            },
            {
                "role": "user",
                "content": texts
            }
        ],
        "temperature": 0,
        "max_tokens": 1024,
    }

    try:
        r = requests.post(api_url, headers=headers, json=data, timeout=15)
        r.raise_for_status()
        resp = r.json()

        # OpenAI 标准返回格式
        if "choices" in resp and len(resp["choices"]) > 0:
            choice = resp["choices"][0]
            if "message" in choice and "content" in choice["message"]:
                return choice["message"]["content"].strip()
            elif "text" in choice:
                return choice["text"].strip()

        if "error" in resp:
            return {
                "error_code": r.status_code,
                "error_msg": resp["error"].get("message", "")
            }

        return {
            "error_code": -1,
            "error_msg": f"Unexpected response format: {resp}"
        }

    except requests.exceptions.RequestException as e:
        return {
            "error_code": -1,
            "error_msg": str(e),
        }


if __name__ == "__main__":
    text = "これは日本語の文章です。This should remain in English."
    key = "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"
    result = openai_translate(
        texts=text,
        url="https://api.groq.com/openai/v1/chat/completions",
        api_key=key,
        model="llama-3.3-70b-versatile"
    )
    print(result)



