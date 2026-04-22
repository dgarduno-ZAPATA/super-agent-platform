from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from api.dependencies import (
    get_audit_log_service,
    get_current_user,
    get_knowledge_ingestion_service,
    get_knowledge_repository,
)
from core.services.audit_log_service import AuditLogService
from core.services.knowledge_ingestion_service import KnowledgeIngestionService

router = APIRouter(prefix="/api/v1", tags=["knowledge"])

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt", ".docx"}


@router.post("/admin/knowledge/upload")
async def upload_knowledge_file(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    source_label: Annotated[str, Form(...)],
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    ingestion_service: Annotated[
        KnowledgeIngestionService, Depends(get_knowledge_ingestion_service)
    ],
    audit_log_service: Annotated[AuditLogService, Depends(get_audit_log_service)],
) -> dict[str, object]:
    del current_user
    filename = file.filename or ""
    extension = ""
    if "." in filename:
        extension = f".{filename.rsplit('.', 1)[1].lower()}"
    if extension not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported_file_type",
        )

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_too_large",
        )

    if not source_label.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_source_label")

    result = await ingestion_service.ingest_file(
        file_bytes=file_bytes,
        filename=filename,
        source_label=source_label.strip(),
    )
    client_host = request.client.host if request.client is not None else None
    await audit_log_service.log(
        actor="admin",
        action="knowledge_upload",
        resource_type="knowledge_source",
        resource_id=source_label.strip(),
        details={
            "filename": filename,
            "chunks_created": int(result.get("chunks_created", 0)),
        },
        ip_address=client_host,
        user_agent=request.headers.get("user-agent"),
    )
    return result


@router.get("/admin/knowledge/sources")
async def list_knowledge_sources(
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
) -> dict[str, object]:
    del current_user
    repo = get_knowledge_repository()
    sources = await repo.list_sources()
    return {
        "sources": [
            {
                "source_label": item.source_label,
                "chunk_count": item.chunk_count,
                "indexed_at": item.indexed_at.isoformat() if item.indexed_at else None,
            }
            for item in sources
        ]
    }


@router.delete("/admin/knowledge/sources/{source_label}")
async def delete_knowledge_source(
    source_label: str,
    request: Request,
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    ingestion_service: Annotated[
        KnowledgeIngestionService, Depends(get_knowledge_ingestion_service)
    ],
    audit_log_service: Annotated[AuditLogService, Depends(get_audit_log_service)],
) -> dict[str, object]:
    del current_user
    deleted = await ingestion_service.delete_source(source_label=source_label)
    client_host = request.client.host if request.client is not None else None
    await audit_log_service.log(
        actor="admin",
        action="knowledge_delete",
        resource_type="knowledge_source",
        resource_id=source_label,
        details={"chunks_deleted": deleted},
        ip_address=client_host,
        user_agent=request.headers.get("user-agent"),
    )
    return {"source_label": source_label, "chunks_deleted": deleted}
