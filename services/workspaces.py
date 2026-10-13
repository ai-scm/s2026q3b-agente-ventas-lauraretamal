"""Almacenamiento local de bases CSV y espacios de trabajo."""

import csv
import json
import re
import sqlite3
import unicodedata
import uuid
from io import BytesIO
from pathlib import Path

import pandas as pd

from services.database import DB_PATH, CSV_PATH, ensure_database

ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_DIR = ROOT / "data" / "workspaces"
DEFAULT_ID = "demo"
SQL_WORDS = {"as", "by", "case", "create", "delete", "drop", "from", "group", "index", "insert", "join", "key", "limit", "on", "order", "primary", "select", "table", "update", "values", "where"}


def _directory(workspace_id: str) -> Path:
    if workspace_id != DEFAULT_ID and not re.fullmatch(r"[a-f0-9]{32}", workspace_id):
        raise ValueError("Espacio de trabajo no válido.")
    return WORKSPACES_DIR / workspace_id


def _write_metadata(path: Path, metadata: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def initialize_workspaces() -> None:
    ensure_database()
    directory = _directory(DEFAULT_ID)
    directory.joinpath("chats").mkdir(parents=True, exist_ok=True)
    directory.joinpath("outputs").mkdir(parents=True, exist_ok=True)
    metadata_path = directory / "workspace.json"
    if not metadata_path.exists():
        _write_metadata(metadata_path, {"id": DEFAULT_ID, "name": "Ventas de ejemplo", "default": True})


def _column_names(columns) -> list[str]:
    names, used = [], set()
    for index, original in enumerate(columns, start=1):
        name = unicodedata.normalize("NFKD", str(original)).encode("ascii", "ignore").decode().lower()
        name = re.sub(r"[^a-z0-9]+", "_", name).strip("_") or f"columna_{index}"
        if name[0].isdigit():
            name = f"col_{name}"
        if name in SQL_WORDS:
            name = f"col_{name}"
        candidate, suffix = name, 2
        while candidate in used:
            candidate = f"{name}_{suffix}"
            suffix += 1
        names.append(candidate)
        used.add(candidate)
    return names


def create_workspace(name: str, filename: str, content: bytes) -> dict:
    """Valida un CSV y crea una base SQLite aislada para él."""
    title = name.strip() or Path(filename).stem or "Nueva base"
    if not content:
        raise ValueError("El archivo CSV está vacío.")
    try:
        sample = content[:8192].decode("utf-8-sig")
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
        frame = pd.read_csv(BytesIO(content), encoding="utf-8-sig", sep=delimiter)
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError("No se pudo leer el CSV. Comprueba que sea un archivo CSV válido en UTF-8.") from exc
    if frame.empty and not len(frame.columns):
        raise ValueError("El CSV debe tener encabezados de columna.")
    frame.columns = _column_names(frame.columns)

    workspace_id = uuid.uuid4().hex
    directory = _directory(workspace_id)
    directory.mkdir(parents=True)
    csv_path = directory / "datos.csv"
    db_path = directory / "ventas.db"
    csv_path.write_bytes(content)
    with sqlite3.connect(db_path) as connection:
        frame.to_sql("ventas", connection, if_exists="replace", index=False)
    metadata = {"id": workspace_id, "name": title, "default": False, "columns": list(frame.columns), "rows": len(frame)}
    _write_metadata(directory / "workspace.json", metadata)
    (directory / "chats").mkdir()
    (directory / "outputs").mkdir()
    return get_workspace(workspace_id)


def list_workspaces() -> list[dict]:
    workspaces = [get_workspace(DEFAULT_ID)]
    for path in WORKSPACES_DIR.iterdir():
        if not path.is_dir() or path.name == DEFAULT_ID:
            continue
        metadata_path = path / "workspace.json"
        if metadata_path.exists():
            try:
                workspaces.append(get_workspace(path.name))
            except (ValueError, OSError, json.JSONDecodeError):
                continue
    return workspaces


def get_workspace(workspace_id: str) -> dict:
    directory = _directory(workspace_id)
    if workspace_id == DEFAULT_ID:
        db_path, csv_path = DB_PATH, CSV_PATH
        name, default = "Ventas de ejemplo", True
        with sqlite3.connect(db_path) as connection:
            schema = [{"name": row[1], "type": row[2]} for row in connection.execute("PRAGMA table_info(ventas)")]
            rows = connection.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
    else:
        metadata_path = directory / "workspace.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("id") != workspace_id:
            raise ValueError("Espacio de trabajo no válido.")
        db_path, csv_path = directory / "ventas.db", directory / "datos.csv"
        name, default = metadata["name"], False
        with sqlite3.connect(db_path) as connection:
            schema = [{"name": row[1], "type": row[2]} for row in connection.execute("PRAGMA table_info(ventas)")]
            rows = connection.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
    return {
        "id": workspace_id, "name": name, "default": default,
        "db_path": db_path, "csv_path": csv_path,
        "directory": directory, "chat_dir": directory / "chats",
        "output_dir": directory / "outputs", "schema": schema,
        "columns": [column["name"] for column in schema], "rows": rows,
    }
