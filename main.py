#!/usr/bin/env python3
"""APIQIK Image Generation Web Server."""

from __future__ import annotations

import asyncio
import json
import struct
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import core as api_core
import os
import re

app = FastAPI(title="APIQIK Image Generator")

OUTPUT_DIR = Path("./output").absolute()
OUTPUT_DIR.mkdir(exist_ok=True)

STATIC_DIR = Path("./static").absolute()

# 每个 Space 实例最多保留的 session 数量，超出时清理最旧的
_MAX_SESSIONS = 200
_SESSION_ID_RE = re.compile(r'^[0-9a-f-]{36}$')

# 任务状态存储：task_id -> {"status": ..., "queue": asyncio.Queue, "total": int, "done": int}
_tasks: dict[str, dict[str, Any]] = {}

# 线程池，用于运行同步 API 调用
_executor = ThreadPoolExecutor(max_workers=50)
_history_lock = threading.RLock()


# ──────────────────────────────────────────────
# 请求体模型
# ──────────────────────────────────────────────

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
    concurrency: int = 10
    image_urls: list[str] = Field(default_factory=list)


class ImageHostDeleteRequest(BaseModel):
    token: str


# ──────────────────────────────────────────────
# 路由：页面
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    content = html_path.read_text(encoding="utf-8")
    return HTMLResponse(content=_inject_server_config(content))


def _server_config() -> dict[str, bool]:
    has_public_r2 = all([
        os.getenv("CF_ACCESS_KEY"),
        os.getenv("CF_SECRET_KEY"),
        os.getenv("CF_ACCOUNT_ID"),
        os.getenv("CF_BUCKET"),
        os.getenv("CF_PUBLIC_URL")
    ])
    is_huggingface = any([
        os.getenv("SPACE_ID"),
        os.getenv("SPACE_HOST"),
        os.getenv("SPACE_AUTHOR_NAME"),
    ])
    return {
        "has_public_r2": bool(has_public_r2),
        "is_huggingface": bool(is_huggingface),
    }


def _inject_server_config(content: str) -> str:
    config = _server_config()
    config_js = (
        "<script>window.SERVER_CONFIG = { "
        f"'has_public_r2': {'true' if config['has_public_r2'] else 'false'}, "
        f"'is_huggingface': {'true' if config['is_huggingface'] else 'false'} "
        "};</script>"
    )
    return content.replace("<head>", f"<head>{config_js}", 1)


@app.get("/settings", response_class=HTMLResponse)
async def settings():
    html_path = STATIC_DIR / "settings.html"
    content = html_path.read_text(encoding="utf-8")
    return HTMLResponse(content=_inject_server_config(content))


# ──────────────────────────────────────────────
# 路由：参考图上传
# ──────────────────────────────────────────────

@app.post("/api/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    session_id: str | None = Form(None),
    cf_access_key: str | None = Form(None),
    cf_secret_key: str | None = Form(None),
    cf_account_id: str | None = Form(None),
    cf_bucket: str | None = Form(None),
    cf_public_url: str | None = Form(None),
):
    """接收前端上传的参考图，中转至 Cloudflare R2。支持从请求参数或服务器环境变量获取配置。"""
    # 优先从前端传参获取，如果没有则回退到环境变量（服务端默认 R2）
    access_key = cf_access_key or os.getenv("CF_ACCESS_KEY")
    secret_key = cf_secret_key or os.getenv("CF_SECRET_KEY")
    account_id = cf_account_id or os.getenv("CF_ACCOUNT_ID")
    bucket = cf_bucket or os.getenv("CF_BUCKET")
    public_url = cf_public_url or os.getenv("CF_PUBLIC_URL")

    if not all([access_key, secret_key, account_id, bucket, public_url]):
        raise HTTPException(
            status_code=400, 
            detail="未配置 Cloudflare R2 存储。请在'设置'中填写密钥，或联系管理员配置服务端默认存储。"
        )

    suffix = Path(file.filename).suffix if file.filename else ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        public_url_result = await asyncio.to_thread(
            api_core.upload_image_to_r2,
            tmp_path,
            access_key=access_key,
            secret_key=secret_key,
            account_id=account_id,
            bucket_name=bucket,
            public_url_prefix=public_url,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)

    # 记录上传索引 (仅针对成功且有 session_id 的情况)
    if session_id and _SESSION_ID_RE.match(session_id):
        # 提取 Key：由于 R2 Key 包含前缀，我们需要从 URL 倒推
        # 简化处理：我们知道 Key 是拼接在 public_url 后面的
        prefix = public_url.rstrip('/')
        key = public_url_result[len(prefix)+1:] if public_url_result.startswith(prefix) else ""
        
        uploads = _load_uploads(session_id)
        uploads.append({
            "url": public_url_result,
            "key": key,
            "name": file.filename,
            "created_at": datetime.now().isoformat(),
            "is_public": not cf_access_key # 如果前端没传 key，说明用的是公共配置
        })
        _save_uploads(session_id, uploads)

    return {"url": public_url_result}


@app.get("/api/uploads")
async def list_uploads(session_id: str = Query(...), is_public: bool | None = Query(None)):
    """获取当前 session 记录在案的已上传参考图。支持 is_public 过滤。"""
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    
    uploads = _load_uploads(session_id)
    if is_public is not None:
        uploads = [u for u in uploads if u.get("is_public") == is_public]
        
    return {"uploads": uploads}


@app.post("/api/delete-upload")
async def delete_upload(
    url: str = Form(...),
    session_id: str = Form(...),
    cf_access_key: str | None = Form(None),
    cf_secret_key: str | None = Form(None),
    cf_account_id: str | None = Form(None),
    cf_bucket: str | None = Form(None),
):
    """从索引中移除记录，并尝试从 R2 中物理删除文件。支持公共和私有 R2。"""
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")

    uploads = _load_uploads(session_id)
    target = next((u for u in uploads if u["url"] == url), None)
    if not target:
        raise HTTPException(status_code=404, detail="Upload record not found")

    # 物理删除逻辑
    success = False
    if target.get("is_public"):
        # 公共模式：使用服务端环境变量
        access_key = os.getenv("CF_ACCESS_KEY")
        secret_key = os.getenv("CF_SECRET_KEY")
        account_id = os.getenv("CF_ACCOUNT_ID")
        bucket = os.getenv("CF_BUCKET")
    else:
        # 私有模式：使用前端传来的凭证
        access_key = cf_access_key
        secret_key = cf_secret_key
        account_id = cf_account_id
        bucket = cf_bucket
        
    if all([access_key, secret_key, account_id, bucket]) and target.get("key"):
        success = await asyncio.to_thread(
            api_core.delete_image_from_r2,
            target["key"],
            access_key=access_key,
            secret_key=secret_key,
            account_id=account_id,
            bucket_name=bucket
        )

    # 从索引中移除
    new_uploads = [u for u in uploads if u["url"] != url]
    _save_uploads(session_id, new_uploads)

    return {"success": True, "physical_delete": success}


@app.post("/api/delete-all-uploads")
async def delete_all_uploads(
    session_id: str = Form(...),
    is_public: bool | None = Form(None),
    cf_access_key: str | None = Form(None),
    cf_secret_key: str | None = Form(None),
    cf_account_id: str | None = Form(None),
    cf_bucket: str | None = Form(None),
):
    """清空当前 Session 的所有上传记录，并尝试物理删除。"""
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")

    uploads = _load_uploads(session_id)
    
    # 循环删除 R2 上的物理文件
    to_delete = []
    remaining = []
    
    for u in uploads:
        if is_public is None or u.get("is_public") == is_public:
            to_delete.append(u)
        else:
            remaining.append(u)

    for target in to_delete:
        # 确定使用的凭证
        access_key = os.getenv("CF_ACCESS_KEY") if target.get("is_public") else cf_access_key
        secret_key = os.getenv("CF_SECRET_KEY") if target.get("is_public") else cf_secret_key
        account_id = os.getenv("CF_ACCOUNT_ID") if target.get("is_public") else cf_account_id
        bucket = os.getenv("CF_BUCKET") if target.get("is_public") else cf_bucket
        
        if all([access_key, secret_key, account_id, bucket]) and target.get("key"):
            asyncio.create_task(asyncio.to_thread(
                api_core.delete_image_from_r2,
                target["key"],
                access_key=access_key,
                secret_key=secret_key,
                account_id=account_id,
                bucket_name=bucket
            ))

    # 更新本地索引
    _save_uploads(session_id, remaining)
    return {"success": True, "count": len(to_delete)}


def _load_uploads(session_id: str) -> list[dict]:
    path = _ensure_session_dir(session_id) / "uploads.json"
    remote_uploads = _load_public_uploads_from_r2(session_id)
    if not path.exists():
        return remote_uploads
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        local_uploads = data if isinstance(data, list) else []
    except:
        local_uploads = []

    if not remote_uploads:
        return local_uploads

    merged: dict[str, dict] = {}
    for item in local_uploads + remote_uploads:
        if isinstance(item, dict) and item.get("url"):
            merged[item["url"]] = item
    return list(merged.values())


def _save_uploads(session_id: str, data: list[dict]):
    path = _ensure_session_dir(session_id) / "uploads.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_public_uploads_to_r2(session_id, data)


def _public_r2_config() -> dict[str, str] | None:
    config = {
        "access_key": os.getenv("CF_ACCESS_KEY") or "",
        "secret_key": os.getenv("CF_SECRET_KEY") or "",
        "account_id": os.getenv("CF_ACCOUNT_ID") or "",
        "bucket_name": os.getenv("CF_BUCKET") or "",
    }
    return config if all(config.values()) else None


def _public_uploads_index_key(session_id: str) -> str:
    return f"apiqik_indexes/{session_id}/uploads.json"


def _load_public_uploads_from_r2(session_id: str) -> list[dict]:
    config = _public_r2_config()
    if not config:
        return []
    try:
        data = api_core.load_json_from_r2(
            object_key=_public_uploads_index_key(session_id),
            **config,
        )
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _save_public_uploads_to_r2(session_id: str, data: list[dict]) -> None:
    config = _public_r2_config()
    if not config:
        return
    public_uploads = [
        item for item in data
        if isinstance(item, dict) and item.get("is_public") is True
    ]
    try:
        api_core.save_json_to_r2(
            object_key=_public_uploads_index_key(session_id),
            data=public_uploads,
            **config,
        )
    except Exception:
        pass




# ──────────────────────────────────────────────
# 路由：提交生成任务
# ──────────────────────────────────────────────

@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """创建并发生成任务，立即返回 task_id。"""
    api_keys = _normalize_api_keys(req)
    if not api_keys:
        raise HTTPException(status_code=400, detail="api_key 不能为空")
    if not req.prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    if req.concurrency < 1 or req.concurrency > 50:
        raise HTTPException(status_code=400, detail="concurrency 范围 1~50")
    if not _SESSION_ID_RE.match(req.session_id):
        raise HTTPException(status_code=400, detail="session_id 格式不合法")

    _ensure_session_dir(req.session_id)
    req.api_key = api_keys[0]
    req.api_keys = api_keys

    task_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _tasks[task_id] = {
        "status": "running",
        "queue": queue,
        "total": req.concurrency,
        "done": 0,
        "run_id": task_id,
        "session_id": req.session_id,
    }
    run = create_history_run(task_id, req)

    asyncio.create_task(_run_batch(task_id, req))
    return {"task_id": task_id, "run_id": task_id, "run": run}


# ──────────────────────────────────────────────
# 路由：SSE 实时日志流
# ──────────────────────────────────────────────

@app.get("/api/tasks/{task_id}/stream")
async def task_stream(task_id: str):
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        queue = _tasks[task_id]["queue"]
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=60.0)
            except asyncio.TimeoutError:
                # 发送心跳保持连接
                yield "event: ping\ndata: {}\n\n"
                continue

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if event.get("type") == "done":
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────────────────────────────────────────
# 路由：查询任务状态
# ──────────────────────────────────────────────

@app.get("/api/tasks/{task_id}")
async def task_status(task_id: str):
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = _tasks[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "total": task["total"],
        "done": task["done"],
    }


@app.get("/api/history")
async def history(session_id: str = Query(...)):
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="session_id 格式不合法")
    return load_history(session_id)


@app.delete("/api/history/{run_id}")
async def delete_history(run_id: str, session_id: str = Query(...)):
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="session_id 格式不合法")
    deleted = delete_history_run(run_id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    return {"deleted": True, "run_id": run_id}


# ──────────────────────────────────────────────
# 静态文件：生成的图片
# ──────────────────────────────────────────────

app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ──────────────────────────────────────────────
# 核心：批量并发生成逻辑
# ──────────────────────────────────────────────

async def _run_batch(task_id: str, req: GenerateRequest):
    queue = _tasks[task_id]["queue"]
    loop = asyncio.get_running_loop()
    session_output_dir = _session_dir(req.session_id)

    def _push(event: dict):
        """线程安全地将事件推入队列（从同步线程调用）。"""
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def _log(message: str):
        _push({"type": "log", "message": message, "time": _now()})

    def _worker(idx: int, api_key: str, key_number: int) -> dict:
        """单次生成任务，在线程池中运行。"""
        start = time.time()
        clean = "".join(c if c.isalnum() else "_" for c in req.prompt[:30])
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        base_name = f"{clean}_{ts}_{idx + 1}"

        # 根据 output_format 决定后缀
        ext = req.output_format.lower() if req.output_format else "png"
        if ext not in ["png", "jpeg", "webp", "jpg"]:
            ext = "png"

        output_path = session_output_dir / f"{base_name}.{ext}"

        # 防止极低概率的文件名冲突
        counter = 1
        while output_path.exists():
            output_path = OUTPUT_DIR / f"{base_name}({counter}).png"
            counter += 1

        try:
            response = api_core.generate_image(
                api_key=api_key,
                prompt=req.prompt,
                model=req.model,
                size=req.size,
                ratio=req.ratio,
                quality=req.quality,
                output_format=req.output_format,
                image_urls=req.image_urls,
                base_url=req.base_url or api_core.DEFAULT_BASE_URL,
                timeout=300,
                n=1,
            )

            content_text = ""
            choices = response.get("choices") or []
            for choice in choices:
                text = choice.get("message", {}).get("content", "")
                if text:
                    content_text += text + "\n"

            saved = api_core.save_generation_result(response, output_path)
            duration = time.time() - start

            # 推送成功事件
            image_infos = [_result_image_info(p, req.session_id) for p in saved]
            append_history_images(task_id, image_infos, req.session_id)
            _push({
                "type": "result",
                "run_id": task_id,
                "idx": idx + 1,
                "files": [p.name for p in saved],
                "urls": [f"/output/{req.session_id}/{p.name}" for p in saved],
                "images": image_infos,
                "content": content_text.strip(),
                "duration": round(duration, 1),
            })
            return {"success": True, "idx": idx, "key_number": key_number}

        except Exception as e:
            duration = time.time() - start
            _push({
                "type": "error",
                "run_id": task_id,
                "idx": idx + 1,
                "message": f"Key {key_number} 生成失败: {e}",
                "duration": round(duration, 1),
            })
            return {"success": False, "idx": idx, "key_number": key_number, "error": str(e)}

    api_keys = _normalize_api_keys(req)
    pending_indices = list(range(req.concurrency))
    success_count = 0
    _tasks[task_id]["done"] = 0
    _log(f"开始批量生成，总任务数: {req.concurrency}，模型: {req.model}，可用 Key: {len(api_keys)} 个")

    for key_index, api_key in enumerate(api_keys, start=1):
        if not pending_indices:
            break

        round_indices = pending_indices
        pending_indices = []
        _log(f"第 {key_index} 个 Key 开始生成，剩余 {len(round_indices)} 张。")

        futures = []
        for idx in round_indices:
            future = loop.run_in_executor(_executor, _worker, idx, api_key, key_index)
            futures.append(future)
            # 错开启动间隔，避免瞬时请求风暴
            await asyncio.sleep(0.3)

        for future in asyncio.as_completed(futures):
            result = await future
            if result.get("success"):
                success_count += 1
            else:
                pending_indices.append(result["idx"])

            _tasks[task_id]["done"] = success_count
            _push({
                "type": "progress",
                "run_id": task_id,
                "done": success_count,
                "total": req.concurrency,
            })

        pending_indices.sort()
        if pending_indices:
            _log(f"第 {key_index} 个 Key 完成，成功 {success_count} 张，仍剩 {len(pending_indices)} 张。")

    if pending_indices:
        _log(f"所有 Key 都已尝试，仍有 {len(pending_indices)} 张未生成成功。")

    _tasks[task_id]["status"] = "completed"
    set_history_status(task_id, "completed", done=success_count, session_id=req.session_id)
    _log(f"批量生成结束，成功 {success_count}/{req.concurrency} 张。")
    queue.put_nowait({"type": "done", "run_id": task_id, "done": success_count, "total": req.concurrency})


def _normalize_api_keys(req: GenerateRequest) -> list[str]:
    keys: list[str] = []
    for key in [req.api_key, *req.api_keys]:
        normalized = str(key or "").strip()
        if normalized and normalized not in keys:
            keys.append(normalized)
    return keys


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _session_dir(session_id: str) -> Path:
    return OUTPUT_DIR / session_id


def _ensure_session_dir(session_id: str) -> Path:
    """创建 session 目录，同时触发 LRU 清理。"""
    path = _session_dir(session_id)
    path.mkdir(parents=True, exist_ok=True)
    # 更新最后访问时间戳文件，用于 LRU 排序
    (path / ".last_access").write_text(str(time.time()), encoding="utf-8")
    _evict_old_sessions()
    return path


def _evict_old_sessions() -> None:
    """当 session 数量超过上限时，删除最旧的 session 目录。"""
    try:
        dirs = [
            d for d in OUTPUT_DIR.iterdir()
            if d.is_dir() and _SESSION_ID_RE.match(d.name)
        ]
        if len(dirs) <= _MAX_SESSIONS:
            return

        def _last_access(d: Path) -> float:
            ts_file = d / ".last_access"
            try:
                return float(ts_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return d.stat().st_mtime

        dirs.sort(key=_last_access)
        to_remove = dirs[:len(dirs) - _MAX_SESSIONS]
        for old_dir in to_remove:
            import shutil
            shutil.rmtree(old_dir, ignore_errors=True)
    except OSError:
        pass


def history_file(session_id: str) -> Path:
    return _session_dir(session_id) / "history.json"


def load_history(session_id: str) -> dict[str, Any]:
    with _history_lock:
        path = history_file(session_id)
        if not path.exists():
            return {"runs": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"runs": []}
        runs = data.get("runs")
        return {"runs": runs if isinstance(runs, list) else []}


def save_history(data: dict[str, Any], session_id: str) -> None:
    with _history_lock:
        path = history_file(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)


def create_history_run(run_id: str, req: GenerateRequest) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    params = req.model_dump(exclude={"api_key", "api_keys"})
    run = {
        "run_id": run_id,
        "created_at": now,
        "updated_at": now,
        "status": "running",
        "prompt": req.prompt,
        "model": req.model,
        "params": params,
        "total": req.concurrency,
        "done": 0,
        "images": [],
    }
    with _history_lock:
        data = load_history(req.session_id)
        data["runs"] = [item for item in data["runs"] if item.get("run_id") != run_id]
        data["runs"].insert(0, run)
        save_history(data, req.session_id)
    return run


def append_history_images(run_id: str, images: list[dict[str, Any]], session_id: str) -> bool:
    if not images:
        return False
    with _history_lock:
        data = load_history(session_id)
        for run in data["runs"]:
            if run.get("run_id") != run_id:
                continue
            run.setdefault("images", []).extend(images)
            run["done"] = len(run["images"])
            run["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_history(data, session_id)
            return True
    return False


def set_history_status(run_id: str, status: str, done: int | None = None, session_id: str = "") -> bool:
    with _history_lock:
        data = load_history(session_id)
        for run in data["runs"]:
            if run.get("run_id") != run_id:
                continue
            run["status"] = status
            if done is not None:
                run["done"] = done
            run["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_history(data, session_id)
            return True
    return False


def delete_history_run(run_id: str, session_id: str) -> bool:
    with _history_lock:
        data = load_history(session_id)
        run = next((item for item in data["runs"] if item.get("run_id") == run_id), None)
        if not run:
            return False
        data["runs"] = [item for item in data["runs"] if item.get("run_id") != run_id]
        session_out = _session_dir(session_id)
        for image in run.get("images", []):
            if isinstance(image, dict):
                _delete_output_file(image.get("file"), session_out)
        save_history(data, session_id)
        return True


def _delete_output_file(file_name: str | None, session_out: Path) -> None:
    if not file_name:
        return
    try:
        output_root = OUTPUT_DIR.resolve()
        target = (session_out / Path(file_name).name).resolve()
        target.relative_to(output_root)
    except (OSError, ValueError):
        return
    if target.is_file():
        target.unlink(missing_ok=True)


def _result_image_info(path: Path, session_id: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "file": path.name,
        "url": f"/output/{session_id}/{path.name}",
    }
    candidates = [path]
    if not path.is_absolute():
        candidates.append(_session_dir(session_id) / path)

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            info.update(image_file_metadata(candidate))
        except OSError:
            pass
        break

    return info


def image_file_metadata(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    width, height = _image_dimensions(data)
    return {
        "file": path.name,
        "bytes": len(data),
        "size_label": _format_bytes(len(data)),
        "width": width,
        "height": height,
        "dimensions_label": f"{width}x{height}" if width and height else "未知尺寸",
    }


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}".rstrip("0").rstrip(".")
        size /= 1024
    return f"{value} B"


def _image_dimensions(data: bytes) -> tuple[int | None, int | None]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])

    if data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_dimensions(data)
    return None, None


def _jpeg_dimensions(data: bytes) -> tuple[int | None, int | None]:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index:index + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height = int.from_bytes(data[index + 3:index + 5], "big")
            width = int.from_bytes(data[index + 5:index + 7], "big")
            return width, height
        index += segment_length
    return None, None


def _webp_dimensions(data: bytes) -> tuple[int | None, int | None]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None, None

    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return None, None


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=7860, reload=True)
