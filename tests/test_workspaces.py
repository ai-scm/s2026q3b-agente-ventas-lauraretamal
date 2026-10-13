"""Pruebas de importación y aislamiento de espacios CSV."""

import asyncio
import sqlite3
import sys

import pytest

from services import chat_storage, workspaces


def test_csv_creates_independent_workspace_database(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "WORKSPACES_DIR", tmp_path / "workspaces")
    first = workspaces.create_workspace("Primera base", "primera.csv", b"Ciudad,Total\nBogota,20\nCali,30\n")
    second = workspaces.create_workspace("Segunda base", "segunda.csv", b"Producto,Cantidad\nCafe,4\n")

    assert first["id"] != second["id"]
    assert first["columns"] == ["ciudad", "total"]
    assert second["columns"] == ["producto", "cantidad"]
    assert first["rows"] == 2 and second["rows"] == 1
    with sqlite3.connect(first["db_path"]) as connection:
        assert connection.execute("SELECT SUM(total) FROM ventas").fetchone()[0] == 50
    with sqlite3.connect(second["db_path"]) as connection:
        assert connection.execute("SELECT SUM(cantidad) FROM ventas").fetchone()[0] == 4


def test_csv_rejects_empty_and_malformed_files(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "WORKSPACES_DIR", tmp_path / "workspaces")
    with pytest.raises(ValueError, match="vacío"):
        workspaces.create_workspace("Vacío", "empty.csv", b"")
    with pytest.raises(ValueError, match="CSV válido"):
        workspaces.create_workspace("Inválido", "bad.csv", b'"unclosed,header\n')


def test_csv_detects_semicolon_separator(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "WORKSPACES_DIR", tmp_path / "workspaces")
    workspace = workspaces.create_workspace("Europa", "datos.csv", "Ciudad;Total\nLima;5\n".encode())
    assert workspace["columns"] == ["ciudad", "total"]
    assert workspace["rows"] == 1


def test_uploaded_schema_is_given_to_the_agent_prompt():
    from services.prompt import SYSTEM_PROMPT, dataset_prompt

    schema = [{"name": "region", "type": "TEXT"}, {"name": "total", "type": "INTEGER"}]
    prompt = dataset_prompt(schema)
    assert "region (TEXT)" in prompt and "total (INTEGER)" in prompt
    assert dataset_prompt(schema, sample_sales=True) == SYSTEM_PROMPT


def test_chats_and_saved_results_stay_in_their_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "WORKSPACES_DIR", tmp_path / "workspaces")
    first = workspaces.create_workspace("Primera", "primera.csv", b"Valor\n1\n")
    second = workspaces.create_workspace("Segunda", "segunda.csv", b"Valor\n2\n")
    chat_id = chat_storage.new_chat_id()
    messages = [{"role": "user", "text": "¿Cuál es el valor?"}, {"role": "assistant", "text": "1"}]
    results = {"r1": {"columns": ["valor"], "rows": [{"valor": 1}], "total_rows": 1, "query": "SELECT valor FROM ventas"}}

    chat_storage.save_chat(messages, chat_id, first["id"], results)

    assert chat_storage.get_saved_chats(first["id"]) == [chat_id]
    assert chat_storage.get_saved_chats(second["id"]) == []
    assert chat_storage.load_chat_data(chat_id, first["id"])["results"] == results
    chat_storage.delete_chat(chat_id, first["id"])
    assert chat_storage.get_saved_chats(first["id"]) == []


def test_uploaded_database_is_selected_for_its_mcp_server(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "WORKSPACES_DIR", tmp_path / "workspaces")
    workspace = workspaces.create_workspace("Regiones", "datos.csv", b"Region,Ingresos\nNorte,12\nSur,8\n")

    from services import mcp_sql, sqlite_mcp_server
    client = mcp_sql._get_client(workspace["db_path"])
    assert str(workspace["db_path"]) in client.connections["sqlite"]["args"]
    result = sqlite_mcp_server._read_query(
        "SELECT region, SUM(ingresos) AS total FROM ventas GROUP BY region",
        workspace["db_path"],
    )
    assert result["total_rows"] == 2
    assert {row["region"]: row["total"] for row in result["rows"]} == {"Norte": 12, "Sur": 8}


@pytest.mark.skipif(sys.version_info >= (3, 14), reason="La prueba MCP stdio se ejecuta en el runtime Python 3.11 del proyecto")
def test_uploaded_csv_query_runs_through_its_mcp_server(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "WORKSPACES_DIR", tmp_path / "workspaces")
    workspace = workspaces.create_workspace("Regiones", "datos.csv", b"Region,Ingresos\nNorte,12\nSur,8\n")
    from services.mcp_sql import get_read_query_tool, run_sql
    tool = asyncio.run(get_read_query_tool(workspace["db_path"]))
    result = asyncio.run(run_sql("SELECT region, SUM(ingresos) AS total FROM ventas GROUP BY region", tool))
    assert result["ok"]
    assert {row["region"]: row["total"] for row in result["rows"]} == {"Norte": 12, "Sur": 8}
