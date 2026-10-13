"""Selector de bases y conversaciones locales."""

import sqlite3

import streamlit as st

from services.chat_storage import delete_chat, get_chat_titles, get_saved_chats, load_chat_data, new_chat_id
from services.workspaces import create_workspace, list_workspaces


def _new_chat(workspace_id: str) -> None:
    st.session_state.workspace_id = workspace_id
    st.session_state.chat_id = new_chat_id()
    st.session_state.messages = []
    st.session_state.results = {}
    st.session_state.agent_graph = None


def show_sidebar():
    with st.sidebar:
        st.markdown("""
        <style>
        div[class*="st-key-chat_row_"] {
            position: relative;
            border: 1px solid transparent;
            border-radius: .5rem;
            overflow: hidden;
        }
        div[class*="st-key-chat_row_active_"] {
            background: #34353d;
            border-color: #50515b;
        }
        div[class*="st-key-chat_row_"] [data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap;
            gap: 0;
        }
        div[class*="st-key-chat_row_"] [data-testid="stColumn"]:last-child {
            position: absolute;
            right: .25rem;
            top: 50%;
            transform: translateY(-50%);
            width: auto !important;
            min-width: 0 !important;
        }
        div[class*="st-key-chat_row_"] [data-testid="stColumn"]:last-child button {
            opacity: 0;
            border: 0;
            background: transparent;
            padding: .25rem .45rem;
        }
        div[class*="st-key-chat_row_"]:hover [data-testid="stColumn"]:last-child button {
            opacity: 1;
        }
        div[class*="st-key-chat_row_"] button {
            background: transparent !important;
            border-color: transparent !important;
            color: inherit !important;
        }
        div[class*="st-key-chat_row_"] button:hover {
            background: rgba(255, 255, 255, .06) !important;
        }
        div[class*="st-key-chat_row_active_"] button {
            color: #f0f0f3 !important;
        }
        </style>
        """, unsafe_allow_html=True)
        st.header("Bases y conversaciones")
        workspaces = list_workspaces()
        names = {workspace["id"]: workspace["name"] for workspace in workspaces}
        ids = list(names)
        if st.session_state.workspace_id not in names:
            _new_chat(ids[0])
        chosen = st.selectbox(
            "Base de datos", ids, index=ids.index(st.session_state.workspace_id),
            format_func=lambda workspace_id: names[workspace_id], key=f"workspace_selector_{len(ids)}",
        )
        if chosen != st.session_state.workspace_id:
            chats = get_saved_chats(chosen)
            if chats:
                data = load_chat_data(chats[0], chosen)
                st.session_state.workspace_id = chosen
                st.session_state.chat_id = chats[0]
                st.session_state.messages = data["messages"]
                st.session_state.results = data["results"]
                st.session_state.agent_graph = None
            else:
                _new_chat(chosen)
            st.rerun()

        with st.form("upload_csv_form", clear_on_submit=True):
            workspace_name = st.text_input("Nombre del espacio", placeholder="Ej. Ventas 2026")
            uploaded_csv = st.file_uploader("Subir archivo CSV", type=["csv"])
            submitted = st.form_submit_button("Crear espacio")
        if submitted:
            if uploaded_csv is None:
                st.error("Selecciona un archivo CSV.")
            else:
                try:
                    workspace = create_workspace(workspace_name, uploaded_csv.name, uploaded_csv.getvalue())
                    _new_chat(workspace["id"])
                    st.rerun()
                except (ValueError, OSError, sqlite3.Error) as exc:
                    st.error(str(exc))

        st.divider()
        if st.button("+ Nueva conversación", use_container_width=True, key="new_chat_button"):
            _new_chat(st.session_state.workspace_id)
            st.rerun()
        try:
            chats = get_saved_chats(st.session_state.workspace_id)
            titles = get_chat_titles(st.session_state.workspace_id)
        except (OSError, ValueError) as exc:
            chats, titles = [], {}
            st.warning(f"No se pudo cargar el historial local: {exc}")
        if not chats:
            st.caption("Aún no hay conversaciones guardadas en esta base.")
        for chat_id in chats:
            active = chat_id == st.session_state.chat_id
            row_key = f"chat_row_active_{chat_id}" if active else f"chat_row_{chat_id}"
            with st.container(key=row_key):
                col_select, col_delete = st.columns([5, 1])
                with col_select:
                    if st.button(titles.get(chat_id, "Nueva conversación"), key=f"select_{chat_id}", use_container_width=True, type="secondary"):
                        data = load_chat_data(chat_id, st.session_state.workspace_id)
                        st.session_state.chat_id = chat_id
                        st.session_state.messages = data["messages"]
                        st.session_state.results = data["results"]
                        st.session_state.agent_graph = None
                        st.rerun()
                with col_delete:
                    if st.button("✕", key=f"delete_{chat_id}", help="Eliminar conversación"):
                        delete_chat(chat_id, st.session_state.workspace_id)
                        if active:
                            _new_chat(st.session_state.workspace_id)
                        st.rerun()
