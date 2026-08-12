"""HTTP endpoints for the ingestion module."""

import hashlib
import logging
import uuid

import sentry_sdk
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from pydantic import EmailStr, TypeAdapter, ValidationError

from app.api.deps import CurrentInspectorDep, OwnedDocumentDep, SessionDep
from app.ingestion import service
from app.ingestion.schemas import DocumentCreate, DocumentDetail, DocumentRead, NotifyEmailUpdate

_email_adapter = TypeAdapter(EmailStr)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["ingestion"])


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: DocumentCreate, current: CurrentInspectorDep, session: SessionDep
) -> DocumentRead:
    """Ingest a document from raw text, owned by the logged-in inspector."""
    document = await service.ingest_document(session, payload, inspector_id=current.id)
    return DocumentRead.model_validate(document)


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    current: CurrentInspectorDep,
    session: SessionDep,
    file: UploadFile = File(..., description="A PDF, or a UTF-8 text file (.txt, .md, .csv)"),
    title: str | None = Form(default=None),
    notify_email: str | None = Form(
        default=None, description="Optional -- opts this report into weekly roadmap reminders."
    ),
) -> DocumentRead:
    """Ingest a file upload, owned by the logged-in inspector. PDFs are sent
    to Document AI for OCR first.
    """
    if notify_email:
        try:
            notify_email = _email_adapter.validate_python(notify_email)
        except ValidationError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="notify_email is not a valid email address.",
            ) from None

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
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("stage", "ocr")
            scope.set_context("upload", {"filename": file.filename})
            sentry_sdk.capture_exception(e)
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
            notify_email=notify_email,
        ),
        inspector_id=current.id,
    )
    return DocumentRead.model_validate(document)


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    current: CurrentInspectorDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[DocumentRead]:
    """The logged-in inspector's own documents -- never anyone else's."""
    documents = await service.list_documents(session, inspector_id=current.id, limit=limit)
    return [DocumentRead.model_validate(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(document: OwnedDocumentDep, session: SessionDep) -> DocumentDetail:
    # OwnedDocumentDep's lookup doesn't load chunks -- DocumentDetail needs
    # them, so they're fetched only once ownership is already confirmed.
    await session.refresh(document, attribute_names=["chunks"])
    return DocumentDetail.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document: OwnedDocumentDep, session: SessionDep) -> None:
    await service.delete_document(session, document.id)


@router.patch("/{document_id}/notify-email", response_model=DocumentRead)
async def update_notify_email(
    document: OwnedDocumentDep, payload: NotifyEmailUpdate, session: SessionDep
) -> DocumentRead:
    """Inspector correction: the homeowner's email is typed once at upload
    time, before the report exists, so this is the only way to fix a typo
    or add/remove it afterwards. Owner-only, unlike the unsubscribe route
    below -- this one's reached from the inspector's own report view.
    """
    document = await service.set_notify_email(session, document, payload.notify_email)
    return DocumentRead.model_validate(document)


@router.delete("/{document_id}/notify-email", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(document_id: uuid.UUID, session: SessionDep) -> None:
    """The unsubscribe link every weekly roadmap reminder email includes --
    see app/notifications/service.py. Deliberately excluded from
    CurrentInspectorDep/OwnedDocumentDep: this is clicked by a homeowner
    from an email, and homeowners don't have inspector accounts. Same trust
    model as the report link itself -- an unguessable id, no login.
    """
    if not await service.clear_notify_email(session, document_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
