from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from textual.widgets import Label

from hermes_gate.app import HermesGateApp


def test_session_hint_text_lists_all_available_shortcuts():
    app = HermesGateApp()
    label = Label("initial", id="session-hint")
    app.query_one = MagicMock(return_value=label)
    app.set_timer = MagicMock()

    app._hint("session-hint", "Done", error=False)

    reset = app.set_timer.call_args[0][1]
    reset()
    assert (
        str(label.content)
        == "↑↓ Select · Enter Attach · N New · K Kill · R Refresh · Ctrl+B Back · Q Quit"
    )
