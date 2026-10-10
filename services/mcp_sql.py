"""Validación de solo lectura y cliente MCP para la base SQLite."""

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any
from langchain_mcp_adapters.client import MultiServerMCPClient

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "ventas.db"
WRITE_WORDS = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|PRAGMA)\b", re.I)
_client: MultiServerMCPClient | None = None
_read_query_tool = None


def validate_query(query: str) -> tuple[bool, str, str]:
    """Quita comentarios SQL y valida el inicio, escritura y sentencias múltiples."""
    if not isinstance(query, str) or not query.strip():
        return False, "La consulta SQL está vacía.", ""
    cleaned = re.sub(r"/\*.*?\*/|--[^\r\n]*", " ", query, flags=re.S).strip()
    if not re.match(r"^(SELECT|WITH)\b", cleaned, flags=re.I):
        return False, "Solo se permiten consultas SELECT o WITH.", ""
    statement = cleaned.rstrip()
    if statement.endswith(";"):
        statement = statement[:-1].rstrip()
    if ";" in statement:
        return False, "Solo se permite una sentencia SQL.", ""
    if WRITE_WORDS.search(statement):
        return False, "La consulta contiene una palabra o instrucción de escritura no permitida.", ""
    return True, "", statement


def _get_client() -> MultiServerMCPClient:
    """Construye el cliente stdio del servidor oficial SQLite."""
    global _client
    if _client is None:
        _client = MultiServerMCPClient({"sqlite": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "services.sqlite_mcp_server"],
            "cwd": str(ROOT),
        }})
    return _client


async def get_read_query_tool():
    """Carga y filtra la herramienta read_query del servidor SQLite MCP."""
    global _read_query_tool
    if _read_query_tool is None:
        tools = await _get_client().get_tools(server_name="sqlite")
        _read_query_tool = next((tool for tool in tools if tool.name == "read_query"), None)
        if _read_query_tool is None:
            raise RuntimeError("El servidor MCP SQLite no expuso la herramienta read_query.")
    return _read_query_tool


async def run_sql(query: str, read_query_tool: Any | None = None) -> dict[str, Any]:
    """Ejecuta una sola consulta validada a través de read_query y limita a 1000 filas."""
    valid, error, statement = validate_query(query)
    if not valid:
        return {"ok": False, "message": error, "rows": [], "query": query}
    try:
        tool = read_query_tool or await get_read_query_tool()
        # El servidor de lectura solo acepta SELECT; esta envoltura permite CTE (WITH).
        mcp_query = f"SELECT * FROM ({statement}) AS _ventas_query LIMIT 1000"
        response = await tool.ainvoke({"query": mcp_query})
        if isinstance(response, tuple):
            response = response[0]
        text = response
        if isinstance(response, list):
            text = "\n".join(block.get("text", "") for block in response if isinstance(block, dict))
        if isinstance(text, str):
            try:
                rows = json.loads(text)
            except json.JSONDecodeError:
                rows = ast.literal_eval(text)
        else:
            rows = text
        if isinstance(rows, dict) and isinstance(rows.get("rows"), list):
            rows = rows["rows"]
        if not isinstance(rows, list):
            return {"ok": False, "message": str(rows), "rows": [], "query": statement}
        return {"ok": True, "rows": rows[:1000], "total_rows": min(len(rows), 1000), "query": statement}
    except Exception as exc:
        return {"ok": False, "message": f"No se pudo ejecutar la consulta SQL: {exc}", "rows": [], "query": statement}
