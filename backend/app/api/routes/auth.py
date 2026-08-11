"""HTTP endpoints for the auth module."""

import logging
import uuid

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentInspectorDep, SessionDep
from app.auth import service
from app.auth.oauth import oauth, provider_configured
from app.auth.schemas import InspectorRead, LoginRequest, SignupRequest
from app.auth.service import OAuthEmailMissingError
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _set_session_cookie(response: Response, inspector_id: uuid.UUID) -> None:
    token = service.create_access_token(inspector_id)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        # SameSite=None is required for the cookie to be sent on cross-site
        # fetch() calls (the frontend and backend live on different domains
        # in production, e.g. vercel.app / up.railway.app). Browsers reject
        # SameSite=None without Secure, so this only flips once cookie_secure
        # (HTTPS) is also on -- local http:// dev keeps the Lax default.
        samesite="none" if settings.cookie_secure else "lax",
        max_age=settings.jwt_expires_days * 24 * 60 * 60,
        path="/",
    )


@router.post("/signup", response_model=InspectorRead, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, response: Response, session: SessionDep) -> InspectorRead:
    try:
        inspector = await service.create_inspector(session, payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from None

    _set_session_cookie(response, inspector.id)
    return InspectorRead.model_validate(inspector)


@router.post("/login", response_model=InspectorRead)
async def login(payload: LoginRequest, response: Response, session: SessionDep) -> InspectorRead:
    inspector = await service.authenticate(session, payload.email, payload.password)
    if inspector is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password."
        )

    _set_session_cookie(response, inspector.id)
    return InspectorRead.model_validate(inspector)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(key=settings.auth_cookie_name, path="/")


@router.get("/me", response_model=InspectorRead)
async def me(current: CurrentInspectorDep) -> InspectorRead:
    return InspectorRead.model_validate(current)


@router.get("/google/login")
async def google_login(request: Request):
    if not provider_configured("google"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google sign-in isn't configured yet.",
        )
    redirect_uri = f"{settings.backend_base_url}{settings.api_prefix}/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, session: SessionDep) -> RedirectResponse:
    login_url = f"{settings.frontend_base_url}/login"
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        logger.warning("Google OAuth exchange failed", exc_info=True)
        return RedirectResponse(f"{login_url}?error=google_failed")

    userinfo = token.get("userinfo")
    if not userinfo:
        logger.warning("Google OAuth token had no userinfo claims")
        return RedirectResponse(f"{login_url}?error=google_failed")

    try:
        inspector = await service.find_or_create_from_oauth(
            session,
            provider="google",
            provider_user_id=userinfo["sub"],
            email=userinfo.get("email"),
            email_verified=bool(userinfo.get("email_verified")),
            name=userinfo.get("name"),
        )
    except OAuthEmailMissingError:
        return RedirectResponse(f"{login_url}?error=google_no_email")

    redirect = RedirectResponse(f"{settings.frontend_base_url}/upload")
    _set_session_cookie(redirect, inspector.id)
    return redirect
