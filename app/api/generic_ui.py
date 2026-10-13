"""One page: connect, index, optionally ask. The cards stay on the cluster."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.indexing.signals.store import MissingGenericIndex, index_database, load_generic_handlers
from app.llm import get_embedding_model
from app.retrieval.agent_loop import run_agent

router = APIRouter()
_URI = re.compile(r"mongodb(?:\+srv)?://\S+")
_SKIP_DATABASES = {"admin", "local", "config"}

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MARE</title>
  <style>
    body { font: 16px/1.45 system-ui, sans-serif; margin: 0; background: #f6f5f2; color: #1c1917; }
    main { max-width: 36rem; margin: 3.5rem auto; padding: 0 1.25rem 3rem; }
    h1 { font-size: 1.6rem; margin: 0 0 0.35rem; }
    .lead { margin: 0 0 1.25rem; color: #44403c; }
    label { display: block; font-size: 0.85rem; margin: 1rem 0 0.35rem; }
    input, select, textarea, button { font: inherit; width: 100%; box-sizing: border-box; }
    input, select, textarea {
      padding: 0.55rem 0.65rem; border: 1px solid #d6d3d1; border-radius: 6px; background: #fff;
    }
    textarea { min-height: 5.5rem; resize: vertical; }
    button {
      margin-top: 0.75rem; padding: 0.6rem 0.8rem; border: 0; border-radius: 6px;
      background: #1c1917; color: #fff;
    }
    button:disabled { opacity: 0.45; }
    .note { margin-top: 0.8rem; color: #44403c; }
    .answer { white-space: pre-wrap; margin-top: 1rem; }
    section[hidden] { display: none; }
  </style>
</head>
<body>
  <main>
    <h1>MARE</h1>
    <p class="lead">Paste a connection string. MARE indexes that database and saves the cards
    on the cluster. You can ask here, or close the page.</p>
    <label for="uri">Connection string</label>
    <input id="uri" type="password" autocomplete="off" placeholder="mongodb+srv://…">
    <button id="connect" type="button">Connect</button>
    <section id="pick" hidden>
      <label for="database">Database</label>
      <select id="database"></select>
      <label for="limit">Document limit per collection (0 = all)</label>
      <input id="limit" type="number" min="0" value="0">
      <button id="index" type="button">Index</button>
    </section>
    <p id="status" class="note"></p>
    <section id="ask" hidden>
      <label for="question">Question</label>
      <textarea id="question" placeholder="Ask a question about this database"></textarea>
      <button id="submit" type="button">Ask</button>
      <div id="answer" class="answer"></div>
    </section>
  </main>
  <script>
    const uri = document.querySelector("#uri");
    const status = document.querySelector("#status");
    const pick = document.querySelector("#pick");
    const ask = document.querySelector("#ask");
    const database = document.querySelector("#database");

    async function post(path, body) {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(typeof detail === "string" ? detail : "Request failed");
      }
      return payload;
    }

    document.querySelector("#connect").addEventListener("click", async () => {
      status.textContent = "Connecting…";
      pick.hidden = true;
      ask.hidden = true;
      try {
        const payload = await post("/ui/connect", { uri: uri.value });
        database.replaceChildren();
        for (const name of payload.databases) {
          const option = document.createElement("option");
          option.value = name;
          option.textContent = name;
          database.append(option);
        }
        pick.hidden = false;
        status.textContent = payload.databases.length
          ? "Choose a database and index it."
          : "No user databases on this cluster.";
      } catch (error) {
        status.textContent = error.message;
      }
    });

    document.querySelector("#index").addEventListener("click", async () => {
      status.textContent = "Indexing…";
      ask.hidden = true;
      try {
        const payload = await post("/ui/index", {
          uri: uri.value,
          database: database.value,
          limit: Number(document.querySelector("#limit").value || 0),
        });
        const partial = payload.partial.length
          ? " Partial collections: " + payload.partial.join(", ") + "."
          : "";
        status.textContent =
          "Saved " + payload.documents + " documents as " + payload.cards +
          " cards on " + payload.database + "." + partial +
          " You can close this page. The index stays on the cluster.";
        ask.hidden = false;
      } catch (error) {
        status.textContent = error.message;
      }
    });

    document.querySelector("#submit").addEventListener("click", async () => {
      const answer = document.querySelector("#answer");
      answer.textContent = "Asking…";
      try {
        const payload = await post("/ui/ask", {
          uri: uri.value,
          question: document.querySelector("#question").value,
        });
        answer.textContent = payload.answer || "(empty answer)";
      } catch (error) {
        answer.textContent = error.message;
      }
    });
  </script>
</body>
</html>
"""


class ConnectBody(BaseModel):
    uri: str = ""


class IndexBody(BaseModel):
    uri: str = ""
    database: str = ""
    limit: int = Field(default=0, ge=0)


class AskBody(BaseModel):
    uri: str = ""
    question: str = ""


@router.get("/", response_class=HTMLResponse)
def connect_page() -> str:
    return PAGE


@router.post("/ui/connect")
def connect(body: ConnectBody) -> dict:
    client = _open(body.uri)
    try:
        names = [
            name
            for name in client.list_database_names()
            if name not in _SKIP_DATABASES
        ]
    except PyMongoError as exc:
        raise HTTPException(400, _public_error(exc)) from exc
    finally:
        client.close()
    return {"databases": names}


@router.post("/ui/index")
def build_index(body: IndexBody) -> dict:
    if not body.database.strip():
        raise HTTPException(400, "Choose a database.")
    client = _open(body.uri)
    try:
        return index_database(client, body.database.strip(), limit=body.limit or None)
    except PyMongoError as exc:
        raise HTTPException(400, _public_error(exc)) from exc
    finally:
        client.close()


@router.post("/ui/ask")
def ask_saved(body: AskBody) -> dict:
    if not body.question.strip():
        raise HTTPException(400, "Type a question.")
    client = _open(body.uri)
    try:
        session = run_agent(
            body.question.strip(),
            handlers=load_generic_handlers(client, get_embedding_model()),
            persist=False,
            schema_in_prompt=False,
        )
    except MissingGenericIndex as exc:
        raise HTTPException(409, str(exc)) from exc
    except PyMongoError as exc:
        raise HTTPException(400, _public_error(exc)) from exc
    finally:
        client.close()
    return {
        "answer": session.answer,
        "tokens": session.tokens_consumed,
        "elapsed_ms": round(session.elapsed_ms or 0),
    }


def _open(uri: str) -> MongoClient:
    text = (uri or "").strip()
    if not text:
        raise HTTPException(400, "Connection string is required.")
    client = MongoClient(text, serverSelectionTimeoutMS=8000)
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        client.close()
        raise HTTPException(400, _public_error(exc)) from exc
    return client


def _public_error(exc: Exception) -> str:
    text = _URI.sub("[uri]", str(exc)).strip()
    return text[:400] or "Could not reach MongoDB."
