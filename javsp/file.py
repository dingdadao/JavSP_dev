"""与文件相关的各类功能"""
import os
from pathlib import Path
import re
import ctypes
import logging
import itertools
import json
from sys import platform
from typing import List


__all__ = ['scan_movies', 'get_fmt_size', 'get_remaining_path_len',
           'replace_illegal_chars', 'get_failed_when_scan', 'find_subtitle_in_dir']


from javsp.avid import *
from javsp.lib import re_escape
from javsp.config import Cfg
from javsp.datatype import Movie

logger = logging.getLogger(__name__)
failed_items = []

# 记录需要跳过的文件
skipped_files_record = '.skipped'
skipped_files = set()


def scan_movies(root: str) -> List[Movie]:
    """获取文件夹内的所有影片的列表（自动探测同一文件夹内的分片）"""
    # 由于实现的限制:
    # 1. 以数字编号最多支持10个分片，字母编号最多支持26个分片
    # 2. 允许分片间的编号有公共的前导符（如编号01, 02, 03），因为求prefix时前导符也会算进去

    # 加载需要跳过的文件记录
    load_skipped_files(root)

    # 声明使用全局变量
    global skipped_files

    # 扫描所有影片文件并获取它们的番号
    dic = {}    # avid: [abspath1, abspath2...]
    small_videos = {}
    skipped_processed_files = []  # 记录被跳过的已处理文件
    ignore_folder_name_pattern = re.compile(
        '|'.join(Cfg().scanner.ignored_folder_name_pattern))
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames.copy():
            if ignore_folder_name_pattern.match(name):
                dirnames.remove(name)
            # 移除有nfo的文件夹
            if Cfg().scanner.skip_nfo_dir:
                if any(file.lower().endswith(".nfo") for file in os.listdir(os.path.join(dirpath, name)) if isinstance(file, str)):
                    print(f"skip file {name}")
                    dirnames.remove(name)

        for file in filenames:
            ext = os.path.splitext(file)[1].lower()
            if ext in Cfg().scanner.filename_extensions:
                fullpath = os.path.join(dirpath, file)

                # 检查是否在跳过记录中
                if fullpath in skipped_files:
                    skipped_processed_files.append(fullpath)
                    logger.debug(f"跳过已跳过的文件: {fullpath}")
                    continue

                # 忽略小于指定大小的文件
                filesize = os.path.getsize(fullpath)
                if filesize < Cfg().scanner.minimum_size:
                    small_videos.setdefault(file, []).append(fullpath)
                    continue
                dvdid = get_id(fullpath)
                cid = get_cid(fullpath)
                # 如果文件名能匹配到cid，那么将cid视为有效id，因为此时dvdid多半是错的
                avid = cid if cid else dvdid
                if avid:
                    if avid in dic:
                        dic[avid].append(fullpath)
                    else:
                        dic[avid] = [fullpath]
                else:
                    fail = Movie('无法识别番号')
                    fail.files = [fullpath]
                    failed_items.append(fail)
                    logger.error(f"无法提取影片番号: '{fullpath}'")
    # 多分片影片容易有文件大小低于阈值的子片，进行特殊处理
    has_avid = {}
    for name in list(small_videos.keys()):
        dvdid = get_id(name)
        cid = get_cid(name)
        avid = cid if cid else dvdid
        if avid in dic:
            dic[avid].extend(small_videos.pop(name))
        elif avid:
            has_avid[name] = avid
    # 对于前面忽略的视频生成一个简单的提示
    small_videos = {k: sorted(v) for k, v in sorted(small_videos.items())}
    small_size_skipped_files = list(itertools.chain(*small_videos.values()))
    skipped_cnt = len(small_size_skipped_files)
    if skipped_cnt > 0:
        if len(has_avid) > 0:
            logger.info(
                f"跳过了 {', '.join(has_avid)} 等{skipped_cnt}个小于指定大小的视频文件")
        else:
            logger.info(f"跳过了{skipped_cnt}个小于指定大小的视频文件")
        logger.debug('跳过的视频文件如下:\n' + '\n'.join(small_size_skipped_files))
    # 检查是否有多部影片对应同一个番号
    non_slice_dup = {}  # avid: [abspath1, abspath2...]
    for avid, files in dic.copy().items():
        # 一一对应的直接略过
        if len(files) == 1:
            continue
        
        # 提取分片信息（允许不同目录的文件）
        basenames = [os.path.basename(i) for i in files]
        
        # 尝试从文件名中提取番号部分，构建更准确的前缀
        # 策略：找到所有文件名中都包含的、以番号开头的最长公共子串
        # 先尝试用 avid 作为锚点
        avid_clean = avid.replace('-', '').replace('_', '')
        
        # 找到每个文件名中 avid 出现的位置，然后提取公共前缀
        def extract_prefix_from_avid(basename, avid_id):
            """从文件名中提取以番号为起点的部分"""
            basename_upper = basename.upper()
            avid_upper = avid_id.upper()
            # 尝试匹配番号（忽略大小写和分隔符）
            for i in range(len(basename_upper)):
                if basename_upper[i:].replace('-', '').replace('_', '').startswith(avid_upper.replace('-', '').replace('_', '')):
                    return basename[i:]
            return basename
        
        # 提取以番号为起点的文件名部分
        avid_parts = [extract_prefix_from_avid(b, avid) for b in basenames]
        prefix = os.path.commonprefix(avid_parts)
        
        # 如果前缀太短（小于3个字符），尝试其他策略
        if len(prefix) < 3:
            # 使用原始方法
            prefix = os.path.commonprefix(basenames)
        
        # 尝试提取分片信息，支持两种模式：
        # 1. 所有文件都有分片标记（如 A/B/C/D）
        # 2. 部分文件没有分片标记（作为主文件/第1部分）
        try:
            # 使用 .*? 允许前缀出现在文件名的任意位置
            # 使用 [-_\s]* 允许分片标记前有分隔符（如 -, _, 空格）
            # 注意：[-_\s]* 在末尾是贪婪的，会尽可能消耗分隔符
            pattern_expr = r'.*?' + re_escape(prefix) + r'[-_\s]*([a-z\d])'
            pattern = re.compile(pattern_expr, flags=re.I)
        except re.error:
            logger.debug(f"正则识别影片分片信息时出错: '{pattern_expr}'")
            non_slice_dup[avid] = files
            del dic[avid]
            continue
        
        # 对于没有分片标记的文件，正则不会匹配，需要特殊处理
        slices = []
        extensions = []
        for bn in basenames:
            match = pattern.match(bn)
            if match:
                slice_char = match.group(1).lower()
                slices.append(slice_char)
                # 提取扩展名
                _, ext = os.path.splitext(bn)
                extensions.append(ext.lower())
            else:
                # 没有分片标记，尝试直接提取扩展名
                _, ext = os.path.splitext(bn)
                slices.append('')
                extensions.append(ext.lower())
        
        # 检查扩展名是否一致（允许不同扩展名，但需要记录）
        unique_extensions = set(extensions)
        if len(unique_extensions) > 1:
            logger.debug(f"分片文件扩展名不一致: {unique_extensions}")
            # 不直接报错，继续处理
        
        # 处理分片信息
        # 空字符串表示没有分片标记，应作为第1部分
        normalized_slices = []
        unmarked_count = slices.count('')
        
        if unmarked_count > 1:
            # 有多个未标记的文件，这是错误的
            logger.debug(f"有多个未标记分片的文件: {slices=}")
            non_slice_dup[avid] = files
            del dic[avid]
            continue
        
        for s in slices:
            if s == '':
                normalized_slices.append('a')  # 无标记的作为第1部分
            elif s.isdigit():
                # 数字编号：1->a, 2->b, 3->c...
                # 如果有未标记的文件，数字1应该映射到 'b'
                if unmarked_count == 1:
                    normalized_slices.append(chr(ord('a') + int(s)))
                else:
                    normalized_slices.append(chr(ord('a') + int(s) - 1))
            else:
                # 字母编号：a->a, b->b, c->c...
                # 如果有未标记的文件，字母a应该映射到 'b'
                if unmarked_count == 1:
                    normalized_slices.append(chr(ord(s) + 1))
                else:
                    normalized_slices.append(s)
        
        # 检查编号是否连续且从a开始
        sorted_slices = sorted(normalized_slices)
        first, last = sorted_slices[0], sorted_slices[-1]
        if first != 'a' or (ord(last) != ord('a') + len(sorted_slices) - 1):
            logger.debug(f"无效的分片起始编号或分片编号不连续: {sorted_slices=}")
            non_slice_dup[avid] = files
            del dic[avid]
            continue
        
        # 生成最终的分片信息
        mapped_files = [files[normalized_slices.index(i)] for i in sorted_slices]
        dic[avid] = mapped_files
        logger.debug(f"识别到分片影片 {avid}: {len(mapped_files)} 个分片")
        for i, f in enumerate(mapped_files):
            logger.debug(f"  分片 {chr(ord('A') + i)}: {os.path.basename(f)}")

    # 处理重复文件（相同分片标记的文件）
    if non_slice_dup:
        duplicate_policy = Cfg().summarizer.duplicate_file
        strategy = duplicate_policy.strategy
        size_threshold = duplicate_policy.size_threshold
        
        resolved = {}
        still_unresolved = {}
        
        for avid, files in non_slice_dup.items():
            # 获取文件大小
            file_sizes = [(f, os.path.getsize(f)) for f in files]
            
            # 优先选择带 -C 的文件（带字幕）
            def has_subtitle_marker(filepath):
                """检查文件名是否带 -C 标记（带字幕）"""
                basename = os.path.basename(filepath).upper()
                # 匹配 -C. 或 -C/ 或 -C结尾
                return bool(re.search(r'-C[./\\]?$|-C$', basename))
            
            # 先按是否带字幕排序，再按大小排序
            file_sizes.sort(key=lambda x: (
                0 if has_subtitle_marker(x[0]) else 1,  # 带字幕的优先
                -x[1]  # 大小降序
            ))
            
            best_file = file_sizes[0]
            second_best = file_sizes[1] if len(file_sizes) > 1 else None
            
            # 检查大小差异
            if second_best and (best_file[1] - second_best[1]) > size_threshold:
                # 大小差异明显，自动选择
                if strategy == 'auto_select':
                    resolved[avid] = [best_file[0]]
                    subtitle_mark = "（带字幕）" if has_subtitle_marker(best_file[0]) else ""
                    logger.info(f"自动选择文件 {avid}: {os.path.basename(best_file[0])} ({get_fmt_size(best_file[1])}){subtitle_mark}")
                    continue
            
            # 需要手动选择或跳过
            if strategy == 'skip':
                still_unresolved[avid] = files
            elif strategy == 'manual':
                # 显示选项
                print(f"\n发现重复文件 {avid}:")
                for idx, (f, size) in enumerate(file_sizes, 1):
                    subtitle_mark = " [带字幕]" if has_subtitle_marker(f) else ""
                    print(f"  {idx}. {os.path.relpath(f, root)} ({get_fmt_size(size)}){subtitle_mark}")
                
                # 提示用户选择
                if Cfg().other.interactive:
                    choice = input("请选择要使用的文件编号（输入数字，多个文件用逗号分隔）[1]: ").strip() or "1"
                else:
                    logger.info(f"非交互模式，自动选择: {os.path.basename(best_file[0])}")
                    choice = "1"
                
                try:
                    choices = [int(c.strip()) for c in choice.split(',')]
                    selected = [file_sizes[c - 1][0] for c in choices if 1 <= c <= len(file_sizes)]
                    if selected:
                        resolved[avid] = selected
                    else:
                        still_unresolved[avid] = files
                except (ValueError, IndexError):
                    still_unresolved[avid] = files
            else:
                # auto_select 但大小差异不明显，跳过
                still_unresolved[avid] = files
                # 记录到跳过文件
                for f in files:
                    add_skipped_file(f, root)
        
        # 更新 dic 和 non_slice_dup
        dic.update(resolved)
        non_slice_dup = still_unresolved

    # 汇总输出错误提示信息
    msg = ''
    for avid, files in non_slice_dup.items():
        msg += f'{avid}: \n'
        for f in files:
            msg += ('  ' + os.path.relpath(f, root) + '\n')
    if msg:
        logger.error("下列番号对应多部影片文件且不符合分片规则，已略过整理，请手动处理后重新运行脚本: \n" + msg)
    # 输出跳过的已处理文件信息
    if skipped_processed_files:
        logger.info(f"跳过了 {len(skipped_processed_files)} 个已处理的文件:")
        for filepath in skipped_processed_files:
            logger.info(f"  - {os.path.relpath(filepath, root)}")

    # 转换数据的组织格式
    movies: List[Movie] = []
    for avid, files in dic.items():
        src = guess_av_type(avid)
        if src != 'cid':
            mov = Movie(avid)
        else:
            mov = Movie(cid=avid)
            # 即使初步识别为cid，也存储dvdid以供误识别时退回到dvdid模式进行抓取
            mov.dvdid = get_id(files[0])
        mov.files = files
        mov.data_src = src
        logger.debug(f'影片数据源类型: {avid}: {src}')
        movies.append(mov)
    return movies


def get_failed_when_scan():
    """获取扫描影片过程中无法自动识别番号的条目"""
    return failed_items


_PARDIR_REPLACE = re.compile(r'\.{2,}')


def replace_illegal_chars(name):
    """将不能用于文件名的字符替换为形近的字符"""
    # 非法字符列表 https://stackoverflow.com/a/31976060/6415337
    if platform == 'win32':
        # http://www.unicode.org/Public/security/latest/confusables.txt
        charmap = {'<': '❮',
                   '>': '❯',
                   ':': '：',
                   '"': '″',
                   '/': '／',
                   '\\': '＼',
                   '|': '｜',
                   '?': '？',
                   '*': '꘎'}
        for c, rep in charmap.items():
            name = name.replace(c, rep)
    elif platform == "darwin":  # MAC OS X
        name = name.replace(':', '：')
    else:   # 其余都当做Linux处理
        name = name.replace('/', '／')
    # 处理连续多个英文句点.
    if os.pardir in name:
        name = _PARDIR_REPLACE.sub('…', name)
    return name


def load_skipped_files(root: str):
    """加载需要跳过的文件记录"""
    global skipped_files
    record_path = os.path.join(root, skipped_files_record)
    
    # 如果配置了清理跳过记录，则删除 .skipped 文件
    if Cfg().scanner.clear_skipped_on_rescan and os.path.exists(record_path):
        try:
            os.remove(record_path)
            logger.info("已清理跳过文件记录")
            skipped_files = set()
            return
        except Exception as e:
            logger.warning(f"清理跳过文件记录失败: {e}")
    
    if os.path.exists(record_path):
        try:
            with open(record_path, 'r', encoding='utf-8') as f:
                # 读取每行作为一个文件路径
                lines = [line.strip()
                         for line in f.readlines() if line.strip()]
                skipped_files = set(lines)
                logger.info(f"已加载 {len(skipped_files)} 个需要跳过的文件")
        except Exception as e:
            logger.warning(f"加载跳过文件记录失败: {e}")
            skipped_files = set()
    else:
        skipped_files = set()
        logger.info("未找到跳过文件记录")
    # 确保skipped_files始终是set类型
    if not isinstance(skipped_files, set):
        skipped_files = set()


def add_skipped_file(filepath: str, root: str):
    """添加一个需要跳过的文件到记录"""
    global skipped_files
    # 确保skipped_files是set类型
    if not isinstance(skipped_files, set):
        skipped_files = set(skipped_files) if skipped_files else set()
    # 检查文件是否已经记录过，避免重复写入
    if filepath not in skipped_files:
        skipped_files.add(filepath)
        record_path = os.path.join(root, skipped_files_record)
        try:
            with open(record_path, 'a', encoding='utf-8') as f:
                f.write(filepath + '\n')
        except Exception as e:
            logger.error(f"添加跳过文件记录失败: {e}")


def is_remote_drive(path: str):
    """判断一个路径是否为远程映射到本地"""
    # TODO: 当前仅支持Windows平台
    if platform != 'win32':
        return False
    DRIVE_REMOTE = 0x4
    drive = os.path.splitdrive(os.path.abspath(path))[0] + os.sep
    result = ctypes.windll.kernel32.GetDriveTypeW(drive)
    return result == DRIVE_REMOTE


def get_remaining_path_len(path):
    """计算当前系统支持的最大路径长度与给定路径长度的差值"""
    # TODO: 支持不同的操作系统
    fullpath = os.path.abspath(path)
    # Windows: If the length exceeds ~256 characters, you will be able to see the path/files via Windows/File Explorer, but may not be able to delete/move/rename these paths/files
    length = len(fullpath.encode('utf-8')
                 ) if Cfg().summarizer.path.length_by_byte else len(fullpath)
    remaining = Cfg().summarizer.path.length_maximum - length
    return remaining


def get_fmt_size(file_or_size) -> str:
    """获取格式化后的文件大小

    Args:
        file_or_size (str or int): 文件路径或者文件大小

    Returns:
        str: e.g. 20.21 MiB
    """
    if isinstance(file_or_size, (int, float)):
        size = file_or_size
    else:
        size = os.path.getsize(file_or_size)
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti']:
        # 1023.995: to avoid rounding bug when format str, e.g. 1048571 -> 1024.0 KiB
        if abs(size) < 1023.995:
            return f"{size:3.2f} {unit}B"
        size /= 1024.0


_sub_files = {}
SUB_EXTENSIONS = ('.srt', '.ass')


def find_subtitle_in_dir(folder: str, dvdid: str):
    """在folder内寻找是否有匹配dvdid的字幕"""
    folder_data = _sub_files.get(folder)
    if folder_data is None:
        # 此文件夹从未检查过时
        folder_data = {}
        for dirpath, dirnames, filenames in os.walk(folder):
            for file in filenames:
                basename, ext = os.path.splitext(file)
                if ext in SUB_EXTENSIONS:
                    match_id = get_id(basename)
                    if match_id:
                        folder_data[match_id.upper()] = os.path.join(
                            dirpath, file)
        _sub_files[folder] = folder_data
    sub_file = folder_data.get(dvdid.upper())
    return sub_file


if __name__ == "__main__":
    p = "C:/Windows\\System32//PerceptionSimulation\\..\\Assets\\/ClosedHand.png"
    print(get_remaining_path_len(p))
