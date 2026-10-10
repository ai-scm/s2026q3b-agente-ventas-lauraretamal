"""Planificación de ventas con una llamada Bedrock y ejecución MCP local."""

import json
import re
from typing import Any, Literal

from botocore.exceptions import ClientError
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel, Field

from services.actions import create_chart, export_file
from services.bedrock import MODEL_ID, REGION_NAME
from services.mcp_sql import get_read_query_tool, run_sql


class ChartRequest(BaseModel):
    """Gráfico pedido por el usuario."""
    chart_type: Literal["bar", "line", "pie"] = "bar"
    x: str = Field(description="Columna de categorías")
    y: str = Field(description="Columna numérica")
    title: str
    result_id: str = ""
    all_categories: bool = True


class ExportRequest(BaseModel):
    """Archivo pedido por el usuario."""
    format: Literal["csv", "xlsx"]
    filename: str = Field(description="Nombre sencillo sin rutas ni extensión")
    result_id: str = ""
    columns: list[str] = Field(description="Nombres exactos de las columnas que debe contener el archivo")
    use_previous: bool = False


class SalesPlan(BaseModel):
    """Plan único de consulta y acciones, interpretado semánticamente por Bedrock."""
    query: str = Field(description="Consulta SELECT/WITH necesaria. Solo déjala vacía cuando haya un resultado anterior completo compatible que se reutilizará")
    requested_output: Literal["table", "chart", "export", "chart_and_export"] | None = Field(default=None, description="Formato pedido explícitamente en el mensaje más reciente")
    single_result: bool = Field(default=False, description="True si la pregunta pide una sola entidad ganadora o un único máximo/mínimo")
    rank_by: str = Field(default="", description="Alias de la columna numérica usada para ordenar el resultado")
    rank_direction: Literal["ASC", "DESC"] = "DESC"
    group_by: str = Field(default="", description="Dimensión para devolver un ganador por cada grupo, por ejemplo sede")
    rank_entity: str = Field(default="", description="Entidad que gana dentro de cada grupo, por ejemplo vendedor")
    charts: list[ChartRequest] = Field(default_factory=list, description="Solo gráficos que el usuario pidió explícitamente")
    exports: list[ExportRequest] = Field(default_factory=list, description="Solo archivos que el usuario pidió explícitamente")
    clarification: str = Field(default="", description="Pregunta de aclaración o respuesta breve fuera de alcance; vacío si se puede proceder")


class SalesState(MessagesState):
    """Estado mínimo del turno conversacional."""


def _rank_query(query: str, plan: SalesPlan) -> str:
    """Aplica límites de cardinalidad declarados por el planificador."""
    statement = query.strip().rstrip(";")
    if plan.single_result or plan.group_by:
        statement = re.sub(r"\s+LIMIT\s+\d+(?:\s+OFFSET\s+\d+)?\s*$", "", statement, flags=re.I)
    if plan.single_result:
        if plan.rank_by and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", plan.rank_by):
            statement = re.sub(r"\s+ORDER\s+BY\s+.+$", "", statement, flags=re.I | re.S)
            statement += f" ORDER BY {plan.rank_by} {plan.rank_direction}"
        statement += " LIMIT 1"
    return statement


def _group_rank_query(plan: SalesPlan) -> str:
    """Construye un ranking SQL correcto por grupo cuando no hay filtros explícitos."""
    group = plan.group_by.casefold()
    query = plan.query
    if group not in {"sede", "vendedor", "producto"} or re.search(r"\bWHERE\b", query, re.I):
        return ""
    entity = plan.rank_entity if plan.rank_entity in {"vendedor", "producto"} else ""
    if not entity:
        entity = next((name for name in ("vendedor", "producto") if name != group and re.search(rf"\b{name}\b", query, re.I)), "")
    if not entity and group == "sede":
        entity = "vendedor"
    alias = plan.rank_by
    if not entity or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
        return ""
    metric = re.sub(r"[^a-z0-9]", "", alias.lower())
    metric = re.sub(r"(totales|total|vendidas|vendidos|ventas)$", "", metric)
    if metric in {"ingreso", "ingresos", "venta"}:
        expression = "SUM(cantidad * precio)"
    elif metric in {"unidad", "unidades", "cantidad"}:
        expression = "SUM(cantidad)"
    else:
        return ""
    return (
        f"WITH _agrupado AS (SELECT {group}, {entity}, {expression} AS {alias} FROM ventas "
        f"GROUP BY {group}, {entity}), "
        f"_ranking AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY {group} ORDER BY {alias} {plan.rank_direction}) AS _pos "
        f"FROM _agrupado) SELECT {group}, {entity}, {alias} FROM _ranking WHERE _pos = 1 ORDER BY {group}"
    )


def _output_intent(plan: SalesPlan) -> str:
    """Resuelve planes antiguos o parciales a partir de las acciones que contienen."""
    if plan.requested_output:
        return plan.requested_output
    if plan.charts and plan.exports:
        return "chart_and_export"
    if plan.charts:
        return "chart"
    if plan.exports:
        return "export"
    return "table"


def _expand_contextual_charts(charts: list[ChartRequest], results: dict[str, dict[str, Any]], reference: str) -> list[ChartRequest]:
    """Añade métricas previas compatibles cuando el usuario pide graficar varios resultados referidos."""
    text = reference.casefold()
    if not charts or not any(token in text for token in ("esos resultados", "estos resultados", "resultados anteriores", "consulta anterior", "esos datos", "estos datos")):
        return charts
    expanded = list(charts)
    for chart in charts:
        used_metrics = set()
        for name in (chart.y,):
            key = re.sub(r"[^a-z0-9]", "", name.casefold())
            key = re.sub(r"(totales|total|vendidas|vendidos|ventas)$", "", key)
            used_metrics.add("ingresos" if key in {"ingreso", "ingresos", "venta"} else "unidades" if key in {"unidad", "unidades", "cantidad"} else key)
        for _, value in reversed(list(results.items())[-8:]):
            if chart.x not in value["columns"] or not value["rows"] or re.search(r"\bLIMIT\s+\d+", value["query"], re.I):
                continue
            for column in value["columns"]:
                if column == chart.x:
                    continue
                sample = value["rows"][0].get(column)
                if not isinstance(sample, (int, float)) or isinstance(sample, bool):
                    continue
                key = re.sub(r"[^a-z0-9]", "", column.casefold())
                metric = re.sub(r"(totales|total|vendidas|vendidos|ventas)$", "", key)
                if metric in {"ingreso", "ingresos", "venta"}:
                    title = f"Ingresos por {chart.x}"
                elif metric in {"unidad", "unidades", "cantidad"}:
                    metric = "unidades"
                    title = f"Unidades vendidas por {chart.x}"
                else:
                    continue
                if metric in used_metrics:
                    continue
                expanded.append(ChartRequest(chart_type=chart.chart_type, x=chart.x, y=column, title=title))
                used_metrics.add(metric)
                break
    return expanded


def _contextual_export_query(exports: list[ExportRequest], results: dict[str, dict[str, Any]], reference: str, recent_context: str = "") -> str:
    """Reúne en SQL las métricas de varios resultados que se exportan juntos."""
    text = reference.casefold()
    if not any(token in text for token in ("esos resultados", "estos resultados", "esos datos", "estos datos")):
        return ""
    export = next((item for item in exports if item.use_previous), None)
    if not export:
        return ""
    columns = {re.sub(r"[^a-z0-9]", "", column.casefold()) for column in export.columns}
    dimension = next((name for name in ("sede", "vendedor", "producto") if name in columns), "")
    if not dimension:
        return ""
    metrics = set()
    for value in list(results.values())[-8:]:
        if dimension not in value["columns"] or re.search(r"\b(?:LIMIT|WHERE)\b", value["query"], re.I):
            continue
        for column in value["columns"]:
            key = re.sub(r"[^a-z0-9]", "", column.casefold())
            key = re.sub(r"(totales|total|vendidas|vendidos|ventas)$", "", key)
            if key in {"ingreso", "ingresos", "venta"}:
                metrics.add("ingresos")
            elif key in {"unidad", "unidades", "cantidad"}:
                metrics.add("unidades")
    context = recent_context.casefold()
    if re.search(r"ingres", context) and re.search(r"unidades?|cantidades?", context):
        metrics.update({"ingresos", "unidades"})
    if len(metrics) < 2:
        return ""
    projections = [dimension]
    if "ingresos" in metrics:
        projections.append("SUM(cantidad * precio) AS ingresos_totales")
    if "unidades" in metrics:
        projections.append("SUM(cantidad) AS unidades_vendidas")
    return f"SELECT {', '.join(projections)} FROM ventas GROUP BY {dimension} ORDER BY {dimension}"


def _top_per_group(rows: list[dict[str, Any]], group_by: str, rank_by: str, direction: str) -> list[dict[str, Any]]:
    """Conserva el mejor registro de cada grupo a partir de resultados agregados."""
    if not group_by or not rank_by or not rows or any(group_by not in row or rank_by not in row for row in rows):
        return rows
    winners = {}
    for row in rows:
        try:
            value = float(row[rank_by])
        except (TypeError, ValueError):
            return rows
        key = row[group_by]
        current = winners.get(key)
        if current is None or (value > float(current[rank_by]) if direction == "DESC" else value < float(current[rank_by])):
            winners[key] = row
    return sorted(winners.values(), key=lambda row: str(row[group_by]))


def create_sales_graph(results: dict[str, dict[str, Any]], mcp_tool: Any):
    """Compila un plan de una llamada y ejecuta SQL, gráficos y archivos en serie."""
    model = ChatBedrockConverse(model=MODEL_ID, region_name=REGION_NAME, temperature=0)
    planner = model.bind_tools([SalesPlan], tool_choice="any")

    async def plan_node(state: SalesState):
        """Interpreta la intención y emite un solo plan estructurado."""
        system = [message for message in state["messages"] if isinstance(message, SystemMessage)]
        dialogue = [message for message in state["messages"] if not isinstance(message, SystemMessage)]
        while dialogue and not isinstance(dialogue[0], HumanMessage):
            dialogue.pop(0)
        messages = system + dialogue
        try:
            answer = await planner.ainvoke(messages)
        except ClientError as exc:
            error = exc.response.get("Error", {})
            detail = error.get("Message", "").lower()
            length_issue = any(term in detail for term in ("token", "length", "too long", "too large", "exceeds", "context", "payload size"))
            if error.get("Code") != "ValidationException" or not length_issue or not messages:
                raise
            system = next((message for message in messages if isinstance(message, SystemMessage)), None)
            recent = [message for message in messages if not isinstance(message, SystemMessage)][-4:]
            while recent and not isinstance(recent[0], HumanMessage):
                recent.pop(0)
            if system:
                compact_system = system.model_copy(update={"content": system.content.split("\nResultados disponibles", 1)[0]})
                recent.insert(0, compact_system)
            answer = await planner.ainvoke(recent)
        return {"messages": [answer]}

    async def execute_node(state: SalesState):
        """Ejecuta únicamente las acciones especificadas en el plan validado."""
        plan_message = state["messages"][-1]
        call = plan_message.tool_calls[0] if isinstance(plan_message, AIMessage) and plan_message.tool_calls else None
        if call is None or call["name"] != "SalesPlan":
            return {"messages": [AIMessage(content="No pude interpretar la solicitud. Intenta formularla de otra manera.")]}

        plan_args = dict(call["args"])
        if "query" not in plan_args:
            reusable = any(
                chart.get("result_id") in results
                or any(chart.get("x") in value["columns"] and chart.get("y") in value["columns"] for value in results.values())
                for chart in plan_args.get("charts", [])
            )
            reusable = reusable or any(item.get("use_previous") or item.get("result_id") in results for item in plan_args.get("exports", []))
            rank_by = plan_args.get("rank_by")
            reusable = reusable or bool(rank_by and any(rank_by in value["columns"] for value in results.values()))
            if reusable:
                plan_args["query"] = ""
        try:
            plan = SalesPlan.model_validate(plan_args)
        except Exception:
            return {"messages": [AIMessage(content="No pude preparar una consulta válida para esa solicitud.")]}
        tool_messages = [ToolMessage(
            content=json.dumps({"ok": True}, ensure_ascii=False),
            tool_call_id=call["id"], name="SalesPlan",
        )]
        if plan.clarification:
            return {"messages": [*tool_messages, AIMessage(content=plan.clarification)]}
        output_intent = _output_intent(plan)
        charts = plan.charts if output_intent in {"chart", "chart_and_export"} else []
        exports = plan.exports if output_intent in {"export", "chart_and_export"} else []
        latest_user = next((message.content for message in reversed(state["messages"]) if isinstance(message, HumanMessage) and isinstance(message.content, str)), "")
        recent_context = " ".join(message.content for message in state["messages"] if isinstance(message, HumanMessage) and isinstance(message.content, str))
        charts = _expand_contextual_charts(charts, results, latest_user)
        if len(charts) > 2 or len(exports) > 2:
            return {"messages": [*tool_messages, AIMessage(content="Limité este turno a dos gráficos y dos archivos. Divide la solicitud para continuar.")]}
        result_id = ""
        contextual_export_query = _contextual_export_query(exports, results, latest_user, recent_context)
        query = contextual_export_query or ((_group_rank_query(plan) or _rank_query(plan.query, plan)) if plan.query else "")
        if query:
            result = await run_sql(query, read_query_tool=mcp_tool)
            if not result.get("ok"):
                tool_messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call["id"] + "-sql", name="run_sql"))
                return {"messages": [*tool_messages, AIMessage(content="No pude completar la consulta. Revisa los filtros o intenta reformularla.")]}
            rows = result.get("rows", [])
            if rows and all(all(value is None for value in row.values()) for row in rows):
                rows = []
            if plan.group_by and plan.rank_by:
                rows = _top_per_group(rows, plan.group_by, plan.rank_by, plan.rank_direction)
            columns = list(rows[0]) if rows else []
            result_id = f"r{len(results) + 1}"
            results[result_id] = {"columns": columns, "rows": rows, "total_rows": result.get("total_rows", len(rows)) if rows else 0, "query": result["query"]}
            sql_output = {"ok": True, "result_id": result_id, "columns": columns, "rows": rows[:50], "total_rows": len(rows), "query": result["query"]}
            tool_messages.append(ToolMessage(content=json.dumps(sql_output, ensure_ascii=False, default=str), tool_call_id=call["id"] + "-sql", name="run_sql"))
        elif plan.single_result and plan.rank_by and output_intent == "table":
            source_id = next((rid for rid, value in reversed(list(results.items()))
                              if plan.rank_by in value["columns"] and value["rows"]
                              and not re.search(r"\bLIMIT\s+\d+", value["query"], re.I)), "")
            if source_id:
                source = results[source_id]
                try:
                    winner = (max if plan.rank_direction == "DESC" else min)(source["rows"], key=lambda row: float(row[plan.rank_by]))
                    result_id = f"r{len(results) + 1}"
                    results[result_id] = {**source, "rows": [winner], "total_rows": 1}
                    payload = {"ok": True, "result_id": result_id, "columns": results[result_id]["columns"], "rows": [winner], "total_rows": 1, "query": results[result_id]["query"]}
                    tool_messages.append(ToolMessage(content=json.dumps(payload, ensure_ascii=False), tool_call_id=call["id"] + "-result", name="result_data"))
                except (KeyError, TypeError, ValueError):
                    result_id = ""

        chart_paths, file_paths = [], []
        action_errors = []
        for chart in charts if not (result_id and not results[result_id]["rows"]) else []:
            source_id = chart.result_id if chart.result_id in results else result_id
            if not source_id or chart.x not in results[source_id]["columns"] or chart.y not in results[source_id]["columns"]:
                source_id = next((rid for rid, value in reversed(list(results.items())) if chart.x in value["columns"] and chart.y in value["columns"]), "")
            if source_id and chart.all_categories and re.search(r"\bLIMIT\s+\d+", results[source_id]["query"], re.I):
                full_query = re.sub(r"\s+LIMIT\s+\d+(?:\s+OFFSET\s+\d+)?\s*;?\s*$", "", results[source_id]["query"], flags=re.I)
                expanded = await run_sql(full_query, read_query_tool=mcp_tool)
                if expanded.get("ok"):
                    rows = expanded["rows"]
                    source_id = f"r{len(results) + 1}"
                    results[source_id] = {"columns": list(rows[0]) if rows else results.get(source_id, {}).get("columns", []), "rows": rows, "total_rows": len(rows), "query": expanded["query"]}
                    payload = {"ok": True, "result_id": source_id, "columns": results[source_id]["columns"], "rows": rows[:50], "total_rows": len(rows), "query": expanded["query"]}
                    tool_messages.append(ToolMessage(content=json.dumps(payload, ensure_ascii=False), tool_call_id=call["id"] + "-sql-full", name="run_sql"))
            if source_id:
                value = results[source_id]
                tool_messages.append(ToolMessage(content=json.dumps({"ok": True, "result_id": source_id, "columns": value["columns"], "rows": value["rows"][:50], "total_rows": value["total_rows"], "query": value["query"]}, ensure_ascii=False), tool_call_id=call["id"] + "-data", name="result_data"))
                output = create_chart(results, source_id, chart.chart_type, chart.x, chart.y, chart.title)
            else:
                output = {"ok": False, "message": "No hay un resultado completo compatible con este gráfico."}
            tool_messages.append(ToolMessage(content=json.dumps(output, ensure_ascii=False), tool_call_id=call["id"] + "-chart", name="create_chart"))
            if output.get("ok"):
                chart_paths.append(output["chart_path"])
            else:
                action_errors.append(output.get("message", "No se pudo crear el gráfico."))

        for export in exports if not (result_id and not results[result_id]["rows"]) else []:
            def column_key(name: str) -> str:
                key = re.sub(r"[^a-z0-9]", "", name.lower())
                key = re.sub(r"^(total|sum|suma)", "", key)
                key = re.sub(r"(totales|total|vendidas|vendidos|ventas)$", "", key)
                if key in {"cantidad", "unidad", "unidades", "units"}:
                    return "unidades"
                if key in {"ingreso", "ingresos", "venta", "ventas"}:
                    return "ingresos"
                return key

            def matches_export(rid: str) -> bool:
                value = results[rid]
                available = {column_key(column) for column in value["columns"]}
                expected = {column_key(column) for column in export.columns}
                return expected.issubset(available) and (not re.search(r"\bLIMIT\s+\d+", value["query"], re.I))

            if result_id and matches_export(result_id):
                source_id = result_id
            elif export.use_previous:
                source_id = next((rid for rid, value in reversed(list(results.items())) if rid != result_id and matches_export(rid)), "")
            else:
                source_id = export.result_id if export.result_id in results and matches_export(export.result_id) else ""
            if not source_id and export.use_previous:
                requested = {column_key(column) for column in export.columns}
                dimensions = [name for name in ("sede", "vendedor", "producto") if name in requested]
                metrics = []
                if "ingresos" in requested:
                    metrics.append("SUM(cantidad * precio) AS ingresos_totales")
                if "unidades" in requested:
                    metrics.append("SUM(cantidad) AS unidades_vendidas")
                if dimensions and metrics and len(requested) == len(dimensions) + len(metrics):
                    columns_sql = ", ".join([*dimensions, *metrics])
                    query = f"SELECT {columns_sql} FROM ventas GROUP BY {', '.join(dimensions)} ORDER BY {', '.join(dimensions)}"
                    result = await run_sql(query, read_query_tool=mcp_tool)
                    if result.get("ok") and result.get("rows"):
                        rows = result["rows"]
                        source_id = f"r{len(results) + 1}"
                        results[source_id] = {"columns": list(rows[0]), "rows": rows, "total_rows": len(rows), "query": result["query"]}
                        tool_messages.append(ToolMessage(content=json.dumps({"ok": True, "result_id": source_id, "columns": results[source_id]["columns"], "rows": rows[:50], "total_rows": len(rows), "query": result["query"]}, ensure_ascii=False), tool_call_id=call["id"] + "-sql-export", name="run_sql"))
            if source_id:
                value = results[source_id]
                tool_messages.append(ToolMessage(content=json.dumps({"ok": True, "result_id": source_id, "columns": value["columns"], "rows": value["rows"][:50], "total_rows": value["total_rows"], "query": value["query"]}, ensure_ascii=False), tool_call_id=call["id"] + "-data", name="result_data"))
                output = export_file(results, source_id, export.format, export.filename)
            else:
                output = {"ok": False, "message": "No hay resultados disponibles para exportar."}
            tool_messages.append(ToolMessage(content=json.dumps(output, ensure_ascii=False), tool_call_id=call["id"] + "-export", name="export_file"))
            if output.get("ok"):
                file_paths.append(output["file_path"])
            else:
                action_errors.append(output.get("message", "No se pudo exportar el archivo."))

        if not result_id and not charts and not exports:
            return {"messages": [*tool_messages, AIMessage(content="No pude preparar una consulta para esa solicitud.")]}

        if result_id and not results[result_id]["rows"]:
            answer = "No encontré ventas que coincidan con esos criterios."
        elif chart_paths and file_paths:
            answer = "Listo. Generé los gráficos y preparé los archivos solicitados."
        elif chart_paths:
            answer = "Listo. Generé los gráficos solicitados."
        elif file_paths:
            answer = "Listo. Preparé los archivos solicitados para descargar."
        elif charts or exports:
            answer = "Encontré los datos, pero no pude completar una de las acciones solicitadas. " + " ".join(action_errors)
        else:
            answer = "Aquí están los resultados solicitados."
        return {"messages": [*tool_messages, AIMessage(content=answer)]}

    graph = StateGraph(SalesState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", END)
    return graph.compile()


async def create_sales_agent(results: dict[str, dict[str, Any]]):
    """Conecta una sola herramienta de lectura MCP y compila el flujo."""
    return create_sales_graph(results, await get_read_query_tool())


def assistant_text(message: BaseMessage) -> str:
    """Normaliza el contenido textual de una respuesta LangChain."""
    if isinstance(message.content, str):
        return message.content
    return "\n".join(block.get("text", "") for block in message.content if isinstance(block, dict) and block.get("type") == "text")
