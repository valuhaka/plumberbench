"""Render the current view to a JPEG: MuJoCo for the 3D scene, Pillow for tags.

OpenGL backend: on Linux, EGL (headless, works on CPU through Mesa) unless
MUJOCO_GL is already set. On macOS MuJoCo picks CGL by itself and on Windows
WGL, so nothing is set there. One GL renderer is kept per view; between frames only the shapes' positions, sizes and colours
change, so a frame costs one scene compile and one draw.

The status line is stamped into the top of every image, so an agent can tell
a fresh frame from a stale one. Frames are JPEG.

`render` also returns hotspots: the box of every tag label drawn on the
picture. They carry nothing that is not visible in the picture itself; the
browser play page uses them to make the labels clickable.
"""
from __future__ import annotations

import io
import math
import os
import platform
from concurrent.futures import ThreadPoolExecutor


def default_gl(system: str) -> str | None:
    """The MUJOCO_GL value to use when none is set, or None to let MuJoCo choose."""
    return "egl" if system == "Linux" else None


if "MUJOCO_GL" not in os.environ and default_gl(platform.system()):
    os.environ["MUJOCO_GL"] = default_gl(platform.system())

import mujoco  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from .scene import Scene, build  # noqa: E402
from .world import State  # noqa: E402

WIDTH, HEIGHT = 800, 600
_cache: dict[str, tuple] = {}


def _fmt(v) -> str:
    return " ".join(f"{x:.5g}" for x in v)


def _look_at(pos, target) -> str:
    p, t = np.array(pos, float), np.array(target, float)
    f = t - p
    f /= np.linalg.norm(f)
    x = np.cross(f, [0.0, 0.0, 1.0])
    x /= np.linalg.norm(x)
    y = np.cross(x, f)
    return _fmt([*x, *y])


def to_xml(sc: Scene) -> str:
    rows = []
    for g in sc.shapes:
        attrs = [f'name="{g.name}"', f'type="{g.type}"', f'rgba="{_fmt(g.rgba)}"', f'size="{_fmt(g.size)}"']
        if g.fromto is not None:
            attrs.append(f'fromto="{_fmt(g.fromto)}"')
        else:
            attrs.append(f'pos="{_fmt(g.pos)}"')
        if g.quat is not None:
            attrs.append(f'quat="{_fmt(g.quat)}"')
        rows.append(f"    <geom {' '.join(attrs)} contype=\"0\" conaffinity=\"0\"/>")
    # The scene's size is stated, not measured: hidden shapes are parked far below
    # the floor, and a measured extent would push the near clipping plane out to
    # about half a metre and blank every close-up.
    return f"""<mujoco>
  <statistic extent="3" center="0 0 0.8"/>
  <visual>
    <global offwidth="{WIDTH}" offheight="{HEIGHT}"/>
    <headlight ambient="0.38 0.38 0.38" diffuse="0.55 0.55 0.55" specular="0.1 0.1 0.1"/>
    <quality shadowsize="2048"/>
  </visual>
  <worldbody>
    <light pos="0.4 -1.2 2.2" dir="-0.15 0.5 -1" diffuse="0.55 0.55 0.55" castshadow="true"/>
    <camera name="view" pos="{_fmt(sc.camera_pos)}" xyaxes="{_look_at(sc.camera_pos, sc.camera_target)}" fovy="{sc.fovy}"/>
{chr(10).join(rows)}
  </worldbody>
</mujoco>"""


_COPY = ("geom_pos", "geom_quat", "geom_size", "geom_rgba", "geom_rbound", "geom_aabb",
         "cam_pos", "cam_quat", "cam_fovy")
JPEG_QUALITY = 85


def _renderer_for(sc: Scene, model_now: mujoco.MjModel):
    entry = _cache.get(sc.key)
    if entry is None or entry[0].ngeom != model_now.ngeom:
        if entry is not None:
            entry[2].close()
        data = mujoco.MjData(model_now)
        entry = (model_now, data, mujoco.Renderer(model_now, height=HEIGHT, width=WIDTH))
        _cache[sc.key] = entry
        return entry
    model, data, renderer = entry
    for name in _COPY:
        if hasattr(model, name):
            getattr(model, name)[:] = getattr(model_now, name)
    return entry


def _project(model, data, point) -> tuple[float, float, float]:
    cam = 0
    pos = data.cam_xpos[cam]
    rot = data.cam_xmat[cam].reshape(3, 3)  # columns are the camera's x, y, z axes
    d = np.asarray(point) - pos
    xc, yc, zc = d @ rot[:, 0], d @ rot[:, 1], d @ rot[:, 2]
    depth = -zc
    f = (HEIGHT / 2) / math.tan(math.radians(model.cam_fovy[cam]) / 2)
    return WIDTH / 2 + f * xc / depth, HEIGHT / 2 - f * yc / depth, depth


def _font(size: int):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",   # Debian, Ubuntu
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",            # Fedora
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf",      # macOS
                 "/Library/Fonts/Arial Bold.ttf",
                 "C:/Windows/Fonts/arialbd.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


_OFFSETS = [(34, -30), (-34, -30), (34, 30), (-34, 30), (52, 0), (-52, 0), (0, -40), (0, 40),
            (60, -45), (-60, -45), (60, 45), (-60, 45)]


def _labels(img: Image.Image, placed: list[tuple[str, float, float]]) -> list[dict]:
    draw = ImageDraw.Draw(img)
    font = _font(17)
    boxes: list[tuple[float, float, float, float]] = []
    anchors = [(u, v) for _, u, v in placed]

    def clashes(b):
        if b[0] < 2 or b[1] < 34 or b[2] > WIDTH - 2 or b[3] > HEIGHT - 2:
            return True
        if any(not (b[2] < o[0] or b[0] > o[2] or b[3] < o[1] or b[1] > o[3]) for o in boxes):
            return True
        return any(b[0] - 3 < u < b[2] + 3 and b[1] - 3 < v < b[3] + 3 for u, v in anchors)

    for tag, u, v in sorted(placed, key=lambda t: (t[2], t[1])):
        w = draw.textlength(tag, font=font) + 10
        h = 22
        choice = None
        for dx, dy in _OFFSETS:
            cx, cy = u + dx, v + dy
            b = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if not clashes(b):
                choice = b
                break
        if choice is None:
            cx, cy = u + _OFFSETS[0][0], v + _OFFSETS[0][1]
            choice = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        boxes.append(choice)
        mid = ((choice[0] + choice[2]) / 2, (choice[1] + choice[3]) / 2)
        draw.line([mid, (u, v)], fill=(20, 20, 20), width=2)
        draw.ellipse([u - 3.5, v - 3.5, u + 3.5, v + 3.5], fill=(255, 210, 0), outline=(20, 20, 20))
        draw.rounded_rectangle(choice, radius=5, fill=(255, 250, 225), outline=(20, 20, 20), width=2)
        draw.text((choice[0] + 5, choice[1] + 2), tag, fill=(10, 10, 10), font=font)
    return [{"tag": tag, "box": [round(b[0]), round(b[1]), round(b[2]), round(b[3])]}
            for (tag, _, _), b in zip(sorted(placed, key=lambda t: (t[2], t[1])), boxes)]


def _notes(img: Image.Image, model, data, sc: Scene) -> None:
    draw = ImageDraw.Draw(img)
    font = _font(13)
    for text, point in sc.notes.items():
        u, v, depth = _project(model, data, point)
        if depth > 0:
            draw.text((u, v - 8), text, fill=(15, 15, 15), font=font, stroke_width=2,
                      stroke_fill=(245, 245, 245))


def _stamp(img: Image.Image, s: State, focus: str | None) -> None:
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, WIDTH, 30], fill=(20, 22, 28))
    line = (f"step {s.step} | time {s.tick}/{s.budget} | damage {s.damage} | "
            f"{s.room} / {s.view.replace('_', ' ')}" + (f" | close-up {focus}" if focus else ""))
    draw.text((10, 5), line, fill=(255, 255, 255), font=_font(17))


# A GL context can be current on only one thread at a time, and servers may call
# from any thread. All GL work therefore runs on this one thread.
_gl_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="plumberbench-gl")


def render_array(s: State, focus: str | None = None) -> tuple[np.ndarray, list[dict]]:
    """Pixels of the current view (or a close-up of `focus`) and the label hotspots."""
    return _gl_thread.submit(_render_array, s, focus).result()


def _render_array(s: State, focus: str | None) -> tuple[np.ndarray, list[dict]]:
    sc = build(s, focus)
    model_now = mujoco.MjModel.from_xml_string(to_xml(sc))
    model, data, renderer = _renderer_for(sc, model_now)
    mujoco.mj_forward(model, data)
    renderer.update_scene(data, camera="view")
    frame = renderer.render()
    img = Image.fromarray(frame)
    placed = []
    for tag, point in sc.anchors.items():
        u, v, depth = _project(model, data, point)
        if depth > 0 and 0 <= u < WIDTH and 30 <= v < HEIGHT:
            placed.append((tag, u, v))
    _notes(img, model, data, sc)
    hotspots = _labels(img, placed)
    _stamp(img, s, focus)
    return np.asarray(img), hotspots


def encode(pixels: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="JPEG", quality=JPEG_QUALITY, subsampling=0)
    return buf.getvalue()


def render(s: State, focus: str | None = None) -> tuple[bytes, list[dict]]:
    """JPEG of the current view (or a close-up of `focus`) and the label hotspots."""
    pixels, hotspots = render_array(s, focus)
    return encode(pixels), hotspots
