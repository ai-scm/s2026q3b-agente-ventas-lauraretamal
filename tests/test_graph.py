"""Pruebas del plan LangGraph y sus acciones solicitadas."""

import asyncio
import json

from botocore.exceptions import ClientError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from services import sales_agent


class FakePlanModel:
    """Devuelve un único plan estructurado y cuenta las llamadas al modelo."""
    def __init__(self, plan):
        self.plan = plan
        self.calls = 0

    def bind_tools(self, tools, **kwargs):
        assert kwargs.get("tool_choice") == "any"
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return AIMessage(content="", tool_calls=[{
            "name": "SalesPlan", "args": self.plan, "id": "plan1", "type": "tool_call",
        }])


def test_plan_executes_only_requested_chart(monkeypatch):
    """Una sola llamada al modelo consulta y genera solo el gráfico pedido."""
    model = FakePlanModel({
        "requested_output": "chart",
        "query": "SELECT producto, SUM(cantidad) AS unidades FROM ventas GROUP BY producto",
        "charts": [{"chart_type": "bar", "x": "producto", "y": "unidades", "title": "Unidades por producto"}],
        "exports": [], "clarification": "",
    })
    monkeypatch.setattr(sales_agent, "ChatBedrockConverse", lambda **kwargs: model)
    calls = []

    async def fake_run_sql(query, read_query_tool=None):
        calls.append(("sql", query))
        return {"ok": True, "rows": [{"producto": "Café", "unidades": 8}], "total_rows": 1, "query": query}

    def fake_chart(results, result_id, chart_type, x, y, title):
        calls.append(("chart", result_id, x, y))
        return {"ok": True, "chart_path": "/tmp/chart.png"}

    def fail_export(*args, **kwargs):
        raise AssertionError("No se pidió exportar un archivo")

    monkeypatch.setattr(sales_agent, "run_sql", fake_run_sql)
    monkeypatch.setattr(sales_agent, "create_chart", fake_chart)
    monkeypatch.setattr(sales_agent, "export_file", fail_export)
    results = {}
    graph = sales_agent.create_sales_graph(results, object())
    output = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="Grafica unidades por producto")]}))
    assert model.calls == 1
    assert [call[0] for call in calls] == ["sql", "chart"]
    assert "Generé los gráficos" in output["messages"][-1].content
    charts = [json.loads(m.content) for m in output["messages"] if isinstance(m, ToolMessage) and m.name == "create_chart"]
    assert charts[0]["ok"]


def test_plan_does_not_create_unsolicited_visuals(monkeypatch):
    """Una pregunta factual no crea gráficos ni archivos por defecto."""
    model = FakePlanModel({"requested_output": "table", "query": "SELECT COUNT(DISTINCT producto) AS total_productos FROM ventas", "charts": [{"x": "producto", "y": "total_productos", "title": "No solicitado"}], "exports": [], "clarification": ""})
    monkeypatch.setattr(sales_agent, "ChatBedrockConverse", lambda **kwargs: model)

    async def fake_run_sql(query, read_query_tool=None):
        return {"ok": True, "rows": [{"total_productos": 10}], "total_rows": 1, "query": query}

    monkeypatch.setattr(sales_agent, "run_sql", fake_run_sql)
    monkeypatch.setattr(sales_agent, "create_chart", lambda *args: (_ for _ in ()).throw(AssertionError("gráfico no solicitado")))
    monkeypatch.setattr(sales_agent, "export_file", lambda *args: (_ for _ in ()).throw(AssertionError("archivo no solicitado")))
    output = asyncio.run(sales_agent.create_sales_graph({}, object()).ainvoke({"messages": [HumanMessage(content="¿Cuántos productos hay?")]}))
    assert output["messages"][-1].content == "Aquí están los resultados solicitados."


def test_plan_can_clarify_without_running_sql(monkeypatch):
    """Las solicitudes ambiguas pueden pedir precisión sin tocar la base."""
    model = FakePlanModel({"requested_output": "table", "query": "", "charts": [], "exports": [], "clarification": "¿Qué período quieres analizar?"})
    monkeypatch.setattr(sales_agent, "ChatBedrockConverse", lambda **kwargs: model)
    output = asyncio.run(sales_agent.create_sales_graph({}, object()).ainvoke({"messages": [HumanMessage(content="¿Qué fechas?")]}))
    assert output["messages"][-1].content == "¿Qué período quieres analizar?"


def test_previous_combined_export_rebuilds_missing_result(monkeypatch):
    """Reúne por MCP dos métricas referidas cuando no existe un resultado combinado."""
    model = FakePlanModel({
        "requested_output": "export", "query": "", "charts": [],
        "exports": [{"format": "csv", "filename": "ventas_sede", "columns": ["sede", "ingresos_totales", "unidades_vendidas"], "use_previous": True}],
        "clarification": "",
    })
    monkeypatch.setattr(sales_agent, "ChatBedrockConverse", lambda **kwargs: model)
    results = {"r1": {"columns": ["sede", "ingresos_totales"], "rows": [], "total_rows": 0, "query": "SELECT sede, SUM(cantidad*precio) FROM ventas GROUP BY sede"}}
    calls = []

    async def fake_run_sql(query, read_query_tool=None):
        calls.append(query)
        return {"ok": True, "rows": [{"sede": "Bogotá", "ingresos_totales": 100, "unidades_vendidas": 5}], "query": query}

    monkeypatch.setattr(sales_agent, "run_sql", fake_run_sql)
    monkeypatch.setattr(sales_agent, "export_file", lambda _results, rid, *_args: {"ok": True, "file_path": f"/tmp/{rid}.csv"})
    output = asyncio.run(sales_agent.create_sales_graph(results, object()).ainvoke({"messages": [HumanMessage(content="Guarda esos resultados en CSV")]}))
    assert "SUM(cantidad * precio) AS ingresos_totales" in calls[0]
    assert "SUM(cantidad) AS unidades_vendidas" in calls[0]
    assert output["messages"][-1].content == "Listo. Preparé los archivos solicitados para descargar."


def test_validation_error_retries_with_shorter_history(monkeypatch):
    """Un rechazo de validación reintenta la petición con menos turnos previos."""
    class RetryModel(FakePlanModel):
        def __init__(self):
            super().__init__({"requested_output": "table", "query": "", "charts": [], "exports": [], "clarification": "¿Qué deseas consultar?"})
            self.message_counts = []

        async def ainvoke(self, messages):
            self.calls += 1
            self.message_counts.append(len(messages))
            if self.calls == 1:
                raise ClientError({"Error": {"Code": "ValidationException", "Message": "input too long"}}, "Converse")
            return AIMessage(content="", tool_calls=[{"name": "SalesPlan", "args": self.plan, "id": "plan2", "type": "tool_call"}])

    model = RetryModel()
    monkeypatch.setattr(sales_agent, "ChatBedrockConverse", lambda **kwargs: model)
    history = [SystemMessage(content="system"), *[HumanMessage(content=f"turno {index}") for index in range(7)]]
    output = asyncio.run(sales_agent.create_sales_graph({}, object()).ainvoke({"messages": history}))
    assert model.message_counts == [8, 5]
    assert output["messages"][-1].content == "¿Qué deseas consultar?"


def test_agent_drops_orphan_assistant_turn_at_history_start(monkeypatch):
    """Bedrock recibe la conversación empezando por el primer usuario completo."""
    class HistoryModel(FakePlanModel):
        async def ainvoke(self, messages):
            self.received = messages
            return AIMessage(content="", tool_calls=[{"name": "SalesPlan", "args": self.plan, "id": "plan3", "type": "tool_call"}])

    model = HistoryModel({"requested_output": "table", "query": "", "charts": [], "exports": [], "clarification": "Listo"})
    monkeypatch.setattr(sales_agent, "ChatBedrockConverse", lambda **kwargs: model)
    messages = [
        SystemMessage(content="system"), AIMessage(content="respuesta huérfana"),
        HumanMessage(content="pregunta anterior"), AIMessage(content="respuesta anterior"),
        HumanMessage(content="pregunta actual"),
    ]
    asyncio.run(sales_agent.create_sales_graph({}, object()).ainvoke({"messages": messages}))
    dialogue = [message for message in model.received if not isinstance(message, SystemMessage)]
    assert isinstance(dialogue[0], HumanMessage)
    assert dialogue[0].content == "pregunta anterior"


def test_singular_ranking_is_limited_to_one_ordered_row():
    plan = sales_agent.SalesPlan(query="", requested_output="table", single_result=True, rank_by="ingresos", rank_direction="DESC")
    query = "SELECT vendedor, SUM(cantidad * precio) AS ingresos FROM ventas GROUP BY vendedor ORDER BY ingresos DESC LIMIT 5"
    ranked = sales_agent._rank_query(query, plan)
    assert ranked.endswith("ORDER BY ingresos DESC LIMIT 1")
    assert "LIMIT 5" not in ranked


def test_per_group_ranking_keeps_one_winner_for_each_branch():
    rows = [
        {"sede": "Bogotá", "vendedor": "A", "ingresos": 10},
        {"sede": "Bogotá", "vendedor": "B", "ingresos": 20},
        {"sede": "Cali", "vendedor": "C", "ingresos": 5},
        {"sede": "Cali", "vendedor": "D", "ingresos": 4},
    ]
    winners = sales_agent._top_per_group(rows, "sede", "ingresos", "DESC")
    assert [(row["sede"], row["vendedor"]) for row in winners] == [("Bogotá", "B"), ("Cali", "C")]


def test_per_group_ranking_uses_sql_row_number():
    plan = sales_agent.SalesPlan(
        requested_output="table",
        query="SELECT sede, MAX(ingresos) FROM ventas GROUP BY sede",
        group_by="sede", rank_by="ingresos",
    )
    query = sales_agent._group_rank_query(plan)
    assert "ROW_NUMBER() OVER (PARTITION BY sede ORDER BY ingresos DESC)" in query
    assert "SELECT sede, vendedor" in query
    assert "GROUP BY sede, vendedor" in query
    assert "WHERE _pos = 1" in query


def test_partial_plan_infers_output_from_requested_actions():
    assert sales_agent._output_intent(sales_agent.SalesPlan(query="", exports=[{"format": "csv", "filename": "ventas", "columns": ["sede"]}])) == "export"
    assert sales_agent._output_intent(sales_agent.SalesPlan(query="", charts=[{"x": "sede", "y": "unidades", "title": "Unidades"}])) == "chart"
    assert sales_agent._output_intent(sales_agent.SalesPlan(query="")) == "table"


def test_contextual_chart_includes_related_revenue_and_units():
    charts = [sales_agent.ChartRequest(x="sede", y="unidades_vendidas", title="Unidades por sede")]
    results = {
        "r1": {"columns": ["sede", "ingresos_totales"], "rows": [{"sede": "Bogotá", "ingresos_totales": 10}], "query": "SELECT sede, SUM(cantidad*precio) AS ingresos_totales FROM ventas GROUP BY sede"},
        "r2": {"columns": ["sede", "unidades_vendidas"], "rows": [{"sede": "Bogotá", "unidades_vendidas": 2}], "query": "SELECT sede, SUM(cantidad) AS unidades_vendidas FROM ventas GROUP BY sede"},
    }
    expanded = sales_agent._expand_contextual_charts(charts, results, "Muéstrame esos resultados en un gráfico")
    assert {chart.y for chart in expanded} == {"unidades_vendidas", "ingresos_totales"}
    assert len(sales_agent._expand_contextual_charts(charts, results, "Muéstrame unidades por sede")) == 1


def test_contextual_export_combines_metrics_from_related_results():
    exports = [sales_agent.ExportRequest(format="csv", filename="resultados", columns=["sede", "unidades_vendidas"], use_previous=True)]
    results = {
        "r1": {"columns": ["sede", "ingresos_totales"], "rows": [{"sede": "Bogotá", "ingresos_totales": 10}], "query": "SELECT sede, SUM(cantidad*precio) AS ingresos_totales FROM ventas GROUP BY sede"},
        "r2": {"columns": ["sede", "unidades_vendidas"], "rows": [{"sede": "Bogotá", "unidades_vendidas": 2}], "query": "SELECT sede, SUM(cantidad) AS unidades_vendidas FROM ventas GROUP BY sede"},
    }
    query = sales_agent._contextual_export_query(exports, results, "Guarda esos resultados en CSV")
    assert "SUM(cantidad * precio) AS ingresos_totales" in query
    assert "SUM(cantidad) AS unidades_vendidas" in query
    assert sales_agent._contextual_export_query(exports, results, "Guarda los resultados de la consulta anterior") == ""
    partial = {"r1": results["r2"]}
    query_from_context = sales_agent._contextual_export_query(
        exports, partial, "Guarda esos resultados en CSV",
        "¿Cuáles son los ingresos totales por sede? ¿Y cuál vendió más unidades?",
    )
    assert "SUM(cantidad * precio) AS ingresos_totales" in query_from_context


def test_contextual_single_winner_reuses_and_ranks_prior_result(monkeypatch):
    model = FakePlanModel({
        "requested_output": "table", "query": "", "single_result": True,
        "rank_by": "unidades_vendidas", "rank_direction": "DESC", "charts": [], "exports": [],
    })
    monkeypatch.setattr(sales_agent, "ChatBedrockConverse", lambda **kwargs: model)
    results = {"r1": {
        "columns": ["sede", "unidades_vendidas"],
        "rows": [{"sede": "Cali", "unidades_vendidas": 10}, {"sede": "Bogotá", "unidades_vendidas": 15}],
        "total_rows": 2, "query": "SELECT sede, SUM(cantidad) AS unidades_vendidas FROM ventas GROUP BY sede",
    }}
    output = asyncio.run(sales_agent.create_sales_graph(results, object()).ainvoke({"messages": [HumanMessage(content="¿Cuál sede vendió más unidades?")]}))
    payload = next(json.loads(message.content) for message in output["messages"] if isinstance(message, ToolMessage) and message.name == "result_data")
    assert payload["rows"] == [{"sede": "Bogotá", "unidades_vendidas": 15}]
