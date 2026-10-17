PhotoCraft 原创代码、Logo 与界面图标采用根目录 MIT License。
依赖组件保留各自版权与许可，不因打包而变更许可。安装包的 `licenses/` 目录包含构建环境中发行包提供的许可原文。

| 组件 | 上游许可与源码 |
| --- | --- |
| PySide6 Essentials / Shiboken6 / Qt | LGPL-3.0 / GPL-3.0 / commercial，见 [Qt for Python](https://code.qt.io/cgit/pyside/pyside-setup.git/) 与 [Qt 许可](https://doc.qt.io/qt-6/licensing.html) |
| Pillow 及其编解码库 | [Pillow 源码与许可](https://github.com/python-pillow/Pillow) |
| NumPy | [BSD-3-Clause 及内含第三方库声明](https://github.com/numpy/numpy) |
| PyInstaller 引导程序 | [GPL-2.0 with bootloader exception](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt) |

应用使用单目录动态链接形式分发 Qt，Qt 与 Python 扩展位于 `_internal/`。没有将 Qt 静态链接到 PhotoCraft。替换库时需使用与冻结程序 Python / ABI / Qt 版本相容的构建。
Qt 源码可从 https://download.qt.io/official_releases/qt/ 获取，对应版本记录在 requirements-lock.txt。
未捆绑商用字体、AI 模型或外部照片；中文显示使用操作系统字体，演示图由项目代码绘制。
