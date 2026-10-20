import sys
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photocraft.web_server import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "config")) as result:
        yield result


def photo(client, *, transparent=True):
    image = Image.effect_noise((400, 560), 60).convert("RGBA")
    if transparent:
        image.putalpha(100)
    data = BytesIO()
    image.save(data, "PNG")
    result = client.post(
        "/api/sessions", content=data.getvalue(), headers={"X-Filename": "%E7%85%A7%E7%89%87.png"}
    )
    assert result.status_code == 201, result.text
    return result.json(), data.getvalue()


def preview(client, session, tool, params):
    result = client.post(
        f"/api/sessions/{session['id']}/preview",
        json={
            "revision": session["revision"],
            "tool": tool,
            "params": params,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def apply(client, session, entry, gesture=""):
    result = client.post(
        f"/api/sessions/{session['id']}/apply",
        json={
            "revision": session["revision"],
            "preview_id": entry["preview_id"],
            "gesture": gesture,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_web_assets_and_health_need_no_qt(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/assets/logo.svg").status_code == 200
    assert client.get("/api/health").json()["status"] == "ok"
    assert "PySide6" not in sys.modules
    data = client.get("/api/bootstrap").json()
    assert len(data["templates"]) == 4 and "version" in data


def test_crop_preview_apply_download_and_history_share_exact_results(client):
    session, original = photo(client)
    route = f"/api/sessions/{session['id']}"
    entry = preview(client, session, "crop", {"box": [20, 30, 315, 443], "size": [295, 413]})
    assert entry["info"]["width"] == 295 and entry["info"]["height"] == 413
    assert client.get(route + "/download").content == original
    applied = apply(client, session, entry)
    encoded = client.get(route + "/download")
    assert len(encoded.content) == entry["info"]["bytes"]
    assert "filename*=UTF-8''" in encoded.headers["Content-Disposition"]
    with Image.open(BytesIO(encoded.content)) as image:
        assert image.size == (295, 413)
    undone = client.post(route + "/undo", json={"revision": applied["revision"]}).json()
    assert client.get(route + "/download").content == original
    client.post(route + "/redo", json={"revision": undone["revision"]})
    assert client.get(route + "/download").content == encoded.content


def test_scaling_requires_permission_and_invalid_crop_preserves_current(client):
    session, original = photo(client)
    entry = preview(client, session, "crop", {"box": [0, 0, 295, 413], "size": [295, 413]})
    session = apply(client, session, entry)
    route = f"/api/sessions/{session['id']}"
    current = client.get(route + "/download").content
    result = client.post(
        route + "/preview",
        json={
            "revision": session["revision"],
            "tool": "crop",
            "params": {
                "box": [0, 0, 295, 413],
                "size": [413, 579],
            },
        },
    )
    assert result.status_code == 422 and "允许缩放" in result.text
    assert client.get(route + "/download").content == current != original
    entry = preview(
        client, session, "crop", {"box": [0, 0, 295, 413], "size": [413, 579], "allow_resize": True}
    )
    session = apply(client, session, entry)
    assert (session["current"]["width"], session["current"]["height"]) == (413, 579)


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "BMP", "TIFF"])
def test_compression_uses_exact_cached_bytes_and_does_not_resize(client, monkeypatch, fmt):
    from photocraft import web_editor

    session, original = photo(client, transparent=False)
    entry = preview(client, session, "compress", {"format": fmt, "quality": 45})
    route = f"/api/sessions/{session['id']}"
    assert client.get(route + "/download").content == original

    def forbidden(*args, **kwargs):
        pytest.fail("An existing encoded preview must not be recomputed for apply/download")

    monkeypatch.setattr(web_editor, "compress", forbidden)
    assert preview(client, session, "compress", {"format": fmt, "quality": 45}) == entry
    session = apply(client, session, entry)
    result = client.get(route + "/download")
    assert len(result.content) == entry["info"]["bytes"]
    assert entry["info"]["lossy"] == (fmt in ("JPEG", "WEBP"))
    with Image.open(BytesIO(result.content)) as image:
        assert image.size == (400, 560) and image.format == fmt


def test_removed_background_tool_is_rejected(client):
    session, _ = photo(client)
    response = client.post(
        f"/api/sessions/{session['id']}/preview",
        json={"revision": 0, "tool": "background", "params": {"color": "#ff0000"}},
    )
    assert response.status_code == 422


def test_enhancement_is_absolute_and_gesture_is_one_undo_step(client):
    session, original = photo(client)
    for brightness in (1.1, 1.2, 1.4):
        entry = preview(client, session, "enhance", {"brightness": brightness})
        session = apply(client, session, entry, "one-slider-drag")
    assert session["enhancement"]["brightness"] == 1.4
    editor = client.app.state.editors.get(session["id"])
    assert len(editor.history) == 1
    session = client.post(
        f"/api/sessions/{session['id']}/undo", json={"revision": session["revision"]}
    ).json()
    assert client.get(f"/api/sessions/{session['id']}/download").content == original


@pytest.mark.parametrize("flip", ["horizontal", "vertical", "both"])
def test_rotate_preserves_full_frame_and_combines_flips(client, flip):
    from PIL import ImageOps

    session, _ = photo(client)
    editor = client.app.state.editors.get(session["id"])
    source = editor.current.state.base.copy()
    expected = source.rotate(23, expand=True, resample=Image.Resampling.BICUBIC)
    if flip in ("horizontal", "both"):
        expected = ImageOps.mirror(expected)
    if flip in ("vertical", "both"):
        expected = ImageOps.flip(expected)
    updated = apply(client, session, preview(client, session, "rotate", {"angle": 23, "flip": flip}))
    assert (updated["current"]["width"], updated["current"]["height"]) == expected.size
    assert editor.current.state.base.tobytes() == expected.tobytes()


def test_stale_preview_is_rejected_and_other_sessions_stay_unchanged(client):
    session, _ = photo(client)
    other, original = photo(client)
    entry = preview(client, session, "rotate", {"angle": 90})
    updated = apply(client, session, entry)
    assert updated["current"]["width"] == 560
    assert (
        client.post(
            f"/api/sessions/{session['id']}/apply", json={"revision": 0, "preview_id": entry["preview_id"]}
        ).status_code
        == 409
    )
    assert client.get(f"/api/sessions/{other['id']}/download").content == original
    assert client.get("/api/sessions/unknown").status_code == 404


def test_watermark_text_limit_and_undoable_clear(client):
    session, _ = photo(client)
    route = f"/api/sessions/{session['id']}"
    assert (
        client.post(
            route + "/preview", json={"revision": 0, "tool": "watermark", "params": {"text": "x" * 51}}
        ).status_code
        == 422
    )
    entry = preview(client, session, "watermark", {"text": "测试水印", "angle": 30})
    session = apply(client, session, entry)
    marked = client.get(route + "/download").content
    assert len(client.app.state.editors.get(session["id"]).current.state.marks) == 1
    session = apply(client, session, preview(client, session, "clear_watermarks", {}))
    assert not client.app.state.editors.get(session["id"]).current.state.marks
    client.post(route + "/undo", json={"revision": session["revision"]})
    assert client.get(route + "/download").content == marked


def test_cloud_configuration_routes_are_absent_and_cannot_modify_service(client):
    session, original = photo(client)
    config = client.app.state.config
    initial = config.path.read_bytes()
    for method, route, payload in [
        ("get", "/api/config", None),
        ("put", "/api/config", b"[crop]\ntemplates=[]\n"),
        ("post", "/api/config/reset", b"{}"),
        ("post", "/api/templates", b'{"name":"New","width":320,"height":480}'),
        ("put", "/api/preferences", b'{"watermark_color":"#ff0000"}'),
    ]:
        result = client.request(method.upper(), route, content=payload)
        assert result.status_code == 404
    assert config.path.read_bytes() == initial
    assert client.get(f"/api/sessions/{session['id']}/download").content == original
    html = client.get("/").text
    assert 'class="menus"' not in html
    for removed in ("config-dialog", "template-dialog", "new-template"):
        assert removed not in html


def test_administrator_templates_and_palette_are_read_only_public_defaults(tmp_path):
    folder = tmp_path / "config"
    folder.mkdir()
    path = folder / "PhotoCraft.conf"
    path.write_text('[crop]\ntemplates=[]\n[colors]\ncustom=["#123456"]\n', encoding="utf-8")
    original = path.read_bytes()
    with TestClient(create_app(folder)) as client:
        bootstrap = client.get("/api/bootstrap").json()
        assert bootstrap["templates"] == []
        assert len(bootstrap["colors"]) == 16 and bootstrap["colors"][0] == "#123456"
        assert "config_errors" not in bootstrap
        assert client.post("/api/demo").status_code == 201
    assert path.read_bytes() == original


def test_upload_limits_invalid_data_and_session_close(client, monkeypatch):
    from photocraft import web_server

    assert client.post("/api/sessions", content=b"not an image").status_code == 422
    monkeypatch.setattr(web_server, "MAX_UPLOAD", 32)
    assert client.post("/api/sessions", content=b"x" * 33).status_code == 413
    monkeypatch.setattr(web_server, "MAX_UPLOAD", 40 * 1024 * 1024)
    session, _ = photo(client)
    client.post(f"/api/sessions/{session['id']}/close")
    assert client.get(f"/api/sessions/{session['id']}").status_code == 404


@pytest.mark.parametrize("tool", ["brush", "erase", "mosaic", "blur"])
def test_brush_effects_apply_and_undo_without_leaking_drafts(client, tool):
    session, original = photo(client)
    params = {"points": [[100, 100], [150, 150]], "size": 30, "color": "#ff0000", "erase": tool == "erase"}
    entry = preview(client, session, "brush" if tool == "erase" else tool, params)
    route = f"/api/sessions/{session['id']}"
    assert client.get(route + "/download").content == original
    session = apply(client, session, entry)
    assert client.get(route + "/download").content != original
    client.post(route + "/undo", json={"revision": session["revision"]})
    assert client.get(route + "/download").content == original


def test_session_expiry_capacity_and_cross_site_changes(client):
    store = client.app.state.editors
    store.limit = 1
    session, _ = photo(client)
    assert client.post("/api/demo").status_code == 409
    store.items[session["id"]].touched -= store.ttl + 1
    assert client.get(f"/api/sessions/{session['id']}").status_code == 404
    assert client.post("/api/demo", headers={"Origin": "https://unrelated.invalid"}).status_code == 403
    assert client.post("/api/demo").status_code == 201


def test_invalid_persistent_config_uses_defaults_and_logs_for_administrator(tmp_path, caplog):
    folder = tmp_path / "config"
    folder.mkdir()
    path = folder / "PhotoCraft.conf"
    path.write_text("broken = [", encoding="utf-8")
    with TestClient(create_app(folder)) as client:
        bootstrap = client.get("/api/bootstrap").json()
        assert len(bootstrap["templates"]) == 4
        assert "config_errors" not in bootstrap
        assert client.get("/api/config").status_code == 404
        assert "Service configuration:" in caplog.text
    assert path.read_text(encoding="utf-8") == "broken = ["


def test_remove_marks_click_hold_redo_and_other_edit_boundary(client):
    session, _ = photo(client)
    session = apply(client, session, preview(client, session, "crop", {"box": [0, 0, 300, 420]}))
    editor = client.app.state.editors.get(session["id"])
    cropped = editor.current
    snapshots = []
    for color in ("#ff0000", "#00ff00", "#0000ff"):
        session = apply(client, session, preview(client, session, "brush", {"points": [[20, 20]], "color": color}))
        snapshots.append(editor.current)
    route = f"/api/sessions/{session['id']}"
    assert session["can_remove_marks"]
    response = client.post(route + "/remove-strokes", json={"revision": session["revision"], "all": False})
    assert response.status_code == 200
    session = response.json()
    assert editor.current is snapshots[1]
    response = client.post(route + "/remove-strokes", json={"revision": session["revision"], "all": True})
    assert response.status_code == 200
    session = response.json()
    assert editor.current is cropped and not session["can_remove_marks"]
    assert session["current"]["width"] == 300
    # Every retained stroke can still be redone after removing the group.
    session = client.post(route + "/redo", json={"revision": session["revision"]}).json()
    assert editor.current is snapshots[0]
    session = client.post(route + "/redo", json={"revision": session["revision"]}).json()
    assert editor.current is snapshots[1]
    session = apply(client, session, preview(client, session, "enhance", {"brightness": 1.2}))
    assert not session["can_remove_marks"]
    revision = session["revision"]
    session = client.post(route + "/remove-strokes", json={"revision": revision, "all": True}).json()
    assert session["revision"] == revision and session["enhancement"]["brightness"] == 1.2
    assert client.post(route + "/remove-strokes", json={"revision": revision - 1, "all": True}).status_code == 409


def test_remove_all_marks_retains_origin_when_history_is_trimmed(client, monkeypatch):
    monkeypatch.setenv("PHOTOCRAFT_HISTORY_MB", "0")
    session, original = photo(client)
    editor = client.app.state.editors.get(session["id"])
    for tool in ("brush", "mosaic", "blur", "brush"):
        session = apply(client, session, preview(client, session, tool, {"points": [[20, 20], [40, 40]]}))
    assert len(editor.history) == 1
    route = f"/api/sessions/{session['id']}"
    response = client.post(route + "/remove-strokes", json={"revision": session["revision"], "all": True})
    assert response.status_code == 200
    assert editor.current is editor.source
    assert client.get(route + "/download").content == original


def test_clipboard_full_resolution_excludes_draft(client):
    session, original = photo(client)
    preview(client, session, "rotate", {"angle": 90, "expand": True})
    result = client.get(f"/api/sessions/{session['id']}/clipboard")
    assert result.status_code == 200
    assert result.headers["content-type"] == "image/png"
    assert int(result.headers["X-PhotoCraft-Revision"]) == session["revision"]
    with Image.open(BytesIO(result.content)) as copied, Image.open(BytesIO(original)) as source:
        assert copied.size == source.size
        assert copied.convert("RGBA").tobytes() == source.convert("RGBA").tobytes()
