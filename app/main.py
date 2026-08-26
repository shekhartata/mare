from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.mongo.client import close_client, ping


@asynccontextmanager
async def lifespan(app: FastAPI):
    ping()
    yield
    close_client()


app = FastAPI(
    title="Mongo Adaptive Retrieval Engine",
    description="MongoDB-native alternative/complement to conventional RAG.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=False)
