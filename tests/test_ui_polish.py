"""Layout and looks: what fits at the smallest window, what is hidden when it does not apply."""
import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QLineEdit

from test_ui import make_controller
from ttspython.core.theme import THEME_PRESETS, derive_tokens
from ttspython.ui import icons, style
from ttspython.ui.voice_browser import VoiceBrowser
from ttspython.ui.widgets import Slider


@pytest.fixture
def c(qtbot, tmp_path):
    controller = make_controller(qtbot, tmp_path)
    yield controller
    controller.quit()


def settle(qtbot, window, size):
    window.resize(*size)
    qtbot.wait(30)
    QApplication.processEvents()


# --- sliders ----------------------------------------------------------------------------------
def handle_pixels(slider):
    """The (x, y) of pixels in the handle's ring color, away from the groove's row."""
    image = slider.grab().toImage().convertToFormat(QImage.Format_RGB32)
    ring = QColor(icons.color("line"))
    found = []
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if abs(c.red() - ring.red()) + abs(c.green() - ring.green()) + abs(c.blue() - ring.blue()) < 60:
                found.append((x, y))
    return image, found


@pytest.mark.parametrize("value", [0, 50, 100])
def test_the_slider_handle_is_never_cut_off(qtbot, value):
    slider = Slider()
    qtbot.addWidget(slider)
    slider.setRange(0, 100)
    slider.resize(120, slider.minimumHeight())
    slider.setValue(value)
    slider.show()
    image, pixels = handle_pixels(slider)
    ys = [y for _x, y in pixels]
    assert min(ys) > 0 and max(ys) < image.height() - 1  # clear of the top and bottom edges
    assert max(ys) - min(ys) + 1 >= 12  # a whole circle, not the 4 px groove
    assert (min(ys) + max(ys)) / 2 == pytest.approx((image.height() - 1) / 2, abs=1)  # centered


def test_the_slider_keeps_the_drag_position_of_a_normal_one(qtbot):
    slider = Slider()
    qtbot.addWidget(slider)
    slider.setRange(0, 100)
    slider.resize(120, 22)
    slider.setValue(100)
    assert slider.handle_center() <= 120 - 8  # the handle stops with its whole circle inside
    slider.setValue(0)
    assert slider.handle_center() >= 8


def test_every_slider_in_the_app_is_the_round_one(c):
    assert isinstance(c.window.transport.rate, Slider) and isinstance(c.window.transport.volume, Slider)
    assert isinstance(c.popover.rate, Slider) and isinstance(c.popover.volume, Slider)
    c.open_settings("speech")
    assert isinstance(c._settings_dialog.rate, Slider) and isinstance(c._settings_dialog.volume, Slider)


# --- radio buttons ----------------------------------------------------------------------------
@pytest.mark.parametrize("key", list(THEME_PRESETS))
def test_a_checked_radio_button_stays_round_in_every_theme(key):
    t = derive_tokens(THEME_PRESETS[key])
    qss = style.build_qss(t, "")
    outer = 16 + 2 * t["border_w"]
    assert f"QRadioButton::indicator:checked {{ width: {outer - 10}px; height: {outer - 10}px;" in qss
    assert f"border-radius: {outer // 2}px;" in qss


# --- main window ------------------------------------------------------------------------------
def test_speak_and_listen_fit_at_the_smallest_window(c, qtbot):
    settle(qtbot, c.window, (760, 500))
    switch = c.window.mode_switch
    for key in ("tts", "stt"):
        button = switch.button(key)
        assert button.width() >= button.minimumWidth()
        assert button.geometry().right() < switch.width()


def test_the_transport_keeps_progress_and_percentages_at_the_smallest_window(c, qtbot):
    settle(qtbot, c.window, (760, 500))
    t = c.window.transport
    for widget in (t.now, t.progress, t.rate_label, t.volume_label):
        assert widget.isVisible()
    assert t.progress.width() >= 100


def test_the_transport_waveform_shows_only_while_speech_plays(c, qtbot):
    settle(qtbot, c.window, (1100, 720))
    t = c.window.transport
    assert not t.wave.isVisible()
    t.set_level_source(lambda: 0.3)
    assert t.wave.isVisible() and t.wave.width() >= 100  # it was 0 px wide, so it never showed
    settle(qtbot, c.window, (800, 720))
    assert not t.wave.isVisible()
    settle(qtbot, c.window, (1100, 720))
    assert t.wave.isVisible()
    t.set_level_source(None)
    assert not t.wave.isVisible()


def test_volume_shows_its_percent_like_speed(c):
    t = c.window.transport
    t.volume.setValue(55)
    assert t.volume_label.text() == "55%"
    t.set_values(200, 0.8)
    assert t.volume_label.text() == "80%"


def test_clipboard_mode_shows_only_while_the_clipboard_is_watched(c, qtbot):
    w = c.window
    settle(qtbot, w, (1100, 720))
    w.clip_switch.setChecked(False)
    assert not w.clip_mode.isVisible()
    assert w.auto_queue.isVisible()  # it also reads the queue when reading ends, clipboard or not
    w.clip_switch.setChecked(True)
    assert w.clip_mode.isVisible()


def test_saved_clipboard_setting_is_reflected_at_start(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path, settings_data={"clipboard_monitor": True})
    try:
        assert c.window.clip_mode.isVisible()
    finally:
        c.quit()


def test_status_bar_gives_way_in_order_as_the_window_narrows(c, qtbot):
    w = c.window
    w.clip_switch.setChecked(False)
    settle(qtbot, w, (1100, 720))
    assert w.perf_switch.isVisible() and w.device_chip.isVisible()
    settle(qtbot, w, (760, 500))
    assert not w.device_chip.isVisible()  # the chip goes first
    assert w.status_label.width() >= 280
    w.clip_switch.setChecked(True)
    assert not w.perf_switch.isVisible()  # with the clipboard's options shown, Performance goes too


def test_the_queue_badge_is_hidden_when_empty_and_small_when_not(c, qtbot):
    panel = c.window.queue_panel
    assert not panel.badge.isVisible()
    c.queue.add("Some text here", "Item", "text")
    qtbot.waitUntil(lambda: panel.badge.text() == "1", timeout=2000)
    assert panel.badge.isVisible()
    assert panel.badge.height() <= 22


def test_the_queue_shows_more_rows_at_the_smallest_window(c, qtbot):
    settle(qtbot, c.window, (760, 500))
    assert c.window.queue_panel.list.height() >= 3 * 48  # one row of its buttons was folded into another


def test_speak_selected_and_the_queue_panel_no_longer_share_an_icon(c):
    assert icons._P["panel_right"] != icons._P["speak_selected"]
    assert c.actions["toggle_queue"].icon().cacheKey() != c.actions["speak_selected"].icon().cacheKey()


# --- settings ---------------------------------------------------------------------------------
def test_settings_reopens_on_the_page_last_used(c):
    c.open_settings("clipboard")
    c._settings_dialog.show_page("mini")
    c._settings_dialog.close()
    c.open_settings()
    assert c._settings_dialog.current_page() == "mini"


def test_a_shortcut_to_a_page_works_while_settings_is_open(c):
    c.open_settings("mini")
    dialog = c._settings_dialog
    c.open_settings("general")
    assert c._settings_dialog is dialog and dialog.current_page() == "general"
    c.open_settings()  # the toolbar button leaves the page alone
    assert dialog.current_page() == "general"


def test_what_a_switch_turned_off_is_greyed_out_but_keeps_its_value(c):
    c.open_settings("clipboard")
    d = c._settings_dialog
    d.clip_monitor.setChecked(False)
    assert not d.clip_action.isEnabled()
    assert d.clip_auto_queue.isEnabled()  # works without watching the clipboard
    d.clip_monitor.setChecked(True)
    assert d.clip_action.isEnabled()
    d.auto_unload.setChecked(False)
    assert not d.auto_unload_minutes.isEnabled()
    d.out_clip.setChecked(True)
    assert not d.keystroke.isEnabled()
    d.out_paste.setChecked(True)
    assert d.keystroke.isEnabled()
    d.global_enabled.setChecked(False)
    assert not any(edit.isEnabled() for edit, _status in d.global_edits.values())
    before = d.form_values()["global_hotkeys"]
    assert before == c.settings["global_hotkeys"]  # greyed out, not cleared


def test_empty_notes_take_no_room_in_settings(c):
    c.open_settings("speech")
    d = c._settings_dialog
    assert d.device_note.isHidden() and d.model_note.isHidden()


def test_voice_names_fit_in_settings(c, qtbot):
    c.open_settings("speech")
    d = c._settings_dialog
    qtbot.wait(30)
    assert d.voice.width() >= d.voice.fontMetrics().averageCharWidth() * 26


def test_shortcut_rows_are_compact(c, qtbot):
    c.open_settings("shortcuts")
    d = c._settings_dialog
    qtbot.wait(30)
    total = len(d.shortcut_edits) + len(d.global_edits)
    assert d.stack.currentWidget().widget().height() <= total * 44 + 200


def test_clear_buttons_use_the_quiet_icon(c):
    c.open_settings("shortcuts")
    edit, _status = next(iter(c._settings_dialog.shortcut_edits.values()))
    line = edit.findChild(QLineEdit)
    assert line.findChildren(type(c.actions["stop"]))


# --- voice browser ----------------------------------------------------------------------------
def test_the_voice_list_can_be_filtered(qtbot, tmp_path, monkeypatch):
    dlg = VoiceBrowser()
    qtbot.addWidget(dlg)
    everything = dlg.list.count()
    assert everything > 10
    dlg.filter.setText("great britain best")
    assert 0 < dlg.list.count() < everything
    for i in range(dlg.list.count()):
        item = dlg.list.item(i).text()
        assert "Great Britain" in item and "best" in item
    dlg.filter.setText("no such voice")
    assert dlg.list.count() == 0
    dlg.filter.clear()
    assert dlg.list.count() == everything
