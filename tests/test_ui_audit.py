"""Bugs the 5.0.0 audit of the interface found: each of these failed before its fix."""
import json

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QToolButton

from test_ui import LONG, make_controller
from ttspython.core.settings import defaults
from ttspython.core.theme import THEME_PRESETS
from ttspython.ui import panels
from ttspython.ui.panels import ID_ROLE
from ttspython.ui.settings_dialog import SettingRow
from ttspython.ui.voice_browser import VoiceBrowser
from ttspython.ui.widgets import ElidedLabel


@pytest.fixture
def c(qtbot, tmp_path):
    controller = make_controller(qtbot, tmp_path)
    yield controller
    controller.quit()


def settle(qtbot, window, size):
    window.resize(*size)
    qtbot.wait(30)
    QApplication.processEvents()


def other_theme(c):
    return next(k for k in THEME_PRESETS if k != c.theme.key)


def count_calls(monkeypatch, panel):
    calls = []
    real = panel.set_items
    monkeypatch.setattr(panel, "set_items", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    return calls


# --- settings ---------------------------------------------------------------------------------
def test_reset_to_defaults_puts_speed_and_volume_back_for_real(c):
    fresh = defaults()
    c.open_settings("speech")
    d = c._settings_dialog
    d.rate.setValue(150)
    d.volume.setValue(40)
    d._reset()
    assert c.speech.rate == fresh["tts_rate"] and c.speech.volume == fresh["tts_volume"]
    assert d.rate.value() == c.window.transport.rate.value()
    assert d.volume.value() == c.window.transport.volume.value()


def test_settings_comes_forward_with_its_window_when_already_open(c):
    c.open_settings("speech")
    c.window.hide()
    c.open_settings()
    assert c.window.isVisible()


def test_the_voice_window_outlives_settings(c):
    c.open_settings("speech")
    c.open_voice_browser()
    assert c._voice_browser.parent() is c.window


def test_themes_can_be_picked_by_keyboard(c, qtbot):
    c.open_settings("appearance")
    d = c._settings_dialog
    key, card = next((k, v) for k, v in d.theme_cards.items() if k != c.theme.key)
    assert card.focusPolicy() & Qt.TabFocus and card.accessibleName()
    qtbot.keyClick(card, Qt.Key_Space)
    assert c.theme.key == key


def test_controls_in_settings_are_named_for_screen_readers(c):
    c.open_settings("clipboard")
    d = c._settings_dialog
    assert d.clip_monitor.accessibleName() == "Watch the clipboard"
    assert d.voice.accessibleName() == "Voice" and d.rate.accessibleName() == "Speed"
    assert c.window.transport.rate.accessibleName() and c.window.transport.volume.accessibleName()
    assert c.popover.rate.accessibleName() and c.popover.volume.accessibleName()


@pytest.mark.parametrize("page", ["appearance", "speech", "clipboard", "shortcuts", "mini", "general"])
def test_settings_pages_fit_the_smallest_dialog(c, qtbot, page):
    c.open_settings(page)
    d = c._settings_dialog
    d.resize(660, 440)
    qtbot.wait(40)
    area = d.stack.currentWidget()
    assert area.widget().width() <= area.viewport().width()
    for row in area.widget().findChildren(SettingRow):
        assert row.control.geometry().right() <= row.width()


def test_a_long_whisper_model_label_stays_inside_the_smallest_dialog(c, qtbot, monkeypatch):
    # Not the Listen page itself: showing it would open the real microphone for the level meter.
    c.open_settings("speech")
    d = c._settings_dialog
    d.resize(660, 440)
    d.model_status.setText("Loaded: large-v3-turbo")
    assert d.model.maximumWidth() <= 340 and d.model.minimumContentsLength() <= 22


# --- mini bar ---------------------------------------------------------------------------------
def wheel_event(delta):
    return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                       Qt.NoScrollPhase, False)


def test_a_touchpad_scroll_changes_volume_both_ways_on_the_mini_bar(c):
    steps = []
    c.mini.volume_step.connect(steps.append)
    c.mini.wheelEvent(wheel_event(-15))  # a small nudge is not a whole step yet
    assert steps == []
    for _ in range(9):
        c.mini.wheelEvent(wheel_event(15))
    assert steps == [1]  # 120 up in all
    c.mini.wheelEvent(wheel_event(-120))
    assert steps == [1, -1]


def test_a_mouse_wheel_notch_is_one_step(c):
    steps = []
    c.mini.volume_step.connect(steps.append)
    c.mini.wheelEvent(wheel_event(120))
    c.mini.wheelEvent(wheel_event(-120))
    assert steps == [1, -1]


# --- editor -----------------------------------------------------------------------------------
def test_dragging_speed_does_not_recount_the_document(c, monkeypatch):
    card = c.window.editor_card
    c.editor.setPlainText("word " * 1000)
    card._update_counts()
    card._count_timer.stop()
    monkeypatch.setattr(card.editor, "toPlainText", lambda: pytest.fail("recounted the whole document"))
    before = card.counts.text()
    card.set_wpm(50)
    assert "1,000 words" in card.counts.text() and card.counts.text() != before  # the reading time still follows


def test_a_long_file_name_does_not_push_the_editor_buttons_away(c, qtbot):
    settle(qtbot, c.window, (760, 500))
    card = c.window.editor_card
    name = "A very long file name that goes on and on and on and on and on and on.txt"
    card.set_title(name)
    qtbot.wait(30)
    assert card.title.text() == name
    assert card.counts.geometry().right() < card.width()
    assert card.title.width() < card.width() / 2


def test_replace_works_on_a_match_across_lines(c):
    c.editor.setPlainText("one\ntwo\nthree")
    bar = c.window.find_bar
    bar.open_bar()
    bar.regex_btn.setChecked(True)
    bar.find_edit.setText(r"one\ntwo")
    bar.replace_edit.setText("joined")
    bar.find(False)
    bar.replace_one()
    assert c.editor.toPlainText() == "joined\nthree"


def test_clear_buttons_follow_the_theme(c):
    action = c.window.find_bar.find_edit._clear_actions[0]
    before = action.icon().cacheKey()
    c.theme.apply(other_theme(c))
    assert action.icon().cacheKey() != before


# --- queue ------------------------------------------------------------------------------------
def test_files_dropped_on_an_empty_queue_are_added(c, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Some notes to read.", encoding="utf-8")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    panel = c.window.queue_panel
    assert len(c.queue) == 0 and panel.acceptDrops()
    panel.dropEvent(QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert len(c.queue) == 1


def test_loading_the_queue_at_start_rebuilds_once_and_rewrites_nothing(qtbot, tmp_path, monkeypatch):
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps({"items": [{"text": f"Item {i} text", "name": f"I{i}", "kind": "text"}
                                                for i in range(20)]}), encoding="utf-8")
    calls = []
    real = panels.QueuePanel.set_items
    monkeypatch.setattr(panels.QueuePanel, "set_items", lambda self, *a, **k: (calls.append(1), real(self, *a, **k))[1])
    c = make_controller(qtbot, tmp_path)
    try:
        assert len(c.queue) == 20 and c.window.queue_panel.list.count() == 20
        assert len(calls) == 1
        assert not c._queue_save_timer.isActive()
        c.queue.add("One more", "New", "text")
        assert c._queue_save_timer.isActive()  # a real change is still saved
    finally:
        c.quit()


def test_moving_a_queue_item_rebuilds_once_and_keeps_it_selected(c, monkeypatch):
    for i in range(3):
        c.queue.add(f"Item {i} text", f"I{i}", "text")
    panel = c.window.queue_panel
    panel.list.setCurrentRow(1)
    panel.list.item(1).setSelected(True)
    moved = panel.selected_id()
    calls = count_calls(monkeypatch, panel)
    c.queue_move(-1)
    assert len(calls) == 1
    assert panel.selected_id() == moved and panel.list.item(0).data(ID_ROLE) == moved


def test_adding_many_files_rebuilds_the_queue_once(c, tmp_path, monkeypatch):
    paths = []
    for i in range(4):
        path = tmp_path / f"f{i}.txt"
        path.write_text("Text to read.", encoding="utf-8")
        paths.append(str(path))
    calls = count_calls(monkeypatch, c.window.queue_panel)
    c.queue_add_paths(paths)
    assert len(c.queue) == 4 and len(calls) == 1


def test_unreadable_files_give_one_message_not_one_each(c, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(c, "_error", lambda _title, message: errors.append(message))
    c.queue_add_paths([str(tmp_path / "missing1.txt"), str(tmp_path / "missing2.txt")])
    assert len(errors) == 1 and "missing1.txt" in errors[0] and "missing2.txt" in errors[0]


def test_the_queue_play_row_fits_at_the_narrowest_panel(c, qtbot):
    settle(qtbot, c.window, (760, 500))
    panel = c.window.queue_panel
    c.window.splitter.setSizes([700, panel.minimumWidth()])
    qtbot.wait(40)
    assert panel.width() <= panel.minimumWidth() + 2
    shown = [b for b in panel.findChildren(QToolButton) if b.isVisible()]
    assert shown
    for button in shown:
        assert button.geometry().right() <= panel.width(), button.text()
    actions = [c.actions[a] for a in ("queue_play", "queue_up", "queue_down", "queue_remove")]
    row = sorted((b.geometry() for b in shown if b.defaultAction() in actions), key=lambda g: g.left())
    assert len(row) == 4
    for left, right in zip(row, row[1:], strict=False):
        assert left.right() < right.left()  # none on top of another


# --- theme, tooltips, messages ----------------------------------------------------------------
def test_applying_the_theme_already_on_does_nothing(c):
    fired = []
    c.theme.changed.connect(fired.append)
    c.theme.apply(c.theme.key)
    assert fired == []
    c.theme.apply(other_theme(c))
    assert len(fired) == 1


def test_the_play_button_says_what_it_will_do(c, qtbot):
    play = c.actions["play_pause"]
    assert play.toolTip().startswith("Play")
    c.editor.setPlainText(LONG)
    play.trigger()
    qtbot.waitUntil(lambda: play.toolTip().startswith("Pause"), timeout=3000)
    play.trigger()
    qtbot.waitUntil(lambda: play.toolTip().startswith("Resume"), timeout=3000)
    c.actions["stop"].trigger()
    qtbot.waitUntil(lambda: play.toolTip().startswith("Play"), timeout=3000)
    c.set_mode("stt")
    assert "Speak" in play.toolTip()


def test_a_shortened_chip_shows_its_full_text_and_what_a_click_does(qtbot):
    chip = ElidedLabel("Mic: A very long microphone name that cannot possibly fit in here")
    qtbot.addWidget(chip)
    chip.set_clickable("Change the microphone")
    chip.resize(80, 20)
    chip.show()  # the tooltip follows the size it is shown at
    assert "A very long microphone" in chip.toolTip() and "Change the microphone" in chip.toolTip()


def test_the_output_chip_keeps_its_click_hint(c, qtbot):
    qtbot.waitUntil(lambda: bool(c.window.device_chip.text()), timeout=3000)
    tip = c.window.device_chip.toolTip()
    assert "Speech plays on" in tip and "lick" in tip


def test_a_long_toast_is_wide_not_a_narrow_column(c):
    c.window.show_toast("Could not export audio: " + "this message goes on for a while " * 4)
    toast = c.window.toast
    assert toast.width() == toast.maximumWidth()
    assert toast.height() < toast.width() / 2


def test_enter_works_like_a_double_click_in_the_voice_list(qtbot, monkeypatch):
    dlg = VoiceBrowser()
    qtbot.addWidget(dlg)
    called = []
    monkeypatch.setattr(dlg, "_primary", lambda: called.append(1))
    dlg.list.itemActivated.emit(dlg.list.item(0))
    assert called == [1]


def test_export_open_button_is_not_hidden_early_by_the_last_export(c, tmp_path):
    c._on_export_finished(str(tmp_path / "a.mp3"))
    assert c.window.export_open.isVisible()
    assert c._export_open_timer.isActive()
    c._export_open_timer.timeout.emit()
    assert not c.window.export_open.isVisible()
