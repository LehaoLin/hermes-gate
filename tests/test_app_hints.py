from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from textual.widgets import Label

from hermes_gate.app import HermesGateApp, _tmux_capture_args, _tmux_capture_to_text


def test_hint_reset_clears_inline_color_instead_of_setting_theme_variable():
    """Runtime styles must not assign Textual CSS variables as color values."""
    app = HermesGateApp()
    label = Label("initial", id="viewer-hint")
    timers = []

    app.query_one = MagicMock(return_value=label)
    app.set_timer = MagicMock(side_effect=lambda _delay, callback: timers.append(callback))

    app._hint("viewer-hint", "Sent", error=False)

    assert label.styles.color is not None
    assert timers

    timers[0]()

    expected = "Ctrl+B Back \u00b7 Ctrl+C Interrupt \u00b7 Ctrl+E Remote Esc \u00b7 Enter Send"
    assert str(label.content) == expected
    assert not label.styles.has_rule("color")


def test_tmux_capture_is_rendered_as_ansi_text_not_markup():
    """Captured terminal output may contain brackets and ANSI styling."""
    rendered = _tmux_capture_to_text("\x1b[31m[not rich markup]\x1b[0m\n")

    assert rendered.plain == "[not rich markup]"
    assert rendered.spans == []


def test_tmux_capture_uses_current_pane_without_history_or_ansi_backgrounds():
    """Viewer should show the current Hermes screen without remote backgrounds."""
    assert _tmux_capture_args("gate-3") == ("capture-pane", "-t", "gate-3", "-p")
