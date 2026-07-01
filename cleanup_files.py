#!/usr/bin/env python3
import os
import glob

root = "/Volumes/data/goodStuff/download"

# 小文件（广告/预告片）
small_patterns = [
    "jul-953-C/uur76.mp4",
    "jur-682/苍 老 师 强 力 推 荐.mp4",
    "MIDA-458-C/社 區 最 新 情 報.mp4",
    "MIDA-458-C/台 妹 子 線 上 現 場 直 播 各 式 花 式 表 演.mp4",
]

# 重复文件（删除路径不规范的）- 使用 glob 模式
duplicate_patterns = [
    "白石茉莉奈/想让妻子承认爱，把妻子和绝伦的后辈两个人独处3个小时……/*",
    "竹内有紀/*一周3天，和妻子SEX正在做*",
    "一乃あおい/*一周3天，和妻子SEX正在做*",
    "橘メアリー/请把爱的妻子犯到最深处。/*",
    "市来まひろ/*一周3天，和妻子SEX正在做*",
    "市来まひろ/想让妻子承认爱，把妻子和绝伦的后辈两个人独处3个小时……/*",
]

# 收集要删除的文件
files_to_delete = []

# 添加小文件
for pattern in small_patterns:
    path = os.path.join(root, pattern)
    if os.path.exists(path):
        files_to_delete.append(path)

# 添加重复文件（使用 glob）
for pattern in duplicate_patterns:
    matched = glob.glob(os.path.join(root, pattern))
    for f in matched:
        # 只删除 mp4 文件
        if f.endswith('.mp4'):
            files_to_delete.append(f)

# 去重
files_to_delete = list(set(files_to_delete))

print(f"找到 {len(files_to_delete)} 个文件要删除\n")

deleted = 0
not_found = 0
failed = 0

for f in files_to_delete:
    if os.path.exists(f):
        try:
            os.remove(f)
            print(f"✓ 已删除: {os.path.basename(f)[:60]}...")
            deleted += 1
        except Exception as e:
            print(f"✗ 删除失败: {os.path.basename(f)[:60]}... - {e}")
            failed += 1
    else:
        print(f"- 文件不存在: {os.path.basename(f)[:60]}...")
        not_found += 1

print(f"\n统计: 成功 {deleted}, 不存在 {not_found}, 失败 {failed}")

# 清空 .skipped 文件
skipped_path = os.path.join(root, ".skipped")
try:
    with open(skipped_path, 'w', encoding='utf-8') as f:
        f.write('')
    print(f"\n✓ 已清空 .skipped 文件")
except Exception as e:
    print(f"\n✗ 清空 .skipped 文件失败: {e}")