"""Conversaciones locales separadas por espacio de trabajo."""

import json
import re
import uuid
from pathlib import Path
from typing import Any

from services.workspaces import get_workspace


def new_chat_id() -> str:
    return f"chat_{uuid.uuid4().hex}"


def _chat_path(workspace_id: str, chat_id: str) -> Path:
    if not re.fullmatch(r"chat_[a-f0-9]{32}", chat_id):
        raise ValueError("Identificador de conversación no válido.")
    return get_workspace(workspace_id)["chat_dir"] / f"{chat_id}.json"


def _normalize_messages(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("messages", [])
    normalized = []
    for message in payload if isinstance(payload, list) else []:
        if not isinstance(message, dict):
            continue
        text = message.get("text", message.get("content", ""))
        normalized.append({
            "role": message.get("role", "assistant"), "text": str(text or ""),
            "sql": message.get("sql"), "table": message.get("table"),
            "chart_path": message.get("chart_path"), "file_path": message.get("file_path"),
            "chart_paths": message.get("chart_paths", []), "file_paths": message.get("file_paths", []),
            "total_rows": message.get("total_rows"),
        })
    return normalized


def save_chat(messages: list[dict[str, Any]], chat_id: str, workspace_id: str, results: dict | None = None) -> bool:
    normalized = _normalize_messages(messages)
    title = next((message["text"][:60] for message in normalized if message["role"] == "user" and message["text"]), "Nueva conversación")
    payload = {"title": title, "messages": normalized, "results": results or {}}
    path = _chat_path(workspace_id, chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)
    return True


def load_chat_data(chat_id: str, workspace_id: str) -> dict:
    payload = json.loads(_chat_path(workspace_id, chat_id).read_text(encoding="utf-8"))
    return {"messages": _normalize_messages(payload), "results": payload.get("results", {})}


def load_chat(chat_id: str, workspace_id: str) -> list[dict[str, Any]]:
    return load_chat_data(chat_id, workspace_id)["messages"]


def get_saved_chats(workspace_id: str) -> list[str]:
    directory = get_workspace(workspace_id)["chat_dir"]
    return [path.stem for path in sorted(directory.glob("chat_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)]


def get_chat_titles(workspace_id: str) -> dict[str, str]:
    titles = {}
    for chat_id in get_saved_chats(workspace_id):
        payload = json.loads(_chat_path(workspace_id, chat_id).read_text(encoding="utf-8"))
        titles[chat_id] = payload.get("title", "Nueva conversación")
    return titles


def delete_chat(chat_id: str, workspace_id: str) -> bool:
    _chat_path(workspace_id, chat_id).unlink(missing_ok=True)
    return True
