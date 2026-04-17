from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from textual.widgets import Label

from hermes_gate.app import HermesGateApp


def test_hint_reset_clears_inline_color_instead_of_setting_theme_variable():
    """Runtime styles must not assign Textual CSS variables as color values."""
    app = HermesGateApp()
    label = Label("initial", id="session-hint")
    timers = []

    app.query_one = MagicMock(return_value=label)
    app.set_timer = MagicMock(side_effect=lambda _delay, callback: timers.append(callback))

    app._hint("session-hint", "Sent", error=False)

    assert label.styles.color is not None
    assert timers

    timers[0]()

    expected = "↑↓ Select · Enter Attach · N New · K Kill · R Refresh · Esc/Shift+Tab Back · Q Quit"
    assert str(label.content) == expected
    assert not label.styles.has_rule("color")
