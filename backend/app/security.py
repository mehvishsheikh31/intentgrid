import secrets

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.config import settings


def client_ip(request: Request) -> str:
    """Real client IP. Behind Render's proxy it is in X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=client_ip)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Temporary guard for owner endpoints. Replaced by JWT in step 6.3."""
    expected = settings.internal_api_key
    ok = bool(expected) and bool(x_api_key) and secrets.compare_digest(
        x_api_key.encode(), expected.encode()
    )
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please wait a minute and try again."},
        headers={"Retry-After": "60"},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side."})
