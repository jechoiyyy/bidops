"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import SessionLocal, init_db
from .routers.attachments import router as attachments_router
from .routers.metrics import router as metrics_router
from .routers.notices import router as notices_router
from .routers.portals import router as portals_router
from .routers.reviews import notice_router as notice_reviews_router
from .routers.reviews import router as reviews_router
from .routers.runs import router as runs_router
from .services.attachments import seed_default_portals


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as session:
        seed_default_portals(session)
    yield


app = FastAPI(title="BidOps Admin API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Return a lightweight liveness response."""

    return {"status": "ok"}


app.include_router(runs_router)
app.include_router(notices_router)
app.include_router(notice_reviews_router)
app.include_router(reviews_router)
app.include_router(metrics_router)
app.include_router(attachments_router)
app.include_router(portals_router)
