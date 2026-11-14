"""Smoke test: every call shows a new random six-digit number, only as a picture.

Each number shown is appended to /var/smoke/shown.json, which the verifier
reads after the run.
"""
import io
import json
import os
import secrets
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from PIL import Image as PILImage, ImageDraw, ImageFont
from starlette.requests import Request
from starlette.responses import PlainTextResponse

LOG = Path(os.environ.get("SMOKE_LOG_DIR", "/var/smoke"))
LOG.mkdir(parents=True, exist_ok=True)
shown: list[str] = []
mcp = FastMCP("smoke")


def font(size: int):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def picture(number: str, call: int) -> bytes:
    img = PILImage.new("RGB", (480, 240), (250, 248, 240))
    draw = ImageDraw.Draw(img)
    draw.text((20, 14), f"call {call}", fill=(90, 90, 90), font=font(22))
    draw.text((52, 80), number, fill=(15, 15, 15), font=font(80))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@mcp.tool
def show_number():
    """Show a new six-digit number. The number is only in the picture."""
    number = f"{secrets.randbelow(900000) + 100000}"
    shown.append(number)
    (LOG / "shown.json").write_text(json.dumps(shown))
    return [f"Call {len(shown)}: the number is in the attached picture.",
            Image(data=picture(number, len(shown)), format="png")]


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request):
    return PlainTextResponse("ok")


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
            path="/mcp")
