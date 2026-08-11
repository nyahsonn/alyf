"""Request/response shapes for the ingestion module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)
    source_type: str = Field(default="text", max_length=50)
    source_ref: str | None = Field(default=None, max_length=1000)
    file_bytes: bytes | None = Field(default=None)
    file_sha256: str | None = Field(default=None, max_length=64)
    notify_email: EmailStr | None = Field(default=None)


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    content: str
    word_count: int


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: str
    source_ref: str | None
    status: str
    file_sha256: str | None
    notify_email: str | None
    created_at: datetime


class DocumentDetail(DocumentRead):
    content: str
    chunks: list[ChunkRead] = []
