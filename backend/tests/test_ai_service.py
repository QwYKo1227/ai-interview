import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.schemas.position import JDChatMessage
from app.services.ai_service import chat_jd_stream


def test_chat_jd_stream_accepts_validated_message_models(monkeypatch):
    client = MagicMock()
    client.chat.completions.create.return_value = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content='{"description":"updated","requirements":"Python"}'
                    )
                )
            ]
        )
    ]
    monkeypatch.setattr(
        "app.services.ai_service._get_llm_config",
        lambda: {
            "llm_model": "test-model",
            "llm_temperature": 0.2,
            "llm_max_tokens": None,
        },
    )
    monkeypatch.setattr("app.services.ai_service._get_client", lambda: client)
    monkeypatch.setattr("app.services.ai_service._get_extra_body", lambda: {})

    events = list(
        chat_jd_stream(
            messages=[JDChatMessage(role="user", content="Add Python")],
            current_description="Current description",
            current_requirements="Current requirements",
        )
    )

    create_kwargs = client.chat.completions.create.call_args.kwargs
    assert create_kwargs["messages"][1] == {
        "role": "user",
        "content": "Add Python",
    }
    assert json.loads(events[-1].removeprefix("data: ")) == {"done": True}
