# Jav Manager

**AV 元数据刮削器 & Web 管理界面**

本项目 fork 自 [Yuukiy/JavSP](https://github.com/Yuukiy/JavSP)，在其原有命令行刮削器基础上进行二次开发，新增了 Web 管理界面、文件监控、命名检查、媒体库管理等功能。保留并扩展了自动识别番号、多站点数据汇总、NFO 生成、封面下载、翻译等核心能力。

自动识别影片番号、抓取并汇总多个站点的 AV 元数据，根据指定规则分类整理影片文件，并为 Emby、Jellyfin、Kodi 等媒体管理软件生成 NFO 元数据文件。内置 Web 管理界面，通过浏览器即可完成配置、刮削、监控等全部操作。

## 功能特点

- 自动识别影片番号，支持分片影片处理
- 多线程并行抓取多个站点数据，汇总生成 NFO 文件
- 下载高清封面，支持 AI 人体分析裁剪非常规封面
- 翻译标题和剧情简介（支持 Google / Bing / Baidu / OpenAI 兼容接口 / 本地 AI）
- **Web 管理界面**：可视化配置、实时刮削进度、任务管理、文件监控
- **文件变动监控**：监控目录变动，自动触发刮削

## 快速开始

### 一键部署（推荐）

```bash
git clone https://github.com/dingdadao/jav-manager.git
cd jav-manager

# 安装所有依赖并构建前端
./deploy.sh install

# 启动服务
./deploy.sh start
```

启动后访问 `http://localhost:5001` 即可使用 Web 管理界面。

## 部署脚本

`deploy.sh` 自动检测并安装缺失的系统依赖（Python、Poetry、Node.js），兼容 macOS 和 Linux。

```bash
./deploy.sh install    # 安装所有依赖并构建前端
./deploy.sh start      # 启动服务（首次自动执行安装）
./deploy.sh stop       # 停止服务
./deploy.sh restart    # 重启服务
./deploy.sh status     # 查看运行状态和依赖信息
./deploy.sh logs       # 实时查看日志
```

自定义端口或监听地址：

```bash
JAVSP_HOST=127.0.0.1 JAVSP_PORT=8080 ./deploy.sh start
```

## Web 管理界面

| 页面 | 功能 |
|------|------|
| 仪表盘 | 系统统计、实时刮削进度、最近任务、操作日志 |
| 开始刮削 | 选择媒体库或手动路径，一键启动刮削任务，实时显示成功/失败/未识别番号统计 |
| 任务列表 | 查看所有历史任务，每部影片的刮削结果详情 |
| 命名检查 | 扫描媒体库，检查命名是否符合规则，支持批量修复/重新刮削 |
| 配置管理 | 可视化编辑全部配置项（扫描/网络/爬虫/整理/翻译/封面/监控） |
| 文件监控 | 管理监控路径，检测到新文件自动触发刮削 |
| 媒体库 | 管理多个媒体库路径，设置默认库 |
| 操作日志 | 按级别筛选查看系统日志 |

## 命名规则

在 Web 管理界面的「配置管理 → 整理与命名」中可以设置影片文件、文件夹、NFO、封面的命名规则。支持以下变量：

| 变量 | 含义 | 备注 |
|------|------|------|
| `{num}` | 影片番号 | 优先 DVD ID，cid 模式下为 cid |
| `{title}` | 影片标题（翻译后） | |
| `{rawtitle}` | 原始标题（翻译前） | 无论是否启用翻译，始终为原始标题 |
| `{actress}` | 女优 | 多个用逗号分隔 |
| `{censor}` | 有码/无码 | 有码 / 无码 / 不确定 |
| `{score}` | 影片评分 | 10 分制，例如 7.81 |
| `{serial}` | 系列 | |
| `{label}` | 番号系列 | 番号拆分后的系列前缀 |
| `{director}` | 导演 | |
| `{producer}` | 制作商 | |
| `{publisher}` | 发行商 | |
| `{date}` | 发行日期 | 例如 2020-05-20 |
| `{year}` | 发行年份 | |

> 使用 NFO 时，不建议在文件名中添加 `{title}`，可能影响媒体管理软件兼容性。Linux 文件系统对长路径支持有限。

## 远程部署

```bash
ssh user@your-server
git clone https://github.com/dingdadao/jav-manager.git
cd jav-manager
./deploy.sh start
```

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

## 技术栈

**后端**：Python / Flask / Flask-SocketIO / SQLite / watchdog

**前端**：React / TypeScript / Ant Design / Vite / Socket.IO

## 项目结构

```
jav-manager/
├── javsp/
│   ├── __main__.py          # 命令行入口（当前版本主要使用 Web 模式）
│   ├── config.py            # 配置管理
│   ├── datatype.py          # 数据类型定义
│   ├── web/                 # 各站点爬虫
│   ├── core/                # 核心功能
│   ├── utils/               # 工具函数
│   └── webapp/              # Web 管理界面
│       ├── app.py           # Flask 应用
│       ├── database.py      # SQLite 数据库
│       ├── routes.py        # API 路由
│       ├── scraper.py       # 刮削执行器
│       ├── watcher.py       # 文件监控
│       ├── server.py        # Web 启动入口
│       └── frontend/        # React 前端
│           └── src/
│               ├── pages/   # 页面组件
│               ├── hooks/   # 自定义 Hook
│               └── api/     # API 调用
├── deploy.sh                # 一键部署脚本
├── config.yml               # 配置文件
└── pyproject.toml           # 项目配置
```

## 项目许可

本项目遵循 [GPL-3.0 License](https://opensource.org/licenses/GPL-3.0) 和 [Anti 996 License](https://github.com/996icu/996.ICU/blob/master/LICENSE_CN) 共同许可。

## 使用条款

- 本软件仅供学习 Python 和技术交流使用
- 请勿在微博、微信等墙内社交平台上宣传此项目
- 使用本软件时，请遵守当地法律法规
- 禁止将本软件用于商业用途
