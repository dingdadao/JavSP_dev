# JavSP API 接口文档

JavSP API 提供 HTTP 接口用于刮削日本成人影片信息。

## 快速开始

### 启动 API 服务器

```bash
# 使用默认配置启动 (0.0.0.0:5000)
python api_server.py

# 指定端口
python api_server.py --port 8080

# 调试模式
python api_server.py --debug
```

## 接口列表

### 1. 健康检查

检查 API 服务是否正常运行。

**请求：**
```http
GET /health
```

**响应：**
```json
{
    "code": 0,
    "message": "JavSP API 服务运行中",
    "data": null
}
```

---

### 2. 创建刮削任务

创建刮削任务，只返回成功或失败信息，不返回详细结果。

**请求：**
```http
POST /api/scrape
Content-Type: application/json

{
    "source": "/path/to/movies",      // 可选，源文件夹路径（不传则使用配置文件）
    "dest": "/path/to/output",        // 可选，输出文件夹路径（不传则使用配置文件）
    "translate": true,                 // 可选，是否翻译，默认 true
    "move_files": false                // 可选，是否移动文件，默认 false
}
```

**参数说明：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source | string | 否 | 源文件夹路径，不传则读取配置文件 |
| dest | string | 否 | 输出文件夹路径，不传则读取配置文件 |
| translate | boolean | 否 | 是否翻译标题和简介，默认 true |
| move_files | boolean | 否 | 是否移动文件（false=复制，true=移动），默认 false |

**成功响应：**
```json
{
    "code": 0,
    "message": "任务创建成功，共 10 部影片",
    "data": {
        "total": 10
    }
}
```

**失败响应示例：**

已有任务进行中：
```json
{
    "code": 1007,
    "message": "已有任务进行中，请等待完成后再创建新任务",
    "data": null
}
```

配置文件源路径无效：
```json
{
    "code": 1004,
    "message": "未提供源路径，且配置文件中也未设置有效的源路径",
    "data": null
}
```

配置文件目标路径无效：
```json
{
    "code": 1005,
    "message": "未提供目标路径，且配置文件中也未设置有效的目标路径",
    "data": null
}
```

源路径不存在：
```json
{
    "code": 1002,
    "message": "源路径不存在: /path/to/movies",
    "data": null
}
```

目标路径不存在且无法创建：
```json
{
    "code": 1003,
    "message": "目标路径不存在且无法创建: /path/to/output, 错误: Permission denied",
    "data": null
}
```

未找到影片文件：
```json
{
    "code": 1006,
    "message": "未在路径 /path/to/movies 中找到任何影片文件",
    "data": null
}
```

---

### 3. 查询任务状态

查询当前任务的状态。只保留最近一次任务的结果。

**请求：**
```http
GET /api/scrape/status
```

**响应（无任务）：**
```json
{
    "code": 0,
    "message": "当前无任务",
    "data": null
}
```

**响应（任务进行中）：**
```json
{
    "code": 0,
    "message": "任务进行中",
    "data": {
        "status": "running",
        "total": 10,
        "completed": 5,
        "progress": "5/10"
    }
}
```

**响应（任务已完成）：**
```json
{
    "code": 0,
    "message": "任务已完成",
    "data": {
        "status": "completed",
        "total": 10,
        "completed": 10,
        "progress": "10/10",
        "success_count": 8,
        "failed_count": 2,
        "success": [
            {
                "dvdid": "SSIS-123",
                "source_path": "/path/to/SSIS-123.mp4",
                "dest_path": "/path/to/output/SSIS-123"
            }
        ],
        "failed": [
            {
                "dvdid": "SSIS-999",
                "source_path": "/path/to/SSIS-999.mp4",
                "reason": "无法获取影片信息，所有爬虫均返回失败"
            }
        ]
    }
}
```

**状态说明：**
- `running`: 任务进行中
- `completed`: 全部成功完成
- `partial`: 部分成功（有成功也有失败）
- `failed`: 全部失败
- `error`: 任务执行出错

---

### 4. 获取配置信息

获取当前 JavSP 的配置信息，包括路径配置。

**请求：**
```http
GET /api/config
```

**响应：**
```json
{
    "code": 0,
    "message": "获取配置成功",
    "data": {
        "paths": {
            "source": "/Volumes/data/download",
            "dest": "/Volumes/data/output"
        },
        "crawler": {
            "selection": {
                "normal": ["javdb", "arzon", "airav", "mgstage", "prestige", "javbus"],
                "fc2": ["fc2", "avsox", "javdb", "javmenu", "fc2ppvdb"],
                "cid": ["fanza"]
            },
            "required_keys": ["cover", "title"],
            "hardworking": true
        },
        "translator": {
            "engine": "localai",
            "fields": {
                "title": true,
                "plot": true
            }
        }
    }
}
```

---

## 返回码说明

| 返回码 | 说明 | HTTP 状态码 | 描述 |
|--------|------|------------|------|
| 0 | 成功 | 200 | 操作成功 |
| 1001 | 参数错误 | 400 | 请求参数格式错误 |
| 1002 | 源路径不存在 | 404 | 传入的源路径不存在 |
| 1003 | 目标路径不存在 | 404 | 目标路径不存在且无法创建 |
| 1004 | 配置文件源路径无效 | 400 | 未提供源路径且配置文件未设置 |
| 1005 | 配置文件目标路径无效 | 400 | 未提供目标路径且配置文件未设置 |
| 1006 | 未找到影片文件 | 404 | 在源路径中未找到影片文件 |
| 1007 | 已有任务进行中 | 400 | 当前已有任务在执行中 |
| 9999 | 内部错误 | 500 | 服务器内部错误 |

---

## 使用示例

### 完整刮削流程

```bash
# 1. 创建刮削任务
curl -X POST http://localhost:5000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "source": "/Volumes/data/download",
    "dest": "/Volumes/data/output"
  }'

# 返回: {"code": 0, "message": "任务创建成功，共 10 部影片", "data": {"total": 10}}

# 2. 轮询查询任务状态（每隔几秒查询一次）
curl http://localhost:5000/api/scrape/status

# 进行中返回: {"data": {"status": "running", "progress": "5/10"}}
# 完成返回: {"data": {"status": "completed", "success": [...], "failed": [...]}}
```

### Python 示例

```python
import requests
import time

# 创建任务
response = requests.post('http://localhost:5000/api/scrape', json={
    'source': '/Volumes/data/download',
    'dest': '/Volumes/data/output'
})
data = response.json()

if data['code'] != 0:
    print(f"创建任务失败: {data['message']}")
    exit()

print(f"任务创建成功: {data['data']['total']} 部影片")

# 轮询查询状态
while True:
    response = requests.get('http://localhost:5000/api/scrape/status')
    result = response.json()
    
    if result['data'] is None:
        print("当前无任务")
        break
    
    task = result['data']
    print(f"进度: {task['progress']}")
    
    if task['status'] != 'running':
        print("任务完成!")
        print(f"成功: {task['success_count']}, 失败: {task['failed_count']}")
        
        # 打印失败的影片
        for item in task['failed']:
            print(f"  ✗ {item['dvdid']}: {item['reason']}")
        break
    
    time.sleep(2)  # 每2秒查询一次
```

### JavaScript 示例

```javascript
async function scrapeAndWait() {
    // 创建任务
    const createRes = await fetch('http://localhost:5000/api/scrape', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            source: '/Volumes/data/download',
            dest: '/Volumes/data/output'
        })
    });
    const createData = await createRes.json();
    
    if (createData.code !== 0) {
        console.log(`创建任务失败: ${createData.message}`);
        return;
    }
    
    console.log(`任务创建成功: ${createData.data.total} 部影片`);
    
    // 轮询状态
    const checkStatus = async () => {
        const res = await fetch('http://localhost:5000/api/scrape/status');
        const { data: task } = await res.json();
        
        if (task === null) {
            console.log('当前无任务');
            return;
        }
        
        console.log(`进度: ${task.progress}`);
        
        if (task.status === 'running') {
            setTimeout(checkStatus, 2000);
        } else {
            console.log('任务完成!');
            console.log(`成功: ${task.success_count}, 失败: ${task.failed_count}`);
            
            task.failed.forEach(item => {
                console.log(`✗ ${item.dvdid}: ${item.reason}`);
            });
        }
    };
    
    checkStatus();
}

scrapeAndWait();
```

---

## 注意事项

1. **单次任务**：系统只保留最近一次任务的结果，新任务会覆盖旧任务

2. **并发控制**：同一时间只能有一个任务在执行，创建新任务前必须等待当前任务完成

3. **路径优先级**：传入的参数 > 配置文件

4. **路径检查**：
   - 源路径必须存在，否则返回 `1002` 错误
   - 目标路径不存在时会尝试自动创建，创建失败返回 `1003` 错误

5. **任务状态**：
   - `running`: 任务进行中（只返回进度信息）
   - `completed/partial/failed/error`: 任务已完成（返回完整结果）

6. **文件操作模式**：
   - `move_files: false`（默认）：复制文件到目标路径，保留源文件
   - `move_files: true`：移动文件到目标路径，删除源文件

7. **输出结构**：每部影片会创建独立的文件夹，结构如下：
   ```
   /path/to/output/
   ├── SSIS-123/
   │   ├── SSIS-123.mp4
   │   ├── SSIS-123.nfo
   │   └── poster.jpg
   ├── SSIS-124/
   │   ├── SSIS-124.mp4
   │   ├── SSIS-124.nfo
   │   └── poster.jpg
   ```

---

## 配置文件

API 服务器使用与主程序相同的配置文件 `config.yml`，请确保配置文件正确设置：

```yaml
# 扫描配置
scanner:
  input_directory: "/Volumes/data/download"  # 输入目录

# 输出配置
summarizer:
  path:
    output_folder_pattern: "/Volumes/data/output/{dvdid}"  # 输出路径模板

# 爬虫配置
crawler:
  selection:
    normal: [javdb, arzon, airav, mgstage, prestige, javbus]
  required_keys: [cover, title]

# 翻译配置
translator:
  engine:
    name: localai
    url: "http://localhost:1234"
    model: qwen/qwen3.5-9b
  fields:
    title: true
    plot: true
```
