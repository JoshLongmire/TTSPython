"""Turn theme tokens into a Qt palette and stylesheet."""
from __future__ import annotations

from string import Template

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

from ..core.platform import IS_WINDOWS, IS_DARWIN
from ..core.theme import darken, mix

UI_FONT_CANDIDATES = (
    ["Segoe UI Variable Text", "Segoe UI"] if IS_WINDOWS else
    ["SF Pro Text", "Helvetica Neue"] if IS_DARWIN else
    ["Inter", "Noto Sans", "Cantarell", "DejaVu Sans", "Liberation Sans"]
)
EDITOR_FONT_CANDIDATES = (
    ["Segoe UI Variable Text", "Segoe UI"] if IS_WINDOWS else
    ["SF Pro Text", "Helvetica Neue"] if IS_DARWIN else
    ["Inter", "Noto Sans", "DejaVu Sans"]
)


def pick_family(candidates):
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return QFont().defaultFamily()


def ui_font(size=10):
    font = QFont(pick_family(UI_FONT_CANDIDATES))
    font.setPointSizeF(size)
    font.setHintingPreference(QFont.PreferNoHinting)
    return font


def build_palette(t):
    p = QPalette()
    c = QColor
    p.setColor(QPalette.Window, c(t["window"]))
    p.setColor(QPalette.WindowText, c(t["text"]))
    p.setColor(QPalette.Base, c(t["field"]))
    p.setColor(QPalette.AlternateBase, c(t["surface2"]))
    p.setColor(QPalette.Text, c(t["field_text"]))
    p.setColor(QPalette.Button, c(t["surface2"]))
    p.setColor(QPalette.ButtonText, c(t["text"]))
    p.setColor(QPalette.Highlight, c(t["selection_bg"]))
    p.setColor(QPalette.HighlightedText, c(t["selection_text"]))
    p.setColor(QPalette.ToolTipBase, c(t["surface2"]))
    p.setColor(QPalette.ToolTipText, c(t["text"]))
    p.setColor(QPalette.PlaceholderText, c(t["muted"]))
    p.setColor(QPalette.Link, c(t["accent_text"]))
    p.setColor(QPalette.Accent, c(t["accent"]))
    for group in (QPalette.Disabled,):
        p.setColor(group, QPalette.WindowText, c(t["disabled_text"]))
        p.setColor(group, QPalette.Text, c(t["disabled_text"]))
        p.setColor(group, QPalette.ButtonText, c(t["disabled_text"]))
    return p


_QSS = Template("""
* { outline: none; }
QWidget { color: ${text}; font-size: 10pt; }
QMainWindow, QDialog, #Root { background: ${window}; }
QToolTip { background: ${surface2}; color: ${text}; border: 1px solid ${border}; border-radius: 6px; padding: 5px 8px; }

/* App bar */
#AppBar { background: ${surface}; border-bottom: ${border_w}px solid ${divider}; }
#AppTitle { font-size: 12.5pt; font-weight: 600; color: ${text}; }
#VersionChip { color: ${muted}; background: ${surface2}; border: 1px solid ${divider}; border-radius: 9px; padding: 1px 8px; font-size: 8.5pt; }

/* Cards */
QFrame#Card { background: ${surface}; border: ${border_w}px solid ${divider}; border-radius: ${radius_card}px; }
#CardTitle { font-weight: 600; font-size: 10.5pt; }
#Muted, QLabel[muted="true"] { color: ${muted}; }
#SectionLabel { color: ${muted}; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.6px; }
#Badge { background: ${accent_soft}; color: ${accent_text}; border-radius: 9px; padding: 0px 7px; font-size: 8.5pt; font-weight: 600; }
#Dot { background: ${accent}; border-radius: 3px; }

/* Editor */
QPlainTextEdit#Editor { background: transparent; border: none; color: ${field_text};
    selection-background-color: ${selection_bg}; selection-color: ${selection_text}; font-size: 12pt; padding: 4px 8px; }
QPlainTextEdit, QTextEdit { background: ${field}; color: ${field_text}; border: 1px solid ${field_border}; border-radius: ${radius_ctrl}px;
    selection-background-color: ${selection_bg}; selection-color: ${selection_text}; }

/* Buttons */
QPushButton, QToolButton { background: ${surface2}; color: ${text}; border: ${border_w}px solid ${divider};
    border-radius: ${radius_ctrl}px; padding: 6px 12px; }
QPushButton:hover, QToolButton:hover { background: ${hover}; border-color: ${border}; }
QPushButton:pressed, QToolButton:pressed { background: ${pressed}; }
QPushButton:focus, QToolButton:focus { border-color: ${focus}; }
QPushButton:disabled, QToolButton:disabled { color: ${disabled_text}; background: ${disabled}; border-color: ${divider}; }
QPushButton:checked, QToolButton:checked { background: ${accent_soft}; color: ${accent_text}; border-color: ${accent}; }

QPushButton[variant="primary"], QToolButton[variant="primary"] { background: ${accent_fill}; color: ${on_accent}; border: none; font-weight: 600; }
QPushButton[variant="primary"]:hover, QToolButton[variant="primary"]:hover { background: ${accent_hover}; }
QPushButton[variant="primary"]:pressed, QToolButton[variant="primary"]:pressed { background: ${accent_pressed}; }
QPushButton[variant="primary"]:disabled, QToolButton[variant="primary"]:disabled { background: ${disabled}; color: ${disabled_text}; }

QPushButton[variant="ghost"], QToolButton[variant="ghost"] { background: transparent; border: ${ghost_border}; padding: 5px 9px; }
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover { background: ${hover}; }
QPushButton[variant="ghost"]:pressed, QToolButton[variant="ghost"]:pressed { background: ${pressed}; }
QPushButton[variant="ghost"]:checked, QToolButton[variant="ghost"]:checked { background: ${accent_soft}; color: ${accent_text}; }
QToolButton[variant="ghost"]:disabled { background: transparent; }

QToolButton[variant="round"] { border-radius: 22px; padding: 0px; }
QToolButton[variant="round_primary"] { background: ${accent_fill}; border: none; border-radius: 24px; padding: 0px; }
QToolButton[variant="round_primary"]:hover { background: ${accent_hover}; }
QToolButton[variant="round_primary"]:pressed { background: ${accent_pressed}; }
QToolButton[variant="record"] { background: ${danger}; border: none; border-radius: 30px; }
QToolButton[variant="record"]:hover { background: ${danger_hover}; }
QToolButton[variant="record"]:checked { background: ${danger_hover}; border: 3px solid ${danger_ring}; }
QPushButton[variant="danger"] { color: ${danger}; }

/* Segmented control */
#Segmented { background: ${window}; border: ${border_w}px solid ${divider}; border-radius: 9px; }
#Segmented QToolButton { background: transparent; border: none; border-radius: 7px; padding: 5px 14px; color: ${muted}; font-weight: 600; }
#Segmented QToolButton:hover { color: ${text}; }
#Segmented QToolButton:checked { background: ${surface2}; color: ${text}; border: 1px solid ${border}; }
#SegmentedSmall { background: transparent; border: none; }
#SegmentedSmall QToolButton { background: transparent; border: none; border-radius: 6px; padding: 2px 9px; color: ${muted}; font-weight: 600; font-size: 9pt; }
#SegmentedSmall QToolButton:hover { color: ${text}; }
#SegmentedSmall QToolButton:checked { background: ${accent_soft}; color: ${accent_text}; }
#VSep { background: ${divider}; }

/* Inputs */
QLineEdit, QComboBox, QSpinBox, QKeySequenceEdit { background: ${field}; color: ${field_text}; border: ${border_w}px solid ${field_border};
    border-radius: ${radius_ctrl}px; padding: 5px 8px; selection-background-color: ${selection_bg}; selection-color: ${selection_text}; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QKeySequenceEdit:focus { border-color: ${focus}; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: ${disabled_text}; background: ${disabled}; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url(${chevron}); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: ${surface2}; color: ${text}; border: 1px solid ${border}; border-radius: 8px;
    padding: 4px; selection-background-color: ${accent_soft}; selection-color: ${text}; outline: none; }
QSpinBox::up-button, QSpinBox::down-button { width: 0px; border: none; }

/* Sliders */
QSlider::groove:horizontal { height: 4px; background: ${scrollbar}; border-radius: 2px; }
QSlider::sub-page:horizontal { background: ${accent}; border-radius: 2px; }
QSlider::handle:horizontal { background: ${handle}; border: 2px solid ${accent}; width: 12px; height: 12px; margin: -6px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: ${accent}; }
QSlider::sub-page:horizontal:disabled { background: ${disabled_text}; }

/* Radio buttons */
QRadioButton { spacing: 8px; background: transparent; }
QRadioButton::indicator { width: 16px; height: 16px; border: ${border_w}px solid ${border}; background: ${field}; }
QRadioButton::indicator { border-radius: 9px; }
QRadioButton::indicator:hover { border-color: ${accent}; }
QRadioButton::indicator:checked { background: ${field}; border: 5px solid ${accent_fill}; }

/* Lists */
QListWidget, QListView, QTreeView { background: transparent; border: none; outline: none; }
QListWidget::item, QListView::item { border-radius: 8px; padding: 6px; }
QListWidget::item:hover { background: ${hover}; }
QListWidget::item:selected { background: ${accent_soft}; color: ${text}; }
QListWidget#Nav { background: ${surface}; border-right: ${border_w}px solid ${divider}; padding: 10px 8px; }
QListWidget#Nav::item { padding: 8px 10px; margin: 1px 0px; }

/* Scrollbars */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: ${scrollbar}; border-radius: 3px; min-height: 28px; margin: 0px 2px; }
QScrollBar::handle:vertical:hover { background: ${scrollbar_hover}; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: ${scrollbar}; border-radius: 3px; min-width: 28px; margin: 2px 0px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; border: none; width: 0px; height: 0px; }

/* Transport and status */
#Transport { background: ${surface}; border-top: ${border_w}px solid ${divider}; }
#NowPlaying { color: ${muted}; font-size: 9pt; }
QProgressBar { background: ${scrollbar}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; text-align: center; color: transparent; }
QProgressBar::chunk { background: ${accent}; border-radius: 2px; }
QStatusBar { background: ${window}; color: ${muted}; border-top: ${border_w}px solid ${divider}; }
QStatusBar QLabel { color: ${muted}; }
QStatusBar::item { border: none; }
#StatusChip { color: ${muted}; padding: 2px 8px; border-radius: 8px; }
#StatusText { padding-left: 14px; }
#StatusGroup { background: ${surface}; border: ${border_w}px solid ${divider}; border-radius: 9px; }

/* Splitter */
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 12px; }

/* Find bar */
#FindBar { background: ${surface2}; border-bottom: ${border_w}px solid ${divider}; }

/* Menus */
QMenu { background: ${surface2}; color: ${text}; border: 1px solid ${border}; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 18px 7px 12px; border-radius: 6px; }
QMenu::item:selected { background: ${hover}; }
QMenu::item:disabled { color: ${disabled_text}; }
QMenu::separator { height: 1px; background: ${divider}; margin: 5px 6px; }
QMenu::icon { padding-left: 8px; }

/* Tabs (fallback) */

/* Settings */
#PageTitle { font-size: 15pt; font-weight: 600; }
#PageSubtitle { color: ${muted}; }
#SettingRow { border-bottom: 1px solid ${divider}; }
#Banner { background: ${accent_soft}; border-radius: 8px; padding: 8px 10px; }
#ErrorText { color: ${danger}; }
#ThemeCard { background: transparent; border: 2px solid transparent; border-radius: 12px; }
#ThemeCard:hover { border-color: ${border}; }
#ThemeCard[selected="true"] { border-color: ${accent}; }

/* Toast */
#Toast { background: ${toast_bg}; color: ${toast_text}; border-radius: 10px; padding: 9px 14px; }
""")


def build_qss(t, chevron_path):
    values = dict(t)
    values["chevron"] = chevron_path.replace("\\", "/")
    values["ghost_border"] = f"{t['border_w']}px solid {t['border']}" if t["border_w"] > 1 else "1px solid transparent"
    values["handle"] = t["field"]
    values["danger_hover"] = darken(t["danger"], 0.12)
    values["danger_ring"] = mix(t["danger"], t["window"], 0.55)
    values["toast_bg"] = t["text"]
    values["toast_text"] = t["window"]
    return _QSS.substitute(values)
