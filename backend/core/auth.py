import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.config import get_env
from backend.core.context import supabase_user_token

security = HTTPBearer(auto_error=False)

SUPABASE_URL = get_env("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = (
    get_env("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_OR_ANON_KEY")
    or get_env("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
)
_AUTH_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_AUTH_RETRIES = 2


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase auth is not configured",
        )

    headers = {
        "Authorization": f"Bearer {credentials.credentials}",
        "apikey": SUPABASE_ANON_KEY,
    }
    url = f"{SUPABASE_URL}/auth/v1/user"
    response: httpx.Response | None = None

    async with httpx.AsyncClient(timeout=_AUTH_TIMEOUT) as client:
        for attempt in range(_AUTH_RETRIES + 1):
            try:
                response = await client.get(url, headers=headers)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException) as exc:
                if attempt >= _AUTH_RETRIES:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Cannot reach Supabase Auth — check network / VPN / project status",
                    ) from exc

    if response is None or response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = response.json()
    return {"id": user["id"], "email": user.get("email")}


async def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """Verify JWT and bind token for Supabase RLS-aware REST calls."""
    user = await get_current_user(credentials)
    if credentials and credentials.credentials:
        supabase_user_token.set(credentials.credentials)
    return user
