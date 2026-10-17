from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QRectF, QSignalBlocker, QSize, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QKeySequence, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .canvas import Canvas, pixmap
from .compression import EncodedImage, ExportOptions, compress, save_verified
from .config import CONFIG_FILENAME, Config, ConfigError
from .config_dialog import ConfigEditor
from .core import (
    Document,
    Enhancement,
    Watermark,
    enhance,
    paint_stroke,
    watermark_preview,
)
from .fonts import default_font_family, render_text
from .icons import icon, logo
from .preview_info import PreviewInfo
from .rendering import RenderCache
from .template_dialog import TemplateDialog
from .widgets import TextLengthValidator, Worker, stylesheet

FILTER = "图片 (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff);;所有文件 (*)"
EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "BMP": "bmp", "TIFF": "tiff"}


def tool_icon(name, color="#637087"):
    return icon("compress" if name == "export" else name, color)


def label(text, name="", wrap=False):
    result = QLabel(text)
    result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


def button(text, callback, primary=False, symbol=None):
    result = QPushButton(text)
    if primary:
        result.setObjectName("primary")
    if symbol:
        result.setIcon(icon(symbol, "#ffffff" if primary else "#637087"))
    result.clicked.connect(lambda checked=False: callback())
    return result


def spin(value, minimum=1, maximum=30000, suffix=""):
    result = QSpinBox()
    result.setRange(minimum, maximum)
    result.setValue(value)
    result.setSuffix(suffix)
    result.lineEdit().setTextMargins(10, 0, 8, 0)
    return result


def slider_field(layout, title, value, minimum, maximum, suffix=""):
    caption = label(f"{value}{suffix}", "muted")
    caption.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(row(label(title), caption))
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(minimum, maximum)
    slider.setValue(value)
    slider.setSingleStep(1)
    slider.setPageStep(max(1, (maximum - minimum) // 20))
    slider.setAccessibleName(title)
    slider.valueChanged.connect(lambda v: caption.setText(f"{v}{suffix}"))
    layout.addWidget(slider)
    return slider


def combo(items):
    result = QComboBox()
    result.addItems(items)
    return result


def check(text, checked=False):
    result = QCheckBox(text)
    result.setChecked(checked)
    return result


def row(*widgets):
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for item in widgets:
        if isinstance(item, QLabel) and item.text() in ("×", ":"):
            item.setFixedWidth(12)
        layout.addWidget(item)
    return widget


def divider():
    frame = QFrame()
    frame.setObjectName("divider")
    return frame


def disclosure(title, content):
    toggle = QPushButton("▸ " + title)
    toggle.setObjectName("disclosure")
    toggle.setCheckable(True)
    content.hide()

    def expand(opened):
        content.setVisible(opened)
        toggle.setText(("▾ " if opened else "▸ ") + title)

    toggle.toggled.connect(expand)
    return toggle


def size_text(size):
    return f"{size / 1024 / 1024:.2f} MB" if size >= 1024 * 1024 else f"{size / 1024:.2f} KB"


def source_result(metadata):
    data = metadata.get("source_data")
    if data is None:
        return None
    width, height = metadata.get("encoded_dimensions", metadata["dimensions"])
    return EncodedImage(data, metadata["format"], width, height, None, True, False, "原文件编码", None)


class MainWindow(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self.setWindowTitle("PhotoCraft · 照片工作台")
        self.setWindowIcon(logo())
        self.resize(1450, 940)
        self.setMinimumSize(1080, 720)
        self.config = config if config is not None else Config()
        self.dark = self.config.theme == "dark"
        self.doc = None
        self.current_tool = "crop"
        self.preview_result = None
        self.encoded_preview_image = None
        self.preview_key = None
        self.preview_edit_generation = None
        self.preview_options = None
        self.render_cache = RenderCache()
        self.stroke_preview_base = None
        self.background_color = "#ffffff"
        self.background_preview = None
        self.background_busy = False
        self.background_pending = False
        self.background_apply_pending = False
        self.background_draft_active = False
        self.background_error = ""
        self.background_timer = QTimer(self)
        self.background_timer.setSingleShot(True)
        self.background_timer.setInterval(150)
        self.background_timer.timeout.connect(self.render_background_preview)
        self.export_generation = 0
        self.edit_generation = 0
        self.enhancement_image = None
        self.enhance_busy = False
        self.enhance_pending = False
        self.enhance_dragging = False
        self.enhance_gesture_checkpoint = False
        self.closing = False
        self.encoding = False
        self.apply_after_encode = False
        self.applied_compression = None
        self.applied_compression_generation = None
        self.applied_export_options = None
        self.save_result = None
        self.save_result_key = None
        self.compression_timer = QTimer(self)
        self.compression_timer.setSingleShot(True)
        self.compression_timer.setInterval(300)
        self.compression_timer.timeout.connect(lambda: self.encode_preview(automatic=True))
        self.saving = False
        self.loading = False
        self.compare_state = None
        self.jobs = set()
        self.preview_jobs = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.save_pool = QThreadPool(self)
        self.save_pool.setMaxThreadCount(1)
        self.live_size_generation = 0
        self.live_size_worker = None
        self.live_size_pending = False
        self.live_size_result = None
        self.live_size_error = ""
        self.live_size_timer = QTimer(self)
        self.live_size_timer.setSingleShot(True)
        self.live_size_timer.setInterval(300)
        self.live_size_timer.timeout.connect(self.measure_image_size)
        self.mark_preview_generation = 0
        self.mark_preview_worker = None
        self.mark_preview_pending = False
        self.mark_draft_active = False
        self.mark_bitmap_cache = None
        self.rotation_generation = 0
        self.rotation_busy = False
        self.rotation_preview_cache = None
        self.stroke_info = None
        self.background_alpha_base = None
        self.background_has_transparency = None
        self.compression_error = ""
        self.rotation_timer = QTimer(self)
        self.rotation_timer.setSingleShot(True)
        self.rotation_timer.setInterval(80)
        self.rotation_timer.timeout.connect(self.render_rotation_preview)
        self.mark_preview_timer = QTimer(self)
        self.mark_preview_timer.setSingleShot(True)
        self.mark_preview_timer.setInterval(150)
        self.mark_preview_timer.timeout.connect(self._render_mark_preview)
        self.crop_output_size = None
        self.presets = [dict(p) for p in self.config.templates]
        self._build()
        self.preview_info_controller = PreviewInfo(self)
        self.preview_info_controller.changed.connect(self.update_info)
        self.enhance_timer = QTimer(self)
        self.enhance_timer.setSingleShot(True)
        self.enhance_timer.setInterval(200)
        self.enhance_timer.timeout.connect(self._enhance_preview)
        self._shortcuts()
        self.setStyleSheet(stylesheet(self.dark))
        self.select_tool("crop")
        self.statusBar().showMessage("准备就绪 · 全部处理在本地完成")
        self.restore_window_state()
        if self.config.errors:
            QTimer.singleShot(0, lambda: self.error("\n\n".join(self.config.errors)))

    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(78)
        head = QHBoxLayout(header)
        head.setContentsMargins(24, 10, 24, 10)
        brand_icon = label("")
        brand_icon.setPixmap(logo().pixmap(42, 42))
        head.addWidget(brand_icon)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(label("PhotoCraft", "brand"))
        brand.addWidget(label(__version__, "subtitle"))
        head.addLayout(brand)
        head.addSpacing(28)
        self.offline_badge = label("● 离线模式 · 照片不上传", "offlineBadge")
        self.offline_badge.setToolTip("所有功能均在本机处理，不上传照片。")
        head.addWidget(self.offline_badge)
        head.addStretch()
        theme = QToolButton()
        theme.setIcon(icon("sun"))
        theme.setToolTip("切换浅色 / 深色主题")
        theme.clicked.connect(self.toggle_theme)
        head.addWidget(theme)
        outer.addWidget(header)
        body = QHBoxLayout()
        body.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(86)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(7, 14, 7, 12)
        side.setSpacing(2)
        self.tool_buttons = {}
        group = QButtonGroup(self)
        tools = [
            ("crop", "裁剪"),
            ("background", "背景色"),
            ("rotate", "旋转翻转"),
            ("brush", "画笔"),
            ("mosaic", "马赛克"),
            ("blur", "局部模糊"),
            ("watermark", "水印"),
            ("enhance", "图片增强"),
            ("export", "图像压缩"),
        ]
        for name, title in tools:
            tool = QToolButton()
            tool.setObjectName("tool")
            tool.setText(title)
            tool.setIcon(tool_icon(name))
            tool.setIconSize(QSize(24, 24))
            tool.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            tool.setCheckable(True)
            tool.setFixedSize(72, 58)
            group.addButton(tool)
            tool.clicked.connect(lambda checked=False, key=name: self.select_tool(key))
            side.addWidget(tool)
            self.tool_buttons[name] = tool
        side.addStretch()
        self.version_label = label(__version__, "muted", True)
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.version_label.setToolTip(__version__)
        self.version_label.setStyleSheet("font-size: 10px;")
        self.version_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        side.addWidget(self.version_label)
        body.addWidget(sidebar)
        workspace = QVBoxLayout()
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("workspaceBar")
        bar.setFixedHeight(57)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(22, 0, 16, 0)
        self.filename = label("你的下一张好照片，从这里开始", "muted")
        bar_layout.addWidget(self.filename, 1)
        self.apply_button = button("应用", self.apply_current_tool, True, "check")
        self.apply_button.setEnabled(False)
        bar_layout.addWidget(self.apply_button)
        self.undo_button = self._tool_button("undo", "撤销 · Ctrl+Z", self.undo)
        self.redo_button = self._tool_button("redo", "重做 · Ctrl+Shift+Z", self.redo)
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        bar_layout.addWidget(self.undo_button)
        bar_layout.addWidget(self.redo_button)
        workspace.addWidget(bar)
        self.center_stack = QStackedWidget()
        self.canvas = Canvas()
        self.canvas.fileDropped.connect(self.open_path)
        self.canvas.strokeFinished.connect(self.paint)
        self.canvas.strokePreview.connect(self.preview_paint)
        self.canvas.cropApplied.connect(self.apply_crop)
        self.canvas.cropChanged.connect(self.crop_changed)
        self.canvas.zoomChanged.connect(self.zoom_changed)
        self.center_stack.addWidget(self._welcome())
        self.center_stack.addWidget(self.canvas)
        workspace.addWidget(self.center_stack, 1)
        controls = QWidget()
        controls.setObjectName("canvasControls")
        controls.setFixedHeight(53)
        control = QHBoxLayout(controls)
        control.setContentsMargins(16, 0, 16, 0)
        control.addWidget(
            self._tool_button("hand", "平移 · 按住空格或鼠标中键", lambda: self.canvas.set_tool("hand"))
        )
        control.addWidget(self._tool_button("fit", "适应窗口 · Ctrl+0", self.canvas.fit))
        control.addWidget(button("1:1", self.canvas.actual_size))
        self.zoom_label = label("100%", "muted")
        self.zoom_label.setMinimumWidth(48)
        control.addWidget(self.zoom_label)
        control.addStretch()
        self.compare_button = button("按住查看原图", lambda: None, symbol="compare")
        self.compare_button.pressed.connect(self.begin_compare)
        self.compare_button.released.connect(self.end_compare)
        control.addWidget(self.compare_button)
        self.transparency = check("透明网格", True)
        self.transparency.toggled.connect(self.toggle_checker)
        control.addWidget(self.transparency)
        workspace.addWidget(controls)
        self.info = QWidget()
        self.info.setObjectName("imageInfo")
        info_layout = QHBoxLayout(self.info)
        info_layout.setContentsMargins(20, 10, 20, 10)
        info_layout.setSpacing(18)
        for title, name in (("预览", "preview_info"), ("当前", "modified_info")):
            column = QWidget()
            column.setObjectName("previewInfoColumn" if name == "preview_info" else "modifiedInfoColumn")
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0 if name == "preview_info" else 18, 0, 0, 0)
            column_layout.setSpacing(4)
            heading = label(title)
            heading.setStyleSheet("font-weight: 650;")
            column_layout.addWidget(heading)
            details = label("—", "muted", True)
            details.setTextFormat(Qt.TextFormat.PlainText)
            details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            column_layout.addWidget(details)
            column_layout.addStretch()
            setattr(self, name, details)
            info_layout.addWidget(column, 1)
        workspace.addWidget(self.info)
        body.addLayout(workspace, 1)
        self.properties = QWidget()
        self.properties.setObjectName("properties")
        self.properties.setFixedWidth(325)
        props = QVBoxLayout(self.properties)
        props.setContentsMargins(0, 0, 0, 0)
        self.panels = QStackedWidget()
        self.panel_indexes = {}
        for name, builder in [
            ("crop", self._crop_panel),
            ("background", self._background_panel),
            ("rotate", self._rotate_panel),
            ("brush", lambda: self._brush_panel("brush")),
            ("mosaic", lambda: self._brush_panel("mosaic")),
            ("blur", lambda: self._brush_panel("blur")),
            ("watermark", self._watermark_panel),
            ("enhance", self._enhance_panel),
            ("export", self._export_panel),
        ]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(builder())
            self.panel_indexes[name] = self.panels.addWidget(scroll)
        props.addWidget(self.panels)
        body.addWidget(self.properties)
        outer.addLayout(body, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.status_text = label("本地处理 · 不上传照片", "muted")
        self.statusBar().addPermanentWidget(self.status_text)
        self._watch_export_options()

    def _tool_button(self, name, tooltip, callback):
        result = QToolButton()
        result.setIcon(icon(name))
        result.setToolTip(tooltip)
        result.clicked.connect(lambda checked=False: callback())
        return result

    def _welcome(self):
        widget = QWidget()
        widget.setAcceptDrops(True)
        widget.dragEnterEvent = self.canvas.dragEnterEvent
        widget.dropEvent = self.canvas.dropEvent
        box = QVBoxLayout(widget)
        box.setContentsMargins(65, 40, 65, 40)
        box.addStretch()
        emblem = label("")
        emblem.setPixmap(logo().pixmap(86, 86))
        emblem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(emblem)
        box.addSpacing(24)
        title = label("把照片，调整到刚刚好", "large")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(title)
        sub = label("证件照 · 报名头像 · 日常图片处理", "muted")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(sub)
        box.addSpacing(30)
        action = button("打开一张照片", self.open_dialog, True, "open")
        action.setMinimumHeight(49)
        action.setMaximumWidth(240)
        box.addWidget(action, alignment=Qt.AlignmentFlag.AlignCenter)
        caption = label("也可以将图片拖到这里\n支持 JPG、PNG、WEBP、BMP、TIFF", "muted")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(caption)
        box.addSpacing(12)
        sample = button("使用演示照片，体验工作台 →", self.load_demo)
        sample.setObjectName("ghost")
        box.addWidget(sample, alignment=Qt.AlignmentFlag.AlignCenter)
        box.addStretch()
        box.addWidget(divider())
        box.addSpacing(15)
        offline_icon = label("")
        offline_icon.setPixmap(icon("offline", "#7b879b").pixmap(20, 20))
        offline_icon.setFixedSize(20, 20)
        benefits = row(
            row(offline_icon, label("完全离线", "muted")),
            label("✓  实测文件大小", "muted"),
            label("↶  可撤销编辑", "muted"),
        )
        box.addWidget(benefits)
        return widget

    def _panel(self, title, subtitle):
        widget = QWidget()
        widget.setObjectName("panelContent")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(22, 25, 22, 24)
        layout.setSpacing(16)
        layout.addWidget(label("PHOTO WORKSPACE", "section"))
        layout.addWidget(label(title, "panelTitle"))
        layout.addWidget(label(subtitle, "muted", True))
        layout.addWidget(divider())
        return widget, layout

    def _form(self, layout, fields):
        form = QFormLayout()
        form.setVerticalSpacing(11)
        form.setHorizontalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for name, widget in fields:
            form.addRow(name, widget)
        layout.addLayout(form)

    def _crop_panel(self):
        widget, layout = self._panel("裁剪", "选择规格、调整取景，确认后点击上方「应用」。")
        layout.setSpacing(16)
        self.add_template_button = button("新增模板", self.save_preset, symbol="add")
        self.add_template_button.setObjectName("textAction")
        self.add_template_button.setToolTip("在弹窗中设置模板名称和像素尺寸。")
        layout.addWidget(row(label("裁剪方式", "fieldTitle"), self.add_template_button))
        self.preset_combo = QComboBox()
        self.crop_ratio = self.preset_combo
        self.populate_crop_modes()
        self.preset_combo.currentIndexChanged.connect(self.ratio_changed)
        layout.addWidget(self.preset_combo)
        dimensions_card = QFrame()
        dimensions_card.setObjectName("cropCard")
        dimensions = QVBoxLayout(dimensions_card)
        dimensions.setContentsMargins(14, 14, 14, 14)
        dimensions.setSpacing(12)
        self.ratio_w, self.ratio_h = spin(16), spin(9)
        self.ratio_w.valueChanged.connect(self.ratio_changed)
        self.ratio_h.valueChanged.connect(self.ratio_changed)
        self.crop_ratio_fields = QWidget()
        ratio_layout = QVBoxLayout(self.crop_ratio_fields)
        ratio_layout.setContentsMargins(0, 0, 0, 0)
        ratio_layout.addWidget(label("自定义比例", "fieldTitle"))
        self._form(ratio_layout, [("宽高比例", row(self.ratio_w, label(":"), self.ratio_h))])
        dimensions.addWidget(self.crop_ratio_fields)
        self.crop_w, self.crop_h = spin(295), spin(413)
        for control in (self.crop_w, self.crop_h):
            control.setEnabled(False)
            control.valueChanged.connect(self.crop_pixels_changed)
        self.crop_pixel_fields = QWidget()
        pixels = QVBoxLayout(self.crop_pixel_fields)
        pixels.setContentsMargins(0, 0, 0, 0)
        pixels.addWidget(label("自由裁剪", "fieldTitle"))
        self._form(pixels, [("裁剪框像素", row(self.crop_w, label("×"), self.crop_h))])
        dimensions.addWidget(self.crop_pixel_fields)
        self.crop_spec_fields = self._crop_spec_fields()
        dimensions.addWidget(self.crop_spec_fields)
        layout.addWidget(dimensions_card)
        self.crop_scaling_fields = QFrame()
        self.crop_scaling_fields.setObjectName("cropCard")
        scaling = QVBoxLayout(self.crop_scaling_fields)
        scaling.setContentsMargins(14, 12, 14, 14)
        scaling.setSpacing(8)
        self.crop_allow_resize = check("允许缩放")
        self.crop_allow_resize.setToolTip(
            "允许将裁剪区域放大或缩小到模板像素；放大可能模糊，缩小会丢失细节。"
        )
        self.crop_allow_resize.toggled.connect(self.ratio_changed)
        scaling.addWidget(self.crop_allow_resize)
        self.crop_scaling_hint = label("", "muted", True)
        scaling.addWidget(self.crop_scaling_hint)
        layout.addWidget(self.crop_scaling_fields)
        layout.addStretch()
        return widget

    def _background_panel(self):
        widget, layout = self._panel("背景色", "为透明或半透明区域填充颜色，调整后实时预览。")
        self.background_color_button = button("选择颜色 · #FFFFFF", self.choose_background_color)
        layout.addWidget(row(label("填充颜色"), self.background_color_button))
        layout.addWidget(
            label("仅填充透明区域，不会自动抠图。需要更换不透明背景时，可先使用橡皮擦擦除。", "muted", True)
        )
        layout.addStretch()
        return widget

    def populate_crop_modes(self, selected=0):
        with QSignalBlocker(self.preset_combo):
            self.preset_combo.clear()
            for index, preset in enumerate(self.presets):
                self.preset_combo.addItem(preset["name"], index)
            self.preset_combo.addItem("自由裁剪", "free")
            self.preset_combo.addItem("按比例裁剪", "custom")
            index = self.preset_combo.findData(selected)
            self.preset_combo.setCurrentIndex(index if index >= 0 else self.preset_combo.findData("free"))

    def _rotate_panel(self):
        widget, layout = self._panel("旋转与翻转", "微调照片角度，或快速改变方向。")
        layout.addWidget(
            row(
                button("↶ 左转 90°", lambda: self.transform(90)),
                button("↷ 右转 90°", lambda: self.transform(-90)),
            )
        )
        layout.addWidget(button("旋转 180°", lambda: self.transform(180)))
        layout.addWidget(
            row(
                button("水平翻转", lambda: self.transform(flip="horizontal")),
                button("垂直翻转", lambda: self.transform(flip="vertical")),
            )
        )
        layout.addWidget(divider())
        self.angle = QDoubleSpinBox()
        self.angle.setRange(-180, 180)
        self.angle.setSuffix(" °")
        self.angle.lineEdit().setTextMargins(10, 0, 8, 0)
        self.angle.valueChanged.connect(self.rotation_preview)
        self.expand = check("自动扩展画布，保留完整内容", True)
        self.expand.toggled.connect(self.rotation_preview)
        self._form(layout, [("自定义角度", self.angle)])
        layout.addWidget(self.expand)
        layout.addWidget(label("透明区域在导出时可保留，或填充为所选背景色。", "hint", True))
        layout.addStretch()
        return widget

    def _brush_panel(self, mode):
        titles = {
            "brush": ("画笔与修正", "在照片上自由绘制或擦除背景。"),
            "mosaic": ("马赛克", "沿轨迹遮挡敏感信息，实际像素会被修改。"),
            "blur": ("局部模糊", "只模糊画笔经过的区域。"),
        }
        widget, layout = self._panel(*titles[mode])
        if not hasattr(self, "brush_controls"):
            self.brush_controls = {}
        size = slider_field(layout, "画笔大小", 30, 1, 100, " px")
        opacity = slider_field(layout, "不透明度", 100, 1, 100, " %")
        block = spin(12, 2, 100, " px")
        if mode in ("mosaic", "blur"):
            block = slider_field(layout, "块大小" if mode == "mosaic" else "模糊强度", 12, 2, 100, " px")
        else:
            self.brush_color = "#ffffff"
            self.color_button = button("●  选择画笔颜色", self.choose_brush_color)
            layout.addWidget(self.color_button)
            self.eraser = check("橡皮擦（擦除为透明）")
            self.eraser.toggled.connect(self.brush_settings)
            layout.addWidget(self.eraser)
        self.brush_controls[mode] = (size, opacity, block)
        size.valueChanged.connect(self.brush_settings)
        opacity.valueChanged.connect(self.brush_settings)
        layout.addWidget(
            label("画笔大小以源图片像素为单位。按住空格可平移；Ctrl+Z 撤销上一笔。", "hint", True)
        )
        layout.addStretch()
        return widget

    def _watermark_panel(self):
        widget, layout = self._panel("文字水印", "整页重复平铺，调整后预览，满意再应用。")
        layout.setSpacing(10)
        self.mark_text = QLineEdit("仅用于报名审核")
        self.mark_text.setValidator(TextLengthValidator(50, self.mark_text))
        self.mark_text.setPlaceholderText("输入水印文字")
        self.mark_text.setToolTip("水印文字最多 50 字，超长输入不允许。")
        self.mark_length_error = label("文字超长，不允许超过 50 字。", "warning", True)
        self.mark_length_error.hide()
        self.mark_text.inputRejected.connect(self.mark_length_error.show)
        self.mark_size = spin(28, 4, 200, " px")
        self.mark_font = QFontComboBox()
        self.mark_font.setCurrentFont(QFont(default_font_family()))
        self.mark_font.setEditable(False)
        self.mark_font.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mark_font.setMinimumContentsLength(10)
        self.mark_font.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.mark_color = self.config.watermark_color
        self._form(
            layout,
            [("水印文字", self.mark_text), ("系统字体", self.mark_font), ("字号", self.mark_size)],
        )
        layout.addWidget(self.mark_length_error)
        self.mark_color_button = button("", self.choose_mark_color)
        self.update_mark_color_button()
        self._form(layout, [("文字颜色", self.mark_color_button)])
        self.mark_opacity = slider_field(layout, "不透明度", 28, 1, 100, " %")
        self.mark_angle = slider_field(layout, "倾斜角度", 30, -180, 180, " °")
        self.mark_row_spacing = slider_field(layout, "行间距", 60, 0, 3000, " px")
        self.mark_column_spacing = slider_field(layout, "列间距", 80, 0, 3000, " px")
        self.mark_live_preview = check("实时预览", True)
        self.mark_multiple = check("允许多重水印")
        layout.addWidget(self.mark_live_preview)
        layout.addWidget(self.mark_multiple)
        layout.addWidget(button("清除水印", self.delete_mark))
        layout.addWidget(
            label(
                "间距单位为原图像素。实时预览不保存修改，点击应用后参与导出。Ctrl+Z 可撤销。",
                "muted",
                True,
            )
        )
        for control in (
            self.mark_size,
            self.mark_opacity,
            self.mark_angle,
            self.mark_row_spacing,
            self.mark_column_spacing,
        ):
            control.valueChanged.connect(self.watermark_controls_changed)
        self.mark_text.textChanged.connect(self.watermark_controls_changed)
        self.mark_font.currentFontChanged.connect(self.watermark_controls_changed)
        self.mark_live_preview.toggled.connect(self.watermark_controls_changed)
        self.mark_multiple.toggled.connect(self.watermark_controls_changed)
        self.watermark_controls_changed()
        layout.addStretch()
        return widget

    def _enhance_panel(self):
        widget, layout = self._panel("图片增强", "调整即生效；同一项选择自动或手动调节。")
        layout.setSpacing(10)
        self.enhance_sliders = {}
        self.enhance_value_labels = {}
        self.enhance_checks = {}
        for key, title, lo, hi, value, automatic in [
            ("brightness", "亮度", 20, 200, 100, None),
            ("contrast", "对比度", 20, 200, 100, "autocontrast"),
            ("gamma", "明暗 / Gamma", 20, 300, 100, None),
            ("equalize", "明暗均衡", 0, 100, 0, None),
            ("saturation", "饱和度", 0, 200, 100, None),
            ("temperature", "色温", -100, 100, 0, "white_balance"),
            ("sharpness", "锐化", 0, 300, 100, None),
            ("denoise", "降噪", 0, 100, 0, None),
        ]:
            value_label = label(f"{value / 100:.2f}", "muted")
            self.enhance_value_labels[key] = value_label
            header = row(label(title), value_label)
            if automatic:
                toggle = check("自动" if automatic == "autocontrast" else "自动白平衡")
                toggle.setToolTip("启用自动时暂停此项手动调节，取消后恢复原手动值。")
                toggle.toggled.connect(self.enhancement_changed)
                self.enhance_checks[automatic] = toggle
                header.layout().addWidget(toggle)
            layout.addWidget(header)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(lo, hi)
            slider.setValue(value)
            slider.setAccessibleName(title)
            slider.valueChanged.connect(lambda v, lab=value_label: lab.setText(f"{v / 100:.2f}"))
            slider.valueChanged.connect(self.enhancement_changed)
            slider.sliderPressed.connect(self.begin_enhancement_gesture)
            slider.sliderReleased.connect(self.end_enhancement_gesture)
            self.enhance_sliders[key] = slider
            layout.addWidget(slider)
        layout.addWidget(button("恢复默认参数", self.reset_enhancement))
        layout.addWidget(
            label("调整即生效，参数保持当前位置。Ctrl+Z 可撤销；一次拖动作为一次调整。", "hint", True)
        )
        layout.addStretch()
        return widget

    def _crop_spec_fields(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(label("模板尺寸", "fieldTitle"))
        self.id_w, self.id_h = spin(295), spin(413)
        for control in (self.id_w, self.id_h):
            control.setReadOnly(True)
            control.setToolTip(
                "模板的固定输出像素，不可手动修改。裁剪框用于调整取景；修改模板请打开「配置 → 编辑配置」。"
            )
        fields = QHBoxLayout()
        fields.setSpacing(12)
        for caption, control in (("宽度 / px", self.id_w), ("高度 / px", self.id_h)):
            column = QVBoxLayout()
            column.setSpacing(8)
            column.addWidget(label(caption, "muted"))
            column.addWidget(control)
            fields.addLayout(column, 1)
        layout.addLayout(fields)
        return widget

    def _export_panel(self):
        widget, layout = self._panel("图像压缩", "调整画质与文件大小，保留裁剪确定的像素；通过文件菜单保存。")
        layout.setSpacing(10)
        self.out_format = combo(list(EXTENSIONS))
        layout.addWidget(row(label("文件格式"), self.out_format))
        self.format_hint = label("", "muted", True)
        layout.addWidget(self.format_hint)
        layout.addWidget(divider())
        self.show_encoded_preview = check("在画布查看压缩效果", True)
        self.show_encoded_preview.setEnabled(False)
        self.show_encoded_preview.toggled.connect(lambda: self.show_image(fit=True))
        layout.addWidget(self.show_encoded_preview)
        self.quality_fields = QWidget()
        quality_layout = QVBoxLayout(self.quality_fields)
        quality_layout.setContentsMargins(0, 0, 0, 0)
        quality_layout.setSpacing(8)
        self.out_quality = slider_field(quality_layout, "画质", 95, 1, 100)
        self.out_quality.setToolTip(
            "影响 JPEG / WEBP 的文件体积与细节，不改变像素尺寸；质量 100 也属于有损编码。"
        )
        layout.addWidget(self.quality_fields)
        self.compression_hint = label("", "muted", True)
        layout.addWidget(self.compression_hint)
        advanced = QWidget()
        details = QVBoxLayout(advanced)
        details.setContentsMargins(0, 4, 0, 0)
        details.setSpacing(12)
        self.keep_alpha = check("保留透明背景", True)
        self.keep_exif = check("保留 EXIF（可能含位置）", False)
        self.keep_icc = check("保留 ICC 色彩配置", True)
        self.export_background = "#ffffff"
        self.export_background_button = button("透明区域填充色", self.choose_export_background)
        details.addWidget(self.keep_alpha)
        details.addWidget(self.export_background_button)
        details.addWidget(self.keep_exif)
        details.addWidget(self.keep_icc)
        self.export_advanced_toggle = disclosure("高级设置", advanced)
        layout.addWidget(self.export_advanced_toggle)
        layout.addWidget(advanced)
        layout.addWidget(label("调整仅预览；点击上方「应用」后生效，保存只包含已应用的操作。", "muted", True))
        layout.addWidget(label("文件 → 保存图片（Ctrl+S）", "muted", True))
        self.out_format.currentIndexChanged.connect(self.sync_export_controls)
        self.keep_alpha.toggled.connect(self.sync_export_controls)
        self.out_quality.valueChanged.connect(self.sync_export_controls)
        self.sync_export_controls()
        layout.addStretch()
        return widget

    def sync_export_controls(self, *args):
        fmt = self.out_format.currentText()
        lossy = fmt in ("JPEG", "WEBP")
        self.quality_fields.setVisible(lossy)
        self.keep_alpha.setEnabled(fmt not in ("JPEG", "BMP"))
        self.export_background_button.setVisible(fmt in ("JPEG", "BMP") or not self.keep_alpha.isChecked())
        self.format_hint.setText(
            {
                "JPEG": "适合照片，文件较小；透明区域将填充背景色。",
                "PNG": "适合截图与透明图片，使用无损压缩。",
                "WEBP": "兼顾画质、体积与透明背景。",
                "BMP": "无损保存，文件通常较大。",
                "TIFF": "无损保存，适合保留图像细节。",
            }[fmt]
        )
        self.compression_hint.setText(
            "按所选画质编码，像素尺寸保持不变。" if lossy else "使用无损编码，像素尺寸保持不变。"
        )

    def _shortcuts(self):
        self.menuBar().setNativeMenuBar(False)
        self.menu_actions = {}

        def action(menu, key, title, callback, shortcut=None, checkable=False):
            item = QAction(title, self)
            item.setObjectName(key)
            if shortcut:
                item.setShortcut(QKeySequence(shortcut))
            item.setCheckable(checkable)
            item.triggered.connect(lambda checked=False: callback())
            menu.addAction(item)
            self.menu_actions[key] = item
            return item

        file = self.menuBar().addMenu("文件")
        action(file, "open", "打开图片…", self.open_dialog, "Ctrl+O")
        action(file, "save_image", "保存图片…", self.request_save, "Ctrl+S").setEnabled(False)
        file.addSeparator()
        action(file, "quit", "退出", self.close, "Ctrl+Q")
        edit = self.menuBar().addMenu("编辑")
        self.undo_action = action(edit, "undo", "撤销", self.undo, "Ctrl+Z")
        self.redo_action = action(edit, "redo", "重做", self.redo, "Ctrl+Shift+Z")
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        view = self.menuBar().addMenu("视图")
        action(view, "fit", "适应窗口", self.canvas.fit, "Ctrl+0")
        action(view, "actual_size", "实际像素", self.canvas.actual_size, "Ctrl+1")
        action(
            view,
            "zoom_in",
            "放大",
            lambda: self.canvas.set_zoom(self.canvas.transform().m11() * 1.25),
            "Ctrl++",
        )
        action(
            view,
            "zoom_out",
            "缩小",
            lambda: self.canvas.set_zoom(self.canvas.transform().m11() / 1.25),
            "Ctrl+-",
        )
        view.addSeparator()
        self.dark_action = action(view, "dark_theme", "深色主题", self.toggle_theme, checkable=True)
        self.dark_action.setChecked(self.dark)
        settings = self.menuBar().addMenu("配置")
        action(settings, "config_edit", "编辑配置…", self.edit_config, "Ctrl+,")
        action(settings, "config_reload", "重新加载配置", self.reload_config, "F5")
        settings.addSeparator()
        action(settings, "config_import", "导入配置…", self.import_config)
        action(settings, "config_export", "导出配置…", self.export_config)
        action(settings, "config_folder", "打开配置目录", self.open_config_folder)
        settings.addSeparator()
        action(settings, "config_reset", "恢复默认配置…", self.reset_config)
        help_menu = self.menuBar().addMenu("帮助")
        action(help_menu, "demo", "使用演示照片", self.load_demo)
        action(help_menu, "config_help", "配置说明", self.config_help)
        help_menu.addSeparator()
        action(help_menu, "about", "关于 PhotoCraft", self.about)
        self.menuBar().show()

    def apply_configuration(self):
        if self.mark_color != self.config.watermark_color:
            self.mark_color = self.config.watermark_color
            self.update_mark_color_button()
            self.watermark_controls_changed()
        mode = self.crop_ratio.currentData()
        selected = ("preset", self.presets[mode]["name"]) if isinstance(mode, int) else ("mode", mode)
        old_crop, old_ratio, old_tool = QRectF(self.canvas.crop), self.canvas.ratio, self.canvas.tool
        self.presets = [dict(p) for p in self.config.templates]
        selection = (
            next((i for i, p in enumerate(self.presets) if p["name"] == selected[1]), "free")
            if selected[0] == "preset"
            else mode
        )
        self.populate_crop_modes(selection)
        self.dark = self.config.theme == "dark"
        self.setStyleSheet(stylesheet(self.dark))
        self.dark_action.setChecked(self.dark)
        for key, tool in self.tool_buttons.items():
            tool.setIcon(
                tool_icon(
                    key, "#3767df" if key == self.current_tool else ("#a5b3c9" if self.dark else "#637087")
                )
            )
        if self.current_tool == "crop":
            self.ratio_changed()
            if (selection != "free" or selected == ("mode", "free")) and self.canvas.ratio == old_ratio:
                if self.doc and not old_crop.isEmpty() and self.canvas.bounds.contains(old_crop):
                    self.canvas.crop = old_crop
                    self.canvas.set_tool(old_tool)
                    self.canvas.cropChanged.emit(old_crop)
                    self.update_apply_button()
                    self.canvas.viewport().update()
        else:
            preset = isinstance(selection, int)
            self.crop_spec_fields.setVisible(preset)
            self.crop_scaling_fields.setVisible(preset)
            self.crop_pixel_fields.setVisible(selection == "free")
            self.crop_ratio_fields.setVisible(selection == "custom")
            if preset:
                self.load_preset(selection)
                if self.crop_output_size is not None:
                    self.configure_crop_output()
            elif self.crop_output_size is not None:
                self.crop_output_size = None
                self.invalidate_export()

    def edit_config(self):
        dialog = ConfigEditor(self.config, self)
        if dialog.exec() == ConfigEditor.DialogCode.Accepted:
            self.apply_configuration()
            self.statusBar().showMessage("配置已保存并应用")
        dialog.deleteLater()

    def reload_config(self):
        try:
            self.config.reload()
        except ConfigError as error:
            self.error(str(error))
            return
        self.apply_configuration()
        self.statusBar().showMessage("配置已重新加载")

    def import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入配置", "", "TOML 配置 (*.conf *.toml);;所有文件 (*)")
        if not path:
            return
        try:
            self.config.import_file(path)
        except ConfigError as error:
            self.error(str(error))
            return
        self.apply_configuration()
        self.statusBar().showMessage(f"配置已导入并应用：{Path(path).name}")

    def export_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", CONFIG_FILENAME, "TOML 配置 (*.conf);;所有文件 (*)"
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".conf"
        try:
            self.config.export_file(path)
        except ConfigError as error:
            self.error(str(error))
            return
        self.statusBar().showMessage(f"配置已导出：{path}")

    def reset_config(self):
        if (
            QMessageBox.question(
                self,
                "恢复默认配置",
                "恢复默认主题、颜色与裁剪模板？当前照片的编辑结果将保留。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.config.reset()
        except ConfigError as error:
            self.error(str(error))
            return
        self.apply_configuration()
        self.statusBar().showMessage("已恢复默认配置")

    def open_config_folder(self):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config.directory.resolve()))):
            self.error(f"无法打开配置目录：{self.config.directory}")

    def config_help(self):
        QMessageBox.information(
            self,
            "配置说明",
            f"配置路径：{self.config.path}\n\n文件名固定为 PhotoCraft.conf，内容为 UTF-8 TOML。\n"
            "每个 [[crop.templates]] 块对应一个模板，可以修改、重排或删除。\n"
            "watermark.color 保存上次水印颜色，colors.custom 保存颜色窗口中的 16 个自定义色槽。\n"
            "只保留通用裁剪模式：\n[crop]\ntemplates = []\n\n"
            "菜单中的编辑、导入和重置立即生效；外部编辑后按 F5 重新加载。",
        )

    def _watch_export_options(self):
        self.out_quality.valueChanged.connect(self.invalidate_export)
        self.out_format.currentIndexChanged.connect(self.invalidate_export)
        for control in (
            self.keep_alpha,
            self.keep_exif,
            self.keep_icc,
        ):
            control.toggled.connect(self.invalidate_export)

    def start_job(self, operation, done, *, error=None, message="处理中…", background=False, pool=None):
        worker = Worker(operation)
        self.jobs.add(worker)
        if background:
            self.preview_jobs.add(worker)
        else:
            self.progress.show()
            self.statusBar().showMessage(message)
        worker.signals.done.connect(done)
        worker.signals.error.connect(error or self.error)
        worker.signals.progress.connect(self.statusBar().showMessage)
        worker.signals.finished.connect(lambda: self.finish_job(worker))
        (pool if pool is not None else self.pool).start(worker, 0 if background else 1)

    def finish_job(self, worker):
        self.jobs.discard(worker)
        self.preview_jobs.discard(worker)
        if not self.jobs - self.preview_jobs:
            self.progress.hide()

    def error(self, message):
        self.statusBar().showMessage("处理失败 · " + message)
        QMessageBox.warning(self, "PhotoCraft · 处理失败", message)

    def require_image(self):
        if self.doc is None:
            self.statusBar().showMessage("请先打开一张照片，或使用演示照片。", 5000)
            return False
        return True

    def select_tool(self, name):
        previous = self.current_tool
        if name == "background" and previous != name:
            self.background_draft_active = True
        elif name != "background":
            self.background_timer.stop()
            self.background_apply_pending = False
        self.rotation_generation += 1
        self.rotation_timer.stop()
        if hasattr(self, "angle") and self.current_tool == "rotate" and name != "rotate":
            self.angle.blockSignals(True)
            self.angle.setValue(0)
            self.angle.blockSignals(False)
        self.current_tool = name
        if previous == "rotate" and name != "rotate":
            self.rotation_preview_cache = None
        if previous in ("export", "rotate", "background") or name in ("export", "background"):
            self.show_image(fit=True)
        if name == "watermark":
            self.mark_draft_active = True
        self.schedule_mark_preview()
        self.tool_buttons[name].setChecked(True)
        for key, tool in self.tool_buttons.items():
            tool.setIcon(
                tool_icon(key, "#3767df" if key == name else ("#a5b3c9" if self.dark else "#637087"))
            )
        self.panels.setCurrentIndex(self.panel_indexes[name])
        self.canvas.set_tool(name if name in ("crop", "brush", "mosaic", "blur", "watermark") else "hand")
        self.canvas.portrait_guides = name == "crop" and isinstance(self.crop_ratio.currentData(), int)
        if name in self.brush_controls:
            self.brush_settings()
        self.status_text.setText(self.tool_buttons[name].text() + " · 本地处理")
        if name == "crop":
            self.ratio_changed()
        elif name == "rotate":
            self.rotation_preview()
        if name == "export" and self.doc:
            if self.preview_result is None:
                self.compression_timer.start()
            elif self.encoded_preview_image is None:
                self.show_cached_preview()
        elif name != "export":
            self.compression_timer.stop()
        self.update_info()

    def toggle_theme(self):
        try:
            self.config.set_theme(not self.dark)
        except ConfigError as error:
            self.error(str(error))
            return
        self.apply_configuration()

    def toggle_checker(self, enabled):
        self.canvas.checker = enabled
        self.canvas.viewport().update()

    def confirm_discard(self):
        if self.doc and self.doc.revision:
            return (
                QMessageBox.question(
                    self,
                    "打开另一张照片",
                    "当前编辑未保存为可继续编辑的项目。继续将关闭当前照片，原始文件不会改变。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.Yes
            )
        return True

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开照片", "", FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path):
        if self.loading or not self.confirm_discard():
            return
        self.loading = True

        def loaded(doc):
            self.loading = False
            self.set_document(doc)

        def failed(message):
            self.loading = False
            self.error("无法打开图片：" + message)

        self.start_job(
            lambda progress: Document.open(path),
            loaded,
            error=failed,
            message="正在读取照片并纠正 EXIF 方向…",
        )

    def set_document(self, doc):
        self.mark_draft_active = False
        self.crop_output_size = None
        self.doc = doc
        self.rotation_preview_cache = None
        self.stroke_info = None
        self.background_alpha_base = None
        self.background_has_transparency = None
        self.applied_export_options = None
        self.save_result = None
        self.save_result_key = None
        self.render_cache = RenderCache()
        self.stroke_preview_base = None
        self.background_preview = None
        self.background_apply_pending = False
        self.background_draft_active = self.current_tool == "background"
        self.edit_generation += 1
        self.restore_enhancement_controls()
        self.enhancement_image = None
        self.angle.setValue(0)
        self.center_stack.setCurrentIndex(1)
        self.filename.setText(doc.metadata["name"])
        self.setWindowTitle(f"{doc.metadata['name']} — PhotoCraft")
        self.refresh_marks()
        self.show_image(fit=True)
        self.select_tool(self.current_tool)
        self.invalidate_export()
        self.schedule_size_measurement()
        self.statusBar().showMessage("图片已打开 · 原始文件保留不变")

    def load_demo(self):
        if not self.confirm_discard():
            return
        image = Image.new("RGBA", (720, 1008), "#b7cbd4")
        draw = ImageDraw.Draw(image)
        for y in range(1008):
            t = y / 1008
            draw.line((0, y, 720, y), fill=(int(205 - 31 * t), int(225 - 27 * t), int(231 - 26 * t)))
        draw.ellipse((56, 697, 664, 1306), fill="#293f5c")
        draw.polygon([(302, 639), (416, 639), (459, 797), (360, 899), (263, 797)], fill="#f4d5be")
        draw.polygon([(255, 736), (360, 874), (459, 736), (489, 1008), (230, 1008)], fill="#f7f7f2")
        draw.ellipse((186, 225, 535, 684), fill="#d9ae91")
        draw.ellipse((200, 201, 525, 498), fill="#2b2c35")
        draw.ellipse((221, 327, 509, 693), fill="#edc4a7")
        draw.polygon(
            [(211, 464), (231, 294), (443, 273), (522, 413), (431, 370), (342, 382), (263, 449)],
            fill="#2b2c35",
        )
        draw.arc((269, 451, 316, 478), 190, 340, fill="#574139", width=7)
        draw.arc((403, 451, 449, 478), 190, 340, fill="#574139", width=7)
        draw.ellipse((285, 487, 296, 497), fill="#3c3434")
        draw.ellipse((422, 487, 433, 497), fill="#3c3434")
        draw.line((359, 502, 352, 546, 370, 549), fill="#d29e83", width=5)
        draw.arc((316, 552, 404, 602), 15, 165, fill="#b9746c", width=5)
        data = BytesIO()
        image.convert("RGB").save(data, "JPEG", quality=95)
        self.set_document(
            Document(
                image,
                {
                    "name": "工作台演示.jpg",
                    "format": "JPEG",
                    "size": len(data.getvalue()),
                    "source_data": data.getvalue(),
                    "encoded_dimensions": image.size,
                    "dimensions": image.size,
                    "dpi": (300, 300),
                },
            )
        )

    def show_image(self, original=False, fit=False):
        if not self.doc:
            return
        if self.compare_state is not None and not original:
            return
        if original:
            self.canvas.set_image(self.doc.original, fit=fit)
        elif (
            self.current_tool == "export"
            and self.preview_result
            and self.encoded_preview_image is not None
            and self.show_encoded_preview.isChecked()
        ):
            self.mark_preview_generation += 1
            self.canvas.set_image(
                self.encoded_preview_image,
                fit=fit,
                logical_size=(self.preview_result.width, self.preview_result.height),
            )
        elif self.current_tool == "rotate":
            self.rotation_preview()
        elif (
            self.current_tool == "background"
            and self.background_preview is not None
            and (self.background_preview[0] == (self.edit_generation, self.background_color))
        ):
            self.mark_preview_generation += 1
            self.canvas.set_image(self.background_preview[2], fit=fit, logical_size=self.doc.base.size)
        else:
            base = self.enhancement_image if self.enhancement_image is not None else self.doc.base
            self.canvas.set_image(base, fit=fit)
            if self.current_tool == "background" and self.background_draft_active:
                self.background_timer.start()
            else:
                self.schedule_mark_preview()

    def begin_compare(self):
        if self.doc and self.compare_state is None:
            self.mark_preview_generation += 1
            self.compare_state = {
                "crop": QRectF(self.canvas.crop),
                "tool": self.canvas.tool,
                "pixmap": self.canvas.photo.pixmap(),
                "photo_transform": self.canvas.photo.transform(),
                "bounds": QRectF(self.canvas.bounds),
                "scene_rect": self.canvas.sceneRect(),
                "view_transform": self.canvas.transform(),
                "horizontal": self.canvas.horizontalScrollBar().value(),
                "vertical": self.canvas.verticalScrollBar().value(),
            }
            self.canvas.set_tool("hand")
            self.show_image(original=True, fit=True)
            self.update_info()

    def end_compare(self):
        if self.compare_state is not None:
            state = self.compare_state
            generation = self.edit_generation
            self.compare_state = None
            # Restore the displayed image immediately, including asynchronous rotation previews.
            self.canvas.photo.setPixmap(state["pixmap"])
            self.canvas.photo.setTransform(state["photo_transform"])
            self.canvas.bounds = state["bounds"]
            self.canvas.setSceneRect(state["scene_rect"])
            self.canvas.crop = state["crop"]
            self.canvas.set_tool(state["tool"])
            self.show_image()
            self.canvas.setTransform(state["view_transform"])
            self.canvas.horizontalScrollBar().setValue(state["horizontal"])
            self.canvas.verticalScrollBar().setValue(state["vertical"])
            self.canvas.zoomChanged.emit(self.canvas.transform().m11())
            self.update_info()

            def restore_position():
                if (
                    not self.closing
                    and self.edit_generation == generation
                    and self.compare_state is None
                    and self.canvas.transform() == state["view_transform"]
                ):
                    self.canvas.horizontalScrollBar().setValue(state["horizontal"])
                    self.canvas.verticalScrollBar().setValue(state["vertical"])

            # Scrollbars can resize the viewport after its transform is restored.
            QTimer.singleShot(0, restore_position)

    @staticmethod
    def information_text(measured, encoded=None, note=""):
        if measured is None:
            return "正在计算实测体积…" + ("\n" + note if note else "")
        size, width, height, fmt = measured
        details = f"{size_text(size)}（{size:,} 字节） · {width} × {height} px · {fmt}"
        encoding = ""
        if encoded is not None:
            encoding = (
                "原文件字节，未重新编码"
                if encoded.strategy == "原文件编码"
                else ("有损" if encoded.lossy else "无损")
            )
            if encoded.quality is not None:
                encoding += f" · 质量 {encoded.quality}"
        return details + "\n" + " · ".join(text for text in (encoding, note) if text)

    def update_info(self):
        self.update_apply_button()
        if not self.doc:
            return
        metadata = self.doc.metadata
        original_w, original_h = metadata["dimensions"]
        original_size = metadata["size"]
        original_text = (
            f"原文件  {size_text(original_size)}（{original_size:,} 字节） · "
            f"{original_w} × {original_h} px · {metadata['format']}"
        )
        self.filename.setToolTip(original_text)
        modified = self.information_text(self.live_size_result, self.save_result, "已应用 · 保存使用此结果")
        if self.live_size_error:
            modified = "实测失败：" + self.live_size_error
        self.modified_info.setText(modified)
        self.modified_info.setToolTip(original_text + "\n保存只包含已应用的操作与压缩设置。")
        if hasattr(self, "preview_info_controller"):
            controller = self.preview_info_controller
            controller.refresh()
            plan = controller.plan
            encoded = plan.result or controller.result
            error = plan.error or controller.error
            if error:
                preview = "预览失败：" + error
            elif plan.original:
                preview = self.information_text(
                    (original_size, original_w, original_h, metadata["format"]), note=plan.note
                )
            elif plan.same:
                preview = self.information_text(self.live_size_result, self.save_result, plan.note)
            elif encoded is not None:
                preview = self.information_text(
                    (len(encoded.data), encoded.width, encoded.height, encoded.format), encoded, plan.note
                )
            else:
                preview = "正在计算预览实测…\n" + plan.note
            self.preview_info.setText(preview)
            self.preview_info.setToolTip(
                error or ("、".join(encoded.loss_reasons) if encoded else "") or plan.note
            )
        self.undo_button.setEnabled(bool(self.doc.history))
        self.redo_button.setEnabled(bool(self.doc.future))
        self.undo_action.setEnabled(bool(self.doc.history))
        self.redo_action.setEnabled(bool(self.doc.future))
        self.menu_actions["save_image"].setEnabled(True)

    def update_apply_button(self):
        if not hasattr(self, "apply_button"):
            return
        enabled = False
        tooltip = "请先打开图片。"
        if self.doc:
            mode = self.current_tool
            tooltip = "应用当前功能的预览。"
            if mode == "crop":
                enabled = self.canvas.tool == "crop" and not self.canvas.crop.isEmpty()
            elif mode == "rotate":
                enabled = self.angle.value() != 0
            elif mode == "watermark":
                enabled = (
                    self.mark_draft_active
                    and bool(self.mark_text.text().strip())
                    and len(self.mark_text.text()) <= 50
                    and (not self.mark_multiple.isChecked() or len(self.doc.watermarks) < 10)
                )
            elif mode == "background":
                opaque = (
                    self.background_alpha_base is self.doc.base and self.background_has_transparency is False
                )
                enabled = self.background_draft_active and not opaque and not self.background_apply_pending
                if opaque:
                    tooltip = "图片不含透明区域，背景填充不会改变画面。请先擦除原背景。"
            elif mode == "export":
                enabled = not self.encoding and (
                    self.applied_export_options is None or self.export_options() != self.save_options()
                )
            else:
                tooltip = "此功能调整后立即应用，无需再次点击应用。"
        self.apply_button.setEnabled(enabled)
        self.apply_button.setToolTip(tooltip)

    def apply_current_tool(self):
        actions = {
            "crop": self.apply_crop,
            "rotate": self.apply_rotation,
            "watermark": self.add_text_mark,
            "background": self.apply_background,
            "export": self.apply_compression,
        }
        action = actions.get(self.current_tool)
        if action is not None:
            action()
        self.update_info()

    def schedule_size_measurement(self):
        if not self.doc or self.closing:
            return
        if self.applied_compression_generation == self.edit_generation:
            self.update_info()
            return
        self.applied_compression = None
        self.applied_compression_generation = None
        if self.save_result_key is not None and self.save_result_key[0] != self.edit_generation:
            self.save_result = None
            self.save_result_key = None
        self.live_size_generation += 1
        self.live_size_result = None
        self.live_size_error = ""
        self.update_info()
        if self.live_size_worker is not None:
            self.live_size_pending = True
        else:
            self.live_size_timer.start()

    def measure_image_size(self):
        if not self.doc or self.closing:
            return
        if self.live_size_worker is not None:
            self.live_size_pending = True
            return
        generation = self.live_size_generation
        base, marks, settings = self.doc.snapshot(copy_base=False)
        cache = self.render_cache
        options, metadata = self.save_options(), dict(self.doc.metadata)
        edit_generation = self.edit_generation
        original, revision = self.doc.original, self.doc.revision
        possibly_unchanged = (
            self.applied_export_options is None
            and not self.doc.history
            and settings == Enhancement()
            and not marks
        )

        def check_current(message=""):
            if self.closing or generation != self.live_size_generation:
                raise InterruptedError("实测已取消")

        def operation(progress):
            check_current()
            if possibly_unchanged and (revision == 0 or base == original):
                return (metadata["size"], base.width, base.height, metadata["format"]), source_result(
                    metadata
                )
            image = cache.render(base, marks, settings, check_current=check_current)
            check_current()
            result = (
                self.save_result
                if self.save_result_key == (edit_generation, options)
                else compress(image, options, metadata, check_current)
            )
            return (len(result.data), result.width, result.height, result.format), result

        worker = Worker(operation)
        self.live_size_worker = worker
        self.jobs.add(worker)
        self.preview_jobs.add(worker)

        def done(result):
            if generation != self.live_size_generation or self.closing:
                return
            self.live_size_result, encoded = result
            if encoded is not None:
                self.save_result = encoded
                self.save_result_key = (edit_generation, options)
            self.update_info()

        def failed(message):
            if generation == self.live_size_generation and not self.closing:
                self.live_size_error = message
                self.update_info()

        def finished():
            self.finish_job(worker)
            self.live_size_worker = None
            if self.live_size_pending and not self.closing:
                self.live_size_pending = False
                self.live_size_timer.start()

        worker.signals.done.connect(done)
        worker.signals.error.connect(failed)
        worker.signals.finished.connect(finished)
        self.pool.start(worker)

    def changed(self, fit=False):
        self.edit_generation += 1
        self.stroke_preview_base = None
        self.enhancement_image = None
        self.invalidate_export()
        self.schedule_size_measurement()
        self.refresh_marks()
        self.show_image(fit=fit)
        self.update_info()
        if self.doc.enhancement != Enhancement():
            self.enhance_timer.start()
        else:
            self.enhance_timer.stop()

    def invalidate_export(self, *args):
        if (
            self.preview_result is not None
            and self.preview_edit_generation == self.edit_generation
            and self.preview_options == self.export_options()
        ):
            return
        had_preview = self.encoded_preview_image is not None
        self.export_generation += 1
        self.preview_result = None
        self.encoded_preview_image = None
        self.preview_key = None
        self.preview_edit_generation = None
        self.preview_options = None
        self.show_encoded_preview.setEnabled(False)
        self.compression_error = ""
        if self.doc and self.current_tool == "export" and not self.closing:
            self.compression_timer.start()
        if had_preview and self.current_tool == "export":
            self.show_image()
        self.update_info()

    def zoom_changed(self, value):
        self.zoom_label.setText(f"{value * 100:.0f}%")

    def undo(self):
        if self.require_image():
            self.background_draft_active = False
            self.background_apply_pending = False
            self.background_preview = None
            self.mark_draft_active = False
            self.doc.undo()
            self.restore_enhancement_controls()
            self.changed(fit=True)

    def redo(self):
        if self.require_image():
            self.background_draft_active = False
            self.background_apply_pending = False
            self.background_preview = None
            self.mark_draft_active = False
            self.doc.redo()
            self.restore_enhancement_controls()
            self.changed(fit=True)

    def crop_changed(self, rect):
        width = round(rect.right()) - round(rect.left())
        height = round(rect.bottom()) - round(rect.top())
        if hasattr(self, "crop_w") and not rect.isEmpty():
            with QSignalBlocker(self.crop_w), QSignalBlocker(self.crop_h):
                self.crop_w.setMaximum(max(1, int(self.canvas.bounds.width())))
                self.crop_h.setMaximum(max(1, int(self.canvas.bounds.height())))
                self.crop_w.setValue(width)
                self.crop_h.setValue(height)
                self.crop_w.setEnabled(True)
                self.crop_h.setEnabled(True)
        self.update_info()

    def ratio_changed(self, *args):
        mode = self.crop_ratio.currentData()
        preset = isinstance(mode, int)
        self.crop_ratio_fields.setVisible(mode == "custom")
        self.crop_pixel_fields.setVisible(mode == "free")
        self.crop_spec_fields.setVisible(preset)
        self.crop_scaling_fields.setVisible(preset)
        self.crop_scaling_hint.setText(
            (
                "将选区缩放至模板尺寸。"
                if self.crop_allow_resize.isChecked()
                else "按模板像素裁剪，不进行缩放。"
            )
            + "\n放大可能模糊，缩小会损失细节。"
        )
        self.canvas.crop_fixed_size = preset and not self.crop_allow_resize.isChecked()
        self.canvas.portrait_guides = preset
        if preset:
            self.load_preset(mode)
        if not self.doc:
            return
        self.activate_crop()
        if preset:
            self.configure_crop_output()
            self.reset_template_crop()
        else:
            self.crop_output_size = None
            self.invalidate_export()
            ratio = self.ratio_w.value() / self.ratio_h.value() if mode == "custom" else None
            self.canvas.reset_crop(ratio)

    def activate_crop(self):
        self.canvas.set_tool("crop")
        self.update_apply_button()

    def reset_template_crop(self):
        width, height = self.id_w.value(), self.id_h.value()
        self.canvas.reset_crop(width / height)
        if (
            not self.crop_allow_resize.isChecked()
            and width <= self.canvas.bounds.width()
            and height <= self.canvas.bounds.height()
        ):
            self.canvas.set_crop_pixels(width, height)

    def crop_pixels_changed(self, *args):
        if self.doc and self.current_tool == "crop" and self.crop_ratio.currentData() == "free":
            self.activate_crop()
            self.canvas.set_crop_pixels(self.crop_w.value(), self.crop_h.value())

    def apply_crop(self):
        if not self.require_image() or self.canvas.tool != "crop":
            return
        r = self.canvas.crop
        try:
            target = self.crop_output_size if isinstance(self.crop_ratio.currentData(), int) else None
            self.doc.crop(
                (r.left(), r.top(), r.right(), r.bottom()),
                output_size=target,
                allow_resize=self.crop_allow_resize.isChecked(),
            )
        except ValueError as error:
            self.error(str(error))
            return
        self.canvas.crop = self.canvas.bounds.__class__()
        self.changed(fit=True)
        self.canvas.set_tool("hand")
        self.canvas.crop = self.canvas.bounds.__class__(self.canvas.bounds)
        self.canvas.cropChanged.emit(self.canvas.crop)
        self.update_apply_button()
        self.statusBar().showMessage("裁剪已应用 · Ctrl+Z 可撤销")

    def transform(self, angle=0, flip=None):
        if not self.require_image():
            return
        self.doc.transform(angle, flip, self.expand.isChecked())
        self.changed(fit=True)

    def rotation_preview(self, *args):
        self.rotation_generation += 1
        if self.doc and self.current_tool == "rotate":
            self.rotation_timer.start()
        self.update_info()

    def render_rotation_preview(self):
        if self.closing or not self.doc or self.current_tool != "rotate":
            return
        if self.rotation_busy:
            return  # The active worker starts the latest request when it finishes.
        generation, edit_generation = self.rotation_generation, self.edit_generation
        base, marks, settings = self.doc.snapshot(copy_base=False)
        angle, expand, cache = self.angle.value(), self.expand.isChecked(), self.render_cache
        self.rotation_busy = True

        def current(message=""):
            if (
                self.closing
                or generation != self.rotation_generation
                or edit_generation != self.edit_generation
                or self.compare_state is not None
            ):
                raise InterruptedError("旋转预览已过期")

        def operation(progress):
            image = cache.render(base, marks, settings, check_current=current)
            rotated = image.rotate(angle, expand=expand, resample=Image.Resampling.BICUBIC)
            current()
            size = rotated.size
            thumbnail = rotated.copy()
            thumbnail.thumbnail((1600, 1600))
            return thumbnail, size, rotated

        def done(result):
            self.rotation_busy = False
            if (
                not self.closing
                and generation == self.rotation_generation
                and edit_generation == self.edit_generation
                and self.compare_state is None
            ):
                self.mark_preview_generation += 1
                self.rotation_preview_cache = ((edit_generation, angle, expand), result[2])
                self.canvas.set_image(result[0], logical_size=result[1])
                self.update_info()
            resume()

        def resume():
            if (
                not self.closing
                and self.current_tool == "rotate"
                and (generation != self.rotation_generation or edit_generation != self.edit_generation)
            ):
                self.rotation_timer.start()

        def failed(message):
            self.rotation_busy = False
            resume()

        self.start_job(operation, done, error=failed, background=True)

    def apply_rotation(self):
        self.transform(self.angle.value())
        self.angle.blockSignals(True)
        self.angle.setValue(0)
        self.angle.blockSignals(False)
        self.update_info()

    def brush_settings(self, *args):
        mode = self.current_tool
        if mode not in self.brush_controls:
            return
        size, opacity, _ = self.brush_controls[mode]
        self.canvas.brush_size = size.value()
        self.canvas.brush_opacity = opacity.value() / 100
        self.canvas.brush_color = self.brush_color
        self.canvas.set_tool("erase" if mode == "brush" and self.eraser.isChecked() else mode)

    def choose_brush_color(self):
        color = self.choose_color(self.brush_color, "画笔颜色")
        if color.isValid():
            self.brush_color = color.name()
            self.color_button.setText("●  " + color.name().upper())
            self.brush_settings()

    def paint(self, points):
        if not self.require_image():
            return
        size, opacity, block = self.brush_controls[self.current_tool]
        self.doc.checkpoint()
        self.doc.base = paint_stroke(
            self.doc.base,
            points,
            self.canvas.tool,
            size.value(),
            self.brush_color,
            opacity.value() / 100,
            block.value(),
        )
        self.changed()

    def preview_paint(self, points):
        if not self.doc or self.current_tool not in self.brush_controls:
            return
        size, opacity, block = self.brush_controls[self.current_tool]
        self.stroke_info = (
            self.edit_generation,
            tuple(points),
            self.canvas.tool,
            size.value(),
            self.brush_color,
            opacity.value() / 100,
            block.value(),
        )
        # Screen-only stroke previews are bounded; releasing the mouse still commits
        # the original source-pixel stroke. Cache the thumbnail for the whole gesture.
        source = self.doc.base
        if self.stroke_preview_base is None or self.stroke_preview_base[0] is not source:
            thumbnail = source.copy()
            thumbnail.thumbnail((1600, 1600))
            self.stroke_preview_base = source, thumbnail
        thumbnail = self.stroke_preview_base[1]
        scale = thumbnail.width / source.width
        preview = paint_stroke(
            thumbnail,
            [(x * scale, y * scale) for x, y in points],
            self.canvas.tool,
            max(1, round(size.value() * scale)),
            self.brush_color,
            opacity.value() / 100,
            max(1, round(block.value() * scale)),
        )
        self.canvas.photo.setPixmap(pixmap(enhance(preview, self.doc.enhancement)))
        self.canvas.photo.setTransform(
            QTransform.fromScale(source.width / preview.width, source.height / preview.height)
        )
        self.update_info()

    def choose_color(self, current, title, *, watermark=False):
        palette = self.config.custom_colors
        for index in range(QColorDialog.customCount()):
            QColorDialog.setCustomColor(index, QColor(palette[index]))
        color = QColorDialog.getColor(
            QColor(current), self, title, options=QColorDialog.ColorDialogOption.DontUseNativeDialog
        )
        custom = [QColorDialog.customColor(i).name() for i in range(QColorDialog.customCount())]
        selected = color.name() if watermark and color.isValid() else None
        if (
            custom != palette
            or (selected is not None and selected != self.config.watermark_color)
            or "colors" not in self.config.data
        ):
            try:
                self.config.save_colors(custom, watermark_color=selected)
            except ConfigError as error:
                self.error(str(error))
        return color

    def update_mark_color_button(self):
        self.mark_color_button.setText("●  " + self.mark_color.upper())
        self.mark_color_button.setToolTip("选择文字颜色；自定义色槽自动保存到配置文件。")

    def choose_mark_color(self):
        color = self.choose_color(self.mark_color, "水印颜色", watermark=True)
        if color.isValid():
            self.mark_color = color.name()
            self.update_mark_color_button()
            self.watermark_controls_changed()

    def mark_from_controls(self):
        text = self.mark_text.text().strip()
        if not text:
            raise ValueError("请输入水印文字。")
        if len(self.mark_text.text()) > 50:
            raise ValueError("文字超长，不允许超过 50 字。")
        family = self.mark_font.currentFont().family()
        key = (text, family, self.mark_size.value(), self.mark_color)
        if self.mark_bitmap_cache is None or self.mark_bitmap_cache[0] != key:
            self.mark_bitmap_cache = (key, render_text(text, family, self.mark_size.value(), self.mark_color))
        mark = Watermark(
            text=text,
            size=self.mark_size.value(),
            color=self.mark_color,
            opacity=self.mark_opacity.value() / 100,
            angle=self.mark_angle.value(),
            tile=True,
            font=family,
            row_spacing=self.mark_row_spacing.value(),
            column_spacing=self.mark_column_spacing.value(),
            text_bitmap=self.mark_bitmap_cache[1],
        )
        mark.validate_bitmap_size(mark.text_bitmap.size)
        return mark

    def proposed_marks(self, mark):
        if self.mark_multiple.isChecked():
            if len(self.doc.watermarks) >= 10:
                raise ValueError("最多叠加 10 组水印，请先清除或撤销已有水印。")
            return [*self.doc.watermarks, mark]
        return [mark]

    def watermark_controls_changed(self, *args):
        self.mark_length_error.setVisible(len(self.mark_text.text()) > 50)
        self.mark_draft_active = True
        self.refresh_marks()
        self.schedule_mark_preview()
        self.update_info()

    def refresh_marks(self):
        self.mark_multiple.setToolTip("选中后每次应用叠加一组，最多 10 组；不选中则替换已有水印。")
        self.update_apply_button()

    def schedule_mark_preview(self):
        if self.closing:
            return
        self.mark_preview_generation += 1
        if self.doc:
            if self.mark_preview_worker is not None:
                self.mark_preview_pending = True
            elif not self.mark_preview_timer.isActive():
                self.mark_preview_timer.start()

    def _render_mark_preview(self):
        if not self.doc or self.closing or self.compare_state is not None:
            return
        if self.current_tool == "rotate":
            return  # The rotation preview already includes applied watermarks.
        if self.current_tool == "background" and (
            self.background_draft_active
            or (
                self.background_preview is not None
                and self.background_preview[0] == (self.edit_generation, self.background_color)
            )
        ):
            return
        if self.current_tool == "export" and self.preview_result and self.show_encoded_preview.isChecked():
            return
        if self.mark_preview_worker is not None:
            self.mark_preview_pending = True
            return
        generation = self.mark_preview_generation
        marks = list(self.doc.watermarks)
        if self.current_tool == "watermark" and self.mark_live_preview.isChecked() and self.mark_draft_active:
            try:
                marks = self.proposed_marks(self.mark_from_controls())
            except ValueError:
                self.update_info()
        if not marks:
            self.canvas.clear_watermarks()
            return
        size = self.doc.base.size
        worker = Worker(lambda progress: watermark_preview(size, marks))
        self.mark_preview_worker = worker
        self.jobs.add(worker)
        self.preview_jobs.add(worker)

        def done(result):
            if generation == self.mark_preview_generation and self.compare_state is None:
                self.canvas.set_watermark_preview(*result)

        def failed(message):
            if generation == self.mark_preview_generation:
                self.statusBar().showMessage("水印预览失败：" + message)
                self.canvas.clear_watermarks()

        def finished():
            self.finish_job(worker)
            self.mark_preview_worker = None
            if self.mark_preview_pending and not self.closing:
                self.mark_preview_pending = False
                self.mark_preview_timer.start()

        worker.signals.done.connect(done)
        worker.signals.error.connect(failed)
        worker.signals.finished.connect(finished)
        self.pool.start(worker)

    def add_text_mark(self):
        if not self.require_image():
            return
        try:
            marks = self.proposed_marks(self.mark_from_controls())
        except ValueError as error:
            self.error(str(error))
            return
        self.doc.checkpoint()
        self.doc.watermarks = marks
        self.mark_draft_active = False
        self.changed()
        self.statusBar().showMessage("水印已应用 · Ctrl+Z 可撤销")

    def delete_mark(self):
        if self.doc:
            if self.doc.watermarks:
                self.doc.checkpoint()
                self.doc.watermarks = []
            self.mark_draft_active = False
            self.changed()

    def enhancement_parameters(self):
        values = {key: control.value() / 100 for key, control in self.enhance_sliders.items()}
        values.update({key: control.isChecked() for key, control in self.enhance_checks.items()})
        return Enhancement(**values)

    def sync_enhancement_controls(self):
        for key, automatic in (("contrast", "autocontrast"), ("temperature", "white_balance")):
            enabled = not self.enhance_checks[automatic].isChecked()
            self.enhance_sliders[key].setEnabled(enabled)
            self.enhance_value_labels[key].setEnabled(enabled)
            self.enhance_value_labels[key].setText(
                f"{self.enhance_sliders[key].value() / 100:.2f}" if enabled else "—"
            )

    def enhancement_changed(self, *args):
        self.sync_enhancement_controls()
        parameters = self.enhancement_parameters()
        if self.doc and parameters != self.doc.enhancement:
            if not self.enhance_dragging or not self.enhance_gesture_checkpoint:
                self.doc.checkpoint()
                self.enhance_gesture_checkpoint = True
            self.doc.enhancement = parameters
        self.edit_generation += 1
        self.enhancement_image = None
        self.invalidate_export()
        self.schedule_size_measurement()
        if self.doc:
            if parameters == Enhancement():
                self.enhance_timer.stop()
                self.show_image()
            else:
                self.enhance_timer.start()

    def begin_enhancement_gesture(self):
        self.enhance_dragging = True
        self.enhance_gesture_checkpoint = False

    def end_enhancement_gesture(self):
        self.enhance_dragging = False
        self.enhance_gesture_checkpoint = False

    def _enhance_preview(self):
        if not self.doc or self.closing:
            return
        if self.enhance_busy:
            self.enhance_pending = True
            return
        self.enhance_busy = True
        generation = self.edit_generation
        base, _, settings = self.doc.snapshot(copy_base=False)
        cache = self.render_cache

        def check_current():
            if self.closing or generation != self.edit_generation:
                raise InterruptedError("增强预览已取消")

        def done(image):
            self.enhance_busy = False
            if generation == self.edit_generation:
                self.enhancement_image = image
                self.show_image()
            if self.enhance_pending and not self.closing:
                self.enhance_pending = False
                self.enhance_timer.start()

        def failed(message):
            self.enhance_busy = False
            if generation == self.edit_generation and not self.closing:
                self.error(message)
            if self.enhance_pending and not self.closing:
                self.enhance_pending = False
                self.enhance_timer.start()

        self.start_job(
            lambda progress: cache.enhanced(base, settings, check_current),
            done,
            error=failed,
            background=True,
        )

    def reset_enhancement(self):
        self.restore_enhancement_controls(Enhancement())
        self.enhancement_changed()

    def restore_enhancement_controls(self, settings=None):
        settings = settings if settings is not None else self.doc.enhancement
        self.end_enhancement_gesture()
        for key, control in self.enhance_sliders.items():
            control.blockSignals(True)
            control.setValue(round(getattr(settings, key) * 100))
            control.blockSignals(False)
            self.enhance_value_labels[key].setText(f"{control.value() / 100:.2f}")
        for key, control in self.enhance_checks.items():
            control.blockSignals(True)
            control.setChecked(getattr(settings, key))
            control.blockSignals(False)
        self.sync_enhancement_controls()
        self.enhancement_image = None
        self.edit_generation += 1
        if hasattr(self, "enhance_timer"):
            self.enhance_timer.stop()

    def choose_background_color(self):
        color = self.choose_color(self.background_color, "背景色")
        if color.isValid():
            self.set_background_color(color.name())

    def set_background_color(self, color):
        self.background_color = color
        self.background_color_button.setText("选择颜色 · " + color.upper())
        self.background_draft_active = True
        self.background_error = ""
        if self.doc and self.current_tool == "background":
            self.background_timer.start()
        self.update_info()

    def render_background_preview(self):
        if self.closing or not self.doc or self.current_tool != "background":
            return
        if self.background_busy:
            self.background_pending = True
            return
        key = (self.edit_generation, self.background_color)
        base, marks, settings = self.doc.snapshot(copy_base=False)
        cache = RenderCache()  # Drafts must not evict the applied image's full-resolution cache.
        applied_cache = self.render_cache
        known_alpha = self.background_has_transparency if self.background_alpha_base is base else None
        self.background_busy = True
        self.background_pending = False

        def current(message=""):
            if (
                self.closing
                or key != (self.edit_generation, self.background_color)
                or self.current_tool != "background"
            ):
                raise InterruptedError("背景色预览已过期")

        def operation(progress):
            current()
            transparent = (
                known_alpha if known_alpha is not None else base.getchannel("A").getextrema()[0] < 255
            )
            filled = Image.new("RGBA", base.size, key[1]) if transparent else base
            if transparent:
                filled.alpha_composite(base)
            render_cache = cache if transparent else applied_cache
            current()
            rendered = render_cache.render(filled, marks, settings, check_current=current)
            preview = rendered.copy()
            preview.thumbnail((1600, 1600))
            current()
            return key, filled, preview, render_cache, transparent

        def resume():
            if (
                not self.closing
                and self.current_tool == "background"
                and self.background_draft_active
                and (self.background_pending or key != (self.edit_generation, self.background_color))
            ):
                self.background_timer.start()

        def done(result):
            self.background_busy = False
            if not self.closing and key == (self.edit_generation, self.background_color):
                self.background_preview = result
                self.background_alpha_base = base
                self.background_has_transparency = result[4]
                self.background_error = ""
                if self.current_tool == "background":
                    self.show_image()
                    if self.background_apply_pending:
                        self.apply_background()
                self.update_info()
            resume()

        def failed(message):
            self.background_busy = False
            if message == "背景色预览已过期":
                if not self.closing and self.current_tool == "background" and self.background_draft_active:
                    self.background_timer.start()
                return
            if not self.closing and key == (self.edit_generation, self.background_color):
                self.background_error = message
                self.background_apply_pending = False
                self.update_info()
            resume()

        self.start_job(operation, done, error=failed, background=True)

    def apply_background(self):
        if not self.require_image():
            return
        key = (self.edit_generation, self.background_color)
        if self.background_preview is None or self.background_preview[0] != key:
            self.background_apply_pending = True
            self.background_timer.start()
            self.update_info()
            return
        _, filled, preview, cache, transparent = self.background_preview
        self.background_apply_pending = False
        if not transparent:
            self.update_info()
            return
        self.background_draft_active = False
        self.doc.checkpoint()
        self.doc.base = filled
        self.render_cache = cache
        self.export_background = self.background_color
        self.changed()
        self.background_preview = (
            (self.edit_generation, self.background_color),
            filled,
            preview,
            cache,
            False,
        )
        self.background_alpha_base = filled
        self.background_has_transparency = False
        self.background_timer.stop()
        self.background_pending = False
        self.show_image()
        self.update_info()

    def load_preset(self, index):
        if not hasattr(self, "id_w"):
            return
        p = self.presets[index]
        self.id_w.setValue(p["width"])
        self.id_h.setValue(p["height"])

    def apply_preset(self):
        if not self.require_image():
            return
        self.configure_crop_output()
        self.activate_crop()
        self.reset_template_crop()
        self.statusBar().showMessage("规格已设置 · 请确认人像位置，然后应用裁剪")

    def configure_crop_output(self):
        self.crop_output_size = (self.id_w.value(), self.id_h.value())
        self.invalidate_export()

    def save_preset(self):
        mode = self.crop_ratio.currentData()
        size = (self.id_w.value(), self.id_h.value())
        if not isinstance(mode, int) and self.doc and not self.canvas.crop.isEmpty():
            size = (self.crop_w.value(), self.crop_h.value())
        dialog = TemplateDialog(self.config, size, self)
        if dialog.exec() == TemplateDialog.DialogCode.Accepted:
            self.presets = dialog.templates
            self.populate_crop_modes(
                next(i for i, p in enumerate(self.presets) if p["name"] == dialog.template_name)
            )
            self.ratio_changed()
            self.statusBar().showMessage("模板已新增并选中，点击上方「应用」后才会裁剪图片。")
        dialog.deleteLater()

    def output_dimensions(self):
        # Templates change pixels when crop is applied. Compression and saving
        # always use the actual document, including after undo, rotate or reload.
        if self.doc:
            return self.doc.base.size
        return (1, 1)  # Export requires an open image.

    def output_dpi(self):
        value = self.doc.metadata.get("dpi") if self.doc else None
        if isinstance(value, (tuple, list)):
            value = value[0] if value else None
        return round(value) if type(value) in (int, float) and 1 <= value <= 9600 else 300

    def choose_export_background(self):
        color = self.choose_color(self.export_background, "透明区域填充色")
        if color.isValid():
            self.export_background = color.name()
            self.invalidate_export()

    def export_options(self):
        width, height = self.output_dimensions()
        quality = self.out_quality.value() if self.out_format.currentText() in ("JPEG", "WEBP") else 100
        return ExportOptions(
            format=self.out_format.currentText(),
            width=width,
            height=height,
            dpi=self.output_dpi(),
            max_bytes=None,
            quality=quality,
            min_quality=quality,
            allow_quality=False,
            allow_resize=False,
            resampling="Lanczos",
            background=self.export_background,
            keep_alpha=self.keep_alpha.isChecked(),
            keep_exif=self.keep_exif.isChecked(),
            keep_icc=self.keep_icc.isChecked(),
        )

    def file_info_options(self):
        """A fixed reference encoding, independent of every compression control."""
        width, height = self.doc.base.size
        return ExportOptions(
            format=self.doc.metadata["format"],
            width=width,
            height=height,
            dpi=self.output_dpi(),
            quality=95,
            min_quality=95,
            max_bytes=None,
            allow_quality=False,
            allow_resize=False,
            keep_exif=True,
            keep_icc=True,
        )

    def request_save(self):
        if not self.require_image():
            return
        if self.saving:
            self.statusBar().showMessage("正在保存，请稍候…")
            return
        options = self.save_options()
        key = (self.edit_generation, options)
        if self.save_result is not None and self.save_result_key == key:
            self.save_export(self.save_result)
            return
        base, marks, settings = self.doc.snapshot(copy_base=False)
        metadata, cache = dict(self.doc.metadata), self.render_cache
        unchanged = (
            self.applied_export_options is None
            and not self.doc.history
            and not marks
            and settings == Enhancement()
        )
        self.saving = True

        def current(message=""):
            if self.closing or key != (self.edit_generation, self.save_options()):
                raise InterruptedError("已应用的内容已改变，请重新保存。")

        def operation(progress):
            current()
            original = source_result(metadata) if unchanged else None
            if original is not None:
                return original
            image = cache.render(base, marks, settings, check_current=current)
            return compress(image, options, metadata, current)

        def done(result):
            self.saving = False
            if self.closing:
                return
            if key != (self.edit_generation, self.save_options()):
                self.statusBar().showMessage("已应用的内容已改变，请重新保存。")
                return
            self.save_result, self.save_result_key = result, key
            self.save_export(result)

        def failed(message):
            self.saving = False
            if not self.closing:
                self.error(message)

        self.start_job(operation, done, error=failed, message="正在准备已应用的图片…", pool=self.save_pool)

    def save_options(self):
        if self.applied_export_options is None:
            return self.file_info_options()
        return replace(
            self.applied_export_options,
            width=self.doc.base.width,
            height=self.doc.base.height,
            dpi=self.output_dpi(),
        )

    def apply_compression(self):
        self.encode_preview(apply_after=True)

    def commit_compression(self):
        """Commit the measured bytes to the information display without re-encoding pixels."""
        result = self.preview_result
        if result is None or self.preview_key != self.export_generation:
            return
        self.applied_compression = result
        self.applied_compression_generation = self.edit_generation
        self.applied_export_options = self.preview_options
        self.save_result = result
        self.save_result_key = (self.edit_generation, self.applied_export_options)
        self.live_size_generation += 1
        self.live_size_timer.stop()
        self.live_size_pending = False
        self.live_size_error = ""
        self.live_size_result = (len(result.data), result.width, result.height, result.format)
        self.update_info()
        self.statusBar().showMessage("已应用压缩 · 保存将复用完整编码数据")

    def encode_preview(self, *, apply_after=False, automatic=False):
        if self.closing or (automatic and (self.doc is None or self.current_tool != "export")):
            return
        if not self.require_image():
            return
        self.compression_timer.stop()
        self.apply_after_encode |= apply_after
        if self.preview_result is not None and self.preview_key == self.export_generation:
            if self.apply_after_encode:
                self.apply_after_encode = False
                self.commit_compression()
            if self.encoded_preview_image is None:
                self.show_cached_preview()
            else:
                self.show_encoded_preview.setChecked(True)
                self.show_image(fit=True)
            return
        if self.encoding:
            return
        options = self.export_options()
        try:
            options.validate()
        except ValueError as error:
            self.compression_error = str(error)
            self.apply_after_encode = False
            self.update_info()
            if not automatic:
                self.error(str(error))
            return
        generation = self.export_generation
        self.encoding = True
        self.update_apply_button()
        self.compression_error = ""
        self.update_info()
        base, marks, settings = self.doc.snapshot(copy_base=False)
        cache = self.render_cache
        edit_generation = self.edit_generation
        metadata = dict(self.doc.metadata)

        def operation(progress):
            def check_current(message=""):
                if self.closing or generation != self.export_generation:
                    raise InterruptedError("图片或压缩参数已改变")

            image = cache.render(base, marks, settings, check_current=check_current)
            result = compress(image, options, metadata, check_current)
            check_current()
            with Image.open(BytesIO(result.data)) as decoded:
                decoded.thumbnail((1600, 1600))
                preview = decoded.convert("RGBA")
            check_current()
            return result, preview

        def resume_if_stale():
            if self.closing:
                return
            if self.apply_after_encode:
                self.encode_preview()
            elif self.current_tool == "export":
                self.compression_timer.start()

        def done(encoded):
            result, preview = encoded
            self.encoding = False
            self.update_apply_button()
            if self.closing:
                return
            if generation != self.export_generation:
                resume_if_stale()
                return
            should_apply = self.apply_after_encode
            self.apply_after_encode = False
            self.preview_result = result
            self.encoded_preview_image = preview
            self.preview_key = generation
            self.preview_edit_generation = edit_generation
            self.preview_options = options
            self.compression_error = ""
            self.show_encoded_preview.setEnabled(preview is not None)
            if preview is not None:
                self.mark_preview_generation += 1
                self.show_image()
            self.update_info()
            if should_apply:
                self.commit_compression()

        def failed(message):
            self.encoding = False
            self.update_apply_button()
            if self.closing:
                return
            if generation != self.export_generation:
                resume_if_stale()
                return
            requested = self.apply_after_encode
            self.apply_after_encode = False
            if generation == self.export_generation:
                self.compression_error = message
                self.update_info()
                if not automatic or requested:
                    self.error(message)

        self.start_job(operation, done, error=failed, message="正在编码压缩结果…", background=automatic)

    def show_cached_preview(self):
        result = self.preview_result
        self.update_apply_button()

        def operation(progress):
            with Image.open(BytesIO(result.data)) as decoded:
                decoded.thumbnail((1600, 1600))
                return decoded.convert("RGBA")

        def done(preview):
            self.update_apply_button()
            if not self.closing and result is self.preview_result:
                self.encoded_preview_image = preview
                self.show_encoded_preview.setEnabled(True)
                self.show_encoded_preview.setChecked(True)
                self.show_image(fit=True)

        def failed(message):
            self.update_apply_button()
            if not self.closing and result is self.preview_result:
                self.error(message)

        self.start_job(operation, done, error=failed, background=True)

    def save_export(self, result):
        if self.saving:
            return
        extension = EXTENSIONS[result.format]
        name = Path(self.doc.metadata["name"]).stem + f"_photocraft.{extension}"
        path, _ = QFileDialog.getSaveFileName(self, "保存照片", name, f"{result.format} (*.{extension})")
        if not path:
            return
        if Path(path).suffix.lower() not in {
            "." + extension,
            ".jpeg" if extension == "jpg" else "." + extension,
            ".tif" if extension == "tiff" else "." + extension,
        }:
            path += "." + extension
        overwrite = Path(path).exists()
        if (
            overwrite
            and QMessageBox.question(
                self,
                "确认覆盖",
                f"确定覆盖 {Path(path).name}？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        def done(_):
            self.saving = False
            self.statusBar().showMessage(f"已保存并重新读取验证：{path}")

        def failed(message):
            self.saving = False
            self.error(message)

        self.saving = True
        self.start_job(
            lambda progress: save_verified(result, path, overwrite=overwrite),
            done,
            error=failed,
            message="写入并校验磁盘文件…",
            pool=self.save_pool,
        )

    def about(self):
        QMessageBox.about(
            self,
            "关于 PhotoCraft",
            f"PhotoCraft {__version__}\n离线照片工作台 · Linux / Windows\n\n"
            "支持裁剪、像素编辑、水印、增强与约束压缩。\n规格合规仅指编码参数，不代表报名审核通过。\n"
            "当前版本不提供 Android 安装包及自动人像抠图。\n\n基于 Qt for Python、Pillow 和 NumPy。",
        )

    def window_state(self):
        rect = self.normalGeometry() if self.isMaximized() else self.geometry()
        return {
            "width": rect.width(),
            "height": rect.height(),
            "x": rect.x(),
            "y": rect.y(),
            "maximized": self.isMaximized(),
        }

    def restore_window_state(self):
        state = self.config.window
        if state:
            self.resize(
                max(self.minimumWidth(), min(state.get("width", self.width()), 10000)),
                max(self.minimumHeight(), min(state.get("height", self.height()), 10000)),
            )
            if "x" in state and "y" in state:
                self.move(state["x"], state["y"])
                if not any(
                    screen.availableGeometry().intersects(self.geometry())
                    for screen in QApplication.screens()
                ):
                    self.move(self.screen().availableGeometry().topLeft())
            if state.get("maximized", False):
                self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def closeEvent(self, event):
        if self.jobs - self.preview_jobs:
            QMessageBox.information(self, "处理仍在进行", "请等待当前处理完成后再关闭，以确保文件完整写入。")
            event.ignore()
            return
        if not self.confirm_discard():
            event.ignore()
            return
        try:
            self.config.save_window(self.window_state())
        except ConfigError as error:
            self.error(str(error))
        self.mark_preview_timer.stop()
        self.enhance_timer.stop()
        self.live_size_timer.stop()
        self.compression_timer.stop()
        self.rotation_timer.stop()
        self.background_timer.stop()
        self.preview_info_controller.close()
        self.closing = True
        self.edit_generation += 1
        self.mark_preview_generation += 1
        self.live_size_generation += 1
        event.accept()
