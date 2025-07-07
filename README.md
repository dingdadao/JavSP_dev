

# Jav Scraper Package - Forked Version of JavSP

**汇总多站点数据的 AV 元数据刮削器**

JavSP 是一个强大的工具，用于提取影片文件名中的番号信息，自动抓取并汇总多个站点数据的 AV 元数据。它会根据指定的规则分类整理影片文件，并为 Emby、Jellyfin、Kodi 等软件生成对应的元数据文件。

## 功能特点

JavSP 提供了以下功能，有些已实现，有些正在开发中，欢迎提出新的功能需求：

* [x] 自动识别影片番号
* [x] 支持处理影片分片
* [x] 汇总多个站点的数据并生成 NFO 数据文件
* [x] 每天自动对站点抓取器进行测试
* [x] 支持多线程并行抓取
* [x] 下载高清封面
* [x] 基于 AI 人体分析裁剪非常规封面
* [x] 自动检查和更新新版本
* [x] 翻译标题和剧情简介
* [ ] 匹配本地字幕
* [ ] 使用小缩略图创建文件夹封面
* [ ] 保持不同站点之间的 genre 分类统一
* [ ] 不同的运行模式（抓取数据+整理，仅抓取数据）
* [ ] 可选：所有站点抓取失败时由人工介入

## 安装并运行

### 从源代码运行

请确保您已经安装了 Poetry 构建系统：

```bash
pipx install poetry
poetry self add poetry-dynamic-versioning
```

然后，克隆此项目：

```bash
git clone https://github.com/dingdadao/JavSP_dev.git
cd JavSP
```

使用 Poetry 构建并运行：

```bash
poetry install
poetry run javsp
```

## 使用

JavSP 开箱即用。如果您希望自定义配置，可以修改 `config.yml` 文件，按需调整配置项。

此外，JavSP 也支持从命令行指定运行参数（命令行参数优先于配置文件）。使用以下命令查看支持的参数列表：

```bash
JavSP -h
```

### 命名规则

在 `config.yml` 配置文件中的 `NamingRule` 下：

* **`save_dir`**：存放影片、封面和 NFO 数据文件等的文件夹路径。
* **`filename`**：影片、封面和 NFO 数据文件等的文件名。

这两个字段支持使用变量，举例如下：

```yaml
[NamingRule]
save_dir = $actress/[$num] $title
filename = $num
```

### 支持的变量

| 变量           | 含义    | 默认值                  | 备注                             |
| ------------ | ----- | -------------------- | ------------------------------ |
| `$num`       | 影片番号  |                      | 优先使用 DVD ID，当工作在 cid 模式下则为 cid |
| `$title`     | 影片标题  | `null_for_title`     |                                |
| `$rawtitle`  | 原始标题  | `$title`             | 无论是否启用翻译功能，始终为翻译前的原始标题         |
| `$actress`   | 女优    | `null_for_actress`   | 多个女优用逗号分隔                      |
| `$censor`    | 有码/无码 |                      | 有三种状态：已知有码/已知无码/不确定            |
| `$score`     | 影片评分  | 0                    | 10分制，例如：7.81                   |
| `$serial`    | 系列    | `null_for_serial`    |                                |
| `$label`     | 番号系列  | ---                  | 将番号拆分后得到的系列                    |
| `$director`  | 导演    | `null_for_director`  |                                |
| `$producer`  | 制作商   | `null_for_producer`  |                                |
| `$publisher` | 发行商   | `null_for_publisher` |                                |
| `$date`      | 发行日期  | `0000-00-00`         | 例如：2020-05-20                  |
| `$year`      | 发行年份  | `0000`               |                                |

### 示例配置

如果你希望将有码和无码影片整理到不同文件夹：

```yaml
save_dir = $censor/$actress/[$num]
```

### 注意事项

* 如果在使用 `nfo` 文件时，不建议在命名规则中添加 `$title`（标题），因为它可能会影响媒体管理软件的兼容性，尤其是 Linux 文件系统对长路径的支持有限。
* 对于仅在 Windows 上使用时，添加标题字段 `$title` 可能更加方便。

---

### 项目许可

本项目遵循 [GPL-3.0 License](https://opensource.org/licenses/GPL-3.0) 和 [Anti 996 License](https://github.com/996icu/996.ICU/blob/master/LICENSE_CN) 共同许可。

### 使用条款

* 本软件仅供学习 Python 和技术交流使用。
* 请勿在微博、微信等墙内社交平台上宣传此项目。
* 使用本软件时，请遵守当地法律法规。
* 禁止将本软件用于商业用途。

---

### Star 贡献



---

**优化迭代：**

1. **简化命名规则描述：** 我对命名规则和变量支持部分进行了简化，去掉了一些多余的内容，使其更加易读。
2. **清晰的安装和使用流程：** 将安装和运行的步骤更加清晰地描述，帮助用户顺利启动项目。
3. **添加许可和使用条款：** 明确项目的许可协议及使用条款，增加法律合规性。

---


