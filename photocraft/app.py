import ctypes
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTimer, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from . import __version__
from .icons import logo


def main():
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PhotoCraft.Desktop")
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoCraft")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("PhotoCraft")
    app.setDesktopFileName("photocraft")
    app.setWindowIcon(logo())
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(["Noto Sans CJK SC", "Microsoft YaHei UI", "Segoe UI", "sans-serif"])
    font.setPointSize(10)
    app.setFont(font)
    translator = QTranslator(app)
    if translator.load(
        QLocale("zh_CN"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    ):
        app.installTranslator(translator)
    from .window import MainWindow

    window = MainWindow()
    window.show()
    if "--smoke-test" in sys.argv:

        def smoke():
            try:
                import tempfile

                from PySide6.QtCore import QEventLoop

                from .compression import save_verified

                window.load_demo()
                window.apply_preset()
                window.apply_button.click()
                assert window.doc.base.size == (window.id_w.value(), window.id_h.value())
                assert window.output_dimensions() == window.doc.base.size
                window.enhance_sliders["brightness"].setValue(115)
                assert window.doc.enhancement.brightness == 1.15
                window.select_tool("watermark")
                window.apply_button.click()
                assert window.doc.watermarks[0].tile
                assert window.doc.watermarks[0].text_bitmap is not None
                window.select_tool("export")
                rendered = window.render_cache.render(*window.doc.snapshot(copy_base=False))
                loop = QEventLoop()
                poll = QTimer()
                poll.setInterval(20)

                def preview_ready():
                    if window.preview_result is not None and not window.jobs:
                        loop.quit()

                poll.timeout.connect(preview_ready)
                deadline = QTimer()
                deadline.setSingleShot(True)
                deadline.timeout.connect(loop.quit)
                poll.start()
                deadline.start(30000)
                loop.exec()
                poll.stop()
                deadline.stop()
                result = window.preview_result
                assert result is not None, "实时压缩预览未完成"
                original_info = window.filename.toolTip()
                window.apply_button.click()
                assert window.applied_compression is result
                assert window.save_result is result
                assert window.save_options() == window.preview_options
                assert window.live_size_result == (
                    len(result.data),
                    result.width,
                    result.height,
                    result.format,
                )
                assert window.filename.toolTip() == original_info
                assert f"{result.width} × {result.height} px" in window.modified_info.text()
                assert "有损" in window.preview_info.text()
                assert window.render_cache.render(*window.doc.snapshot(copy_base=False)) is rendered
                assert window.enhance_sliders["brightness"].value() == 115
                assert window.menu_actions["save_image"].shortcut().toString() == "Ctrl+S"
                assert "export_image" not in window.menu_actions
                assert window.tool_buttons["export"].text() == "图像压缩"
                assert window.tool_buttons["background"].text() == "背景色"
                assert not window.tool_buttons["background"].icon().isNull()
                assert not hasattr(window, "limit_size") and not hasattr(window, "out_kb")
                assert window.show_encoded_preview.parentWidget() is window.panels.currentWidget().widget()
                assert not hasattr(window, "out_w") and not hasattr(window, "export_source")
                assert not window.export_options().allow_resize
                assert window.export_options().max_bytes is None
                assert not window.export_options().allow_quality
                assert result.quality == window.out_quality.value()
                assert {"预览", "当前"} <= {item.text() for item in window.info.findChildren(QLabel)}
                assert sum(item.text() == "应用" for item in window.findChildren(QPushButton)) == 1
                assert window.version_label.text() == __version__
                assert window.file_info_options().max_bytes is None
                assert window.file_info_options().format == window.doc.metadata["format"]
                assert (
                    window.file_info_options().width,
                    window.file_info_options().height,
                ) == window.doc.base.size
                with tempfile.TemporaryDirectory() as directory:
                    save_verified(window.save_result, Path(directory) / "smoke.jpg")
                assert not window.windowIcon().isNull()
                screenshot = os.environ.get("PHOTOCRAFT_SMOKE_SCREENSHOT")
                if screenshot:
                    app.processEvents()
                    if not window.grab().save(screenshot):
                        raise OSError("无法保存程序界面截图。")
                report = os.environ.get("PHOTOCRAFT_SMOKE_REPORT")
                if report:
                    Path(report).write_text("PHOTOCRAFT_SMOKE_OK", encoding="utf-8")
                if sys.stdout is not None:
                    print("PHOTOCRAFT_SMOKE_OK", flush=True)
                app.exit(0)
            except Exception:
                import traceback

                traceback.print_exc()
                app.exit(1)

        QTimer.singleShot(100, smoke)
    elif len(sys.argv) > 1:
        window.open_path(sys.argv[1])
    sys.exit(app.exec())
