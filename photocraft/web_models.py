"""Bounded inputs for the browser editor; no UI or desktop dependencies."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Coordinate = Annotated[float, Field(ge=0, le=30000, allow_inf_nan=False)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Crop(Input):
    box: tuple[Coordinate, Coordinate, Coordinate, Coordinate]
    size: tuple[int, int] | None = None
    allow_resize: bool = False


class Rotate(Input):
    angle: float = Field(default=0, ge=-180, le=180)
    flip: Literal["horizontal", "vertical", "both"] | None = None
    expand: bool = True


class Stroke(Input):
    points: list[tuple[Coordinate, Coordinate]] = Field(min_length=1, max_length=5000)
    size: int = Field(default=30, ge=1, le=100)
    color: Color = "#ffffff"
    opacity: float = Field(default=1, ge=0, le=1)
    block: int = Field(default=12, ge=2, le=100)
    erase: bool = False


class Mark(Input):
    text: str = Field(min_length=1, max_length=50)
    font: str = Field(default="", max_length=100)
    size: int = Field(default=28, ge=4, le=200)
    color: Color = "#64748b"
    opacity: float = Field(default=0.28, ge=0, le=1)
    angle: float = Field(default=30, ge=-180, le=180)
    row_spacing: int = Field(default=60, ge=0, le=500)
    column_spacing: int = Field(default=80, ge=0, le=500)
    multiple: bool = False

    @field_validator("text")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("请输入水印文字。")
        return value


class Enhance(Input):
    brightness: float = Field(default=1, ge=0.1, le=3)
    contrast: float = Field(default=1, ge=0.1, le=3)
    saturation: float = Field(default=1, ge=0, le=3)
    sharpness: float = Field(default=1, ge=0, le=5)
    temperature: float = Field(default=0, ge=-1, le=1)
    gamma: float = Field(default=1, ge=0.1, le=3)
    autocontrast: bool = False
    white_balance: bool = False
    denoise: float = Field(default=0, ge=0, le=1)
    equalize: float = Field(default=0, ge=0, le=1)


class Compression(Input):
    format: Literal["JPEG", "PNG", "WEBP", "BMP", "TIFF"] = "JPEG"
    quality: int = Field(default=95, ge=1, le=100)
    keep_alpha: bool = True
    keep_exif: bool = False
    keep_icc: bool = True
    background: Color = "#ffffff"


class Operation(Input):
    revision: int = Field(ge=0)
    tool: Literal[
        "crop",
        "rotate",
        "brush",
        "mosaic",
        "blur",
        "watermark",
        "enhance",
        "compress",
        "clear_watermarks",
    ]
    params: dict = Field(default_factory=dict)


class Apply(Input):
    revision: int = Field(ge=0)
    preview_id: str = Field(min_length=16, max_length=64)
    gesture: str = Field(default="", max_length=64)


class Revision(Input):
    revision: int = Field(ge=0)


class RemoveStrokes(Revision):
    all: bool = False


PARAMETERS = {
    "clear_watermarks": Input,
    "crop": Crop,
    "rotate": Rotate,
    "brush": Stroke,
    "mosaic": Stroke,
    "blur": Stroke,
    "watermark": Mark,
    "enhance": Enhance,
    "compress": Compression,
}
