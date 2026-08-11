"""OAuth/OIDC client registration for Sign in with Google.

Google publishes an OpenID Connect discovery document, so it gets authlib's
`server_metadata_url` registration and, via
`StarletteOAuth2App.authorize_access_token`, an already-verified ID token
back in `token["userinfo"]` -- no hand-rolled JWT verification here.
"""

from authlib.integrations.starlette_client import OAuth

from app.core.config import settings

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def provider_configured(name: str) -> bool:
    """Whether a provider has real credentials, not just a registration.

    Google is registered above unconditionally (so `oauth.google` always
    resolves), but with blank credentials by default -- this is the guard
    the login route checks before ever redirecting a user to Google with
    an empty client id.
    """
    if name == "google":
        return bool(settings.google_client_id and settings.google_client_secret)
    return False
