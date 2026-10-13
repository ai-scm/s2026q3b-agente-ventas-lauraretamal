"""Servidor MCP seguro que expone la lectura de la base de ventas."""

import argparse
import sqlite3
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import FastMCP

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "ventas.db"
server = FastMCP("ventas-sqlite-readonly")


@server.tool(name="read_query")
def read_query(query: str) -> dict[str, Any]:
    """Ejecuta SELECT/WITH de solo lectura y devuelve un máximo de 1000 filas."""
    return _read_query(query, DB_PATH)


def _read_query(query: str, db_path: Path) -> dict[str, Any]:
    try:
        uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute(query).fetchmany(1001)]
        return {"rows": rows[:1000], "total_rows": min(len(rows), 1000)}
    except (sqlite3.Error, OSError) as exc:
        return {"error": f"No se pudo consultar ventas: {exc}", "rows": [], "total_rows": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    DB_PATH = parser.parse_args().db_path.resolve()
    server.run(transport="stdio")
