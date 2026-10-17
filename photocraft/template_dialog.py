"""Create crop templates without editing the current photo."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from .config import ConfigError


class TemplateDialog(QDialog):
    def __init__(self, config, size=(295, 413), parent=None):
        super().__init__(parent)
        self.config = config
        self.templates = None
        self.template_name = ""
        self.setWindowTitle("新增模板 · PhotoCraft")
        self.setMinimumWidth(440)
        self.resize(460, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        title = QLabel("新增裁剪模板")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        subtitle = QLabel("设置名称和像素尺寸，下次裁剪时可直接选用。")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        name_label = QLabel("模板名称")
        layout.addWidget(name_label)
        self.name = QLineEdit()
        self.name.setPlaceholderText("例如：考试报名照片")
        self.name.setMaxLength(100)
        self.name.setAccessibleName("模板名称")
        name_label.setBuddy(self.name)
        layout.addWidget(self.name)
        spec = QFrame()
        spec.setObjectName("cropCard")
        specs = QHBoxLayout(spec)
        specs.setContentsMargins(16, 14, 16, 16)
        specs.setSpacing(16)
        self.width_px, self.height_px = QSpinBox(), QSpinBox()
        for caption, control, value in (
            ("宽度 / px", self.width_px, size[0]),
            ("高度 / px", self.height_px, size[1]),
        ):
            column = QVBoxLayout()
            column.setSpacing(8)
            heading = QLabel(caption)
            heading.setObjectName("muted")
            heading.setBuddy(control)
            column.addWidget(heading)
            control.setRange(1, 30000)
            control.setValue(value)
            control.setAccessibleName(caption)
            column.addWidget(control)
            specs.addLayout(column, 1)
        layout.addWidget(spec)
        hint = QLabel("模板不包含照片或裁剪位置，新增后不会修改当前图片。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.message = QLabel()
        self.message.setObjectName("warning")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)
        layout.addStretch()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText("新增模板")
        self.save_button.setObjectName("primary")
        self.save_button.setDefault(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.name.textChanged.connect(self.message.hide)
        self.width_px.valueChanged.connect(self.message.hide)
        self.height_px.valueChanged.connect(self.message.hide)
        self.name.setFocus()

    def save(self):
        name = self.name.text().strip()
        width, height = self.width_px.value(), self.height_px.value()
        if not name:
            self.message.setText("请填写模板名称。")
            self.message.show()
            self.name.setFocus()
            return
        preset = dict(
            name=name,
            width=width,
            height=height,
            dpi=300,
            mm_w=min(1000, max(0.1, round(width * 25.4 / 300, 2))),
            mm_h=min(1000, max(0.1, round(height * 25.4 / 300, 2))),
            format="JPEG",
            background="#ffffff",
        )
        try:
            self.templates = self.config.save_template(preset, overwrite=False)
        except ConfigError as error:
            self.message.setText(str(error))
            self.message.show()
            return
        self.template_name = name
        self.accept()
