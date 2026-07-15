"""字幕生成模块 - 音轨提取 + mlx-whisper 语音识别 + 翻译"""

import os
import json
import subprocess
import logging
import threading
import platform
import time
from pathlib import Path

logger = logging.getLogger('javsp.webapp.subtitle')

# 视频扩展名
VIDEO_EXTENSIONS = {
    '.3gp', '.avi', '.f4v', '.flv', '.iso', '.m2ts', '.m4v', '.mkv',
    '.mov', '.mp4', '.mpeg', '.rm', '.rmvb', '.ts', '.vob', '.webm',
    '.wmv', '.strm', '.mpg',
}

# 任务停止标志
_stop_flags: dict[str, threading.Event] = {}


def check_platform_support() -> dict:
    """检查当前平台是否支持字幕生成"""
    is_mac = platform.system() == 'Darwin'
    is_arm = platform.machine() == 'arm64'
    supported = is_mac and is_arm

    mlx_available = False
    if supported:
        try:
            import mlx_whisper  # noqa: F401
            mlx_available = True
        except ImportError:
            pass

    ffmpeg_ok = False
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
        ffmpeg_ok = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return {
        'supported': supported,
        'platform': platform.system(),
        'arch': platform.machine(),
        'mlx_whisper': mlx_available,
        'ffmpeg': ffmpeg_ok,
        'reason': None if (supported and mlx_available and ffmpeg_ok) else
                  '仅支持 Mac Apple Silicon (M系列)' if not supported else
                  'mlx-whisper 未安装' if not mlx_available else
                  'ffmpeg 未安装',
    }


def _get_subtitle_config() -> dict:
    """获取字幕配置"""
    from javsp.webapp.database import get_config
    config = get_config('subtitle')
    return config.get('subtitle', {})


def _get_audio_path(item: dict, config: dict) -> str:
    """计算音轨文件存放路径。多音轨时在文件名中加入音轨索引和语言标识"""
    store_path = config.get('audio_store_path', '').strip()
    stem = Path(item['video_basename']).stem
    track_idx = item.get('track_index', 0)
    lang = item.get('track_language') or 'und'
    basename = f"{stem}.track{track_idx}.{lang}.wav"

    if store_path:
        os.makedirs(store_path, exist_ok=True)
        return os.path.join(store_path, basename)
    else:
        return os.path.join(item['video_dir'], basename)


def _get_subtitle_path(item: dict, fmt: str = 'srt') -> str:
    """计算字幕文件存放路径（与视频同目录）。多音轨时加入音轨索引和语言标识"""
    stem = Path(item['video_basename']).stem
    track_idx = item.get('track_index', 0)
    lang = item.get('track_language') or 'und'
    # 如果只有一个音轨且语言为 und，保持简洁文件名
    if track_idx == 0 and lang == 'und':
        basename = f"{stem}.{fmt}"
    else:
        basename = f"{stem}.track{track_idx}.{lang}.{fmt}"
    return os.path.join(item['video_dir'], basename)


def extract_audio(video_path: str, output_path: str, track_index: int = 0) -> dict:
    """用 ffmpeg 从视频中提取指定音轨为 WAV 16kHz 单声道"""
    if not os.path.exists(video_path):
        return {'ok': False, 'errors': '源视频文件已丢失'}
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path):
        os.remove(output_path)
    try:
        result = subprocess.run(
            ['ffmpeg', '-y', '-i', video_path,
             '-map', f'0:a:{track_index}',
             '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
             output_path],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            return {'ok': False, 'errors': result.stderr[-500:] if result.stderr else 'ffmpeg 返回错误'}

        # 获取音频时长
        duration = None
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                 '-of', 'json', output_path],
                capture_output=True, text=True, timeout=10
            )
            info = json.loads(probe.stdout)
            duration = float(info['format']['duration'])
        except Exception:
            pass

        return {'ok': True, 'errors': None, 'audio_path': output_path, 'duration': duration}
    except FileNotFoundError:
        return {'ok': False, 'errors': 'ffmpeg 未安装'}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'errors': '音频提取超时 (>600s)'}
    except Exception as e:
        return {'ok': False, 'errors': str(e)}


def get_audio_tracks(video_path: str) -> list:
    """获取视频的音轨列表"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', video_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return []
        info = json.loads(result.stdout)
        tracks = []
        audio_idx = 0
        for s in info.get('streams', []):
            if s.get('codec_type') == 'audio':
                tracks.append({
                    'index': audio_idx,
                    'codec': s.get('codec_name', ''),
                    'language': s.get('tags', {}).get('language', 'und'),
                    'title': s.get('tags', {}).get('title', ''),
                    'channels': s.get('channels', 0),
                })
                audio_idx += 1
        return tracks
    except Exception as e:
        logger.error(f"获取音轨列表失败: {e}")
        return []


def _get_active_translate_engine():
    """获取当前激活的翻译引擎配置"""
    from javsp.webapp.database import get_active_translate_model, get_all_translate_models, get_config

    translator_config = get_config('translator').get('translator', {})
    translate_mode = translator_config.get('translate_mode', 'normal')

    if translate_mode == 'ai':
        model = get_active_translate_model()
        if model:
            return model['engine'], model['config_json']
        
        all_models = get_all_translate_models()
        if all_models:
            logger.warning(f"存在翻译模型但未激活: {[m['name'] for m in all_models]}")
        else:
            logger.warning("翻译模式为AI，但数据库中没有翻译模型，请在设置页面添加并激活翻译模型")
        return None, None
    else:
        engine = translator_config.get('engine', '')
        if not engine:
            return None, None
        
        config = {}
        if engine in ['openai', 'localai', 'googleai']:
            config['api_url'] = translator_config.get('api_url', '')
            config['api_key'] = translator_config.get('api_key', '')
            config['model'] = translator_config.get('model', '')
            if engine == 'localai':
                config['context_window'] = translator_config.get('context_window', 2048)
        elif engine == 'baidu':
            config['app_id'] = translator_config.get('baidu_app_id', '')
            config['api_key'] = translator_config.get('api_key', '')
        elif engine == 'bing':
            config['api_key'] = translator_config.get('bing_api_key', '')
        elif engine == 'claude':
            config['api_key'] = translator_config.get('api_key', '')
        
        return engine, config


def _translate_text(text: str) -> str:
    """翻译文本为中文。使用配置的翻译引擎"""
    try:
        from javsp.web.translate import translate

        engine, config = _get_active_translate_engine()
        if not engine:
            return text

        result = translate(text, engine, config=config)
        if result and 'trans' in result:
            return result['trans']
        logger.warning(f"翻译失败: {result.get('error', '未知错误')}")
        return text
    except Exception as e:
        logger.exception(f"翻译异常: {e}")
        return text


def _build_subtitle_translate_prompt(texts: list) -> str:
    """构建字幕翻译的优化提示词"""
    DELIMITER = '\n---SUB---\n'
    joined_text = DELIMITER.join(texts)
    
    return f"""你是专业的日语视频字幕翻译助手。请将以下日文台词翻译成中文。

翻译规则：
1. 保持口语化和对话感，像日常聊天一样自然流畅
2. 准确传达情感和语气（如撒娇、生气、害羞等）
3. 保留语气词的中文对应表达（ね→呢，よ→哦，さ→呀）
4. 人名、专有名词、品牌名保留原文不翻译
5. 成人相关术语翻译准确但不过度直白
6. 简短台词不要过度扩展，保持简洁
7. 每段翻译用同样的分隔符隔开
8. 只输出翻译结果，不要添加序号、解释或其他内容

待翻译字幕：
{joined_text}"""


def _translate_subtitle_batch(texts: list, engine, config=None) -> tuple[list, str]:
    """专门用于字幕翻译的批量翻译函数，使用优化的提示词"""
    from javsp.web.translate import translate

    if not texts or not engine:
        return texts, ''

    DELIMITER = '\n---SUB---\n'
    
    try:
        prompt = _build_subtitle_translate_prompt(texts)
        
        logger.info(f"发送字幕翻译请求，{len(texts)} 条字幕，总字符数 {len(prompt)}")
        
        result = translate(prompt, engine, config=config)
        
        if isinstance(result, dict):
            if 'error' in result:
                logger.warning(f"字幕翻译失败: {result['error']}")
                return texts, result['error']
            elif 'trans' in result:
                translated = result['trans']
                translations = translated.split(DELIMITER)
                logger.info(f"字幕翻译成功，返回 {len(translations)} 条结果")
                return [t.strip() for t in translations], ''
            else:
                logger.warning(f"字幕翻译响应格式未知: {result}")
                return texts, f"未知响应格式"
        else:
            translations = str(result).split(DELIMITER)
            logger.info(f"字幕翻译成功（非字典响应），返回 {len(translations)} 条结果")
            return [t.strip() for t in translations], ''
            
    except Exception as e:
        logger.exception(f"字幕翻译异常: {e}")
        return texts, str(e)


def _batch_translate_segments(segments: list) -> tuple[list, str]:
    """批量翻译多个字幕 segment，处理本地模型长度限制和错误回退
    
    Args:
        segments: 字幕片段列表，每个片段包含 'text' 字段
    
    Returns:
        tuple: (翻译后的文本列表, 错误信息)
               列表与输入顺序对应，翻译失败时保留原文
               错误信息为空表示成功，非空表示有错误发生
    """
    if not segments:
        return [], ''

    from javsp.web.translate import translate

    engine, config = _get_active_translate_engine()
    logger.info(f"翻译引擎配置: engine={engine}, config={config}")
    
    if not engine:
        logger.warning("翻译引擎未配置，跳过翻译")
        return [seg['text'] for seg in segments], '翻译引擎未配置'

    subtitle_config = _get_subtitle_config()
    max_chars = int(subtitle_config.get('translate_max_length', 1500))
    if max_chars < 100:
        max_chars = 1500
    logger.info(f"翻译参数: max_chars={max_chars}, segment数量={len(segments)}")

    DELIMITER = '\n---SUB---\n'
    
    batches = []
    current_batch = []
    current_length = 0

    for seg in segments:
        text = seg['text'].strip()
        if not text:
            current_batch.append('')
            continue
        
        text_length = len(text)
        if current_batch and current_length + text_length + len(DELIMITER) > max_chars:
            batches.append(current_batch)
            current_batch = [text]
            current_length = text_length
        else:
            current_batch.append(text)
            current_length += text_length + (len(DELIMITER) if current_batch else 0)
    
    if current_batch:
        batches.append(current_batch)

    all_translations = []
    error_messages = []
    
    for batch_idx, batch in enumerate(batches):
        if not batch:
            continue
        
        logger.info(f"翻译第 {batch_idx+1}/{len(batches)} 批，{len(batch)} 条字幕")
        
        non_empty_texts = []
        empty_indices = []
        for i, text in enumerate(batch):
            if text:
                non_empty_texts.append(text)
            else:
                empty_indices.append(i)
        
        translations, err = _translate_subtitle_batch(non_empty_texts, engine, config)
        
        if err:
            error_messages.append(f"第 {batch_idx+1} 批: {err}")
            logger.warning(f"批量翻译第 {batch_idx+1} 批失败: {err}")
            
            if 'timeout' in err.lower() or 'timed out' in err.lower():
                logger.info(f"批量翻译超时，尝试逐段翻译 {len(non_empty_texts)} 条字幕")
                translations = []
                for text in non_empty_texts:
                    try:
                        trans = _translate_text(text)
                        translations.append(trans)
                    except Exception as e:
                        logger.warning(f"单条翻译失败: {e}")
                        translations.append(text)
            else:
                translations = non_empty_texts
        
        result_pos = 0
        for i in range(len(batch)):
            if i in empty_indices:
                all_translations.append('')
            else:
                all_translations.append(translations[result_pos] if result_pos < len(translations) else batch[i])
                result_pos += 1

    error_summary = ''
    if error_messages:
        error_summary = f"翻译过程中出现 {len(error_messages)} 个错误，部分字幕可能未翻译: " + "; ".join(error_messages[:3])
        if len(error_messages) > 3:
            error_summary += f"（还有 {len(error_messages)-3} 个错误）"

    return all_translations, error_summary


def generate_subtitle(audio_path: str, output_path: str, model: str, language: str = 'ja',
                      fmt: str = 'srt', segment_duration: int = 30, subtitle_mode: str = 'original',
                      video_path: str = '', track_index: int = 0) -> dict:
    """用 mlx-whisper 从音频生成字幕，支持原语言/中文/双语模式"""
    try:
        if not os.path.exists(audio_path):
            if video_path and os.path.exists(video_path):
                logger.info(f"音轨文件不存在，重新提取: {audio_path}")
                os.makedirs(os.path.dirname(audio_path), exist_ok=True)
                if os.path.exists(audio_path):
                    os.remove(audio_path)
                result = subprocess.run(
                    ['ffmpeg', '-y', '-i', video_path,
                     '-map', f'0:a:{track_index}',
                     '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                     audio_path],
                    capture_output=True, text=True, timeout=600
                )
                if result.returncode != 0:
                    return {'ok': False, 'errors': f'重新提取音轨失败: {result.stderr[-500:] if result.stderr else "ffmpeg 返回错误"}'}
                logger.info(f"音轨重新提取成功: {audio_path}")
            else:
                return {'ok': False, 'errors': f'音轨文件不存在: {audio_path}'}
        
        import mlx_whisper

        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=model,
            language=language if language != 'auto' else None,
            word_timestamps=False,
            verbose=False,
        )

        segments = result.get('segments', [])
        if not segments:
            return {'ok': False, 'errors': '未识别到任何语音'}

        detected_lang = result.get('language', language)

        effective_mode = subtitle_mode
        if detected_lang != 'zh' and subtitle_mode == 'original':
            effective_mode = 'bilingual'
            logger.info(f"自动切换为双语模式：识别语言={detected_lang}, 原始模式={subtitle_mode}")

        logger.info(f"字幕模式: 用户配置={subtitle_mode}, 实际生效={effective_mode}, 识别语言={detected_lang}, segment数量={len(segments)}")

        subtitle_config = _get_subtitle_config()
        filter_fillers_value = subtitle_config.get('filter_fillers', False)
        if isinstance(filter_fillers_value, str):
            filter_fillers = filter_fillers_value.lower() == 'true'
        else:
            filter_fillers = bool(filter_fillers_value)
        if filter_fillers:
            segments, removed_count = _filter_segments(segments, detected_lang)
            logger.info(f"语气词过滤已启用，移除 {removed_count} 条片段，剩余 {len(segments)} 条")
            if not segments:
                return {'ok': False, 'errors': '过滤后未保留任何有效字幕'}

        translate_errors = ''
        if effective_mode in ('chinese', 'bilingual'):
            logger.info(f"开始翻译 {len(segments)} 个字幕片段")
            translations, translate_errors = _batch_translate_segments(segments)
            for i, seg in enumerate(segments):
                seg['trans_text'] = translations[i] if i < len(translations) else seg['text']
            logger.info(f"翻译完成，错误信息: {translate_errors or '无'}")
        else:
            logger.info(f"跳过翻译，当前模式={effective_mode}")

        if fmt == 'srt':
            _write_srt(segments, output_path, effective_mode)
        elif fmt == 'ass':
            _write_ass(segments, output_path, effective_mode)
        elif fmt == 'vtt':
            _write_vtt(segments, output_path, effective_mode)
        else:
            _write_srt(segments, output_path, effective_mode)

        _write_debug_txt(segments, output_path)

        return {'ok': True, 'errors': translate_errors or None, 'subtitle_path': output_path, 'language': detected_lang}

    except ImportError:
        return {'ok': False, 'errors': 'mlx-whisper 未安装'}
    except Exception as e:
        logger.exception(f"字幕生成失败: {e}")
        return {'ok': False, 'errors': str(e)}


def _format_srt_time(seconds: float) -> str:
    """将秒数格式化为 SRT 时间戳 HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_ass_time(seconds: float) -> str:
    """将秒数格式化为 ASS 时间戳 H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _write_srt(segments: list, output_path: str, subtitle_mode: str = 'original'):
    """写入 SRT 格式字幕"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            start = _format_srt_time(seg['start'])
            end = _format_srt_time(seg['end'])
            if subtitle_mode == 'chinese':
                text = seg.get('trans_text', seg['text']).strip()
            elif subtitle_mode == 'bilingual':
                original = seg['text'].strip()
                translated = seg.get('trans_text', '').strip()
                text = f"{original}\n{translated}" if translated else original
            else:
                text = seg['text'].strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


def _write_vtt(segments: list, output_path: str, subtitle_mode: str = 'original'):
    """写入 VTT 格式字幕"""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("WEBVTT\n\n")
        for i, seg in enumerate(segments, 1):
            start = _format_srt_time(seg['start']).replace(',', '.')
            end = _format_srt_time(seg['end']).replace(',', '.')
            if subtitle_mode == 'chinese':
                text = seg.get('trans_text', seg['text']).strip()
            elif subtitle_mode == 'bilingual':
                original = seg['text'].strip()
                translated = seg.get('trans_text', '').strip()
                text = f"{original}\n{translated}" if translated else original
            else:
                text = seg['text'].strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


def _write_ass(segments: list, output_path: str, subtitle_mode: str = 'original'):
    """写入 ASS 格式字幕"""
    header = """[Script Info]
Title: Generated by mlx-whisper
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Noto Sans CJK JP,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,10,10,20,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(header)
        for seg in segments:
            start = _format_ass_time(seg['start'])
            end = _format_ass_time(seg['end'])
            if subtitle_mode == 'chinese':
                text = seg.get('trans_text', seg['text']).strip()
            elif subtitle_mode == 'bilingual':
                original = seg['text'].strip()
                translated = seg.get('trans_text', '').strip()
                text = f"{original}\\N{translated}" if translated else original
            else:
                text = seg['text'].strip()
            text = text.replace('\n', '\\N')
            f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")


def _write_debug_txt(segments: list, output_path: str):
    """写入调试用的txt文件，方便排查翻译错误"""
    base_path = str(output_path).rsplit('.', 1)[0]
    
    original_path = f"{base_path}.original.txt"
    translated_path = f"{base_path}.translated.txt"
    comparison_path = f"{base_path}.comparison.txt"
    
    with open(original_path, 'w', encoding='utf-8') as f_orig, \
         open(translated_path, 'w', encoding='utf-8') as f_trans, \
         open(comparison_path, 'w', encoding='utf-8') as f_comp:
        
        f_comp.write("=" * 80 + "\n")
        f_comp.write("字幕翻译对照（日语原文 → 中文翻译）\n")
        f_comp.write("=" * 80 + "\n\n")
        
        for i, seg in enumerate(segments, 1):
            original = seg['text'].strip()
            translated = seg.get('trans_text', '').strip()
            
            if original:
                f_orig.write(f"{i}. {original}\n")
            
            if translated:
                f_trans.write(f"{i}. {translated}\n")
            
            if original or translated:
                f_comp.write(f"【第 {i} 条】\n")
                f_comp.write(f"日语原文: {original or '(空)'}\n")
                f_comp.write(f"中文翻译: {translated or '(未翻译)'}\n")
                if original and translated and original != translated:
                    f_comp.write("-" * 60 + "\n")
    
    logger.info(f"调试文件已保存: {original_path}, {translated_path}, {comparison_path}")


_FILLER_PATTERNS = [
    r'^[あア]{2,}$',
    r'^[いイ]{2,}$',
    r'^[うウ]{2,}$',
    r'^[えエ]{2,}$',
    r'^[おオ]{2,}$',
    r'^[はハ]{2,}$',
    r'^[へヘ]{2,}$',
    r'^[ほホ]{2,}$',
    r'^[まマ]{2,}$',
    r'^[めメ]{2,}$',
    r'^[もモ]{2,}$',
    r'^[くク]{2,}$',
    r'^[けケ]{2,}$',
    r'^[こコ]{2,}$',
    r'^[さサ]{2,}$',
    r'^[しシ]{2,}$',
    r'^[すス]{2,}$',
    r'^[せセ]{2,}$',
    r'^[そソ]{2,}$',
    r'^[たタ]{2,}$',
    r'^[ちチ]{2,}$',
    r'^[つツ]{2,}$',
    r'^[てテ]{2,}$',
    r'^[とト]{2,}$',
    r'^[なナ]{2,}$',
    r'^[にニ]{2,}$',
    r'^[ぬヌ]{2,}$',
    r'^[ねネ]{2,}$',
    r'^[のノ]{2,}$',
    r'^[ひヒ]{2,}$',
    r'^[ふフ]{2,}$',
    r'^[へヘ]{2,}$',
    r'^[ほホ]{2,}$',
    r'^[みミ]{2,}$',
    r'^[むム]{2,}$',
    r'^[やヤ]{2,}$',
    r'^[ゆユ]{2,}$',
    r'^[よヨ]{2,}$',
    r'^[らラ]{2,}$',
    r'^[りリ]{2,}$',
    r'^[るル]{2,}$',
    r'^[れレ]{2,}$',
    r'^[ろロ]{2,}$',
    r'^[わワ]{2,}$',
    r'^[をヲ]{2,}$',
    r'^[んン]{2,}$',
    r'^[呵]{2,}$',
    r'^[哈]{2,}$',
    r'^[嘻]{2,}$',
    r'^[嘿]{2,}$',
    r'^[笑]{2,}$',
    r'^[哼]{2,}$',
    r'^[嗯]{2,}$',
    r'^[唔]{2,}$',
    r'^[啊]{2,}$',
    r'^[呀]{2,}$',
    r'^[哦]{2,}$',
    r'^[咦]{2,}$',
    r'^[哎]{2,}$',
    r'^[唉]{2,}$',
    r'^[嘿]{2,}$',
    r'^[喂]{2,}$',
    r'^[咳]{2,}$',
    r'^ふふふ$|^フフフ$',
    r'^ははは$|^ハハハ$',
    r'^へへへ$|^ヘヘヘ$',
    r'^うふふ$|^ウフフ$',
    r'^うっ$|^ウッ$',
    r'^あっ$|^アッ$',
    r'^おっ$|^オッ$',
    r'^えっ$|^エッ$',
    r'^ほっ$|^ホッ$',
    r'^まっ$|^マッ$',
    r'^やっ$|^ヤッ$',
    r'^よっ$|^ヨッ$',
    r'^わっ$|^ワッ$',
    r'^はっ$|^ハッ$',
    r'^ねえ$|^ネエ$',
    r'^ねぇ$|^ネェ$',
    r'^よう$|^ヨウ$',
    r'^さあ$|^サア$',
    r'^さよ$|^サヨ$',
    r'^まあ$|^マア$',
    r'^そう$|^ソウ$',
    r'^はい$|^ハイ$',
    r'^いい$|^イイ$',
    r'^ええ$|^エエ$',
    r'^うん$|^ウン$',
    r'^うーん$|^ウーン$',
    r'^んー$|^ンー$',
    r'^うー$|^ウー$',
    r'^いー$|^イー$',
    r'^えー$|^エー$',
    r'^おー$|^オー$',
    r'^あー$|^アー$',
    r'^かー$|^カー$',
    r'^きー$|^キー$',
    r'^くー$|^クー$',
    r'^けー$|^ケー$',
    r'^こー$|^コー$',
    r'^さー$|^サー$',
    r'^しー$|^シー$',
    r'^すー$|^スー$',
    r'^せー$|^セー$',
    r'^そー$|^ソー$',
    r'^たー$|^ター$',
    r'^ちー$|^チー$',
    r'^つー$|^ツー$',
    r'^てー$|^テー$',
    r'^とー$|^トー$',
    r'^なー$|^ナー$',
    r'^にー$|^ニー$',
    r'^ぬー$|^ヌー$',
    r'^ねー$|^ネー$',
    r'^のー$|^ノー$',
    r'^はー$|^ハー$',
    r'^ひー$|^ヒー$',
    r'^ふー$|^フー$',
    r'^へー$|^ヘー$',
    r'^ほー$|^ホー$',
    r'^まー$|^マー$',
    r'^みー$|^ミー$',
    r'^むー$|^ムー$',
    r'^めー$|^メー$',
    r'^もー$|^モー$',
    r'^やー$|^ヤー$',
    r'^ゆー$|^ユー$',
    r'^よー$|^ヨー$',
    r'^らー$|^ラー$',
    r'^りー$|^リー$',
    r'^るー$|^ルー$',
    r'^れー$|^レー$',
    r'^ろー$|^ロー$',
    r'^わー$|^ワー$',
    r'^をー$|^ヲー$',
    r'^ほら$|^ホラ$',
    r'^ね$|^ネ$',
    r'^よ$|^ヨ$',
    r'^さ$|^サ$',
    r'^ぞ$|^ゾ$',
    r'^ぜ$|^ゼ$',
    r'^わ$|^ワ$',
    r'^の$|^ノ$',
    r'^な$|^ナ$',
    r'^ば$|^バ$',
    r'^だ$|^ダ$',
    r'^か$|^カ$',
    r'^が$|^ガ$',
    r'^け$|^ケ$',
    r'^げ$|^ゲ$',
    r'^こ$|^コ$',
    r'^ご$|^ゴ$',
    r'^さ$|^サ$',
    r'^ざ$|^ザ$',
    r'^し$|^シ$',
    r'^じ$|^ジ$',
    r'^す$|^ス$',
    r'^ず$|^ズ$',
    r'^せ$|^セ$',
    r'^ぜ$|^ゼ$',
    r'^そ$|^ソ$',
    r'^ぞ$|^ゾ$',
    r'^た$|^タ$',
    r'^だ$|^ダ$',
    r'^ち$|^チ$',
    r'^ぢ$|^ヂ$',
    r'^つ$|^ツ$',
    r'^づ$|^ヅ$',
    r'^て$|^テ$',
    r'^で$|^デ$',
    r'^と$|^ト$',
    r'^ど$|^ド$',
    r'^な$|^ナ$',
    r'^に$|^ニ$',
    r'^ぬ$|^ヌ$',
    r'^ね$|^ネ$',
    r'^の$|^ノ$',
    r'^は$|^ハ$',
    r'^ば$|^バ$',
    r'^ぱ$|^パ$',
    r'^ひ$|^ヒ$',
    r'^び$|^ビ$',
    r'^ぴ$|^ピ$',
    r'^ふ$|^フ$',
    r'^ぶ$|^ブ$',
    r'^ぷ$|^プ$',
    r'^へ$|^ヘ$',
    r'^べ$|^ベ$',
    r'^ぺ$|^ペ$',
    r'^ほ$|^ホ$',
    r'^ぼ$|^ボ$',
    r'^ぽ$|^ポ$',
    r'^ま$|^マ$',
    r'^み$|^ミ$',
    r'^む$|^ム$',
    r'^め$|^メ$',
    r'^も$|^モ$',
    r'^や$|^ヤ$',
    r'^ゆ$|^ユ$',
    r'^よ$|^ヨ$',
    r'^ら$|^ラ$',
    r'^り$|^リ$',
    r'^る$|^ル$',
    r'^れ$|^レ$',
    r'^ろ$|^ロ$',
    r'^わ$|^ワ$',
    r'^を$|^ヲ$',
    r'^ん$|^ン$',
    r'^ん[?？]$|^ン[?？]$',
    r'^うむ$|^ウム$',
    r'^うむ[?？]$|^ウム[?？]$',
    r'^む$|^ム$',
    r'^む[?？]$|^ム[?？]$',
    r'^んー[?？]$|^ンー[?？]$',
    r'^ああ[?？]$|^アア[?？]$',
    r'^うう[?？]$|^ウウ[?？]$',
    r'^いい[?？]$|^イイ[?？]$',
    r'^ええ[?？]$|^エエ[?？]$',
    r'^そう[?？]$|^ソウ[?？]$',
    r'^まあ[?？]$|^マア[?？]$',
    r'^さあ[?？]$|^サア[?？]$',
    r'^ね[?？]$|^ネ[?？]$',
    r'^よ[?？]$|^ヨ[?？]$',
    r'^さ[?？]$|^サ[?？]$',
    r'^ぞ[?？]$|^ゾ[?？]$',
    r'^ぜ[?？]$|^ゼ[?？]$',
    r'^わ[?？]$|^ワ[?？]$',
    r'^の[?？]$|^ノ[?？]$',
    r'^な[?？]$|^ナ[?？]$',
    r'^ば[?？]$|^バ[?？]$',
    r'^だ[?？]$|^ダ[?？]$',
    r'^か[?？]$|^カ[?？]$',
    r'^が[?？]$|^ガ[?？]$',
    r'^け[?？]$|^ケ[?？]$',
    r'^げ[?？]$|^ゲ[?？]$',
    r'^こ[?？]$|^コ[?？]$',
    r'^ご[?？]$|^ゴ[?？]$',
    r'^ざ[?？]$|^ザ[?？]$',
    r'^し[?？]$|^シ[?？]$',
    r'^じ[?？]$|^ジ[?？]$',
    r'^す[?？]$|^ス[?？]$',
    r'^ず[?？]$|^ズ[?？]$',
    r'^せ[?？]$|^セ[?？]$',
    r'^ぜ[?？]$|^ゼ[?？]$',
    r'^そ[?？]$|^ソ[?？]$',
    r'^ぞ[?？]$|^ゾ[?？]$',
    r'^た[?？]$|^タ[?？]$',
    r'^だ[?？]$|^ダ[?？]$',
    r'^ち[?？]$|^チ[?？]$',
    r'^ぢ[?？]$|^ヂ[?？]$',
    r'^つ[?？]$|^ツ[?？]$',
    r'^づ[?？]$|^ヅ[?？]$',
    r'^て[?？]$|^テ[?？]$',
    r'^で[?？]$|^デ[?？]$',
    r'^と[?？]$|^ト[?？]$',
    r'^ど[?？]$|^ド[?？]$',
    r'^に[?？]$|^ニ[?？]$',
    r'^ぬ[?？]$|^ヌ[?？]$',
    r'^の[?？]$|^ノ[?？]$',
    r'^は[?？]$|^ハ[?？]$',
    r'^ば[?？]$|^バ[?？]$',
    r'^ぱ[?？]$|^パ[?？]$',
    r'^ひ[?？]$|^ヒ[?？]$',
    r'^び[?？]$|^ビ[?？]$',
    r'^ぴ[?？]$|^ピ[?？]$',
    r'^ふ[?？]$|^フ[?？]$',
    r'^ぶ[?？]$|^ブ[?？]$',
    r'^ぷ[?？]$|^プ[?？]$',
    r'^へ[?？]$|^ヘ[?？]$',
    r'^べ[?？]$|^ベ[?？]$',
    r'^ぺ[?？]$|^ペ[?？]$',
    r'^ほ[?？]$|^ホ[?？]$',
    r'^ぼ[?？]$|^ボ[?？]$',
    r'^ぽ[?？]$|^ポ[?？]$',
    r'^み[?？]$|^ミ[?？]$',
    r'^む[?？]$|^ム[?？]$',
    r'^め[?？]$|^メ[?？]$',
    r'^も[?？]$|^モ[?？]$',
    r'^や[?？]$|^ヤ[?？]$',
    r'^ゆ[?？]$|^ユ[?？]$',
    r'^よ[?？]$|^ヨ[?？]$',
    r'^ら[?？]$|^ラ[?？]$',
    r'^り[?？]$|^リ[?？]$',
    r'^る[?？]$|^ル[?？]$',
    r'^れ[?？]$|^レ[?？]$',
    r'^ろ[?？]$|^ロ[?？]$',
    r'^わ[?？]$|^ワ[?？]$',
    r'^を[?？]$|^ヲ[?？]$',
    r'^[!！]{1,}$',
    r'^[?？]{1,}$',
    r'^[.。]{1,}$',
    r'^[,，]{1,}$',
    r'^[,、]{1,}$',
    r'^[~～]{1,}$',
    r'^[・]{1,}$',
    r'^[･]{1,}$',
    r'^[「」]{1,}$',
    r'^[『』]{1,}$',
    r'^[（）]{1,}$',
    r'^[()]{1,}$',
    r'^[\[\]]{1,}$',
    r'^【】$',
    r'^[<>＜＞]{1,}$',
    r'^[\[\]【】]{1,}$',
    r'^[-−]{1,}$',
    r'^[_＿]{1,}$',
    r'^[=＝]{1,}$',
    r'^[*＊]{1,}$',
    r'^[+＋]{1,}$',
    r'^[#＃]{1,}$',
    r'^[@＠]{1,}$',
    r'^[$＄]{1,}$',
    r'^[%％]{1,}$',
    r'^[&＆]{1,}$',
    r'^[|｜]{1,}$',
    r'^[\\￥]{1,}$',
    r'^[/／]{1,}$',
    r'^[;；]{1,}$',
    r'^[:：]{1,}$',
    r'^[''‘’''""“”]{1,}$',
    r'^[`｀]{1,}$',
    r'^[’‘]{1,}$',
    r'^[”“]{1,}$',
    r'^[・・]{1,}$',
    r'^[、。]{1,}$',
    r'^[！？]{1,}$',
    r'^[!?！？]{1,}$',
    r'^[!！?？]{1,}$',
    r'^[！？。]{1,}$',
    r'^[！？、]{1,}$',
    r'^[！。]{1,}$',
    r'^[？。]{1,}$',
    r'^[？、]{1,}$',
    r'^[！、]{1,}$',
    r'^[。、]{1,}$',
    r'^[!！.。]{1,}$',
    r'^[?？.。]{1,}$',
    r'^[!！,，]{1,}$',
    r'^[?？,，]{1,}$',
    r'^[!！~～]{1,}$',
    r'^[?？~～]{1,}$',
    r'^[.。~～]{1,}$',
    r'^[,，~～]{1,}$',
    r'^[、~～]{1,}$',
    r'^[！~～]{1,}$',
    r'^[？~～]{1,}$',
    r'^[。~～]{1,}$',
    r'^[、~～]{1,}$',
    r'^[\s]{1,}$',
    r'^[　]{1,}$',
    r'^[ ]{1,}$',
    r'^[\t]{1,}$',
    r'^[\n]{1,}$',
    r'^[\r]{1,}$',
]


def _filter_segments(segments: list, language: str = 'ja') -> tuple[list, int]:
    """过滤只包含语气词/拟声词的字幕片段
    
    Args:
        segments: 字幕片段列表
        language: 语言代码（ja/zh/en）
        
    Returns:
        tuple: (过滤后的片段列表, 被过滤的数量)
    """
    import re
    
    filtered = []
    removed_count = 0
    
    for seg in segments:
        text = seg.get('text', '').strip()
        if not text:
            removed_count += 1
            continue
        
        if language == 'ja':
            is_filler = False
            for pattern in _FILLER_PATTERNS:
                if re.match(pattern, text):
                    is_filler = True
                    break
            
            if is_filler:
                removed_count += 1
                continue
        
        filtered.append(seg)
    
    logger.info(f"语气词过滤完成: 原始 {len(segments)} 条, 过滤后 {len(filtered)} 条, 移除 {removed_count} 条")
    return filtered, removed_count


SUBTITLE_EXTENSIONS = {'.srt', '.ass', '.ssa'}
AUDIO_EXTENSIONS = {'.wav'}


def scan_media_files(path: str, check_exists: bool = True) -> list:
    """扫描目录下的媒体文件。check_exists=True 时跳过不存在的文件"""
    from javsp.webapp.database import get_config
    config = get_config('scanner')
    exts = config.get('scanner', {}).get('filename_extensions', list(VIDEO_EXTENSIONS))
    ext_set = {e.lower() if e.startswith('.') else f'.{e.lower()}' for e in exts}
    if not ext_set:
        ext_set = VIDEO_EXTENSIONS

    files = []
    ignored_patterns = config.get('scanner', {}).get('ignored_folder_name_pattern', [])
    import re
    ignored_res = []
    for pat in ignored_patterns:
        try:
            ignored_res.append(re.compile(pat))
        except re.error:
            pass

    for dirpath, dirnames, filenames in os.walk(path):
        base = os.path.basename(dirpath)
        if any(r.search(base) for r in ignored_res):
            dirnames.clear()
            continue

        dir_files = {}
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            stem = os.path.splitext(filename)[0]
            filepath = os.path.join(dirpath, filename)
            if ext in SUBTITLE_EXTENSIONS:
                if stem not in dir_files:
                    dir_files[stem] = {'subtitles': [], 'audio': None}
                dir_files[stem]['subtitles'].append(filepath)
            elif ext in AUDIO_EXTENSIONS:
                if stem not in dir_files:
                    dir_files[stem] = {'subtitles': [], 'audio': None}
                dir_files[stem]['audio'] = filepath

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ext_set:
                continue
            filepath = os.path.join(dirpath, filename)
            if check_exists and not os.path.exists(filepath):
                continue
            try:
                fsize = os.path.getsize(filepath)
                stem = os.path.splitext(filename)[0]
                dir_info = dir_files.get(stem, {'subtitles': [], 'audio': None})
                
                local_subtitle_path = None
                if dir_info['subtitles']:
                    local_subtitle_path = dir_info['subtitles'][0]
                
                files.append({
                    'path': filepath,
                    'basename': filename,
                    'dir': dirpath,
                    'size': fsize,
                    'local_subtitle_path': local_subtitle_path,
                    'local_audio_path': dir_info['audio'],
                    'subtitle_count': len(dir_info['subtitles']),
                })
            except OSError:
                continue
    return files


# ==================== 任务执行 ====================

_stop_events: dict[str, threading.Event] = {}


def request_subtitle_stop(task_id: str):
    """请求停止字幕任务。如果 stop_event 已丢失（如服务重启），直接更新数据库状态为 stopped"""
    if task_id in _stop_events:
        _stop_events[task_id].set()
    else:
        from javsp.webapp.database import get_subtitle_task, update_subtitle_task_status
        task = get_subtitle_task(task_id)
        if task and task['status'] in ('running', 'subtitle_running'):
            update_subtitle_task_status(task_id, 'stopped')


def clear_subtitle_stop(task_id: str):
    """清除停止标志"""
    _stop_events.pop(task_id, None)


def validate_files_exist(files: list) -> tuple:
    """校验文件是否存在。返回 (valid_files, missing_files)。兼容 path 和 video_path 字段"""
    valid_files = []
    missing_files = []
    for f in files:
        p = f.get('path') or f.get('video_path') or ''
        if p and os.path.exists(p):
            valid_files.append(f)
        else:
            missing_files.append(f)
    return valid_files, missing_files


def refresh_scan_extracted_status():
    """刷新扫描结果中的已提取状态"""
    from javsp.webapp.database import refresh_subtitle_scan_extracted_status
    refresh_subtitle_scan_extracted_status()


def start_subtitle_task(task_id: str, name: str, scan_path: str, files: list = None, socketio=None) -> dict:
    """创建字幕任务并启动后台音频提取线程。files 为 None 时扫描整个目录。
    每个视频文件的每个音轨都会创建一条记录。
    """
    from javsp.webapp.database import (
        create_subtitle_task, get_config as _get_config,
        add_log, update_subtitle_scan_result_exists,
        update_subtitle_scan_result_extracted
    )

    if not os.path.isdir(scan_path):
        return {'error': f'目录不存在: {scan_path}'}

    platform_info = check_platform_support()
    if not platform_info['supported'] or not platform_info['mlx_whisper']:
        return {'error': platform_info['reason']}

    if files is None:
        files = scan_media_files(scan_path)
    if not files:
        return {'error': '未选择或找到媒体文件'}

    # 校验文件存在性，并更新扫描结果状态
    for f in files:
        p = f.get('path') or f.get('video_path') or ''
        exists = p and os.path.exists(p)
        update_subtitle_scan_result_exists(p, exists)

    valid_files = [f for f in files if os.path.exists(f.get('path') or f.get('video_path') or '')]
    if not valid_files:
        return {'error': '选中的文件已不存在'}

    # 为每个视频文件扫描音轨，生成音轨级记录
    tracks = []
    for f in valid_files:
        video_path = f.get('path') or f.get('video_path')
        video_basename = f.get('basename') or f.get('video_basename')
        video_dir = f.get('dir') or f.get('video_dir')
        video_size = f.get('size') or f.get('file_size') or 0
        video_tracks = get_audio_tracks(video_path)
        if not video_tracks:
            # 没有音轨信息时，默认创建一个 track_index=0 的记录
            video_tracks = [{'index': 0, 'codec': '', 'language': 'und', 'title': '', 'channels': 0}]
        for t in video_tracks:
            tracks.append({
                'path': video_path,
                'basename': video_basename,
                'dir': video_dir,
                'size': video_size,
                'track_index': t['index'],
                'track_language': t['language'],
                'track_title': t['title'],
                'track_codec': t['codec'],
            })

    create_subtitle_task(task_id, name, scan_path, tracks)
    add_log('INFO', 'subtitle', f'创建字幕任务: {name} ({len(valid_files)} 个文件, {len(tracks)} 条音轨)')

    # 标记扫描结果中的视频为已提取
    for f in valid_files:
        p = f.get('path') or f.get('video_path') or ''
        update_subtitle_scan_result_extracted(p, True)

    stop_event = threading.Event()
    _stop_events[task_id] = stop_event

    def _run_audio():
        from javsp.webapp.database import (
            get_pending_subtitle_items, update_subtitle_item,
            update_subtitle_task_progress, update_subtitle_task_status,
            update_subtitle_scan_result_exists,
            add_log as _add_log
        )
        from concurrent.futures import ThreadPoolExecutor, as_completed

        try:
            config = _get_subtitle_config()
            concurrency = max(1, int(config.get('audio_concurrency', 2)))

            def _process_one(item: dict):
                if stop_event.is_set():
                    return None

                # 运行前再次检查源视频是否存在
                if not os.path.exists(item['video_path']):
                    update_subtitle_item(item['id'],
                        audio_status='error', errors='源视频文件已丢失',
                        audio_finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                    update_subtitle_scan_result_exists(item['video_path'], False)
                    update_subtitle_task_progress(task_id)
                    if socketio:
                        socketio.emit('subtitle_progress', {
                            'task_id': task_id, 'phase': 'audio',
                            'item_id': item['id'], 'basename': item['video_basename'],
                            'status': 'error',
                        }, namespace='/')
                    return item['id']

                update_subtitle_item(item['id'], audio_status='processing', audio_started_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                if socketio:
                    socketio.emit('subtitle_progress', {
                        'task_id': task_id, 'phase': 'audio',
                        'item_id': item['id'], 'basename': item['video_basename'],
                        'status': 'processing',
                    }, namespace='/')

                audio_path = _get_audio_path(item, config)
                result = extract_audio(item['video_path'], audio_path, track_index=item.get('track_index', 0))

                if result['ok']:
                    update_subtitle_item(item['id'],
                        audio_status='done', audio_path=result['audio_path'],
                        audio_duration=result['duration'],
                        audio_finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                else:
                    update_subtitle_item(item['id'],
                        audio_status='error', errors=result['errors'],
                        audio_finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                    if result['errors'] == '源视频文件已丢失':
                        update_subtitle_scan_result_exists(item['video_path'], False)

                update_subtitle_task_progress(task_id)

                if socketio:
                    socketio.emit('subtitle_progress', {
                        'task_id': task_id, 'phase': 'audio',
                        'item_id': item['id'], 'basename': item['video_basename'],
                        'status': 'done' if result['ok'] else 'error',
                    }, namespace='/')
                return item['id']

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                pending_items = get_pending_subtitle_items(task_id, 'audio')
                futures = {executor.submit(_process_one, item): item for item in pending_items}
                for future in as_completed(futures):
                    if stop_event.is_set():
                        break
                    try:
                        future.result()
                    except Exception:
                        logger.exception("音频提取单项异常")

            # 完成
            if stop_event.is_set():
                update_subtitle_task_status(task_id, 'stopped')
                _add_log('INFO', 'subtitle', f'字幕任务已停止: {task_id[:8]}')
            else:
                update_subtitle_task_status(task_id, 'audio_done')
                _add_log('INFO', 'subtitle', f'音频提取完成: {task_id[:8]}')

            if socketio:
                socketio.emit('subtitle_progress', {
                    'task_id': task_id, 'phase': 'audio',
                    'status': 'completed' if not stop_event.is_set() else 'stopped',
                }, namespace='/')

        except Exception as e:
            logger.exception("字幕音频提取异常")
            update_subtitle_task_status(task_id, 'failed')
            if socketio:
                socketio.emit('subtitle_progress', {
                    'task_id': task_id, 'phase': 'audio', 'status': 'failed', 'message': str(e),
                }, namespace='/')
        finally:
            clear_subtitle_stop(task_id)

    thread = threading.Thread(target=_run_audio, daemon=True)
    thread.start()
    return {'task_id': task_id, 'total': len(files)}


def start_subtitle_generate(task_id: str, socketio=None) -> dict:
    """启动字幕生成（第二步：音频 → 字幕）"""
    from javsp.webapp.database import (
        get_subtitle_task, get_pending_subtitle_items, update_subtitle_item,
        update_subtitle_task_progress, update_subtitle_task_status, add_log
    )

    task = get_subtitle_task(task_id)
    if not task:
        return {'error': '任务不存在'}

    stop_event = threading.Event()
    _stop_events[task_id] = stop_event

    def _run_subtitle():
        from concurrent.futures import ThreadPoolExecutor, as_completed
        try:
            config = _get_subtitle_config()
            model = config.get('whisper_model', 'mlx-community/whisper-large-v3-turbo')
            language = config.get('whisper_language', 'ja')
            fmt = config.get('subtitle_format', 'srt')
            segment_duration = config.get('segment_duration', 30)
            concurrency = max(1, int(config.get('subtitle_concurrency', 1)))
            subtitle_mode = config.get('subtitle_mode', 'original')

            def _process_one(item: dict):
                if stop_event.is_set():
                    return None

                update_subtitle_item(item['id'],
                    subtitle_status='processing', subtitle_format=fmt,
                    whisper_model=model, whisper_language=language,
                    subtitle_started_at=time.strftime('%Y-%m-%d %H:%M:%S'))

                if socketio:
                    socketio.emit('subtitle_progress', {
                        'task_id': task_id, 'phase': 'subtitle',
                        'item_id': item['id'], 'basename': item['video_basename'],
                        'status': 'processing',
                    }, namespace='/')

                subtitle_path = _get_subtitle_path(item, fmt)
                result = generate_subtitle(
                    item['audio_path'], subtitle_path,
                    model=model, language=language, fmt=fmt,
                    segment_duration=segment_duration,
                    subtitle_mode=subtitle_mode,
                    video_path=item['video_path'],
                    track_index=item.get('track_index', 0)
                )

                if result['ok']:
                    update_subtitle_item(item['id'],
                        subtitle_status='done', subtitle_path=result['subtitle_path'],
                        subtitle_finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                else:
                    update_subtitle_item(item['id'],
                        subtitle_status='error', errors=result['errors'],
                        subtitle_finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))

                update_subtitle_task_progress(task_id)

                if socketio:
                    socketio.emit('subtitle_progress', {
                        'task_id': task_id, 'phase': 'subtitle',
                        'item_id': item['id'], 'basename': item['video_basename'],
                        'status': 'done' if result['ok'] else 'error',
                    }, namespace='/')
                return item['id']

            pending_items = get_pending_subtitle_items(task_id, 'subtitle')
            for item in pending_items:
                if stop_event.is_set():
                    break
                try:
                    _process_one(item)
                except Exception:
                    logger.exception("字幕生成单项异常")

            # 完成
            if stop_event.is_set():
                update_subtitle_task_status(task_id, 'stopped')
                add_log('INFO', 'subtitle', f'字幕生成已停止: {task_id[:8]}')
            else:
                update_subtitle_task_status(task_id, 'completed')
                add_log('INFO', 'subtitle', f'字幕生成完成: {task_id[:8]}')

                # 如果配置了生成后删除音轨
                delete_audio = config.get('delete_audio_after', False)
                if delete_audio:
                    _cleanup_audio_files(task_id)

            if socketio:
                socketio.emit('subtitle_progress', {
                    'task_id': task_id, 'phase': 'subtitle',
                    'status': 'completed' if not stop_event.is_set() else 'stopped',
                }, namespace='/')

        except Exception as e:
            logger.exception("字幕生成异常")
            update_subtitle_task_status(task_id, 'failed')
            if socketio:
                socketio.emit('subtitle_progress', {
                    'task_id': task_id, 'phase': 'subtitle', 'status': 'failed', 'message': str(e),
                }, namespace='/')
        finally:
            clear_subtitle_stop(task_id)

    thread = threading.Thread(target=_run_subtitle, daemon=True)
    thread.start()
    return {'task_id': task_id}


def _cleanup_audio_files(task_id: str):
    """清理任务关联的音轨文件"""
    from javsp.webapp.database import get_subtitle_items
    items = get_subtitle_items(task_id)
    for item in items:
        if item.get('audio_path') and os.path.exists(item['audio_path']):
            try:
                os.remove(item['audio_path'])
                logger.info(f"已删除音轨文件: {item['audio_path']}")
            except Exception as e:
                logger.warning(f"删除音轨文件失败: {e}")


def start_subtitle_generate_for_video(task_id: str, video_path: str, socketio=None) -> dict:
    """仅生成指定视频的字幕（可反复重新生成）"""
    from javsp.webapp.database import (
        get_subtitle_task, get_pending_subtitle_items_by_video,
        update_subtitle_item, update_subtitle_task_progress,
        update_subtitle_task_status, reset_subtitle_status_for_video, add_log
    )

    task = get_subtitle_task(task_id)
    if not task:
        return {'error': '任务不存在'}

    # 如果任务正在运行，禁止启动新的字幕生成线程
    if task['status'] in ('running', 'subtitle_running'):
        return {'error': '任务正在运行中，请等待完成或停止后再操作'}

    # 重置该影片的字幕状态
    reset_count = reset_subtitle_status_for_video(task_id, video_path)
    if reset_count == 0:
        return {'error': '该影片没有可生成字幕的音轨（请确保音频已提取完成）'}

    stop_event = threading.Event()
    _stop_events[task_id] = stop_event

    def _run_subtitle_for_video():
        from concurrent.futures import ThreadPoolExecutor, as_completed
        try:
            config = _get_subtitle_config()
            model = config.get('whisper_model', 'mlx-community/whisper-large-v3-turbo')
            language = config.get('whisper_language', 'ja')
            fmt = config.get('subtitle_format', 'srt')
            segment_duration = config.get('segment_duration', 30)
            concurrency = max(1, int(config.get('subtitle_concurrency', 1)))
            subtitle_mode = config.get('subtitle_mode', 'original')

            update_subtitle_task_status(task_id, 'subtitle_running')

            def _process_one(item: dict):
                if stop_event.is_set():
                    return None

                update_subtitle_item(item['id'],
                    subtitle_status='processing', subtitle_format=fmt,
                    whisper_model=model, whisper_language=language,
                    subtitle_started_at=time.strftime('%Y-%m-%d %H:%M:%S'))

                if socketio:
                    socketio.emit('subtitle_progress', {
                        'task_id': task_id, 'phase': 'subtitle',
                        'item_id': item['id'], 'basename': item['video_basename'],
                        'status': 'processing',
                    }, namespace='/')

                subtitle_path = _get_subtitle_path(item, fmt)
                result = generate_subtitle(
                    item['audio_path'], subtitle_path,
                    model=model, language=language, fmt=fmt,
                    segment_duration=segment_duration,
                    subtitle_mode=subtitle_mode,
                    video_path=item['video_path'],
                    track_index=item.get('track_index', 0)
                )

                if result['ok']:
                    update_subtitle_item(item['id'],
                        subtitle_status='done', subtitle_path=result['subtitle_path'],
                        subtitle_finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
                else:
                    update_subtitle_item(item['id'],
                        subtitle_status='error', errors=result['errors'],
                        subtitle_finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))

                update_subtitle_task_progress(task_id)

                if socketio:
                    socketio.emit('subtitle_progress', {
                        'task_id': task_id, 'phase': 'subtitle',
                        'item_id': item['id'], 'basename': item['video_basename'],
                        'status': 'done' if result['ok'] else 'error',
                    }, namespace='/')
                return item['id']

            pending_items = get_pending_subtitle_items_by_video(task_id, video_path, 'subtitle')
            for item in pending_items:
                if stop_event.is_set():
                    break
                try:
                    _process_one(item)
                except Exception:
                    logger.exception("单影片字幕生成单项异常")

            # 完成
            if stop_event.is_set():
                update_subtitle_task_status(task_id, 'stopped')
                add_log('INFO', 'subtitle', f'字幕生成已停止: {task_id[:8]}')
            else:
                # 检查是否还有未完成的字幕项
                from javsp.webapp.database import get_subtitle_task as _gst
                cur_task = _gst(task_id)
                if cur_task and cur_task['subtitle_completed'] >= cur_task['total']:
                    update_subtitle_task_status(task_id, 'completed')
                    add_log('INFO', 'subtitle', f'字幕生成完成: {task_id[:8]}')
                    delete_audio = config.get('delete_audio_after', False)
                    if delete_audio:
                        _cleanup_audio_files(task_id)
                else:
                    update_subtitle_task_status(task_id, 'audio_done')
                    add_log('INFO', 'subtitle', f'单影片字幕生成完成: {task_id[:8]}')

            if socketio:
                socketio.emit('subtitle_progress', {
                    'task_id': task_id, 'phase': 'subtitle',
                    'status': 'completed' if not stop_event.is_set() else 'stopped',
                }, namespace='/')

        except Exception as e:
            logger.exception("单影片字幕生成异常")
            update_subtitle_task_status(task_id, 'failed')
            if socketio:
                socketio.emit('subtitle_progress', {
                    'task_id': task_id, 'phase': 'subtitle', 'status': 'failed', 'message': str(e),
                }, namespace='/')
        finally:
            clear_subtitle_stop(task_id)

    thread = threading.Thread(target=_run_subtitle_for_video, daemon=True)
    thread.start()
    return {'task_id': task_id, 'video_path': video_path, 'count': reset_count}


def delete_audio_files_for_items(item_ids: list) -> dict:
    """删除指定项的音轨文件"""
    from javsp.webapp.database import get_db
    deleted = []
    failed = []
    with get_db() as conn:
        for item_id in item_ids:
            row = conn.execute("SELECT audio_path FROM subtitle_items WHERE id = ?", (item_id,)).fetchone()
            if row and row['audio_path']:
                path = row['audio_path']
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        conn.execute("UPDATE subtitle_items SET audio_path = NULL, audio_status = 'pending' WHERE id = ?", (item_id,))
                        deleted.append(path)
                    except Exception as e:
                        failed.append({'path': path, 'error': str(e)})
                else:
                    conn.execute("UPDATE subtitle_items SET audio_path = NULL, audio_status = 'pending' WHERE id = ?", (item_id,))
                    deleted.append(path)
    return {'deleted': deleted, 'failed': failed}


# ==================== 字幕搜索 ====================

def search_subtitle_for_video(video_path: str) -> dict:
    """搜索单个视频的字幕（优先迅雷，然后射手网）"""
    from javsp.webapp.subtitle_search import search_subtitle, search_xunlei_subtitle, search_shooter_subtitle
    from javsp.webapp.database import update_subtitle_search_status
    
    if not os.path.exists(video_path):
        return {'ok': False, 'errors': '视频文件不存在'}
    
    try:
        update_subtitle_search_status(video_path, 'searching')
        
        xunlei_results = search_xunlei_subtitle(video_path)
        shooter_results = []
        
        if not xunlei_results:
            shooter_results = search_shooter_subtitle(video_path)
        
        all_results = []
        seen_ids = set()
        
        for r in xunlei_results:
            if r['id'] not in seen_ids:
                seen_ids.add(r['id'])
                all_results.append(r)
        
        for r in shooter_results:
            if r['id'] not in seen_ids:
                seen_ids.add(r['id'])
                all_results.append(r)
        
        status = 'found' if all_results else 'not_found'
        update_subtitle_search_status(video_path, status, all_results)
        
        logger.info(f"字幕搜索完成: {video_path} -> {len(all_results)} 条结果")
        return {'ok': True, 'results': all_results, 'count': len(all_results)}
    
    except Exception as e:
        logger.error(f"字幕搜索异常: {video_path} - {e}")
        update_subtitle_search_status(video_path, 'error')
        return {'ok': False, 'errors': str(e)}


def batch_search_subtitles(files: list) -> dict:
    """批量搜索字幕"""
    success_count = 0
    fail_count = 0
    total_count = 0
    
    for f in files:
        video_path = f.get('path') or f.get('video_path') or ''
        if not video_path or not os.path.exists(video_path):
            continue
        
        total_count += 1
        result = search_subtitle_for_video(video_path)
        if result['ok']:
            success_count += 1
        else:
            fail_count += 1
    
    return {'ok': True, 'total': total_count, 'success': success_count, 'failed': fail_count}


def download_selected_subtitle(video_path: str, video_dir: str, video_basename: str, subtitle_result: dict) -> dict:
    """下载选中的字幕文件，保持与大模型生成一致的命名规则"""
    from javsp.webapp.subtitle_search import download_subtitle
    
    if not os.path.exists(video_path):
        return {'ok': False, 'errors': '视频文件不存在'}
    
    try:
        stem = Path(video_basename).stem
        fmt = 'srt'
        save_path = os.path.join(video_dir, f"{stem}.{fmt}")
        
        result = download_subtitle(subtitle_result['url'], save_path)
        
        if result['ok']:
            logger.info(f"字幕下载成功: {video_basename} -> {result['path']}")
            return {
                'ok': True,
                'subtitle_path': result['path'],
                'source': subtitle_result['source'],
                'language': subtitle_result['language'],
            }
        else:
            return {'ok': False, 'errors': result['errors']}
    
    except Exception as e:
        logger.error(f"下载字幕异常: {video_path} - {e}")
        return {'ok': False, 'errors': str(e)}


def batch_delete_audio(files: list) -> dict:
    """批量删除音轨文件"""
    deleted = 0
    skipped = 0
    failed = 0
    
    for f in files:
        audio_path = f.get('local_audio_path') or f.get('audio_path')
        if not audio_path:
            skipped += 1
            continue
        
        if not os.path.exists(audio_path):
            skipped += 1
            continue
        
        try:
            os.remove(audio_path)
            deleted += 1
            logger.info(f"音轨文件已删除: {audio_path}")
        except Exception as e:
            failed += 1
            logger.error(f"删除音轨文件失败: {audio_path} - {e}")
    
    return {'ok': True, 'deleted': deleted, 'skipped': skipped, 'failed': failed}


def batch_delete_subtitle(files: list) -> dict:
    """批量删除字幕文件"""
    deleted = 0
    skipped = 0
    failed = 0
    
    for f in files:
        subtitle_path = f.get('local_subtitle_path')
        if not subtitle_path:
            skipped += 1
            continue
        
        if not os.path.exists(subtitle_path):
            skipped += 1
            continue
        
        try:
            os.remove(subtitle_path)
            deleted += 1
            logger.info(f"字幕文件已删除: {subtitle_path}")
        except Exception as e:
            failed += 1
            logger.error(f"删除字幕文件失败: {subtitle_path} - {e}")
    
    return {'ok': True, 'deleted': deleted, 'skipped': skipped, 'failed': failed}
