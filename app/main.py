import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.generic_ui import router as generic_ui_router
from app.api.routes import router
from app.mongo.client import close_client, ping

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ping()
    except Exception:
        log.warning(
            "Demo MongoDB is not reachable. The connect page can still index another cluster."
        )
    yield
    close_client()


app = FastAPI(
    title="Mongo Adaptive Retrieval Engine",
    description="MongoDB-native alternative/complement to conventional RAG.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
app.include_router(generic_ui_router)


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=False)
