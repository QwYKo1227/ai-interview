# JD Chat Message Access Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make JD follow-up chat accept the `JDChatMessage` objects produced by FastAPI/Pydantic without changing the HTTP or SSE contracts.

**Architecture:** Keep request validation in `JDChatRequest` and make the AI service's parameter type match the validated objects it actually receives. Verify the service boundary with a real Pydantic message and a local fake OpenAI stream so the test never accesses the database or network.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, pytest, unittest.mock

## Global Constraints

- Do not modify request JSON, SSE response format, frontend state management, or user-facing copy.
- Keep the current stream-level exception handling unchanged.
- Support the real `JDChatMessage` input type; do not add an unused dictionary compatibility branch.

---

### Task 1: Correct JD chat message conversion

**Files:**
- Create: `backend/tests/test_ai_service.py`
- Modify: `backend/app/services/ai_service.py:1-8,395-430`

**Interfaces:**
- Consumes: `JDChatMessage(role: str, content: str)` from `app.schemas.position`.
- Produces: `chat_jd_stream(messages: List[JDChatMessage], current_description: str = "", current_requirements: str = "")`, yielding the existing SSE strings.

- [x] **Step 1: Write the failing regression test**

```python
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
```

- [x] **Step 2: Run the regression test and verify RED**

Run:

```powershell
docker run --rm --mount "type=bind,source=E:\ai-interview-main\.worktrees\fix-jd-chat-message\backend,target=/app" -w /app ai-interview-backend:latest pytest tests/test_ai_service.py::test_chat_jd_stream_accepts_validated_message_models -v
```

Expected: FAIL because the captured `create()` call is absent and the stream contains `TypeError: 'JDChatMessage' object is not subscriptable`.

- [x] **Step 3: Implement the minimal type-correct conversion**

In `backend/app/services/ai_service.py`, extend the imports and update the function:

```python
from typing import Dict, Any, List
from app.schemas.position import JDChatMessage


def chat_jd_stream(
    messages: List[JDChatMessage],
    current_description: str = "",
    current_requirements: str = ""
):
    # Keep the existing prompt and stream setup unchanged.
    formatted_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        formatted_messages.append({"role": msg.role, "content": msg.content})
```

- [x] **Step 4: Run the focused regression test and verify GREEN**

Run:

```powershell
docker run --rm --mount "type=bind,source=E:\ai-interview-main\.worktrees\fix-jd-chat-message\backend,target=/app" -w /app ai-interview-backend:latest pytest tests/test_ai_service.py::test_chat_jd_stream_accepts_validated_message_models -v
```

Expected: PASS with one collected test and no warnings introduced by the change.

- [x] **Step 5: Run the backend regression suite**

Run:

```powershell
docker run --rm --mount "type=bind,source=E:\ai-interview-main\.worktrees\fix-jd-chat-message\backend,target=/app" -w /app ai-interview-backend:latest pytest -v
```

Expected: all backend tests PASS. Any unrelated pre-existing failure must be reported separately with its exact test name and error.

- [x] **Step 6: Commit the fix**

```powershell
git add backend/tests/test_ai_service.py backend/app/services/ai_service.py docs/superpowers/plans/2026-07-23-jd-chat-message-access.md
git commit -m "fix: accept validated JD chat messages"
```
