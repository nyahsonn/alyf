"""HTTP endpoints for the ingestion module."""

import hashlib
import logging
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status

from app.api.deps import SessionDep
from app.ingestion import service
from app.ingestion.schemas import DocumentCreate, DocumentDetail, DocumentRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["ingestion"])


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(payload: DocumentCreate, session: SessionDep) -> DocumentRead:
    """Ingest a document from raw text."""
    document = await service.ingest_document(session, payload)
    return DocumentRead.model_validate(document)


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    session: SessionDep,
    file: UploadFile = File(..., description="A PDF, or a UTF-8 text file (.txt, .md, .csv)"),
    title: str | None = Form(default=None),
) -> DocumentRead:
    """Ingest a file upload. PDFs are sent to Document AI for OCR first."""
    raw = await file.read()

    try:
        content, source_type = await service.text_from_upload(raw)
    except service.UnsupportedUpload as e:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(e)
        ) from None
    except service.UploadTooLarge as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e)
        ) from None
    except service.OcrFailed as e:
        # The underlying message can name the project and processor, so it is
        # logged rather than returned to whoever posted the file.
        logger.error("OCR failed for upload %r: %s", file.filename, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not extract text from the PDF. See the server log for details.",
        ) from None

    if not content.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No text could be read from this PDF -- it may be blank."
                if source_type == "pdf"
                else "The uploaded file is empty."
            ),
        )

    document = await service.ingest_document(
        session,
        DocumentCreate(
            title=title or file.filename or "Untitled upload",
            content=content,
            source_type=source_type,
            source_ref=file.filename,
            file_bytes=raw,
            file_sha256=hashlib.sha256(raw).hexdigest(),
        ),
    )
    return DocumentRead.model_validate(document)


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[DocumentRead]:
    documents = await service.list_documents(session, limit=limit)
    return [DocumentRead.model_validate(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: uuid.UUID, session: SessionDep) -> DocumentDetail:
    document = await service.get_document_with_chunks(session, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentDetail.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, session: SessionDep) -> None:
    if not await service.delete_document(session, document_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
