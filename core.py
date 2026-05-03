#!/usr/bin/env python3
"""Generate images with the APIQIK OpenAI-compatible image API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import boto3
    from botocore.config import Config
except ImportError:
    boto3 = None
    Config = None


DEFAULT_BASE_URL = "https://value.apiqik.online"
DEFAULT_IMAGE_API_BASE = "https://img.apiqik.online"
DEFAULT_MODEL = "gpt-image-2-flatfee"
SUPPORTED_RATIOS = {
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
}
SUPPORTED_SIZES = {
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "2048x2048",
    "2048x1152",
    "3840x2160",
    "2160x3840",
}
SUPPORTED_QUALITIES = {"high"}


def normalize_base_url(base_url: str) -> str:
    """Return the upstream base URL in the shape used by APIQIK's web client."""
    return f"{base_url.rstrip('/')}/"


def is_http_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def load_env_value(name: str, env_path: Path = Path(".env")) -> str | None:
    """Read one value from the process environment or a simple .env file."""
    if os.getenv(name):
        return os.environ[name]

    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        if key.strip() != name:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value

    return None





def build_payload_chat(
    *,
    prompt: str,
    model: str,
    image_urls: list[str],
    n: int = 1,
    size: str = "1024x1024",
    group: str = "codex-image",
) -> dict[str, Any]:
    """Build the /v1/chat/completions request body."""
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt.strip()}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})

    payload: dict[str, Any] = {
        "model": model,
        "group": group,
        "messages": [{"role": "user", "content": content}],
        "image_config": {
            "n": n,
            "size": size
        },
        "stream": False,
        "temperature": 0.7,
        "top_p": 1,
    }
    return payload


def build_image_request(
    *,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    image_urls: list[str] | None = None,
    size: str | None = None,
    quality: str | None = None,
    background: str | None = None,
    output_format: str | None = None,
    image_api_base: str = DEFAULT_IMAGE_API_BASE,
) -> tuple[str, dict[str, Any]]:
    """Build the APIQIK web image request for generation or image edits."""
    images = [url for url in image_urls or [] if url]
    endpoint_name = "images-edits" if images else "images-generations"
    endpoint = f"{image_api_base.rstrip('/')}/api/ai-image/{endpoint_name}"

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt.strip(),
    }
    if images:
        payload["image"] = images
    if size:
        payload["size"] = size
    if quality:
        payload["quality"] = quality
    if background:
        payload["background"] = background
    if output_format:
        payload["output_format"] = output_format

    return endpoint, {
        "baseUrl": normalize_base_url(base_url),
        "apiKey": api_key,
        "payload": payload,
    }


def extract_url_from_markdown(text: str) -> str | None:
    """Extract the first image URL from Markdown like ![alt](url)."""
    import re
    # Match ![...](url)
    match = re.search(r"!\[.*?\]\((https?://.*?)\)", text)
    if match:
        return match.group(1)
    # Fallback to any http URL in the text
    match = re.search(r"(https?://[^\s\)\>]+(?:\.png|\.jpg|\.jpeg|\.webp))", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def generate_image(
    *,
    api_key: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    n: int = 1,
    size: str | None = None,
    ratio: str | None = "1:1",
    quality: str | None = None,
    background: str | None = None,
    output_format: str | None = None,
    image_urls: list[str] | None = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = 600,
    group: str = "codex-image",
) -> dict[str, Any]:
    """Call APIQIK's web image generation/edit endpoint."""
    endpoint, payload = build_image_request(
        api_key=api_key,
        base_url=base_url,
        prompt=prompt,
        model=model,
        image_urls=image_urls or [],
        size=size,
        quality=quality,
        background=background,
        output_format=output_format,
    )

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API request failed with HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"API request failed: {error.reason}") from error


def upload_image_to_r2(
    image_path: Path,
    *,
    access_key: str,
    secret_key: str,
    account_id: str,
    bucket_name: str,
    public_url_prefix: str,
    timeout: int = 300,
) -> str:
    """Upload a local image file to Cloudflare R2 and return the public image URL."""
    if boto3 is None:
        raise RuntimeError("boto3 is not installed. Please run 'pip install boto3'")
    
    if not image_path.is_file():
        raise ValueError(f"Reference image file not found: {image_path}")

    s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )

    # 创建唯一文件名
    timestamp = int(time.time() * 1000)
    file_key = f"apiqik_uploads/{timestamp}_{image_path.name}"
    
    # 简单的 ContentType 映射
    content_type = "image/png"
    if image_path.suffix.lower() in [".jpg", ".jpeg"]:
        content_type = "image/jpeg"
    elif image_path.suffix.lower() == ".webp":
        content_type = "image/webp"

    try:
        s3_client.upload_file(
            str(image_path),
            bucket_name,
            file_key,
            ExtraArgs={"ContentType": content_type}
        )
    except Exception as e:
        raise RuntimeError(f"Cloudflare R2 upload failed: {e}")

    return f"{public_url_prefix.rstrip('/')}/{file_key}"
 
 
def delete_image_from_r2(
    file_key: str,
    *,
    access_key: str,
    secret_key: str,
    account_id: str,
    bucket_name: str,
    timeout: int = 60,
) -> bool:
    """从 Cloudflare R2 中删除指定对象。"""
    if boto3 is None:
        return False
    
    s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", connect_timeout=timeout, read_timeout=timeout),
        region_name="auto",
    )
    
    try:
        s3_client.delete_object(Bucket=bucket_name, Key=file_key)
        return True
    except Exception:
        return False


def load_json_from_r2(
    *,
    object_key: str,
    access_key: str,
    secret_key: str,
    account_id: str,
    bucket_name: str,
    timeout: int = 60,
) -> Any | None:
    """Load a JSON object from Cloudflare R2. Return None when the object is missing."""
    if boto3 is None:
        raise RuntimeError("boto3 is not installed. Please run 'pip install boto3'")

    s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", connect_timeout=timeout, read_timeout=timeout),
        region_name="auto",
    )

    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
    except Exception as exc:
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if error_code in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise RuntimeError(f"Cloudflare R2 JSON load failed: {exc}") from exc

    body = response["Body"].read().decode("utf-8")
    return json.loads(body)


def save_json_to_r2(
    *,
    object_key: str,
    data: Any,
    access_key: str,
    secret_key: str,
    account_id: str,
    bucket_name: str,
    timeout: int = 60,
) -> None:
    """Save a JSON object to Cloudflare R2."""
    if boto3 is None:
        raise RuntimeError("boto3 is not installed. Please run 'pip install boto3'")

    s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", connect_timeout=timeout, read_timeout=timeout),
        region_name="auto",
    )
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=object_key,
            Body=body,
            ContentType="application/json; charset=utf-8",
        )
    except Exception as exc:
        raise RuntimeError(f"Cloudflare R2 JSON save failed: {exc}") from exc


def resolve_image_inputs(
    image_inputs: list[str],
    *,
    env_path: Path = Path(".env"),
    timeout: int = 300,
) -> list[str]:
    """Convert URL/local reference image inputs into URLs accepted by APIQIK."""
    image_urls: list[str] = []
    
    # 预加载 R2 配置
    r2_config = {
        "access_key": load_env_value("CF_ACCESS_KEY", env_path),
        "secret_key": load_env_value("CF_SECRET_KEY", env_path),
        "account_id": load_env_value("CF_ACCOUNT_ID", env_path),
        "bucket_name": load_env_value("CF_BUCKET", env_path),
        "public_url_prefix": load_env_value("CF_PUBLIC_URL", env_path),
    }

    for image_input in image_inputs:
        if is_http_url(image_input):
            image_urls.append(image_input)
            continue

        image_path = Path(image_input).expanduser()
        if not image_path.is_file():
            raise ValueError(f"Reference image is not a URL or local file: {image_input}")
        
        # 检查 R2 配置是否完整
        missing = [k for k, v in r2_config.items() if not v]
        if missing:
            raise ValueError(f"Missing R2 configuration in .env: {', '.join(missing)}")

        image_urls.append(
            upload_image_to_r2(
                image_path,
                **r2_config,
                timeout=timeout,
            )
        )
    return image_urls


def save_generation_result(
    response: dict[str, Any],
    output_path: Path,
    *,
    on_download_attempt: Callable[[int, int, str, Exception | None], None] | None = None,
) -> list[Path]:
    """Save all generated images from APIQIK web or chat-shaped responses."""
    saved_paths = []

    data = response.get("data")
    if isinstance(data, list):
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                continue

            current_path = _get_indexed_path(output_path, i + 1 if len(data) > 1 else 0)
            url = item.get("url")
            if isinstance(url, str) and url:
                saved_paths.append(_download_and_save(url, current_path, on_attempt=on_download_attempt))
                continue

            b64_json = item.get("b64_json") or item.get("base64")
            if isinstance(b64_json, str) and b64_json:
                saved_paths.append(_save_base64_image(b64_json, current_path))

    if saved_paths:
        return saved_paths

    for key in ("url", "image_url"):
        url = response.get(key)
        if isinstance(url, str) and url:
            return [_download_and_save(url, output_path, on_attempt=on_download_attempt)]
    
    # Chat Completions response
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        all_urls = []
        for choice in choices:
            content = choice.get("message", {}).get("content", "")
            # 提取 Markdown 中所有的图片链接
            import re
            urls = re.findall(r"!\[.*?\]\((https?://.*?)\)", content)
            if not urls:
                # 备选正则
                urls = re.findall(r"(https?://[^\s\)\>]+(?:\.png|\.jpg|\.jpeg|\.webp))", content, re.IGNORECASE)
            all_urls.extend(urls)
        
        for i, url in enumerate(all_urls):
            current_path = _get_indexed_path(output_path, i + 1 if len(all_urls) > 1 else 0)
            saved_paths.append(_download_and_save(url, current_path, on_attempt=on_download_attempt))

    if not saved_paths:
        raise ValueError(f"No images found in response: {json.dumps(response)[:200]}...")
    
    return saved_paths


def describe_image_references(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Return image references from a generation response without saving them."""
    refs: list[dict[str, Any]] = []

    data = response.get("data")
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if isinstance(url, str) and url:
                refs.append({"kind": "url", "value": url, "index": len(refs) + 1})
                continue
            b64_json = item.get("b64_json") or item.get("base64")
            if isinstance(b64_json, str) and b64_json:
                refs.append({"kind": "base64", "value": b64_json, "index": len(refs) + 1})

    if refs:
        return refs

    for key in ("url", "image_url"):
        url = response.get(key)
        if isinstance(url, str) and url:
            return [{"kind": "url", "value": url, "index": 1}]

    choices = response.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            content = choice.get("message", {}).get("content", "")
            if not isinstance(content, str):
                continue
            urls = re.findall(r"!\[.*?\]\((https?://.*?)\)", content)
            if not urls:
                urls = re.findall(
                    r"(https?://[^\s\)>]+(?:\.png|\.jpg|\.jpeg|\.webp))",
                    content,
                    re.IGNORECASE,
                )
            for url in urls:
                refs.append({"kind": "url", "value": url, "index": len(refs) + 1})

    return refs


def _save_base64_image(value: str, output_path: Path) -> Path:
    """Decode a base64 image field and save it to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if "," in value and value.split(",", 1)[0].startswith("data:"):
        value = value.split(",", 1)[1]
    output_path.write_bytes(base64.b64decode(value))
    return output_path


def _get_indexed_path(base_path: Path, index: int) -> Path:
    """Helper to add an index suffix to a filename if needed."""
    if index <= 0:
        return base_path
    return base_path.with_name(f"{base_path.stem}_{index}{base_path.suffix}")


def _download_and_save(
    url: str,
    output_path: Path,
    *,
    attempts: int = 3,
    on_attempt: Callable[[int, int, str, Exception | None], None] | None = None,
) -> Path:
    """Helper to download a URL and save to path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    total_attempts = max(1, attempts)
    for attempt in range(1, total_attempts + 1):
        if on_attempt:
            on_attempt(attempt, total_attempts, url, None)
        try:
            request = Request(url, headers={"User-Agent": "apiqik-image-client/1.0"})
            with urlopen(request, timeout=300) as response_obj:
                output_path.write_bytes(response_obj.read())
            return output_path
        except Exception as error:
            last_error = error
            if on_attempt:
                on_attempt(attempt, total_attempts, url, error)
            if attempt < total_attempts:
                time.sleep(min(2, attempt))

    raise RuntimeError(f"Image download failed after {total_attempts} attempts: {url} ({last_error})")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an image with APIQIK's OpenAI-compatible API."
    )
    parser.add_argument("prompt", nargs="?", help="Image prompt")
    parser.add_argument("--prompt", dest="prompt_option", help="Image prompt")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="Reference image URL or local file path",
    )
    parser.add_argument(
        "--image-url",
        action="append",
        default=[],
        help="Reference image URL or local file path, same as --image",
    )
    parser.add_argument("--output", "-o", default="generated_apiqik.png")
    parser.add_argument("--model", default=os.getenv("APIQIK_IMAGE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.getenv("APIQIK_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--size", default="1024x1024", choices=sorted(SUPPORTED_SIZES))
    parser.add_argument("--ratio", default="1:1", choices=sorted(SUPPORTED_RATIOS))
    parser.add_argument("--quality", default="high", choices=sorted(SUPPORTED_QUALITIES))
    parser.add_argument("--n", type=int, default=1, help="Number of images to generate")
    parser.add_argument("--timeout", type=int, default=120)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    prompt = args.prompt_option or args.prompt
    if not prompt:
        print("Missing prompt. Example: python core.py \"一只猫在月球上\"", file=sys.stderr)
        return 2

    api_key = load_env_value("APIQIK_KEY", Path(args.env_file))
    if not api_key:
        print("Missing APIQIK_KEY in environment or .env", file=sys.stderr)
        return 2

    try:
        image_urls = resolve_image_inputs(
            args.image + args.image_url,
            env_path=Path(args.env_file),
            timeout=args.timeout,
        )
        response = generate_image(
            api_key=api_key,
            prompt=prompt,
            model=args.model,
            n=args.n,
            size=args.size,
            ratio=args.ratio,
            quality=args.quality,
            image_urls=image_urls,
            base_url=args.base_url,
            timeout=args.timeout,
        )
        output_path = save_generation_result(response, Path(args.output))
    except (RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    data = response.get("data") or []
    if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get("url"):
        print(f"Image URL: {data[0]['url']}")
    print(f"Saved image: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
