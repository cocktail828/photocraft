"""Optional extensions can implement this protocol; no AI runtime is imported by the app."""

from typing import Protocol

from PIL import Image


class ImagePlugin(Protocol):
    name: str

    def process(self, image: Image.Image, progress) -> Image.Image: ...
