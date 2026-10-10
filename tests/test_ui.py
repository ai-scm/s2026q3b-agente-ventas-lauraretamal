"""Prueba de carga de la interfaz sin llamadas a AWS."""

from pathlib import Path
from streamlit.testing.v1 import AppTest
from ui.chat import _format_rows


def test_streamlit_app_loads_without_s3_configuration():
    """Carga el inicio sin mostrar un aviso si S3 es opcional."""
    result = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=20).run()
    assert not result.exception
    assert result.title[0].value == "Agente de análisis de ventas"
    assert not result.info


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
