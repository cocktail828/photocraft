"""Self-hosted HTTP API and bundled browser UI. No third-party image service is used."""

import argparse
import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import Config
from .web_editor import EXTENSIONS, MIMES, Conflict, Editors, demo_bytes
from .web_fonts import fonts
from .web_models import Apply, Operation, Revision

ROOT = Path(__file__).resolve().parent
MAX_UPLOAD = int(os.environ.get("PHOTOCRAFT_MAX_UPLOAD_MB", "40")) * 1024 * 1024


def create_app(config_dir=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.config = Config(config_dir)
        for issue in app.state.config.errors:
            logging.getLogger("uvicorn.error").warning("Service configuration: %s", issue)
        app.state.editors = Editors()
        app.state.config_lock = threading.RLock()

        async def cleanup():
            while True:
                await asyncio.sleep(60)
                await run_in_threadpool(app.state.editors.purge)

        task = asyncio.create_task(cleanup())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            app.state.editors.items.clear()

    app = FastAPI(title="PhotoCraft", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def headers(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            if urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "不允许来自其他站点的修改请求。"}, status_code=403)
        if (
            request.headers.get("content-length", "").isdigit()
            and int(request.headers["content-length"]) > MAX_UPLOAD
        ):
            return JSONResponse({"detail": "上传文件超过服务允许的大小。"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409 if isinstance(error, Conflict) else 422)

    @app.exception_handler(ValidationError)
    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        details = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()]
        return JSONResponse({"detail": "参数无效：" + "；".join(details)}, status_code=422)

    @app.exception_handler(UnidentifiedImageError)
    @app.exception_handler(Image.DecompressionBombError)
    @app.exception_handler(OSError)
    async def image_error(request, error):
        return JSONResponse(
            {"detail": "无法读取图片，请选择有效的 JPG、PNG、WEBP、BMP 或 TIFF。"}, status_code=422
        )

    def editor(sid):
        try:
            return app.state.editors.get(sid)
        except KeyError as error:
            raise HTTPException(404, error.args[0]) from error

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/bootstrap")
    def bootstrap():
        config = app.state.config
        with app.state.config_lock:
            return dict(
                version=__version__,
                templates=config.templates,
                theme=config.theme,
                colors=config.custom_colors,
                watermark_color=config.watermark_color,
                fonts=[dict(id=f["id"], name=f["name"]) for f in fonts()],
                max_upload_mb=MAX_UPLOAD // 1024 // 1024,
            )

    @app.post("/api/sessions", status_code=201)
    async def upload(request: Request):
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD:
                raise HTTPException(413, "上传文件超过服务允许的大小。")
            chunks.append(chunk)
        name = unquote(request.headers.get("x-filename", "照片.png"))
        name = name.replace("\\", "/").split("/")[-1].replace("\x00", "")[:200] or "照片.png"
        return await run_in_threadpool(app.state.editors.add, b"".join(chunks), name)

    @app.post("/api/demo", status_code=201)
    def demo():
        return app.state.editors.add(demo_bytes(), "工作台演示.jpg")

    @app.get("/api/sessions/{sid}")
    def status(sid: str):
        item = editor(sid)
        with item.lock:
            return item.describe()

    @app.post("/api/sessions/{sid}/close")
    def close(sid: str):
        app.state.editors.remove(sid)
        return {"closed": True}

    @app.post("/api/sessions/{sid}/preview")
    def preview(sid: str, body: Operation):
        return editor(sid).preview(body)

    @app.post("/api/sessions/{sid}/apply")
    def apply(sid: str, body: Apply):
        return editor(sid).apply(body)

    @app.post("/api/sessions/{sid}/undo")
    def undo(sid: str, body: Revision):
        return editor(sid).travel(body.revision)

    @app.post("/api/sessions/{sid}/redo")
    def redo(sid: str, body: Revision):
        return editor(sid).travel(body.revision, redo=True)

    @app.get("/api/sessions/{sid}/image")
    def image(sid: str):
        return Response(editor(sid).current.image(), media_type="image/webp")

    @app.get("/api/sessions/{sid}/original")
    def original(sid: str):
        return Response(editor(sid).source.image(), media_type="image/webp")

    @app.get("/api/sessions/{sid}/previews/{pid}")
    def preview_image(sid: str, pid: str):
        item = editor(sid)
        with item.lock:
            entry = item.previews.get(pid)
            if entry is None:
                raise HTTPException(404, "预览已过期。")
            return Response(entry.image(), media_type="image/webp")

    @app.get("/api/sessions/{sid}/download")
    def download(sid: str):
        # Snapshot an immutable entry: drafts neither delay saving nor enter downloaded bytes.
        item = editor(sid)
        entry, revision = item.applied
        stem = Path(item.metadata["name"]).stem
        name = f"{stem}-edited.{EXTENSIONS[entry.encoded.format]}"
        return Response(
            entry.encoded.data,
            media_type=MIMES[entry.encoded.format],
            headers={
                "Content-Disposition": f"attachment; filename=photocraft.{EXTENSIONS[entry.encoded.format]}; filename*=UTF-8''{quote(name)}",
                "X-PhotoCraft-Revision": str(revision),
            },
        )

    app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")
    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")

    @app.get("/")
    def home():
        return FileResponse(ROOT / "web/index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()


def main():
    parser = argparse.ArgumentParser(description="PhotoCraft Web 图片工作台")
    parser.add_argument("--host", default=os.environ.get("PHOTOCRAFT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    uvicorn.run("photocraft.web_server:app", host=args.host, port=args.port, workers=1, limit_concurrency=32)


if __name__ == "__main__":
    main()
