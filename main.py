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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import core as api_core

app = FastAPI(title="APIQIK Image Generator")

OUTPUT_DIR = Path("./output").absolute()
OUTPUT_DIR.mkdir(exist_ok=True)

STATIC_DIR = Path("./static").absolute()

# 任务状态存储：task_id -> {"status": ..., "queue": asyncio.Queue, "total": int, "done": int}
_tasks: dict[str, dict[str, Any]] = {}

# 线程池，用于运行同步 API 调用
_executor = ThreadPoolExecutor(max_workers=50)
_history_lock = threading.RLock()


# ──────────────────────────────────────────────
# 请求体模型
# ──────────────────────────────────────────────

class GenerateRequest(BaseModel):
    api_key: str
    prompt: str
    model: str = api_core.DEFAULT_MODEL
    base_url: str = api_core.DEFAULT_BASE_URL
    size: str | None = None
    ratio: str = "1:1"
    quality: str | None = None
    quality: str | None = None
    output_format: str | None = None
    concurrency: int = 10
    image_urls: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────
# 路由：页面
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/settings", response_class=HTMLResponse)
async def settings():
    html_path = STATIC_DIR / "settings.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────
# 路由：参考图上传
# ──────────────────────────────────────────────

@app.post("/api/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    cf_access_key: str = Form(...),
    cf_secret_key: str = Form(...),
    cf_account_id: str = Form(...),
    cf_bucket: str = Form(...),
    cf_public_url: str = Form(...),
):
    """接收前端上传的参考图，中转至 Cloudflare R2，返回公开 URL。"""
    suffix = Path(file.filename).suffix if file.filename else ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        public_url = await asyncio.to_thread(
            api_core.upload_image_to_r2,
            tmp_path,
            access_key=cf_access_key,
            secret_key=cf_secret_key,
            account_id=cf_account_id,
            bucket_name=cf_bucket,
            public_url_prefix=cf_public_url,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)

    return {"url": public_url}


# ──────────────────────────────────────────────
# 路由：提交生成任务
# ──────────────────────────────────────────────

@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """创建并发生成任务，立即返回 task_id。"""
    if not req.api_key:
        raise HTTPException(status_code=400, detail="api_key 不能为空")
    if not req.prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    if req.concurrency < 1 or req.concurrency > 50:
        raise HTTPException(status_code=400, detail="concurrency 范围 1~50")

    task_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _tasks[task_id] = {
        "status": "running",
        "queue": queue,
        "total": req.concurrency,
        "done": 0,
        "run_id": task_id,
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
async def history():
    return load_history()


@app.delete("/api/history/{run_id}")
async def delete_history(run_id: str):
    deleted = delete_history_run(run_id)
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

    def _push(event: dict):
        """线程安全地将事件推入队列（从同步线程调用）。"""
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def _log(message: str):
        _push({"type": "log", "message": message, "time": _now()})

    def _worker(idx: int) -> dict:
        """单次生成任务，在线程池中运行。"""
        start = time.time()
        clean = "".join(c if c.isalnum() else "_" for c in req.prompt[:30])
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        base_name = f"{clean}_{ts}_{idx + 1}"

        # 根据 output_format 决定后缀
        ext = req.output_format.lower() if req.output_format else "png"
        if ext not in ["png", "jpeg", "webp", "jpg"]:
            ext = "png"
        
        output_path = OUTPUT_DIR / f"{base_name}.{ext}"

        # 防止极低概率的文件名冲突
        counter = 1
        while output_path.exists():
            output_path = OUTPUT_DIR / f"{base_name}({counter}).png"
            counter += 1

        try:
            response = api_core.generate_image(
                api_key=req.api_key,
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
            image_infos = [_result_image_info(p) for p in saved]
            append_history_images(task_id, image_infos)
            _push({
                "type": "result",
                "run_id": task_id,
                "idx": idx + 1,
                "files": [p.name for p in saved],
                "urls": [f"/output/{p.name}" for p in saved],
                "images": image_infos,
                "content": content_text.strip(),
                "duration": round(duration, 1),
            })
            return {"success": True}

        except Exception as e:
            duration = time.time() - start
            set_history_status(task_id, "error")
            _push({
                "type": "error",
                "run_id": task_id,
                "idx": idx + 1,
                "message": str(e),
                "duration": round(duration, 1),
            })
            return {"success": False, "error": str(e)}

    _log(f"开始批量生成，总任务数: {req.concurrency}，模型: {req.model}")

    futures = []
    for i in range(req.concurrency):
        future = loop.run_in_executor(_executor, _worker, i)
        futures.append(future)
        # 错开启动间隔，避免瞬时请求风暴
        await asyncio.sleep(0.3)

    for future in asyncio.as_completed(futures):
        await future
        _tasks[task_id]["done"] += 1
        done = _tasks[task_id]["done"]
        _push({
            "type": "progress",
            "run_id": task_id,
            "done": done,
            "total": req.concurrency,
        })

    _tasks[task_id]["status"] = "completed"
    set_history_status(task_id, "completed", done=_tasks[task_id]["done"])
    _log(f"所有任务已完成，共 {req.concurrency} 个。")
    queue.put_nowait({"type": "done", "run_id": task_id})


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def history_file() -> Path:
    return OUTPUT_DIR / "history.json"


def load_history() -> dict[str, Any]:
    with _history_lock:
        path = history_file()
        if not path.exists():
            return {"runs": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"runs": []}
        runs = data.get("runs")
        return {"runs": runs if isinstance(runs, list) else []}


def save_history(data: dict[str, Any]) -> None:
    with _history_lock:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = history_file()
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)


def create_history_run(run_id: str, req: GenerateRequest) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    params = req.model_dump(exclude={"api_key"})
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
        data = load_history()
        data["runs"] = [item for item in data["runs"] if item.get("run_id") != run_id]
        data["runs"].insert(0, run)
        save_history(data)
    return run


def append_history_images(run_id: str, images: list[dict[str, Any]]) -> bool:
    if not images:
        return False
    with _history_lock:
        data = load_history()
        for run in data["runs"]:
            if run.get("run_id") != run_id:
                continue
            run.setdefault("images", []).extend(images)
            run["done"] = len(run["images"])
            run["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_history(data)
            return True
    return False


def set_history_status(run_id: str, status: str, done: int | None = None) -> bool:
    with _history_lock:
        data = load_history()
        for run in data["runs"]:
            if run.get("run_id") != run_id:
                continue
            run["status"] = status
            if done is not None:
                run["done"] = done
            run["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_history(data)
            return True
    return False


def delete_history_run(run_id: str) -> bool:
    with _history_lock:
        data = load_history()
        run = next((item for item in data["runs"] if item.get("run_id") == run_id), None)
        if not run:
            return False
        data["runs"] = [item for item in data["runs"] if item.get("run_id") != run_id]
        for image in run.get("images", []):
            if isinstance(image, dict):
                _delete_output_file(image.get("file"))
        save_history(data)
        return True


def _delete_output_file(file_name: str | None) -> None:
    if not file_name:
        return
    try:
        output_root = OUTPUT_DIR.resolve()
        target = (OUTPUT_DIR / Path(file_name).name).resolve()
        target.relative_to(output_root)
    except (OSError, ValueError):
        return
    if target.is_file() and target.name != history_file().name:
        target.unlink(missing_ok=True)


def _result_image_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "file": path.name,
        "url": f"/output/{path.name}",
    }
    candidates = [path]
    if not path.is_absolute():
        candidates.append(OUTPUT_DIR / path)

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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
