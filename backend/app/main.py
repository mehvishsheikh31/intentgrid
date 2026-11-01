from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.routers import contact, tickets
from app.security import (
    limiter,
    rate_limit_handler,
    require_api_key,
    unhandled_error_handler,
)

app = FastAPI(title="IntentGrid API")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_methods=["GET", "POST", "PATCH", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

app.include_router(contact.router)
app.include_router(tickets.router, dependencies=[Depends(require_api_key)])


@app.get("/api/health")
def health():
    return {"status": "ok"}
