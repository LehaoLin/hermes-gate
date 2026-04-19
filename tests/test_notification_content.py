from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from hermes_gate.app import HermesGateApp


def test_notify_formats_additive_payload_for_file_signal():
    app = HermesGateApp()
    notify_payloads = []

    app._emit_host_notification = lambda title, message, sound="complete.wav", **extra: notify_payloads.append(
        {"title": title, "message": message, "sound": sound, **extra}
    )

    app._notify("gate-7", "Assistant finished the requested fix")

    assert notify_payloads == [
        {
            "title": "Hermes Gate",
            "message": "Hermes gate-7: Assistant finished the requested fix",
            "sound": "complete.wav",
            "session_name": "gate-7",
            "response_preview": "Assistant finished the requested fix",
        }
    ]


@pytest.mark.asyncio
async def test_check_completion_uses_response_preview_instead_of_message_preview():
    app = HermesGateApp()
    app.session_mgr = MagicMock()
    app.session_mgr.check_completion_signals = MagicMock(
        return_value=[
            {
                "session_id": 3,
                "message_preview": "old user prompt",
                "response_preview": "new assistant response",
            }
        ]
    )
    app._notify = MagicMock()

    await HermesGateApp._check_completion.__wrapped__(app)

    app._notify.assert_called_once_with("gate-3", "new assistant response")


@pytest.mark.asyncio
async def test_check_completion_falls_back_when_response_preview_missing():
    app = HermesGateApp()
    app.session_mgr = MagicMock()
    app.session_mgr.check_completion_signals = MagicMock(
        return_value=[{"session_id": 5}]
    )
    app._notify = MagicMock()

    await HermesGateApp._check_completion.__wrapped__(app)

    app._notify.assert_called_once_with("gate-5", "task completed")
