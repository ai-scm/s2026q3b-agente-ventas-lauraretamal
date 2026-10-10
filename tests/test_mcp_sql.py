"""Pruebas de validación y wrapper MCP de solo lectura."""

import ast
import asyncio
import sqlite3

from services import mcp_sql


def test_rejects_write_queries_and_multiple_statements():
    """Bloquea sentencias de escritura, SQL malicioso y consultas vacías."""
    invalid = [
        "", "INSERT INTO ventas VALUES (1)", "UPDATE ventas SET precio=0",
        "DELETE FROM ventas", "DROP TABLE ventas", "ALTER TABLE ventas ADD x",
        "CREATE TABLE t(x)", "SELECT REPLACE(vendedor, 'a', 'b') FROM ventas",
        "SELECT 1; SELECT 2", "SELECT 1; /* otro */ SELECT 2",
        "SELECT 'DELETE' FROM ventas", "PRAGMA table_info(ventas)",
        "ATTACH DATABASE 'x' AS x", "/* comentario */ DELETE FROM ventas",
    ]
    for query in invalid:
        ok, _, _ = mcp_sql.validate_query(query)
        assert not ok, query


def test_accepts_select_with_comments_and_with_cte():
    """Permite SELECT y WITH tras espacios y comentarios iniciales."""
    assert mcp_sql.validate_query("  -- nota\n SELECT 1")[0]
    assert mcp_sql.validate_query("/* nota */ WITH x AS (SELECT 1) SELECT * FROM x")[0]
    assert mcp_sql.validate_query("SELECT 1;")[0]


def test_run_sql_wraps_select_and_with_and_limits_rows(monkeypatch, tmp_path):
    """Envía consultas al MCP read_query y aplica el máximo exterior de filas."""
    db = tmp_path / "ventas.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE ventas (id INTEGER, cantidad INTEGER)")
        conn.executemany("INSERT INTO ventas VALUES (?, ?)", [(i, i * 2) for i in range(1200)])

    calls = []

    class FakeReadQuery:
        name = "read_query"

        async def ainvoke(self, args):
            calls.append(args["query"])
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                return str([dict(row) for row in conn.execute(args["query"]).fetchall()])

    async def fake_get_tool():
        return FakeReadQuery()

    monkeypatch.setattr(mcp_sql, "get_read_query_tool", fake_get_tool)
    select = asyncio.run(mcp_sql.run_sql("SELECT id FROM ventas ORDER BY id"))
    cte = asyncio.run(mcp_sql.run_sql("WITH d AS (SELECT id FROM ventas) SELECT id FROM d"))
    assert select["ok"] and select["total_rows"] == 1000
    assert cte["ok"] and cte["total_rows"] == 1000
    assert calls[0].startswith("SELECT * FROM (SELECT")
    assert calls[1].startswith("SELECT * FROM (WITH")
    assert all("LIMIT 1000" in query for query in calls)


def test_invalid_query_never_calls_server(monkeypatch):
    """Devuelve un error tipado y no inicia el servidor para SQL inválido."""
    async def unexpected():
        raise AssertionError("No debe conectarse al MCP")
    monkeypatch.setattr(mcp_sql, "get_read_query_tool", unexpected)
    response = asyncio.run(mcp_sql.run_sql("DELETE FROM ventas"))
    assert response["ok"] is False
    assert "SELECT" in response["message"]
