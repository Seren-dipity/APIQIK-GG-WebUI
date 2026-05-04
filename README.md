---
title: GG Panel APIQIK
emoji: 🚀
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# APIQIK GG WebUI

APIQIK GG WebUI 是一个面向 APIQIK 图像生成接口的 FastAPI Web 应用。后端负责请求编排、批量并发、参考图上传、结果落盘、历史记录和 SSE 日志推送；前端是静态 HTML/CSS/JavaScript 页面，直接由 FastAPI 托管。

本文档面向开发者，描述项目结构、运行方式、配置边界、接口约定和维护注意事项。

## 技术栈

- Python 3.10+
- FastAPI / Uvicorn
- Pydantic
- Cloudflare R2 via `boto3`
- 原生静态前端：`static/index.html`、`static/settings.html`、CSS、少量独立 JS
- Docker / Hugging Face Space Docker SDK

## 项目结构

```text
.
├── main.py                 # FastAPI 应用、路由、任务队列、历史记录、上传索引
├── core.py                 # APIQIK 请求构造、兼容模式调用、R2 操作、结果解析与保存
├── static/
│   ├── index.html          # 主生成页面，包含主要前端交互逻辑
│   ├── settings.html       # 本地配置页面
│   ├── css/                # 基础样式、主题变量、兼容模式样式
│   └── js/                 # 主题和上传图库逻辑
├── scripts/launcher.ps1    # Windows 启动器，负责依赖检查、端口检查、启动 Uvicorn
├── 启动.bat                # Windows 快捷启动入口
├── Dockerfile              # Hugging Face / Docker 部署入口
├── requirements.txt        # Python 依赖
├── output/                 # 运行期产物：生成图、历史记录、上传索引、审计日志
└── tests/                  # 本地测试用例
```

## 本地运行

安装依赖：

```bash
pip install -r requirements.txt
```

启动开发服务：

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

访问：

```text
http://127.0.0.1:8080/
```

Windows 用户也可以运行 `启动.bat`。它会调用 `scripts/launcher.ps1`，检查 Python 依赖、询问端口、处理端口占用，然后启动 `uvicorn main:app`。

## Docker / Hugging Face

项目根目录的 `Dockerfile` 使用 `python:3.10-slim`：

```bash
docker build -t apiqik-webui .
docker run --rm -p 7860:7860 apiqik-webui
```

容器默认执行：

```bash
python main.py
```

README 顶部保留了 Hugging Face Space metadata，默认端口为 `7860`。

## 配置模型

项目有两类配置来源：

1. 前端本地配置：APIQIK Key、多个 Key、base URL、私有 R2 参数等保存在浏览器 `localStorage`，由前端发给后端。
2. 服务端环境变量：只用于部署方提供公共 R2 存储，以及识别 Hugging Face 环境。

服务端可选环境变量：

| 变量 | 用途 |
| --- | --- |
| `CF_ACCESS_KEY` | 公共 Cloudflare R2 Access Key |
| `CF_SECRET_KEY` | 公共 Cloudflare R2 Secret Key |
| `CF_ACCOUNT_ID` | Cloudflare Account ID |
| `CF_BUCKET` | R2 Bucket 名称 |
| `CF_PUBLIC_URL` | R2 公开访问前缀，不带结尾斜线 |
| `SPACE_ID` / `SPACE_HOST` / `SPACE_AUTHOR_NAME` | Hugging Face 环境识别，任一存在即视为云端环境 |

`main.py` 不读取项目文件中的本地配置文件。部署时需要让变量进入进程环境，例如平台控制台、Docker `-e`、Compose `environment` 或宿主系统环境变量。

## 核心后端流程

### 常规生成

`POST /api/generate` 接收 `GenerateRequest`：

```python
class GenerateRequest(BaseModel):
    api_key: str = ""
    api_keys: list[str] = Field(default_factory=list)
    prompt: str
    session_id: str
    model: str = api_core.DEFAULT_MODEL
    base_url: str = api_core.DEFAULT_BASE_URL
    size: str | None = None
    ratio: str = "1:1"
    quality: str | None = None
    output_format: str | None = None
    concurrency: int = 1
    image_urls: list[str] = Field(default_factory=list)
    is_pg_mode: bool = False
```

后端会：

1. 校验 Key、prompt、`session_id`、`concurrency`。
2. 创建 `task_id`，初始化 `_tasks[task_id]`。
3. 创建历史记录。
4. 用 `asyncio.create_task()` 启动 `_run_batch()`。
5. 立即返回 `{ task_id, run_id, run }`。

`_run_batch()` 会按 Key 轮次处理未成功的任务。每轮用 `ThreadPoolExecutor(max_workers=50)` 执行同步上游请求，单个 Key 失败后把对应任务放回待处理队列，交给下一个 Key 重试。

### 上游接口封装

`core.py` 负责实际请求：

- 常规模式：`build_image_request()` 调用 `https://img.apiqik.online/api/ai-image/images-generations` 或 `images-edits`。
- 兼容模式：`generate_image(is_pg_mode=True)` 调用 `{base_url}/pg/chat/completions`，强制 `group="auto"`，不传尺寸。

常规模式会根据是否有参考图选择：

- 无参考图：`images-generations`
- 有参考图：`images-edits`

### 结果解析

`save_generation_result()` 支持多种响应形态：

- OpenAI 风格 `data[].url`
- OpenAI 风格 `data[].b64_json` / `base64`
- 顶层 `url` / `image_url`
- Chat Completions 风格 `choices[].message.content`
- 兼容模式可能返回的顶层 `messages[].content`
- Markdown 图片、普通 Markdown 链接、HTML `<img src="">`、裸 URL

无法解析到图片时会抛出包含完整响应 JSON 的 `ValueError`，用于定位上游返回结构变更。

### SSE 日志

任务日志通过：

```text
GET /api/tasks/{task_id}/stream
```

事件格式是普通 SSE `data:` 消息，JSON 里常见 `type`：

- `log`
- `progress`
- `result`
- `error`
- `done`

连接空闲 60 秒会发送 `ping` 事件保活。

## 参考图上传

`POST /api/upload-image` 接收 multipart 文件，并上传到 Cloudflare R2。

R2 配置来源：

- 前端传入 `cf_access_key` 等字段：私有 R2。
- 服务端环境变量：公共 R2。

上传成功后，如果 `session_id` 合法，会写入当前 session 的上传索引：

```text
output/{session_id}/uploads.json
```

如果服务端配置了公共 R2，公共上传索引还会同步到 R2：

```text
apiqik_indexes/{session_id}/uploads.json
```

相关接口：

- `POST /api/upload-image`
- `GET /api/uploads?session_id=...&is_public=true|false`
- `POST /api/delete-upload`
- `POST /api/delete-all-uploads`

## 历史记录和输出目录

所有运行期文件都放在 `output/` 下，以浏览器生成的 UUID `session_id` 隔离：

```text
output/{session_id}/
├── history.json
├── uploads.json
├── attempt_audit.jsonl
├── .last_access
└── *.png / *.jpeg / *.webp
```

`main.py` 会维护最多 200 个 session 目录。超过上限时，根据 `.last_access` 删除最旧目录。

结果图片通过静态挂载暴露：

```text
/output/{session_id}/{filename}
```

## 操练场兼容模式

兼容模式用于通过 APIQIK 官网登录态调用 `/pg/chat/completions`。

相关接口：

- `GET /api/auth/status?session_id=...`
- `POST /api/auth/apiqik-login`
- `POST /api/auth/logout`

后端把登录得到的 Cookie 存在进程内 `_pg_session_cookies: dict[str, str]`，按 `session_id` 绑定。服务重启后登录态丢失。

安全边界：

- Hugging Face 环境下禁用兼容模式登录。
- Cookie 只在当前服务进程内保存，没有持久化。
- 401 / 403 会被视为 Cookie 失效，并清理对应 session 的 Cookie。

## 前端架构

前端没有构建步骤。

- `static/index.html`：主页面、生成参数、任务订阅、结果渲染、兼容模式弹窗。
- `static/settings.html`：配置页，主要写入浏览器 `localStorage`。
- `static/js/upload-manager.js`：上传图库弹窗、上传记录列表、批量删除。
- `static/js/theme.js`：主题切换和主题持久化。
- `static/css/base.css`：主要布局和组件样式。
- `static/css/pg_mode.css`：操练场兼容模式样式。
- `static/css/themes/*`：主题变量。

服务端在返回 HTML 前会注入：

```js
window.SERVER_CONFIG = {
  has_public_r2: boolean,
  is_huggingface: boolean
}
```

前端据此决定是否展示公共存储、云端安全提示和兼容模式入口。

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 主页面 |
| `GET` | `/settings` | 设置页面 |
| `POST` | `/api/generate` | 创建批量生成任务 |
| `GET` | `/api/tasks/{task_id}/stream` | SSE 实时事件 |
| `GET` | `/api/tasks/{task_id}` | 查询任务状态 |
| `GET` | `/api/history` | 查询当前 session 历史 |
| `DELETE` | `/api/history/{run_id}` | 删除历史记录和对应输出文件 |
| `POST` | `/api/upload-image` | 上传参考图到 R2 |
| `GET` | `/api/uploads` | 查询上传记录 |
| `POST` | `/api/delete-upload` | 删除单个上传记录，并尝试删除 R2 对象 |
| `POST` | `/api/delete-all-uploads` | 批量删除上传记录，并尝试删除 R2 对象 |
| `GET` | `/api/auth/status` | 查询兼容模式登录态 |
| `POST` | `/api/auth/apiqik-login` | 登录 APIQIK 官网并保存兼容模式 Cookie |
| `POST` | `/api/auth/logout` | 清除兼容模式 Cookie |

## 测试

运行全部测试：

```bash
pytest -q
```

运行核心解析与诊断测试：

```bash
pytest tests/test_core_diagnostics.py -q
```

当前测试覆盖重点包括：

- APIQIK 响应里的 URL / base64 图片引用解析
- 兼容模式 Markdown、HTML、顶层 `messages` 链接解析
- 下载重试日志回调
- 页面静态结构断言
- 上传、历史记录和批量任务事件流的后端行为

## 维护注意事项

- `main.py` 的任务状态和兼容模式 Cookie 都是进程内状态；多进程部署需要重新设计共享状态。
- `ThreadPoolExecutor(max_workers=50)` 和 `concurrency <= 50` 是当前并发上限，调整时要同步考虑上游限流和内存占用。
- `output/` 是运行期数据目录，不应提交到仓库。
- 前端配置依赖浏览器 `localStorage`，清理浏览器数据会丢失本地 Key 和私有 R2 配置。
- 上游返回结构变更时，优先扩展 `core.describe_image_references()` 和 `core.save_generation_result()`，并补充 `tests/test_core_diagnostics.py`。
- Hugging Face 环境下不应开启兼容模式登录，因为账号密码会经过云端服务进程。
