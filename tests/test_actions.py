"""Pruebas de gráficos, exportación y resultados de sesión."""

from pathlib import Path

import pandas as pd

from services import actions


def sample_results():
    """Devuelve un registro pequeño para las pruebas de herramientas."""
    return {"r1": {
        "columns": ["producto", "unidades"],
        "rows": [{"producto": "Café", "unidades": 10}, {"producto": "Té", "unidades": 5}],
        "total_rows": 2,
        "query": "SELECT producto, SUM(cantidad) AS unidades FROM ventas GROUP BY producto",
    }}


def test_chart_export_and_result_listing(tmp_path, monkeypatch):
    """Genera PNG, CSV y XLSX y expone los metadatos de r1."""
    monkeypatch.setattr(actions, "OUTPUT_DIR", tmp_path)
    results = sample_results()
    chart = actions.create_chart(results, "r1", "bar", "producto", "unidades", "Unidades por producto")
    csv_result = actions.export_file(results, "r1", "csv", "ventas")
    xlsx_result = actions.export_file(results, "r1", "xlsx", "ventas_excel")
    assert chart["ok"] and (tmp_path / "Unidades_por_producto_r1.png").exists()
    assert csv_result["ok"] and pd.read_csv(csv_result["file_path"]).shape == (2, 2)
    assert xlsx_result["ok"] and pd.read_excel(xlsx_result["file_path"]).shape == (2, 2)


def test_action_validation(tmp_path, monkeypatch):
    """Rechaza IDs, columnas, formatos y rutas que no cumplen el contrato."""
    monkeypatch.setattr(actions, "OUTPUT_DIR", tmp_path)
    results = sample_results()
    assert not actions.create_chart(results, "missing", "bar", "producto", "unidades", "t").get("ok")
    assert not actions.create_chart(results, "r1", "bar", "no_existe", "unidades", "t").get("ok")
    assert not actions.export_file(results, "missing", "csv", "file").get("ok")
    assert not actions.export_file(results, "r1", "json", "file").get("ok")
    assert not actions.export_file(results, "r1", "csv", "../fuera").get("ok")


def test_artifacts_can_be_saved_in_the_active_workspace(tmp_path):
    output_dir = tmp_path / "workspace" / "outputs"
    results = sample_results()
    chart = actions.create_chart(results, "r1", "bar", "producto", "unidades", "Unidades", output_dir)
    export = actions.export_file(results, "r1", "csv", "resumen", output_dir)
    assert Path(chart["chart_path"]).parent == output_dir
    assert Path(export["file_path"]).parent == output_dir
