"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from .config import get_settings
from .db import SessionLocal, init_db
from .routers.attachments import router as attachments_router
from .routers.metrics import router as metrics_router
from .routers.notices import router as notices_router
from .routers.portals import router as portals_router
from .routers.profile import router as profile_router
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
app.include_router(profile_router)


class SPAStaticFiles(StaticFiles):
    """Serve built assets and fall back to index.html for client routes."""

    async def get_response(self, path: str, scope) -> Response:  # type: ignore[no-untyped-def]
        request_path = scope.get("path", "")
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code == 404 and not request_path.startswith("/api"):
                return await super().get_response("index.html", scope)
            raise


FRONTEND_DIST = get_settings().bidops_root / "web" / "frontend" / "dist"


def install_frontend(application: FastAPI, directory: Path = FRONTEND_DIST) -> None:
    """Attach the built frontend without making a missing build fatal."""

    index_path = directory / "index.html"
    if directory.is_dir() and index_path.is_file():
        # This mount is deliberately last so all /api routes win first.
        application.mount(
            "/",
            SPAStaticFiles(directory=str(directory), html=True),
            name="frontend",
        )
        return

    @application.get("/{path:path}", include_in_schema=False)
    def missing_frontend(path: str) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "빌드된 프론트엔드가 없습니다. web/frontend에서 npm run build를 실행하십시오.",
                "path": path,
            },
        )


install_frontend(app)
