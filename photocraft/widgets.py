from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from PySide6.QtGui import QValidator


class TextLengthValidator(QValidator):
    def __init__(self, maximum, parent=None):
        super().__init__(parent)
        self.maximum = maximum

    def validate(self, text, position):
        state = self.State.Acceptable if len(text) <= self.maximum else self.State.Invalid
        return state, text, position


class WorkerSignals(QObject):
    done = Signal(object)
    error = Signal(str)
    progress = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.done.emit(self.operation(self.signals.progress.emit))
        except Exception as error:
            self.signals.error.emit(str(error) or type(error).__name__)
        finally:
            self.signals.finished.emit()


def stylesheet(dark=False):
    bg = "#141b29" if dark else "#f5f7fb"
    panel = "#1e2738" if dark else "#ffffff"
    fg = "#e5eaf5" if dark else "#243047"
    muted = "#9aaac1" if dark else "#7b879b"
    line = "#303c52" if dark else "#e7ebf2"
    field = "#263248" if dark else "#f7f9fc"
    return f"""QWidget {{ font-family: 'Noto Sans CJK SC', 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
 font-size: 12px; color: {fg}; }}
QMainWindow, #root {{ background: {bg}; }}
QMenuBar {{ background: {panel}; border-bottom: 1px solid {line}; padding: 3px 14px; }}
QMenuBar::item {{ background: transparent; padding: 5px 12px; border-radius: 5px; }}
QMenuBar::item:selected {{ background: {field}; color: #4376ef; }}
QMenu {{ background: {panel}; border: 1px solid {line}; padding: 6px; }}
QMenu::item {{ padding: 8px 28px 8px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: #4376ef; color: white; }}
QMenu::item:disabled {{ color: {muted}; }}
QMenu::separator {{ height: 1px; background: {line}; margin: 5px 8px; }}
QPlainTextEdit#configEditor {{ background: {field}; border: 1px solid {line}; border-radius: 6px;
 padding: 10px; font-family: 'DejaVu Sans Mono', 'Consolas', monospace; font-size: 12px; }}
#header, #sidebar, #properties, #workspaceBar, #canvasControls {{ background: {panel}; }}
#header {{ border-bottom: 1px solid {line}; }}
#sidebar {{ border-right: 1px solid {line}; }}
#properties {{ border-left: 1px solid {line}; }}
#panelContent {{ background: {panel}; }}
QFrame#cropCard {{ background: {field}; border: 1px solid {line}; border-radius: 10px; }}
QFrame#cropCard QSpinBox, QFrame#cropCard QDoubleSpinBox {{ background: {panel}; }}
QLabel#fieldTitle {{ font-weight: 650; }}
#workspaceBar {{ border-bottom: 1px solid {line}; }}
#canvasControls {{ border-top: 1px solid {line}; }}
#imageInfo {{ background: {panel}; border-top: 1px solid {line}; }}
#modifiedInfoColumn {{ border-left: 1px solid {line}; }}
QLabel {{ background: transparent; }}
QLabel#brand {{ font-size: 22px; font-weight: 800; letter-spacing: -1px; }}
QLabel#subtitle, QLabel#muted {{ color: {muted}; }}
QLabel#offlineBadge {{ color: #13856d; background: {field}; border-radius: 8px; padding: 8px 12px; }}
QLabel#section {{ color: {muted}; font-size: 10px; font-weight: 600; letter-spacing: 2px; }}
QLabel#title {{ font-size: 22px; font-weight: 700; }}
QLabel#panelTitle {{ font-size: 18px; font-weight: 700; }}
QLabel#large {{ font-size: 30px; font-weight: 750; }}
QLabel#hint {{ color: {muted}; line-height: 1.6; padding: 12px; background: {field}; border-radius: 9px; }}
QLabel#success {{ color: #13856d; background: #e7f7f0; padding: 12px; border-radius: 9px; }}
QLabel#warning {{ color: #996519; background: #fff3d8; padding: 12px; border-radius: 9px; }}
QPushButton {{ background: {panel}; border: 1px solid {line}; border-radius: 7px;
 padding: 9px 12px; font-weight: 500; }}
QPushButton:hover {{ background: {field}; border-color: #9eb5ed; }}
QPushButton:pressed {{ background: #dee9ff; color: #235be0; }}
QPushButton:disabled {{ color: {muted}; background: {field}; border-color: {line}; }}
QPushButton#primary {{ color: white; background: #4376ef; border: 1px solid #4376ef; font-weight: 650; }}
QPushButton#primary:hover {{ background: #3263da; }}
QPushButton#primary:disabled {{ background: #a2b4da; border-color: #a2b4da; }}
QPushButton#ghost {{ border: none; background: transparent; color: {muted}; }}
QPushButton#textAction {{ border: none; background: transparent; color: #4376ef; padding: 5px 0 5px 6px; }}
QPushButton#textAction:hover {{ background: {field}; }}
QPushButton#disclosure {{ text-align: left; color: {muted}; background: {field}; }}
QToolButton {{ border: none; background: transparent; border-radius: 9px; padding: 9px; }}
QToolButton:hover {{ background: {field}; }}
QToolButton:checked {{ background: #edf2ff; color: #3767df; }}
QToolButton#tool {{ margin: 0; padding: 6px 4px; font-size: 11px; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {field}; border: 1px solid {line};
 border-radius: 6px; padding: 8px; min-height: 16px; selection-background-color: #4376ef; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: #4376ef; }}
QAbstractSpinBox QLineEdit {{ background: transparent; border: none; padding: 0; min-height: 0; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0px; height: 0px; }}
QComboBox::drop-down {{ border: none; width: 23px; }}
QComboBox::down-arrow {{ image: url({(Path(__file__).parent / "assets/chevron.svg").as_posix()}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {panel}; selection-background-color: #4376ef; padding: 5px; }}
QCheckBox {{ spacing: 8px; padding: 4px 0; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {line}; border-radius: 4px; background: {field}; }}
QCheckBox::indicator:checked {{ background: #4376ef; border-color: #4376ef; image: url({(Path(__file__).parent / "assets/check.svg").as_posix()}); }}
QSlider::groove:horizontal {{ height: 4px; background: {line}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: #6590f4; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #4376ef; width: 13px; margin: -5px 0; border-radius: 6px; border: 2px solid {panel}; }}
QSlider::sub-page:horizontal:disabled {{ background: {line}; }}
QSlider::handle:horizontal:disabled {{ background: {muted}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 6px; }}
QScrollBar::handle:vertical {{ background: #b5bfd1; border-radius: 3px; min-height: 35px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QStatusBar {{ background: {panel}; color: {muted}; border-top: 1px solid {line}; padding: 3px 12px; }}
QProgressBar {{ background: {field}; border: none; border-radius: 2px; max-height: 3px; }}
QProgressBar::chunk {{ background: #4376ef; }}
QFrame#divider {{ background: {line}; max-height: 1px; min-height: 1px; border: none; }}
QMessageBox, QDialog {{ background: {panel}; }}
QToolTip {{ background: {panel}; color: {fg}; border: 1px solid {line}; padding: 6px; }}
"""
