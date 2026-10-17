"""Reuse full-resolution edit results across canvas, file information and saving."""

from copy import copy
from threading import RLock

from .core import Enhancement, compose, enhance


class RenderCache:
    """One enhanced base and applied/draft composites, shared by concurrent workers.

    Inputs and returned images are read-only. Document edits replace their base
    image; history still owns independent copies. The lock also joins simultaneous
    requests so an enhancement already being computed is not computed twice.
    """

    def __init__(self):
        self._lock = RLock()
        self._base = None
        self._settings = None
        self._enhanced = None
        self._composites = {}

    def enhanced(self, base, settings, check_current=None):
        with self._lock:
            if check_current:
                check_current()
            if base is not self._base or settings != self._settings:
                image = base if settings == Enhancement() else enhance(base, settings)
                if check_current:
                    check_current()
                self._base, self._settings = base, copy(settings)
                self._enhanced = image
                self._composites.clear()
            return self._enhanced

    def render(self, base, marks, settings, *, draft=False, check_current=None):
        with self._lock:
            image = self.enhanced(base, settings, check_current)
            if not marks:
                return image
            key = tuple(
                tuple(
                    (name, id(value) if name == "text_bitmap" else value)
                    for name, value in vars(mark).items()
                )
                for mark in marks
            )
            for entry in tuple(self._composites.values()):
                if entry[0] == key:
                    # Applying an unchanged draft promotes its full-resolution result.
                    self._composites[draft] = entry
                    return entry[2]
            rendered = compose(image, marks)
            if check_current:
                check_current()
            # Retain the marks' bitmaps as well, so their identity cannot be reused.
            self._composites[draft] = (key, [copy(mark) for mark in marks], rendered)
            return rendered
