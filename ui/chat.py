"""Presentación del historial multimodal en la interfaz Streamlit."""

from pathlib import Path
import math
import streamlit as st

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"
_CURRENCY_COLUMNS = ("precio", "ingreso", "total_venta", "venta_total", "revenue")


def _format_number(value: int | float, currency: bool = False) -> str:
    """Presenta importes y cantidades con convenciones numéricas colombianas."""
    number = float(value)
    if not math.isfinite(number):
        return str(value)
    if currency:
        whole, fraction = f"{abs(number):,.2f}".split(".")
        formatted = whole.replace(",", ".")
        if fraction != "00":
            formatted += "," + fraction
        return f"{'-' if number < 0 else ''}$ {formatted}"
    if number.is_integer():
        return f"{int(number):,}".replace(",", ".")
    whole, fraction = f"{abs(number):,.2f}".split(".")
    return f"{'-' if number < 0 else ''}{whole.replace(',', '.')},{fraction}"


def _format_rows(rows: list[dict]) -> list[dict]:
    """Formatea columnas monetarias y valores numéricos de una tabla."""
    formatted = []
    for row in rows:
        item = {}
        for column, value in row.items():
            name = column.casefold()
            currency = any(token in name for token in _CURRENCY_COLUMNS)
            item[column] = _format_number(value, currency) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
        formatted.append(item)
    return formatted


def hide_chat_icons() -> None:
    """Oculta avatares y mantiene alineación de los mensajes del usuario."""
    st.markdown("""
    <style>
    [data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {display:none;}
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageContent"][aria-label="Chat message from user"]) {width:fit-content!important;max-width:75%!important;margin-left:auto!important;}
    </style>
    """, unsafe_allow_html=True)


def _safe_output(path: str | None, output_dir: Path = OUTPUT_DIR) -> Path | None:
    """Valida que un archivo visible exista dentro de outputs/."""
    if not path:
        return None
    try:
        candidate = Path(path).resolve()
        candidate.relative_to(output_dir.resolve())
        return candidate if candidate.is_file() else None
    except (OSError, ValueError):
        return None


def show_messages(output_dir: Path = OUTPUT_DIR) -> None:
    """Dibuja respuestas, tablas, gráficos y descargas sin exponer SQL interno."""
    for index, message in enumerate(st.session_state.messages):
        role = message.get("role", "assistant")
        text = message.get("text", message.get("content", ""))
        with st.chat_message(role, avatar=None):
            if text:
                st.markdown(text)
            if role != "assistant":
                continue
            table = message.get("table")
            if isinstance(table, list) and table:
                st.dataframe(_format_rows(table[:50]), use_container_width=True, hide_index=True)
                if message.get("total_rows") is not None:
                    st.caption(f"Filas mostradas: {min(len(table), 50)} · Total: {message['total_rows']}")
            charts = message.get("chart_paths") or [message.get("chart_path")]
            for chart_value in charts:
                chart = _safe_output(chart_value, output_dir)
                if chart:
                    st.image(str(chart), use_container_width=True)
            files = message.get("file_paths") or [message.get("file_path")]
            for file_index, file_value in enumerate(files):
                file_path = _safe_output(file_value, output_dir)
                if not file_path:
                    continue
                st.download_button(
                    "Descargar archivo", data=file_path.read_bytes(), file_name=file_path.name,
                    mime="text/csv" if file_path.suffix.lower() == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_{index}_{file_index}_{file_path.name}",
                )
