"""Herramientas de gráficos, exportación y registro de resultados por conversación."""

import re
from pathlib import Path
from typing import Any
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"


def create_chart(results: dict[str, dict[str, Any]], result_id: str, chart_type: str, x: str, y: str, title: str) -> dict[str, Any]:
    """Crea un gráfico PNG con el resultado identificado en el registro de sesión."""
    if not isinstance(result_id, str):
        return {"ok": False, "message": "result_id debe ser texto."}
    result = results.get(result_id)
    if result is None:
        return {"ok": False, "message": f"No existe el resultado {result_id}."}
    if not isinstance(chart_type, str) or chart_type not in {"bar", "line", "pie"}:
        return {"ok": False, "message": "chart_type debe ser bar, line o pie."}
    rows = result["rows"]
    columns = result["columns"]
    if not rows:
        return {"ok": False, "message": "El resultado no contiene filas para graficar."}
    if x not in columns or y not in columns:
        return {"ok": False, "message": f"Las columnas x e y deben existir. Columnas disponibles: {', '.join(columns)}."}
    try:
        labels = [str(row[x]) for row in rows]
        values = [float(row[y]) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "message": f"La columna y debe contener valores numéricos: {exc}"}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not isinstance(title, str):
        return {"ok": False, "message": "title debe ser texto."}
    stem = re.sub(r"[^\w.-]+", "_", title, flags=re.UNICODE).strip("._-")[:60] or "ventas"
    path = OUTPUT_DIR / f"{stem}_{result_id}.png"
    fig, ax = plt.subplots(figsize=(10, 6))
    if chart_type == "bar":
        ax.bar(labels, values)
        ax.tick_params(axis="x", rotation=35)
    elif chart_type == "line":
        ax.plot(labels, values, marker="o")
        ax.tick_params(axis="x", rotation=35)
    else:
        if any(value < 0 for value in values) or sum(values) <= 0:
            plt.close(fig)
            return {"ok": False, "message": "El gráfico pie requiere valores no negativos y una suma mayor que cero."}
        ax.pie(values, labels=labels, autopct="%1.1f%%")
    ax.set_title(title)
    if chart_type != "pie":
        ax.set_ylabel(y)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {"ok": True, "result_id": result_id, "chart_path": str(path)}


def export_file(results: dict[str, dict[str, Any]], result_id: str, format: str, filename: str) -> dict[str, Any]:
    """Exporta todas las filas de un resultado como CSV o XLSX en outputs/."""
    if not isinstance(result_id, str):
        return {"ok": False, "message": "result_id debe ser texto."}
    result = results.get(result_id)
    if result is None:
        return {"ok": False, "message": f"No existe el resultado {result_id}."}
    if not isinstance(format, str) or format not in {"csv", "xlsx"}:
        return {"ok": False, "message": "format debe ser csv o xlsx."}
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", filename) or filename in {".", ".."} or ".." in filename:
        return {"ok": False, "message": "El nombre debe contener solo letras, números, guiones, guiones bajos y puntos, sin rutas."}
    suffix = "." + format
    stem = filename[:-len(suffix)] if filename.lower().endswith(suffix) else filename
    if not stem:
        return {"ok": False, "message": "El nombre de archivo no puede estar vacío."}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{stem}{suffix}"
    frame = pd.DataFrame(result["rows"], columns=result["columns"])
    try:
        if format == "csv":
            frame.to_csv(path, index=False, encoding="utf-8-sig")
        else:
            frame.to_excel(path, index=False, engine="openpyxl")
    except Exception as exc:
        return {"ok": False, "message": f"No se pudo exportar el archivo: {exc}"}
    return {"ok": True, "result_id": result_id, "file_path": str(path), "format": format}
