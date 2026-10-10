"""Interfaz Streamlit del agente de análisis de ventas."""

from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import os
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
import streamlit as st
from langchain_core.messages import AIMessage, SystemMessage
from services.database import ensure_database
from services.prompt import SYSTEM_PROMPT
from services.sales_agent import assistant_text, create_sales_agent
from services.chat_storage import new_chat_id, save_chat
from services.chat_history import model_history
from ui.chat import hide_chat_icons, show_messages

st.set_page_config(page_title="Agente de análisis de ventas", page_icon="img/icon.svg", layout="wide")
hide_chat_icons()
ensure_database()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "chat_id" not in st.session_state:
    st.session_state.chat_id = new_chat_id()
if "results" not in st.session_state:
    st.session_state.results = {}
if "agent_graph" not in st.session_state:
    st.session_state.agent_graph = None
if st.session_state.get("agent_chat_id") != st.session_state.chat_id:
    st.session_state.results = {}
    st.session_state.agent_graph = None
    st.session_state.agent_chat_id = st.session_state.chat_id

from ui.sidebar import show_sidebar
show_sidebar()
st.title("Agente de análisis de ventas")
st.caption("Consulta las ventas en lenguaje natural y recibe tablas, gráficos o archivos.")
show_messages()


def _message_history():
    """Convierte los turnos recientes al formato de LangChain para reducir latencia."""
    return model_history(st.session_state.messages)


def _tool_outputs(messages):
    """Recoge filas, gráficos y archivos producidos en el turno."""
    found = {"sql": None, "table": None, "total_rows": None, "chart_paths": [], "file_paths": []}
    for message in messages:
        if getattr(message, "type", "") != "tool":
            continue
        content = message.content
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        try:
            payload = json.loads(content) if isinstance(content, str) else {}
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if message.name in {"run_sql", "result_data"} and payload.get("ok"):
            found.update(sql=payload.get("query"), table=payload.get("rows", [])[:50], total_rows=payload.get("total_rows"))
        elif message.name == "create_chart" and payload.get("ok"):
            found["chart_paths"].append(payload["chart_path"])
        elif message.name == "export_file" and payload.get("ok"):
            found["file_paths"].append(payload["file_path"])
    found["chart_path"] = found["chart_paths"][-1] if found["chart_paths"] else None
    found["file_path"] = found["file_paths"][-1] if found["file_paths"] else None
    return found


def _aws_error(exc):
    """Convierte errores de autenticación, modelo y región en mensajes útiles."""
    code = exc.response.get("Error", {}).get("Code", "") if isinstance(exc, ClientError) else ""
    if isinstance(exc, NoCredentialsError):
        return "No se encontraron credenciales AWS. Configura el perfil AWS o revisa AWS_BEARER_TOKEN_BEDROCK en .env."
    if code in {"UnrecognizedClientException", "InvalidSignatureException", "UnauthorizedException", "AccessDeniedException"}:
        return f"Bedrock rechazó la autenticación o el acceso ({code}). Revisa el token y los permisos del modelo."
    if code in {"ResourceNotFoundException", "ModelNotReadyException"}:
        return f"El modelo {os.getenv('BEDROCK_MODEL_ID', 'amazon.nova-pro-v1:0')} no está disponible en us-east-1 ({code})."
    if code in {"ValidationException", "UnsupportedModelException"}:
        detail = exc.response.get("Error", {}).get("Message", "") if isinstance(exc, ClientError) else ""
        return f"Bedrock rechazó la solicitud ({code}). {detail or 'Revisa el modelo y la solicitud.'}"
    if isinstance(exc, BotoCoreError):
        return f"No fue posible conectar con Bedrock. Revisa la región us-east-1 y la red: {exc}"
    return f"Error de Amazon Bedrock: {exc}"


question = st.chat_input("Pregunta por tus ventas…")
if question:
    st.session_state.messages.append({"role": "user", "text": question, "sql": None, "table": None, "chart_path": None, "file_path": None})
    with st.chat_message("user", avatar=None):
        st.markdown(question)
    try:
        if st.session_state.agent_graph is None:
            with st.spinner("Conectando con el servidor SQL..."):
                st.session_state.agent_graph = asyncio.run(create_sales_agent(st.session_state.results))
        summary = [
            {"result_id": rid, "columns": data["columns"], "total_rows": data["total_rows"], "query": data["query"], "rows": data["rows"][:5]}
            for rid, data in list(st.session_state.results.items())[-8:]
        ]
        context = SYSTEM_PROMPT + "\nResultados disponibles de esta conversación: " + json.dumps(summary, ensure_ascii=False)
        inputs = {"messages": [SystemMessage(content=context), *_message_history()], "tool_calls_used": 0, "limit_reached": False}
        with st.spinner("Analizando tus ventas..."):
            response = asyncio.run(st.session_state.agent_graph.ainvoke(inputs))
        assistant = next((message for message in reversed(response["messages"]) if isinstance(message, AIMessage) and not message.tool_calls), None)
        answer = assistant_text(assistant) if assistant else "No se recibió una respuesta del agente."
        outputs = _tool_outputs(response["messages"])
        if outputs["chart_paths"] and outputs["file_paths"]:
            answer = "Listo. Generé los gráficos y preparé los archivos solicitados para descargar."
        elif outputs["chart_paths"]:
            answer = "Listo. Generé los gráficos solicitados."
        elif outputs["file_paths"]:
            answer = "Listo. Preparé los archivos solicitados para descargar."
        elif outputs["table"] is not None and outputs["total_rows"] == 0:
            answer = "No encontré ventas que coincidan con esos criterios."
        elif outputs["table"]:
            answer = "Aquí están los resultados solicitados."
        st.session_state.messages.append({"role": "assistant", "text": answer, **outputs})
        try:
            save_chat(st.session_state.messages, st.session_state.chat_id)
        except Exception as exc:
            st.sidebar.warning(f"No se pudo guardar en S3: {exc}")
        st.rerun()
    except Exception as exc:
        st.session_state.messages.append({"role": "assistant", "text": _aws_error(exc), "sql": None, "table": None, "chart_path": None, "file_path": None})
        try:
            save_chat(st.session_state.messages, st.session_state.chat_id)
        except Exception:
            pass
        st.rerun()
