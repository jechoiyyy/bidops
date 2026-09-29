"""Browse a restored snapshot using its original image, without starting workers.

Mounted only by transfer.py; normal production startup is unchanged. The normal
lifespan still validates PostgreSQL revision and MinIO configuration.
"""

from starlette.responses import JSONResponse

from app.main import app
from app.runtime import ApplicationRuntime


class BrowseRuntime(ApplicationRuntime):
    def start(self):
        # Construct the normal read-side services, but do not recover queues,
        # start threads, enqueue work, or start a scheduler.
        pass


app.state.runtime_factory = BrowseRuntime


@app.middleware("http")
async def browse_only(request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        return JSONResponse(
            {"detail": "이전본 열람 모드에서는 변경 작업을 실행하지 않습니다."},
            status_code=405,
            headers={"Allow": "GET, HEAD, OPTIONS"},
        )
    return await call_next(request)
