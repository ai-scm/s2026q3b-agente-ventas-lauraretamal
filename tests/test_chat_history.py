from langchain_core.messages import AIMessage, HumanMessage

from services.chat_history import model_history


def test_history_trim_does_not_start_with_assistant():
    messages = [
        {"role": "user", "text": "pregunta 1"},
        {"role": "assistant", "text": "respuesta 1"},
        {"role": "user", "text": "pregunta 2"},
        {"role": "assistant", "text": "respuesta 2"},
    ]
    history = model_history(messages, limit=3)
    assert len(history) == 2
    assert isinstance(history[0], HumanMessage)
    assert isinstance(history[1], AIMessage)
