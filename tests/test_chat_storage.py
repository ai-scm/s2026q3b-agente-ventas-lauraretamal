"""Pruebas sin AWS para migración de mensajes guardados."""

from services.chat_storage import _normalize_messages


def test_migrates_legacy_chat_content():
    """Convierte mensajes antiguos de texto al esquema multimodal nuevo."""
    result = _normalize_messages([
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "respuesta"},
    ])
    assert result == [
        {"role": "user", "text": "hola", "sql": None, "table": None, "chart_path": None, "file_path": None, "chart_paths": [], "file_paths": [], "total_rows": None},
        {"role": "assistant", "text": "respuesta", "sql": None, "table": None, "chart_path": None, "file_path": None, "chart_paths": [], "file_paths": [], "total_rows": None},
    ]


def test_preserves_multiple_artifacts_in_saved_chat():
    """Mantiene cada gráfico y archivo generado en un mismo turno."""
    message = {"role": "assistant", "text": "Listo", "chart_paths": ["a.png", "b.png"], "file_paths": ["a.csv", "b.csv"]}
    normalized = _normalize_messages([message])[0]
    assert normalized["chart_paths"] == message["chart_paths"]
    assert normalized["file_paths"] == message["file_paths"]
