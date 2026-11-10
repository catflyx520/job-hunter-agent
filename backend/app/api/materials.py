"""F4 Cover letter 与申请问答。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.fetch import FetchError
from app.core.i18n import tr
from app.llm.base import LLMError
from app.materials.images import MAX_IMAGE_BYTES, MAX_IMAGES, ImageError, validate_images
from app.materials.service import MaterialError, MaterialRequest, create_material, similar_answers
from app.models import Material, MaterialImage
from app.rag.retrieve import evidence_texts

router = APIRouter(prefix="/api", tags=["materials"])


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    mime: str
    size_bytes: int
    width: int
    height: int


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID | None
    kind: Literal["cover_letter", "qa"]
    question: str | None
    requirements: str | None
    jd_source: str
    resume_id: uuid.UUID | None  # 履历版本删除后为空
    facts_used: list[str] | None
    status: str
    output_text: str | None
    edited_text: str | None
    needs_confirmation: list[dict[str, Any]] | None
    citations: list[dict[str, Any]] | None
    provider_kind: str
    model: str
    error: str | None
    created_at: datetime
    updated_at: datetime
    images: list[ImageOut] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)


class MaterialEdit(BaseModel):
    edited_text: str | None = Field(None, max_length=50_000)


def _out(db: Session, m: Material) -> MaterialOut:
    out = MaterialOut.model_validate(m)
    out.evidence = evidence_texts(db, [i for c in (m.citations or []) for i in c.get("chunk_ids", [])], m.resume_id)
    return out


def _get(db: Session, material_id: uuid.UUID) -> Material:
    m = db.get(Material, material_id)
    if m is None:
        raise HTTPException(404, tr("找不到这份草稿"))
    return m


@router.post("/materials", response_model=MaterialOut, status_code=201)
def create(
    kind: Literal["cover_letter", "qa"] = Form(...),
    job_id: uuid.UUID | None = Form(None),
    url: str | None = Form(None),
    jd_text: str | None = Form(None),
    question: str | None = Form(None),
    requirements: str | None = Form(None),
    language: Literal["en", "zh"] = Form("en"),
    images: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
):
    if len(images) > MAX_IMAGES:
        raise HTTPException(422, tr("最多附 {MAX_IMAGES} 张图片。", MAX_IMAGES=MAX_IMAGES))
    try:
        blobs = [f.file.read(MAX_IMAGE_BYTES + 1) for f in images]
        valid = validate_images(blobs) if blobs else []
        m = create_material(
            db,
            MaterialRequest(kind, job_id, url, jd_text, question, requirements, language, valid),
        )
    except (ImageError, MaterialError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except FetchError as exc:
        raise HTTPException(422, f"{exc}") from exc
    except LLMError as exc:
        raise HTTPException(422 if "图片" in str(exc) else 502, str(exc)) from exc
    return _out(db, m)


@router.get("/materials", response_model=list[MaterialOut])
def list_materials(job_id: uuid.UUID | None = None, kind: str | None = None, db: Session = Depends(get_db)):
    q = select(Material).order_by(Material.created_at.desc()).limit(200)
    if job_id:
        q = q.where(Material.job_id == job_id)
    if kind:
        q = q.where(Material.kind == kind)
    return [_out(db, m) for m in db.scalars(q)]


@router.get("/materials/similar", response_model=list[MaterialOut])
def similar(q: str, db: Session = Depends(get_db)):
    return [_out(db, m) for m in similar_answers(db, q)]


@router.get("/materials/{material_id}", response_model=MaterialOut)
def get_material(material_id: uuid.UUID, db: Session = Depends(get_db)):
    return _out(db, _get(db, material_id))


@router.patch("/materials/{material_id}", response_model=MaterialOut)
def edit_material(material_id: uuid.UUID, body: MaterialEdit, db: Session = Depends(get_db)):
    m = _get(db, material_id)
    m.edited_text = body.edited_text if body.edited_text and body.edited_text != m.output_text else None
    db.flush()
    return _out(db, m)


@router.delete("/materials/{material_id}", status_code=204)
def delete_material(material_id: uuid.UUID, db: Session = Depends(get_db)):
    m = _get(db, material_id)
    folder = get_settings().data_dir / "images" / str(m.id)
    db.delete(m)
    db.flush()
    if folder.is_dir():
        for f in folder.iterdir():
            f.unlink(missing_ok=True)
        folder.rmdir()


@router.get("/materials/{material_id}/download")
def download(material_id: uuid.UUID, db: Session = Depends(get_db)):
    m = _get(db, material_id)
    text = m.edited_text or m.output_text or ""
    name = f"{m.kind}-{m.created_at:%Y%m%d-%H%M}.txt"
    return PlainTextResponse(text, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/materials/{material_id}/images/{position}")
def image(material_id: uuid.UUID, position: int, db: Session = Depends(get_db)):
    img = db.scalar(
        select(MaterialImage).where(MaterialImage.material_id == material_id, MaterialImage.position == position)
    )
    if img is None:
        raise HTTPException(404, tr("找不到这张图片"))
    root = (get_settings().data_dir / "images").resolve()
    path = (get_settings().data_dir / img.file_path).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, tr("找不到这张图片"))
    return FileResponse(path, media_type=img.mime)
