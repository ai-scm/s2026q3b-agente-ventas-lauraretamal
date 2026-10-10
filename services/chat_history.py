"""Construye un historial acotado que cumple el orden de mensajes de Bedrock."""

from langchain_core.messages import AIMessage, HumanMessage


def model_history(items: list[dict], limit: int = 12) -> list[HumanMessage | AIMessage]:
    """Convierte los turnos recientes y descarta cualquier inicio huérfano del asistente."""
    recent = items[-limit:]
    while recent and recent[0].get("role") != "user":
        recent = recent[1:]
    messages = []
    for item in recent:
        text = item.get("text", "")
        if item.get("role") == "user":
            messages.append(HumanMessage(content=text))
        elif text:
            messages.append(AIMessage(content=text))
    return messages
