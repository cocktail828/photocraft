"""In-app TOML editor with validation before any file is replaced."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .config import ConfigError, parse_preferences, read_text, validate_preferences


class ConfigEditor(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("编辑配置 · PhotoCraft")
        self.resize(860, 700)
        self.setMinimumSize(620, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        title = QLabel("编辑配置")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        path = QLabel(str(config.path))
        path.setObjectName("muted")
        path.setTextFormat(Qt.TextFormat.PlainText)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setWordWrap(True)
        layout.addWidget(path)
        hint = QLabel("TOML 格式 · 每个 [[crop.templates]] 块对应一个模板，可修改或删除。保存后立即生效。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("configEditor")
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setTabStopDistance(self.editor.fontMetrics().horizontalAdvance(" ") * 4)
        layout.addWidget(self.editor, 1)
        self.message = QLabel()
        self.message.setObjectName("warning")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.validate_button = QPushButton("检查配置")
        self.validate_button.clicked.connect(self.validate_text)
        buttons.addWidget(self.validate_button)
        buttons.addStretch()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText("保存并应用")
        self.save_button.setObjectName("primary")
        self.save_button.setShortcut(QKeySequence(QKeySequence.StandardKey.Save))
        self.save_button.setToolTip("保存并应用 · Ctrl+S")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        buttons.addWidget(self.buttons)
        layout.addLayout(buttons)
        try:
            self.editor.setPlainText(read_text(config.path))
        except ConfigError as error:
            self.show_message(str(error))
        self.editor.textChanged.connect(self.message.hide)

    def show_message(self, text, success=False):
        self.message.setObjectName("success" if success else "warning")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setText(text)
        self.message.show()

    def validate_text(self):
        try:
            data = parse_preferences(self.editor.toPlainText(), self.config.path)
            theme, templates = validate_preferences(data)
        except ConfigError as error:
            self.show_message(str(error))
            return False
        self.show_message(
            f"✓ 配置有效 · {len(templates)} 个模板 · {'深色' if theme == 'dark' else '浅色'}主题",
            success=True,
        )
        return True

    def save(self):
        try:
            self.config.save_text(self.editor.toPlainText())
        except ConfigError as error:
            self.show_message(str(error))
            return
        self.accept()
