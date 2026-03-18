"""
agents/instagram/reels_renderer.py

Renders a Reels script JSON into a real MP4 video:
  1. Each scene (on_screen_text or script lines) → 1080x1920 PNG via Playwright
  2. ffmpeg stitches scenes with xfade transitions → .mp4 (~25s)
  3. Returns Path to .mp4 or None on failure

Requirements:
  - playwright (pip install playwright && playwright install chromium)
  - ffmpeg (brew install ffmpeg)

Usage:
    from agents.instagram.reels_renderer import render_reel
    mp4_path = render_reel(reel_json, output_dir)
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

BLUE  = "#5b4dff"
MINT  = "#2dd4bf"
DARK  = "#0f172a"
WHITE = "#ffffff"

_SCENE_BG     = [DARK, "#1a1040", "#0f2044", "#060d1a"]
_SCENE_ACCENT = [MINT, BLUE, MINT, BLUE]

_FONT = (
    "<link href='https://fonts.googleapis.com/css2?family=Inter:"
    "wght@400;600;700;800;900&display=swap' rel='stylesheet'>"
)


def _fs(text: str) -> str:
    words = len(text.split())
    if words <= 4:   return "96px"
    if words <= 7:   return "78px"
    if words <= 10:  return "64px"
    return "52px"


def _scene_html(text: str, idx: int, total: int, hook: str = "") -> str:
    bg     = _SCENE_BG[idx % len(_SCENE_BG)]
    accent = _SCENE_ACCENT[idx % len(_SCENE_ACCENT)]
    is_last = idx == total - 1

    hook_html = ""
    if idx == 0 and hook:
        hook_html = (
            f"<div style='position:absolute;top:130px;left:0;right:0;text-align:center;"
            f"font-family:Inter,sans-serif;font-size:22px;font-weight:600;"
            f"color:rgba(255,255,255,.45);letter-spacing:.07em;text-transform:uppercase;"
            f"padding:0 80px;'>{hook[:70]}</div>"
        )

    cta_html = ""
    if is_last:
        cta_html = (
            f"<div style='margin-top:44px;display:inline-block;"
            f"background:{MINT};color:{DARK};"
            f"padding:18px 52px;border-radius:999px;"
            f"font-family:Inter,sans-serif;font-size:24px;font-weight:800;"
            f"letter-spacing:-.01em;'>improveyoursite.com</div>"
        )

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">{_FONT}
<style>*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1920px;overflow:hidden;background:{bg};position:relative}}</style>
</head><body>
{hook_html}
<div style="position:absolute;top:0;left:0;width:6px;height:100%;background:{accent};"></div>
<div style="position:absolute;top:60px;right:72px;font-family:Inter,sans-serif;font-size:18px;
  font-weight:600;color:rgba(255,255,255,.28);letter-spacing:.05em;">{idx+1}&thinsp;/&thinsp;{total}</div>
<div style="position:absolute;top:0;left:0;right:0;bottom:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;padding:140px 80px;text-align:center;">
  <p style="font-family:Inter,sans-serif;font-size:{_fs(text)};font-weight:900;
     color:{WHITE};line-height:1.1;letter-spacing:-.03em;">{text}</p>
  {cta_html}
</div>
<div style="position:absolute;bottom:64px;left:0;right:0;text-align:center;
  display:flex;align-items:center;justify-content:space-between;padding:0 72px;">
  <span style="font-family:Inter,sans-serif;font-size:20px;font-weight:800;
    color:rgba(255,255,255,.38);">Improve<span style="color:{MINT};">YourSite</span></span>
  <span style="font-family:Inter,sans-serif;font-size:16px;font-weight:500;
    color:rgba(255,255,255,.22);">@improveyoursite.au</span>
</div>
</body></html>"""


def _ffmpeg_exe() -> str | None:
    """Return path to ffmpeg binary — system install or imageio-ffmpeg fallback."""
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def render_reel(reel: dict, output_dir: Path) -> Path | None:
    """
    Render reel script dict → MP4.
    Returns Path to .mp4 or None if Playwright/ffmpeg unavailable.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    today      = date.today().isoformat()
    title_slug = re.sub(r"[^\w]", "_", reel.get("title", "reel").lower())[:20]
    mp4_path   = output_dir / f"reel_{today}_{title_slug}.mp4"

    on_screen = reel.get("on_screen_text", [])
    script    = reel.get("script", [])
    hook      = reel.get("hook", "")

    # Build 4 scene texts: prefer on_screen_text, fall back to script lines
    scenes = []
    for i in range(4):
        if i < len(on_screen) and on_screen[i]:
            scenes.append(str(on_screen[i])[:100])
        elif i < len(script):
            text = re.sub(r"Scene \d+:\s*\[\d+[-–]\d+s\]\s*", "", str(script[i])).strip()
            scenes.append(text[:100])
    if not scenes:
        return None

    SCENE_DUR = 6.0
    FADE_DUR  = 0.8

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pngs = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for i, text in enumerate(scenes):
                html = _scene_html(text, i, len(scenes), hook if i == 0 else "")
                page = browser.new_page(viewport={"width": 1080, "height": 1920})
                page.set_content(html)
                page.wait_for_timeout(900)
                p = tmp_dir / f"scene_{i:02d}.png"
                page.screenshot(path=str(p), clip={"x": 0, "y": 0, "width": 1080, "height": 1920})
                page.close()
                pngs.append(str(p))
            browser.close()

        if not pngs:
            return None

        n = len(pngs)

        # Build ffmpeg args
        ff_inputs = []
        for p in pngs:
            ff_inputs += ["-loop", "1", "-t", str(SCENE_DUR + FADE_DUR), "-i", p]

        if n == 1:
            filter_str = "[0:v]scale=1080:1920,fps=30[outv]"
        else:
            parts = []
            prev   = "[0:v]"
            offset = SCENE_DUR - FADE_DUR
            for j in range(1, n):
                out = "[outv]" if j == n - 1 else f"[v{j}]"
                parts.append(
                    f"{prev}[{j}:v]xfade=transition=fade:"
                    f"duration={FADE_DUR}:offset={offset}{out}"
                )
                prev    = f"[v{j}]"
                offset += SCENE_DUR - FADE_DUR
            filter_str = ";".join(parts)

        cmd = (
            [ffmpeg]
            + ff_inputs
            + [
                "-filter_complex", filter_str,
                "-map", "[outv]",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-y",
                str(mp4_path),
            ]
        )
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            return None

    return mp4_path if mp4_path.exists() else None
