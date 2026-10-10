"""Barra lateral de conversaciones y estilos reutilizados del taller."""

import streamlit as st
from services.chat_storage import (
    delete_chat, get_chat_titles, get_saved_chats, load_chat, new_chat_id,
)


def sidebar_styles():
    """Aplica estilos visuales a la lista de conversaciones."""
    st.markdown("""
    <style>
    [data-testid="stSidebarCollapseButton"],[data-testid="stSidebarCollapseButton"] * {opacity:1!important;visibility:visible!important;pointer-events:auto!important;}
    section[data-testid="stSidebar"] h2 {padding-top:0!important;padding-bottom:.25rem!important;}
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {gap:.35rem!important;}
    section[data-testid="stSidebar"] button[data-testid^="stBaseButton"] > div {justify-content:flex-start!important;}
    section[data-testid="stSidebar"] button[data-testid^="stBaseButton"] p {text-align:left!important;}
    div[class*="st-key-chat_row_"] {position:relative;border-radius:.5rem;margin:0!important;overflow:hidden;}
    div[class*="st-key-chat_row_"]:hover {background:rgba(250,250,250,.12);}
    div[class*="st-key-chat_row_"] [data-testid="stHorizontalBlock"] {flex-wrap:nowrap!important;align-items:center!important;gap:0!important;}
    div[class*="st-key-chat_row_"] [data-testid="stColumn"]:last-child {position:absolute!important;right:.35rem;top:50%;transform:translateY(-50%);width:auto!important;min-width:0!important;}
    div[class*="st-key-chat_row_"] [data-testid="stColumn"]:last-child button {opacity:0;padding:.25rem .4rem!important;}
    div[class*="st-key-chat_row_"]:hover [data-testid="stColumn"]:last-child button {opacity:1;}
    </style>
    """, unsafe_allow_html=True)


def show_sidebar():
    """Muestra chats guardados y acciones para abrir, crear o borrar."""
    with st.sidebar:
        sidebar_styles()
        st.header("Conversaciones")
        if st.button("+ Nuevo", use_container_width=True, key="new_chat_button"):
            st.session_state.messages = []
            st.session_state.chat_id = new_chat_id()
            st.session_state.results = {}
            st.session_state.agent_graph = None
            st.session_state.agent_chat_id = st.session_state.chat_id
            st.rerun()
        st.divider()
        try:
            chats, titles = get_saved_chats(), get_chat_titles()
        except Exception as exc:
            chats, titles = [], {}
            st.warning(f"No se pudo cargar el historial S3: {exc}")
        if not chats:
            st.caption("Aún no hay conversaciones guardadas.")
        for chat_id in chats:
            active = chat_id == st.session_state.get("chat_id")
            with st.container(key=f"chat_row_{chat_id}"):
                col_select, col_delete = st.columns([5, 1])
                with col_select:
                    if st.button(f"**{titles.get(chat_id, 'Nueva conversación')}**" if active else titles.get(chat_id, "Nueva conversación"), key=f"select_{chat_id}", use_container_width=True):
                        try:
                            st.session_state.chat_id = chat_id
                            st.session_state.messages = load_chat(chat_id)
                            st.session_state.results = {}
                            st.session_state.agent_graph = None
                            st.session_state.agent_chat_id = chat_id
                            st.rerun()
                        except Exception as exc:
                            st.error(f"No se pudo abrir el chat: {exc}")
                with col_delete:
                    if st.button("✕", key=f"delete_{chat_id}"):
                        try:
                            delete_chat(chat_id)
                            if active:
                                st.session_state.messages = []
                                st.session_state.chat_id = new_chat_id()
                                st.session_state.results = {}
                                st.session_state.agent_graph = None
                                st.session_state.agent_chat_id = st.session_state.chat_id
                            st.rerun()
                        except Exception as exc:
                            st.error(f"No se pudo eliminar el chat: {exc}")
