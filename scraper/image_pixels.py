"""Type-safe, runtime-safe pixel readers for the image pipeline.

Pillow types `Image.load()` as optional, and a pixel may be a single number
(palette / greyscale image) or an RGB(A) tuple. Plain `r, g, b = px[x, y]`
is therefore both a static error and a latent crash on a non-RGB file.
These helpers narrow both cases in one place; every caller converts to RGB
first, so the tuple branch is the normal one and the scalar branch is only a
defensive fallback.
"""

from __future__ import annotations

from typing import Any


def load_pixels(image: Any) -> Any:
    """`image.load()`, raising instead of returning None.

    Callers already run inside a try/except that treats an unreadable file as
    "no measurement", so raising here keeps that behaviour.
    """
    pixels = image.load()
    if pixels is None:
        raise ValueError("image has no pixel data")
    return pixels


def rgb_of(pixel: Any) -> tuple[int, int, int]:
    """One pixel as an (r, g, b) triple."""
    if isinstance(pixel, (tuple, list)):
        values = [int(channel) for channel in pixel[:3]]
        if len(values) < 3:
            # Greyscale ("L") and grey+alpha ("LA") files land here.
            return values[0], values[0], values[0]
        return values[0], values[1], values[2]
    value = int(pixel)
    return value, value, value


def rgb_at(pixels: Any, x: int, y: int) -> tuple[int, int, int]:
    """The (r, g, b) triple at (x, y) of a `load_pixels()` result."""
    return rgb_of(pixels[x, y])
