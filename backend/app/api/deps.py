"""Shared FastAPI dependencies for the API layer."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session

# Use as: async def handler(session: SessionDep) -> ...
SessionDep = Annotated[AsyncSession, Depends(get_session)]
