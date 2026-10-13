"""Prueba de carga de la interfaz sin llamadas a AWS."""

from pathlib import Path
from streamlit.testing.v1 import AppTest
from ui.chat import _format_rows


def test_streamlit_app_loads_with_local_storage():
    """Carga la app usando almacenamiento local."""
    result = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=20).run()
    assert not result.exception
    assert result.title[0].value == "Agente de análisis de datos"
    assert not result.info


def test_user_can_upload_and_switch_csv_workspaces(tmp_path, monkeypatch):
    from services import workspaces

    monkeypatch.setattr(workspaces, "WORKSPACES_DIR", tmp_path / "workspaces")
    result = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=20).run()
    result.text_input[0].set_value("Regiones")
    result.file_uploader[0].set_value(("regiones.csv", b"Region,Total\nNorte,10\n", "text/csv"))
    result.button[0].click().run()

    assert not result.exception
    assert "Regiones" in result.selectbox[0].options
    uploaded_id = result.session_state["workspace_id"]
    result.selectbox[0].set_value("demo").run()
    assert result.session_state["workspace_id"] == "demo"
    result.selectbox[0].set_value(uploaded_id).run()
    assert result.session_state["workspace_id"] == uploaded_id


def test_table_numbers_use_colombian_format():
    """Muestra pesos y cantidades con puntos de miles, sin símbolo en cantidades."""
    assert _format_rows([{"ingresos_totales": 1234567.8, "unidades_vendidas": 1234}]) == [
        {"ingresos_totales": "$ 1.234.567,80", "unidades_vendidas": "1.234"}
    ]


def test_assistant_message_does_not_render_internal_sql():
    """La interfaz no muestra el SQL guardado como metadato del mensaje."""
    result = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=20).run()
    result.session_state["messages"] = [{
        "role": "assistant", "text": "Hay 10 productos distintos.",
        "sql": "SELECT COUNT(DISTINCT producto) FROM ventas",
    }]
    result.run()
    assert not result.exception
    assert not result.code
