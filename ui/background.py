"""Optional user-chosen background image (needs Pillow). The choice is remembered between runs."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

CONFIG = Path.home() / ".tv-debloat" / "config.json"


def load_path() -> str:
    try:
        p = json.loads(CONFIG.read_text(encoding="utf-8")).get("background", "")
        return p if p and Path(p).is_file() else ""
    except Exception:
        return ""


def _update(**values) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if CONFIG.exists():
            data = json.loads(CONFIG.read_text(encoding="utf-8"))
        data.update(values)
        CONFIG.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def save_path(path: str) -> None:
    _update(background=path)


def load_look() -> tuple[float, float]:
    """(darken, blur): darken 1.0 = original brightness; blur 0 = sharp."""
    try:
        d = json.loads(CONFIG.read_text(encoding="utf-8"))
        return float(d.get("darken", 0.4)), float(d.get("blur", 2.0))
    except Exception:
        return 0.4, 2.0


def save_look(darken: float, blur: float) -> None:
    _update(darken=round(darken, 2), blur=round(blur, 1))


def render(path, width: int, height: int, darken: float = 0.4, blur: float = 2.0):
    """Cover-fit the image to width x height, soften and darken it so the text stays readable."""
    from PIL import Image, ImageEnhance, ImageFilter

    img = path if hasattr(path, "convert") else Image.open(path)
    img = img.convert("RGB")
    scale = max(width / img.width, height / img.height)
    img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    left, top = (img.width - width) // 2, (img.height - height) // 2
    img = img.crop((left, top, left + width, top + height))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return ImageEnhance.Brightness(img).enhance(darken)


def to_tk_data(img) -> str:
    """Base64 PNG for tk.PhotoImage(data=...) (no ImageTk needed)."""
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
