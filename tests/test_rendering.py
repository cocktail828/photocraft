from concurrent.futures import ThreadPoolExecutor
from copy import copy
from threading import Event

from PIL import Image

from photocraft import rendering
from photocraft.core import Document, Enhancement, Watermark, compose, enhance
from photocraft.rendering import RenderCache


def test_render_cache_reuses_enhancement_and_promotes_applied_watermark_draft(noise, monkeypatch):
    calls = {"enhance": 0, "compose": 0}

    def counted_enhance(*args):
        calls["enhance"] += 1
        return enhance(*args)

    def counted_compose(*args):
        calls["compose"] += 1
        return compose(*args)

    monkeypatch.setattr(rendering, "enhance", counted_enhance)
    monkeypatch.setattr(rendering, "compose", counted_compose)
    cache, settings = RenderCache(), Enhancement(brightness=1.2)
    marks = [Watermark(text="TEST", size=14)]
    enhanced = cache.enhanced(noise, settings)
    draft = cache.render(noise, marks, settings, draft=True)
    applied = cache.render(noise, [copy(mark) for mark in marks], copy(settings))
    assert applied is draft and cache.enhanced(noise, settings) is enhanced
    assert applied.tobytes() == compose(enhance(noise, settings), marks).tobytes()
    assert calls == {"enhance": 1, "compose": 1}
    changed_draft = [Watermark(text="NEW", size=14)]
    cache.render(noise, changed_draft, settings, draft=True)
    assert cache.render(noise, marks, settings) is applied
    assert calls == {"enhance": 1, "compose": 2}
    changed = Enhancement(brightness=1.4)
    fresh = cache.render(noise, marks, changed)
    assert fresh.tobytes() == compose(enhance(noise, changed), marks).tobytes()
    assert calls == {"enhance": 2, "compose": 3}
    replacement = Image.new("RGBA", noise.size, "red")
    assert (
        cache.render(replacement, marks, changed).tobytes()
        == compose(enhance(replacement, changed), marks).tobytes()
    )
    assert calls == {"enhance": 3, "compose": 4}


def test_concurrent_render_requests_compute_the_same_operations_only_once(noise, monkeypatch):
    started, release, waiting = Event(), Event(), Event()
    calls = []

    def slow_enhance(*args):
        calls.append(True)
        started.set()
        assert release.wait(5)
        return enhance(*args)

    monkeypatch.setattr(rendering, "enhance", slow_enhance)
    cache, settings = RenderCache(), Enhancement(contrast=1.3)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cache.enhanced, noise, settings)
        assert started.wait(5)

        def render():
            waiting.set()
            return cache.render(noise, [], settings)

        second = executor.submit(render)
        assert waiting.wait(5)
        release.set()
        assert first.result(timeout=5) is second.result(timeout=5)
    assert calls == [True]


def test_borrowed_render_snapshot_survives_edits_and_history_keeps_separate_pixels(noise):
    doc = Document(noise, {})
    base, marks, settings = doc.snapshot(copy_base=False)
    pixels = base.tobytes()
    assert base is doc.base
    doc.crop((10, 20, 70, 90))
    assert base.tobytes() == pixels and base is not doc.base
    assert not marks and settings == Enhancement()
    assert doc.history[0][0] is not base
    doc.undo()
    assert doc.base.tobytes() == pixels
