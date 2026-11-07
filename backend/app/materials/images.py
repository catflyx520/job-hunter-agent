"""截图验证（SPEC F4，参考旧项目 materials_images.py 的规则）。

PNG / JPG / WebP，最多 6 张，每张 5MB、合计 12MB。以档案内容判断格式，拒绝伪装格式、SVG、动图、超大解析度。
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

MAX_IMAGES = 6
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
FORMATS = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"), "WEBP": ("image/webp", ".webp")}


class ImageError(ValueError):
    pass


@dataclass
class ValidImage:
    data: bytes
    mime: str
    ext: str
    width: int
    height: int
    sha256: str


def validate_images(blobs: list[bytes]) -> list[ValidImage]:
    if len(blobs) > MAX_IMAGES:
        raise ImageError(f"最多附 {MAX_IMAGES} 张图片。")
    total = 0
    out = []
    for i, raw in enumerate(blobs, start=1):
        if not raw:
            raise ImageError(f"第 {i} 张图片是空的。")
        if len(raw) > MAX_IMAGE_BYTES:
            raise ImageError(f"第 {i} 张图片超过 5MB。")
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise ImageError("图片合计超过 12MB。")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as img:
                    fmt = img.format
                    width, height = img.size
                    if fmt not in FORMATS:
                        raise ImageError(f"第 {i} 张不是 PNG / JPG / WebP（不接受 SVG、GIF、PDF 等）。")
                    if getattr(img, "n_frames", 1) != 1:
                        raise ImageError(f"第 {i} 张是动图，请使用静态截图。")
                    if min(width, height) < 1 or max(width, height) > 12000 or width * height > 20_000_000:
                        raise ImageError(f"第 {i} 张解析度过大，请裁切到相关问题后再上传。")
                    img.load()
        except ImageError:
            raise
        except Exception as exc:  # noqa: BLE001 - Pillow 会丢各种例外
            raise ImageError(f"第 {i} 张图片损坏或无法读取，请重新截图。") from exc
        mime, ext = FORMATS[fmt]
        out.append(ValidImage(raw, mime, ext, width, height, hashlib.sha256(raw).hexdigest()))
    return out


def save_images(data_dir: Path, material_id: str, images: list[ValidImage]) -> list[tuple[int, str, ValidImage]]:
    """存到 data/images/<material_id>/<n>.<ext>，回传 (position, 相对路径, image)。"""
    folder = data_dir / "images" / material_id
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for pos, img in enumerate(images, start=1):
        rel = Path("images") / material_id / f"{pos}{img.ext}"
        with (data_dir / rel).open("xb") as f:
            f.write(img.data)
        saved.append((pos, rel.as_posix(), img))
    return saved
