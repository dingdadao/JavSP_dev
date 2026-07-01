"""网页翻译接口"""
import requests
from javsp.web.base import read_proxy
from javsp.datatype import MovieInfo
from javsp.config import BaiduTranslateEngine, BingTranslateEngine, Cfg, ClaudeTranslateEngine, GoogleTranslateEngine, GoogleAITranslateEngine, LocalAITranslateEngine, OpenAITranslateEngine, TranslateEngine
import json
# 由于翻译服务不走代理，而且需要自己的错误处理机制，因此不通过base.py来管理网络请求
import time
from typing import Union
import re
import uuid
import random
import logging
from pydantic_core import Url
from hashlib import md5
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


__all__ = ['translate', 'translate_movie_info']


logger = logging.getLogger(__name__)


def translate_movie_info(info: MovieInfo):
    """根据配置翻译影片信息"""
    # 翻译标题
    # 注意：如果 ori_title 已经有值（如 JavDB 设置了日文原标题），仍然需要翻译
    if info.title and Cfg().translator.fields.title and not hasattr(info, '_title_translated'):
        try:
            result = translate(
                info.title, Cfg().translator.engine, info.actress)
            if result and 'trans' in result:
                # 保存原文到 ori_title（标记为已翻译的原文）
                info.ori_title = info.title
                info.title = result['trans']
                # 标记标题已翻译成功
                setattr(info, '_title_translated', True)

                # 如果有的话，附加断句信息
                if 'orig_break' in result:
                    setattr(info, 'ori_title_break', result['orig_break'])
                if 'trans_break' in result:
                    setattr(info, 'title_break', result['trans_break'])
            else:
                logger.error(f"翻译标题时出错: {result.get('error', '未知错误')}")
                # 翻译失败时保留原文，不阻止后续处理
                info.ori_title = info.title
        except Exception as e:
            logger.error(f"调用翻译服务时出错: {str(e)}")
            # 翻译失败时保留原文，不阻止后续处理
            info.ori_title = info.title

    # 翻译简介
    if info.plot and Cfg().translator.fields.plot:
        try:
            result = translate(
                info.plot, Cfg().translator.engine, info.actress)
            if result and 'trans' in result:
                # 保存原文到 ori_plot（标记为已翻译的原文）
                setattr(info, 'ori_plot', info.plot)
                info.plot = result['trans']
                # 标记简介已翻译成功
                setattr(info, '_plot_translated', True)
            else:
                logger.error(f"翻译简介时出错: {result.get('error', '未知错误')}")
                # 翻译失败时保留原文，不阻止后续处理
                setattr(info, 'ori_plot', info.plot)
        except Exception as e:
            logger.error(f"调用翻译服务时出错: {str(e)}")
            # 翻译失败时保留原文，不阻止后续处理
            setattr(info, 'ori_plot', info.plot)

    return True


def translate(texts, engine: Union[
    BaiduTranslateEngine,
    BingTranslateEngine,
    ClaudeTranslateEngine,
    OpenAITranslateEngine,
    LocalAITranslateEngine,
    GoogleAITranslateEngine,
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
        result = baidu_translate(
            texts=texts, app_id=engine.app_id, api_key=engine.api_key, 
            max_retry=engine.max_retry, retry_delay=engine.retry_delay)
        if 'error_code' not in result:
            # 进入子结构
            trans_result = result.get('result', {}).get('trans_result', [])
            paragraphs = [i['dst'] for i in trans_result]
            rtn = {'trans': '\n'.join(paragraphs)}
        else:
            err_msg = "{}: {}: {}".format(
                engine, result['error_code'], result['error_msg'])
    elif engine.name == 'bing':
        """主逻辑：使用 Bing 翻译，并对文本分句处理"""
        texts = protect_names(texts, actress)
        result = bing_translate(texts, api_key=engine.api_key, 
                               max_retry=engine.max_retry, retry_delay=engine.retry_delay)

        if not result:
            err_msg = f"{engine.name}: None response from Bing API"
            return {"success": False, "err_msg": err_msg}

            # API 返回错误
        if isinstance(result, dict) and 'error' in result:
            error_code = result['error'].get('code', 'UnknownCode')
            error_msg = result['error'].get('message', 'UnknownMessage')
            err_msg = f"{engine.name}: {error_code}: {error_msg}"
            return {"success": False, "err_msg": err_msg}

            # 格式错误
        if not isinstance(result, list):
            err_msg = f"{engine.name}: Unexpected response format: {result}"
            return {"success": False, "err_msg": err_msg}

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
            rtn = {'trans': trans, 'orig_break': orig_break,
                   'trans_break': trans_break}
        except Exception as e:
            err_msg = "{}: {}: {}".format(
                engine, result['error']['code'], result['error']['message'])
    elif engine.name == 'claude':
        try:
            result = claude_translate(texts, engine.api_key, 
                                     max_retry=engine.max_retry, retry_delay=engine.retry_delay)
            if 'error_code' not in result:
                rtn = {'trans': result}
            else:
                err_msg = "{}: {}: {}".format(
                    engine, result['error_code'], result['error_msg'])
        except Exception as e:
            err_msg = "{}: {}: Exception: {}".format(engine, -2, repr(e))
    elif engine.name == 'openai':
        try:
            result = openai_translate(
                texts, engine.url, engine.api_key, engine.model,
                max_retry=engine.max_retry, retry_delay=engine.retry_delay)
            if 'error_code' not in result:
                rtn = {'trans': result}
            else:
                err_msg = "{}: {}: {}".format(
                    engine, result['error_code'], result['error_msg'])
        except Exception as e:
            err_msg = "{}: {}: Exception: {}".format(engine, -2, repr(e))
    elif engine.name == 'localai':
        try:
            result = localai_translate(
                texts, engine.url, engine.api_key, engine.model,
                max_retry=engine.max_retry, retry_delay=engine.retry_delay)
            if 'error_code' not in result:
                rtn = {'trans': result}
            else:
                err_msg = "{}: {}: {}".format(
                    engine, result['error_code'], result['error_msg'])
        except Exception as e:
            err_msg = "{}: {}: Exception: {}".format(engine, -2, repr(e))
    elif engine.name == 'google':
        try:
            result = google_trans(texts, max_retry=engine.max_retry, retry_delay=engine.retry_delay)
            # 经测试，翻译成功时会带有'sentences'字段；失败时不带，也没有故障码
            if 'sentences' in result:
                # Google会对句子分组，完整的译文需要自行拼接
                orig_break = [i['orig'] for i in result['sentences']]
                trans_break = [i['trans'] for i in result['sentences']]
                trans = ''.join(trans_break)
                rtn = {'trans': trans, 'orig_break': orig_break,
                       'trans_break': trans_break}
            else:
                err_msg = "{}: {}: {}".format(
                    engine, result['error_code'], result['error_msg'])
        except Exception as e:
            err_msg = "{}: {}: Exception: {}".format(engine, -2, repr(e))
    elif engine.name == 'googleai':
        try:
            result = googleai_translate(
                texts, engine.url, engine.api_key, engine.model,
                max_retry=engine.max_retry, retry_delay=engine.retry_delay)
            if isinstance(result, str) and result:
                rtn = {'trans': result, 'orig_break': [
                    texts], 'trans_break': [result]}
            elif isinstance(result, dict) and 'error_code' in result:
                err_msg = "{}: {}: {}".format(
                    engine, result['error_code'], result['error_msg'])
            else:
                err_msg = "{}: Unknown error: {}".format(engine, repr(result))
        except Exception as e:
            err_msg = "{}: -2: Exception: {}".format(engine, repr(e))
    else:
        return {'trans': texts}

    if rtn == {}:
        rtn['error'] = err_msg

    return rtn


# 百度翻译 access_token 缓存（有效期30天）
_baidu_access_token = {'token': None, 'expires_at': 0}


def get_access_token(API_KEY, SECRET_KEY, max_retry=3, retry_delay=1):
    """
    使用 AK，SK 生成鉴权签名（Access Token）
    :return: access_token，或是None(如果错误)
    """
    global _baidu_access_token
    
    # 检查缓存的 token 是否仍然有效（提前5分钟过期）
    import time
    current_time = time.time()
    if _baidu_access_token['token'] and current_time < _baidu_access_token['expires_at'] - 300:
        return _baidu_access_token['token']
    
    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {"grant_type": "client_credentials",
              "client_id": API_KEY, "client_secret": SECRET_KEY}
    
    for attempt in range(1, max_retry + 1):
        try:
            response = requests.post(url, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()
            token = str(result.get("access_token"))
            expires_in = result.get("expires_in", 2592000)  # 默认30天
            
            # 缓存 token
            _baidu_access_token['token'] = token
            _baidu_access_token['expires_at'] = current_time + expires_in
            
            return token
        except Exception as e:
            logger.debug(f"获取百度翻译 access_token 第 {attempt} 次失败: {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
            else:
                logger.error(f"获取百度翻译 access_token 失败: {e}")
                return None


def baidu_translate(texts, app_id, api_key, to='zh', max_retry=3, retry_delay=1):
    """百度翻译，带重试机制"""
    for attempt in range(1, max_retry + 1):
        try:
            access_token = get_access_token(app_id, api_key, max_retry=3, retry_delay=retry_delay)
            if not access_token:
                return {'error_code': -1, 'error_msg': '无法获取 access_token'}
            
            url = f"https://aip.baidubce.com/rpc/2.0/mt/texttrans/v1?access_token={access_token}"
            
            payload = json.dumps({
                "from": "jp",
                "to": to,
                "q": texts
            }, ensure_ascii=False)
            headers = {
                'Accept': 'application/json'
            }

            response = requests.request(
                "POST", url, headers=headers, data=payload.encode("utf-8"), timeout=15)
            response.raise_for_status()
            
            return response.json()
        except requests.exceptions.SSLError as e:
            logger.debug(f"百度翻译第 {attempt} 次失败 (SSL错误): {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
                # 尝试禁用SSL验证重试
                try:
                    url = f"https://aip.baidubce.com/rpc/2.0/mt/texttrans/v1?access_token={access_token}"
                    payload = json.dumps({
                        "from": "jp",
                        "to": to,
                        "q": texts
                    }, ensure_ascii=False)
                    headers = {
                        'Accept': 'application/json'
                    }
                    response = requests.request(
                        "POST", url, headers=headers, data=payload.encode("utf-8"), timeout=15, verify=False)
                    response.raise_for_status()
                    return response.json()
                except Exception as e2:
                    logger.debug(f"禁用SSL验证重试也失败: {e2}")
                    if attempt < max_retry:
                        time.sleep(retry_delay)
            else:
                logger.error(f"百度翻译失败 (SSL错误): {e}")
                return {'error_code': -1, 'error_msg': str(e)}
        except Exception as e:
            logger.debug(f"百度翻译第 {attempt} 次失败: {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
            else:
                logger.error(f"百度翻译失败: {e}")
                return {'error_code': -1, 'error_msg': str(e)}


def protect_names(texts, names):
    """将女优名用 <mstrans:dictionary> 包裹防止翻译"""
    def repl(m):
        name = m.group(0)
        return f'<mstrans:dictionary translation="{name}">{name}</mstrans:dictionary>'
    pattern = '|'.join(re.escape(name)
                       for name in sorted(names, key=len, reverse=True))
    return re.sub(pattern, repl, texts)


def bing_translate(texts, api_key, to='zh-Hans', max_retry=3, retry_delay=1):
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
            r = requests.post(api_url, params=params,
                              headers=headers, json=body, timeout=10)
            r.raise_for_status()
            result = r.json()
            logger.debug(f"[Bing翻译第 {attempt} 次成功] 响应内容: {result}")
            return result
        except Exception as e:
            logger.debug(f"[Bing翻译第 {attempt} 次失败] 错误: {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
            else:
                logger.error("[Bing翻译] 已达到最大重试次数，返回 None")
                return None


_google_trans_wait = 60


def google_trans(texts, to='zh_CN', max_retry=3, retry_delay=1):
    """使用Google翻译文本（默认翻译为简体中文），带重试机制"""
    # API: https://www.jianshu.com/p/ce35d89c25c3
    # client参数的选择: https://github.com/lmk123/crx-selection-translate/issues/223#issue-184432017
    global _google_trans_wait
    
    for attempt in range(1, max_retry + 1):
        try:
            url = f"https://translate.google.com.hk/translate_a/single?client=gtx&dt=t&dj=1&ie=UTF-8&sl=auto&tl={to}&q={texts}"
            proxies = read_proxy()
            r = requests.get(url, proxies=proxies, timeout=15)
            
            while r.status_code == 429:
                logger.warning(
                    f"HTTP {r.status_code}: {r.reason}: Google翻译请求超限，将等待{_google_trans_wait}秒后重试")
                time.sleep(_google_trans_wait)
                r = requests.get(url, proxies=proxies, timeout=15)
                if r.status_code == 429:
                    _google_trans_wait += random.randint(60, 90)
            
            if r.status_code == 200:
                result = r.json()
                time.sleep(4)  # Google翻译的API有QPS限制，因此需要等待一段时间
                return result
            else:
                result = {'error_code': r.status_code, 'error_msg': r.reason}
                if attempt < max_retry:
                    logger.debug(f"Google翻译第 {attempt} 次失败: {result}")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Google翻译失败: {result}")
                    return result
        except Exception as e:
            logger.debug(f"Google翻译第 {attempt} 次失败: {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
            else:
                logger.error(f"Google翻译失败: {e}")
                return {'error_code': -1, 'error_msg': str(e)}


def claude_translate(texts, api_key, to="zh_CN", max_retry=3, retry_delay=1):
    """使用Claude翻译文本（默认翻译为简体中文），带重试机制"""
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
    
    for attempt in range(1, max_retry + 1):
        try:
            r = requests.post(api_url, headers=headers, json=data, timeout=15)
            r.raise_for_status()
            result = r.json().get("content", [{}])[0].get("text", "").strip()
            return result
        except Exception as e:
            logger.debug(f"Claude翻译第 {attempt} 次失败: {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
            else:
                logger.error(f"Claude翻译失败: {e}")
                return {
                    "error_code": -1,
                    "error_msg": str(e),
                }


def openai_translate(texts, url: str, api_key: str, model: str, to="zh_CN", max_retry=3, retry_delay=1):
    """
    兼容 OpenAI Chat API 和 Groq llama-3.1-70b-versatile 翻译接口的翻译函数，带重试机制
    针对日本成人影片标题和简介优化
    """
    api_url = str(url)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    
    # 根据文本长度动态调整 max_tokens 和 timeout
    is_short_text = len(texts) < 100
    max_tokens = 256 if is_short_text else 1024
    timeout = 30 if is_short_text else 60
    
    data = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"你是一位专业的日本成人影片翻译专家。"
                    f"请将以下日文标题或简介翻译成{to}。\n\n"
                    "翻译规则：\n"
                    "1. 保留番号不变（如 ABC-123, SSIS-999 等格式）\n"
                    "2. 保留女优、男优的日文原名（人名不翻译）\n"
                    "3. 保留制作商、系列名称等专有名词（如 S1, MOODYZ, kira☆kira 等）\n"
                    "4. 准确翻译成人相关术语和描述内容\n"
                    "5. 保持原标题的语序和风格，不要过度意译\n"
                    "6. 只返回翻译结果，不要添加任何额外说明或解释"
                )
            },
            {
                "role": "user",
                "content": texts
            }
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }

    for attempt in range(1, max_retry + 1):
        try:
            r = requests.post(api_url, headers=headers, json=data, timeout=timeout)
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
            logger.debug(f"OpenAI翻译第 {attempt} 次失败: {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
            else:
                logger.error(f"OpenAI翻译失败: {e}")
                return {
                    "error_code": -1,
                    "error_msg": str(e),
                }


def localai_translate(texts, url: str, api_key: str, model: str, to="zh_CN", max_retry=3, retry_delay=1):
    """
    兼容本地 AI API (如 Ollama, LocalAI, vLLM 等) 的翻译函数，带重试机制
    针对日本成人影片标题和简介优化
    支持专用翻译模型如 facebook/nllb-200-distilled-600M
    """
    api_url = str(url).rstrip('/') + '/v1/chat/completions'
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    # 根据文本长度动态调整 max_tokens 和 timeout
    is_short_text = len(texts) < 100
    max_tokens = 256 if is_short_text else 1024
    timeout = 30 if is_short_text else 60
    
    # 检测是否为专用翻译模型（如 NLLB, hy-mt2-7b 等）
    is_translation_model = any(x in model.lower() for x in ['nllb', 'translation', 'translator', 'hy-mt2', 'mt2-7b'])
    
    if is_translation_model:
        # 检测是否为 hy-mt2-7b 模型
        is_hy_mt2 = 'hy-mt2' in model.lower() or 'mt2-7b' in model.lower()
        
        if is_hy_mt2:
            # hy-mt2-7b 专用提示词 - 针对日译中优化
            data = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的日语翻译助手，专门翻译日本成人影片的标题和简介。\n"
                            "请将日文翻译成自然流畅的中文。\n\n"
                            "翻译要求：\n"
                            "1. 番号保留原样（如 SSIS-123、ABC-456 等）\n"
                            "2. 人名（女优、男优）保留日文原名不翻译\n"
                            "3. 片商、系列名保留原样（如 S1、MOODYZ、SOD 等）\n"
                            "4. 日文语气词适当转换，使中文更自然\n"
                            "5. 成人术语翻译准确但不过度直白\n"
                            "6. 只输出翻译结果，不要解释"
                        )
                    },
                    {
                        "role": "user",
                        "content": f"请将以下内容翻译成中文：\n\n{texts}"
                    }
                ],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            }
        else:
            # NLLB 等其他专用翻译模型使用简化格式
            data = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Translate from Japanese to Chinese. Keep AV codes and names unchanged."
                    },
                    {
                        "role": "user",
                        "content": texts
                    }
                ],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            }
    else:
        # 通用 LLM 使用详细提示词
        data = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"你是一位专业的日本成人影片翻译专家。"
                        f"请将以下日文标题或简介翻译成{to}。\n\n"
                        "翻译规则：\n"
                        "1. 保留番号不变（如 ABC-123, SSIS-999 等格式）\n"
                        "2. 保留女优、男优的日文原名（人名不翻译）\n"
                        "3. 保留制作商、系列名称等专有名词（如 S1, MOODYZ, kira☆kira 等）\n"
                        "4. 准确翻译成人相关术语和描述内容\n"
                        "5. 保持原标题的语序和风格，不要过度意译\n"
                        "6. 只返回翻译结果，不要添加任何额外说明或解释"
                    )
                },
                {
                    "role": "user",
                    "content": texts
                }
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }

    for attempt in range(1, max_retry + 1):
        try:
            r = requests.post(api_url, headers=headers, json=data, timeout=timeout)
            r.raise_for_status()
            resp = r.json()

            # 标准 OpenAI 兼容格式
            if "choices" in resp and len(resp["choices"]) > 0:
                choice = resp["choices"][0]
                if "message" in choice and "content" in choice["message"]:
                    return choice["message"]["content"].strip()
                elif "text" in choice:
                    return choice["text"].strip()

            # Ollama 格式
            if "response" in resp:
                return resp["response"].strip()

            # 错误返回
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
            error_msg = str(e)
            # 检测LM Studio内存不足错误
            is_memory_error = any(x in error_msg.lower() for x in [
                'insufficient memory', 'out of memory', 'oom', 'gpu memory',
                'channel error', 'compute error', 'failed to decode'
            ])
            
            if is_memory_error:
                logger.warning(f"本地AI翻译第 {attempt} 次失败 (GPU内存不足): {e}")
                # 内存不足时使用指数退避，给GPU释放内存的时间
                wait_time = retry_delay * (2 ** attempt)
                logger.info(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
            else:
                logger.debug(f"本地AI翻译第 {attempt} 次失败: {e}")
                if attempt < max_retry:
                    time.sleep(retry_delay)
            
            if attempt >= max_retry:
                logger.error(f"本地AI翻译失败 (已重试{max_retry}次): {e}")
                return {
                    "error_code": -1,
                    "error_msg": str(e),
                }


def googleai_translate(texts, url: Url, api_key: str, model: str, to="zh_CN", max_retry=3, retry_delay=1):
    """
    使用 Google Gemini 翻译文本（默认翻译为简体中文），带重试机制
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

    for attempt in range(1, max_retry + 1):
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
                if attempt < max_retry:
                    logger.debug(f"GoogleAI翻译第 {attempt} 次失败: {r.status_code}")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"GoogleAI翻译失败: {r.status_code}")
                    return {
                        "error_code": r.status_code,
                        "error_msg": r.reason
                    }
        except requests.exceptions.RequestException as e:
            logger.debug(f"GoogleAI翻译第 {attempt} 次失败: {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
            else:
                logger.error(f"GoogleAI翻译失败: {e}")
                return {
                    "error_code": -1,
                    "error_msg": str(e)
                }


if __name__ == "__main__":
    text = "これは日本語の文章です。This should remain in English."
    key = "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"
    result = baidu_translate(
        texts=text,
        api_key="xlknIh8NbZiq7ksRBhDpySDGUdmCWAUq",
        app_id="1BKABrHJdBrLtJtxQvlyYi7r"

    )
    print(result)
