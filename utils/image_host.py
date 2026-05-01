from __future__ import annotations

import mimetypes
from pathlib import Path

import requests


IMAGE16_BASE_URL = "https://i.111666.best"
IMAGE16_USER_AGENT = "curl/8.18.0"


def _headers(token: str) -> dict[str, str]:
    return {"User-Agent": IMAGE16_USER_AGENT, "Auth-Token": token}


def _image_id_from_src(src: str) -> str:
    image_id = src.rstrip("/").split("/")[-1]
    if not image_id:
        raise RuntimeError("Image16 upload response did not include an image id")
    return image_id


def upload_to_image16(image_path: Path, token: str, timeout: int = 30) -> dict[str, str]:
    if not image_path.is_file():
        raise ValueError(f"Reference image file not found: {image_path}")

    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    with image_path.open("rb") as image_file:
        files = {"image": (image_path.name, image_file, content_type)}
        response = requests.post(
            f"{IMAGE16_BASE_URL}/image",
            headers=_headers(token),
            files=files,
            timeout=timeout,
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"Image16 upload failed: invalid JSON response ({response.status_code})") from exc

    if response.status_code != 200 or not payload.get("ok"):
        raise RuntimeError(f"Image16 upload failed: {response.status_code} {response.text}")

    image_id = _image_id_from_src(str(payload.get("src") or ""))
    return {
        "url": f"{IMAGE16_BASE_URL}/image/{image_id}",
        "image_id": image_id,
    }


def delete_from_image16(image_id: str, token: str, timeout: int = 30) -> bool:
    response = requests.delete(
        f"{IMAGE16_BASE_URL}/image/{image_id}",
        headers=_headers(token),
        timeout=timeout,
    )
    if response.status_code != 200:
        return False
    try:
        payload = response.json()
    except Exception:
        return '"ok":true' in response.text.lower()
    return bool(payload.get("ok"))
