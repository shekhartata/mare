from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.config import Settings, get_settings
from app.constants import AGENT_DB, RAG_DB, RAW_DB

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_client: MongoClient | None = None


def get_client(settings: Settings | None = None) -> MongoClient:
    global _client
    settings = settings or get_settings()
    if not settings.mongodb_uri:
        raise RuntimeError("MONGODB_URI is not set. Copy .env.example to .env.")
    if _client is None:
        _client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=15000)
    return _client


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def raw_db(client: MongoClient | None = None) -> Database:
    return (client or get_client())[RAW_DB]


def agent_db(client: MongoClient | None = None) -> Database:
    return (client or get_client())[AGENT_DB]


def rag_db(client: MongoClient | None = None) -> Database:
    return (client or get_client())[RAG_DB]


def collection(db_name: str, name: str, client: MongoClient | None = None) -> Collection:
    return (client or get_client())[db_name][name]


def ping() -> dict[str, Any]:
    return get_client().admin.command("ping")


def server_version() -> str:
    info = get_client().server_info()
    return str(info.get("version", ""))
