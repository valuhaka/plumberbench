"""Call show_number five times and read the fifth picture by template matching.

Usage: read_number.py <mcp url> <answer file>
"""
import asyncio
import base64
import io
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from mcp.client.session import ClientSession

try:
    from mcp.client.streamable_http import streamablehttp_client  # older mcp
except ImportError:
    from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

ORIGIN, SIZE, CANVAS = (52, 80), 80, (480, 240)


def font(size: int):
    """The font the smoke server draws with: DejaVu Sans Bold if installed, else Pillow's own.

    Both have digits of equal width, which `read` relies on.
    """
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def glyph(text: str) -> np.ndarray:
    img = Image.new("L", CANVAS, 255)
    ImageDraw.Draw(img).text(ORIGIN, text, fill=0, font=font(SIZE))
    return np.asarray(img, dtype=np.int16)


def read(png: bytes) -> str:
    """Pick, position by position, the digit whose rendering best matches the picture."""
    seen = np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=np.int16)
    width = ImageDraw.Draw(Image.new("L", (1, 1))).textlength("0", font=font(SIZE))
    out = ""
    for k in range(6):
        x0 = int(ORIGIN[0] + k * width)
        x1 = int(ORIGIN[0] + (k + 1) * width)
        crop = seen[:, x0:x1]
        best = min("0123456789", key=lambda d: np.abs(glyph(out + d)[:, x0:x1] - crop).sum())
        out += best
    return out


async def main(url: str, answer: str) -> None:
    async with streamablehttp_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            last = None
            for _ in range(5):
                result = await session.call_tool("show_number", {})
                last = [c for c in result.content if getattr(c, "type", "") == "image"][-1]
    number = read(base64.b64decode(last.data))
    with open(answer, "w") as f:
        f.write(number + "\n")
    print("fifth number:", number)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
