PhotoCraft 项目代码与原创 Logo、图标、演示图遵循根目录 [LICENSE](LICENSE)。第三方组件保留各自的版权与许可。

Web 运行依赖和版本列于 `requirements-lock.txt`：

| 组件 | 上游源码与许可 |
| --- | --- |
| FastAPI | [FastAPI](https://github.com/fastapi/fastapi) |
| Starlette | [Starlette](https://github.com/Kludex/starlette) |
| Uvicorn | [Uvicorn](https://github.com/encode/uvicorn) |
| Pydantic / pydantic-core | [Pydantic](https://github.com/pydantic/pydantic) |
| Pillow 及编解码组件 | [Pillow](https://github.com/python-pillow/Pillow) |
| NumPy 及内含数学库 | [NumPy](https://github.com/numpy/numpy) |

Docker 镜像通过系统软件包安装 Fontconfig、DejaVu 与 Noto CJK 字体，许可与版权记录保留在镜像内的 `/usr/share/doc/`。镜像没有捆绑商业字体、外部人物照片或 AI 模型；演示照片是项目代码绘制的插图。

前端无运行时第三方 JavaScript 框架或 CDN 资源。Playwright 仅用于开发和 CI 浏览器检查，不属于镜像运行依赖。

历史桌面入口可选依赖 Qt / PySide6 / Shiboken6 与 PyInstaller，其源码和许可见 [Qt for Python](https://code.qt.io/cgit/pyside/pyside-setup.git/)、[Qt 许可](https://doc.qt.io/qt-6/licensing.html)、[PyInstaller](https://github.com/pyinstaller/pyinstaller)。Web 镜像不安装这些组件。
