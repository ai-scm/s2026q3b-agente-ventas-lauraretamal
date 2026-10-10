"""Aceptación Bedrock de las 22 preguntas del ejercicio; optativa por costo."""

import json
import os
from pathlib import Path

import pandas as pd
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

pytestmark = pytest.mark.skipif(os.getenv("RUN_LLM_TESTS") != "1", reason="define RUN_LLM_TESTS=1 para invocar Bedrock")

QUESTIONS = [
    "¿Cuáles son los 5 productos más vendidos en Medellín?",
    "¿Qué vendedor generó mayores ingresos en Bogotá?",
    "¿Cuántas unidades se vendieron por sede?",
    "¿Cuál es el ingreso total de cada vendedor?",
    "¿Qué producto generó mayores ingresos?",
    "Muéstrame un gráfico de barras con los ingresos totales por vendedor.",
    "Compara visualmente las unidades vendidas por sede.",
    "Muéstrame un gráfico de los ingresos por producto.",
    "Representa visualmente los resultados de la consulta anterior.",
    "Guarda las ventas totales por vendedor en un CSV.",
    "Exporta las unidades vendidas por sede a Excel.",
    "Guarda los resultados de la consulta anterior en CSV.",
    "¿Cuáles son los ingresos totales por sede?",
    "¿Cuál tuvo los ingresos más altos?",
    "¿Y cuál vendió más unidades?",
    "Muéstrame esos resultados en un gráfico.",
    "Guarda esos resultados en CSV.",
    "Necesito saber quién vende mejor en cada sucursal.",
    "¿Qué productos tienen un mejor desempeño comercial?",
    "Compara los ingresos de Bogotá y Medellín. ¿Cuál tiene mejores resultados?",
    "¿Cuántas unidades se vendieron en la sede de Atlantis?",
    "Consulta las ventas de un producto llamado Producto XYZ.",
]


def _payload(message):
    try:
        return json.loads(message.content)
    except (TypeError, json.JSONDecodeError):
        return {}


def _group(frame, keys, value, alias):
    return frame.groupby(keys)[value].sum().rename(alias).sort_index()


def test_exercise_questions_and_artifacts(tmp_path, monkeypatch):
    """Prueba preguntas, contexto, formato y archivos en el mismo hilo."""
    import asyncio
    from services import actions
    from services.database import ensure_database
    from services.prompt import SYSTEM_PROMPT
    from services.sales_agent import assistant_text, create_sales_agent

    ensure_database()
    monkeypatch.setattr(actions, "OUTPUT_DIR", tmp_path)
    source = pd.read_csv("data/ventas.csv")
    results = {}
    graph = asyncio.run(create_sales_agent(results))
    history, turns = [], []

    for question in QUESTIONS:
        recent = [
            {"result_id": rid, "columns": data["columns"], "total_rows": data["total_rows"], "query": data["query"], "rows": data["rows"][:5]}
            for rid, data in list(results.items())[-8:]
        ]
        context = SYSTEM_PROMPT + "\nResultados recientes disponibles: " + json.dumps(recent, ensure_ascii=False)
        response = asyncio.run(graph.ainvoke({
            "messages": [SystemMessage(content=context), *history[-12:], HumanMessage(content=question)],
        }))
        final = next(message for message in reversed(response["messages"]) if isinstance(message, AIMessage) and not message.tool_calls)
        answer = assistant_text(final)
        messages = [message for message in response["messages"] if isinstance(message, ToolMessage)]
        sql = next((_payload(message) for message in messages if message.name in {"run_sql", "result_data"}), None)
        if not sql or not sql.get("ok"):
            plan_args = next((m.tool_calls[0]["args"] for m in response["messages"] if isinstance(m, AIMessage) and m.tool_calls), {})
            metadata = {rid: data["columns"] for rid, data in results.items()}
            pytest.fail(f"Falló SQL/resultado para: {question}; herramientas={[m.name for m in messages]}; plan={plan_args}; columnas={metadata}; respuesta={answer}")
        assert "SELECT " not in answer.upper(), f"El SQL se mostró al usuario: {question}"
        turns.append({
            "result": results[sql["result_id"]],
            "charts": [_payload(m) for m in messages if m.name == "create_chart"],
            "exports": [_payload(m) for m in messages if m.name == "export_file"],
            "answer": answer,
        })
        history.extend([HumanMessage(content=question), AIMessage(content=answer)])

    for index in (5, 6, 7, 8, 15):
        charts = [item for item in turns[index]["charts"] if item.get("ok")]
        assert charts and all((tmp_path / Path(item["chart_path"]).name).is_file() for item in charts), QUESTIONS[index]
    for index in (0, 1, 2, 3, 4, 9, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21):
        assert not turns[index]["charts"], f"Se generó un gráfico no solicitado: {QUESTIONS[index]}"
    for index, suffix in ((9, ".csv"), (10, ".xlsx"), (11, ".csv"), (16, ".csv")):
        files = turns[index]["exports"]
        assert files and all(item.get("ok") and Path(item["file_path"]).suffix == suffix and Path(item["file_path"]).is_file() for item in files), QUESTIONS[index]
    for index in (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 13, 14, 15, 17, 18, 19, 20, 21):
        assert not turns[index]["exports"], f"Se exportó un archivo no solicitado: {QUESTIONS[index]}"
    assert len([item for item in turns[15]["charts"] if item.get("ok")]) >= 2

    top5 = _group(source[source.sede == "Medellín"], "producto", "cantidad", "unidades_vendidas").sort_values(ascending=False).head(5)
    assert turns[0]["result"]["total_rows"] == 5
    assert {row["producto"]: next(value for key, value in row.items() if key != "producto") for row in turns[0]["result"]["rows"]} == top5.to_dict()
    vendor_income_by_site = source[source.sede == "Bogotá"].assign(ingresos=lambda frame: frame.cantidad * frame.precio).groupby("vendedor").ingresos.sum()
    best_bogota_vendor = vendor_income_by_site.idxmax()
    assert len(turns[1]["result"]["rows"]) == 1
    assert turns[1]["result"]["rows"][0]["vendedor"] == best_bogota_vendor
    bogota_row = turns[1]["result"]["rows"][0]
    bogota_metric = next(value for key, value in bogota_row.items() if key != "vendedor")
    assert bogota_metric == pytest.approx(vendor_income_by_site.max())
    product_income = source.assign(ingresos=source.cantidad * source.precio).groupby("producto").ingresos.sum()
    assert len(turns[4]["result"]["rows"]) == 1
    assert turns[4]["result"]["rows"][0]["producto"] == product_income.idxmax()
    expected_units = _group(source, "sede", "cantidad", "unidades_vendidas")
    for index in (2, 6):
        actual = {row["sede"]: next(value for key, value in row.items() if key != "sede") for row in turns[index]["result"]["rows"]}
        assert actual == expected_units.to_dict(), f"Turno {index + 1}: {turns[index]['result']}"
    expected_vendor_income = (source.assign(ingresos=source.cantidad * source.precio).groupby("vendedor").ingresos.sum())
    for index in (3, 5, 9):
        rows = turns[index]["result"]["rows"]
        assert {row["vendedor"]: row.get("ingresos_totales", row.get("ingresos", row.get("total_ventas"))) for row in rows} == pytest.approx(expected_vendor_income.to_dict())
    expected_by_branch = (
        source.assign(ingresos=source.cantidad * source.precio)
        .groupby(["sede", "vendedor"]).ingresos.sum().reset_index()
        .sort_values(["sede", "ingresos"], ascending=[True, False]).groupby("sede").first()["vendedor"].to_dict()
    )
    assert {row["sede"]: row["vendedor"] for row in turns[17]["result"]["rows"]} == expected_by_branch
    assert turns[20]["result"]["total_rows"] == 0 and "No encontré" in turns[20]["answer"], turns[20]["result"]
    assert turns[21]["result"]["total_rows"] == 0 and "No encontré" in turns[21]["answer"], turns[21]["result"]

    csv_vendor = pd.read_csv(turns[9]["exports"][0]["file_path"])
    excel_sede = pd.read_excel(turns[10]["exports"][0]["file_path"])
    csv_previous = pd.read_csv(turns[11]["exports"][0]["file_path"])
    csv_followup = pd.read_csv(turns[16]["exports"][0]["file_path"])
    assert len(csv_vendor) == source.vendedor.nunique()
    assert len(excel_sede) == len(csv_previous) == source.sede.nunique()
    assert excel_sede.set_index("sede")["unidades_vendidas"].to_dict() == expected_units.to_dict()
    assert csv_previous.set_index("sede")["unidades_vendidas"].to_dict() == expected_units.to_dict()
    income_column = next(column for column in csv_followup.columns if "ingres" in column.lower())
    units_column = next(column for column in csv_followup.columns if "unidad" in column.lower() or "cantidad" in column.lower())
    expected_income = source.assign(ingresos=source.cantidad * source.precio).groupby("sede").ingresos.sum()
    assert len(csv_followup) == source.sede.nunique()
    assert csv_followup.set_index("sede")[units_column].to_dict() == expected_units.to_dict()
    assert csv_followup.set_index("sede")[income_column].to_dict() == pytest.approx(expected_income.to_dict())
