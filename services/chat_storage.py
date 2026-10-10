"""Persistencia opcional de conversaciones en S3 bajo el prefijo ventas/."""

import json
import os
from datetime import datetime
from typing import Any
import boto3
from botocore.exceptions import BotoCoreError, ClientError

CHAT_BUCKET_NAME = os.getenv("CHAT_BUCKET_NAME")
S3 = boto3.client("s3", region_name="us-east-1") if CHAT_BUCKET_NAME else None
PREFIX = "ventas/"
INDEX_KEY = f"{PREFIX}index.json"


def persistence_enabled() -> bool:
    """Indica si se configuró un bucket para persistir chats."""
    return bool(CHAT_BUCKET_NAME)


def new_chat_id() -> str:
    """Genera un identificador temporal para una conversación."""
    return datetime.now().strftime("chat_%Y%m%d_%H%M%S_%f")


def _key(chat_id: str) -> str:
    """Construye una clave S3 validando el identificador del chat."""
    if not chat_id.startswith("chat_") or "/" in chat_id or "\\" in chat_id:
        raise ValueError("Identificador de chat no válido.")
    return f"{PREFIX}{chat_id}.json"


def _read_index() -> dict[str, str]:
    """Lee el índice compacto de títulos; no descarga los chats individuales."""
    if not S3 or not CHAT_BUCKET_NAME:
        return {}
    try:
        obj = S3.get_object(Bucket=CHAT_BUCKET_NAME, Key=INDEX_KEY)
        value = json.loads(obj["Body"].read().decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
            return {}
        raise


def _write_index(index: dict[str, str]) -> None:
    """Guarda el índice compacto de títulos de conversación."""
    if S3 and CHAT_BUCKET_NAME:
        S3.put_object(Bucket=CHAT_BUCKET_NAME, Key=INDEX_KEY, Body=json.dumps(index, ensure_ascii=False).encode("utf-8"), ContentType="application/json")


def _normalize_messages(payload: Any) -> list[dict[str, Any]]:
    """Migra chats antiguos guardados como role/content a objetos multimodales."""
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


def save_chat(messages: list[dict[str, Any]], chat_id: str, title: str | None = None) -> bool:
    """Guarda el chat y actualiza un índice para consultar títulos sin descargarlo."""
    if not S3 or not CHAT_BUCKET_NAME:
        return False
    normalized = _normalize_messages(messages)
    saved_title = title or next((m["text"][:60] for m in normalized if m["role"] == "user" and m["text"]), "Nueva conversación")
    S3.put_object(Bucket=CHAT_BUCKET_NAME, Key=_key(chat_id), Body=json.dumps({"title": saved_title, "messages": normalized}, ensure_ascii=False, indent=2).encode("utf-8"), ContentType="application/json")
    index = _read_index()
    index[chat_id] = saved_title
    _write_index(index)
    return True


def load_chat(chat_id: str) -> list[dict[str, Any]]:
    """Carga una conversación y migra automáticamente el formato anterior."""
    if not S3 or not CHAT_BUCKET_NAME:
        return []
    obj = S3.get_object(Bucket=CHAT_BUCKET_NAME, Key=_key(chat_id))
    payload = json.loads(obj["Body"].read().decode("utf-8"))
    return _normalize_messages(payload)


def get_saved_chats() -> list[str]:
    """Lista chats exclusivamente del prefijo ventas/."""
    if not S3 or not CHAT_BUCKET_NAME:
        return []
    paginator = S3.get_paginator("list_objects_v2")
    ids = []
    for page in paginator.paginate(Bucket=CHAT_BUCKET_NAME, Prefix=PREFIX):
        for item in page.get("Contents", []):
            key = item["Key"]
            if key.startswith(PREFIX) and key.endswith(".json") and key != INDEX_KEY:
                ids.append(key[len(PREFIX):-5])
    return sorted(ids, reverse=True)


def get_chat_titles() -> dict[str, str]:
    """Devuelve títulos desde el índice y evita descargas individuales de chats."""
    return _read_index() if S3 else {}


def get_chat_title(chat_id: str) -> str:
    """Consulta el título del índice de chats sin bajar el cuerpo del chat."""
    return get_chat_titles().get(chat_id, "Nueva conversación")


def delete_chat(chat_id: str) -> bool:
    """Elimina el chat y su título del índice S3."""
    if not S3 or not CHAT_BUCKET_NAME:
        return False
    S3.delete_object(Bucket=CHAT_BUCKET_NAME, Key=_key(chat_id))
    index = _read_index()
    index.pop(chat_id, None)
    _write_index(index)
    return True
