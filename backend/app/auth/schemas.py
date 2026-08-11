"""Request/response shapes for the auth module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    # bcrypt silently caps at 72 bytes and raises past it -- capped here so
    # an overlong password is a normal 422, not a 500.
    password: str = Field(min_length=8, max_length=72)
    name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class InspectorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str | None
    created_at: datetime
