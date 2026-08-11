"""Shared FastAPI dependencies for the API layer."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Inspector
from app.auth.service import decode_access_token
from app.core.config import settings
from app.core.database import get_session
from app.ingestion import service as ingestion_service
from app.ingestion.models import Document

# Use as: async def handler(session: SessionDep) -> ...
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_inspector(request: Request, session: SessionDep) -> Inspector:
    """The logged-in inspector, from the session cookie set by
    POST /auth/login or /auth/signup. 401 for anything wrong with it --
    missing, tampered, expired, or naming an inspector that no longer
    exists -- there's nothing about *why* that should reach the client
    (see decode_access_token's docstring).
    """
    token = request.cookies.get(settings.auth_cookie_name)
    inspector_id = decode_access_token(token) if token else None
    if inspector_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")

    inspector = await session.get(Inspector, inspector_id)
    if inspector is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    return inspector


# Use as: async def handler(current: CurrentInspectorDep) -> ...
CurrentInspectorDep = Annotated[Inspector, Depends(get_current_inspector)]


async def get_owned_document(
    document_id: uuid.UUID, current: CurrentInspectorDep, session: SessionDep
) -> Document:
    """A document, only if it belongs to the logged-in inspector.

    404, not 403, on a mismatch -- same response either way, so a request
    can't tell "this document doesn't exist" apart from "it exists but
    isn't yours." Every document-scoped route depends on this instead of
    doing its own lookup, so the ownership check lives in exactly one place.
    """
    document = await ingestion_service.get_document(session, document_id)
    if document is None or document.inspector_id != current.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


# Use as: async def handler(document: OwnedDocumentDep) -> ...
OwnedDocumentDep = Annotated[Document, Depends(get_owned_document)]
