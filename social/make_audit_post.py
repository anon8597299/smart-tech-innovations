#!/usr/bin/env python3
"""
make_audit_post.py — Free audit outreach carousel (5 slides).
Output: ~/Documents/ImproveYourSite - Social Media/Tiles/

Usage:
    python3 social/make_audit_post.py
"""

import tempfile
from datetime import date
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Run: pip3 install playwright && playwright install chromium")
    import sys; sys.exit(1)

OUT   = Path.home() / "Documents" / "ImproveYourSite - Social Media" / "Tiles"
TODAY = date.today().strftime("%Y-%m-%d")

BLUE  = "#5b4dff"
MINT  = "#2dd4bf"
DARK  = "#0f172a"
WHITE = "#ffffff"
OFF   = "#f8f7ff"
MUTED = "#64748b"
FONT  = ("<link href='https://fonts.googleapis.com/css2?family=Inter:"
         "wght@400;500;600;700;800;900&display=swap' rel='stylesheet'>")


def brand_bar(on_dark=False):
    name_c = "rgba(255,255,255,.5)" if on_dark else MUTED
    dot_c  = MINT                   if on_dark else BLUE
    url_c  = "rgba(255,255,255,.3)" if on_dark else "rgba(0,0,0,.2)"
    return (
        f"<div style='position:absolute;bottom:48px;left:88px;right:88px;"
        f"display:flex;align-items:center;justify-content:space-between;z-index:10;'>"
        f"<span style='font-size:30px;font-weight:800;color:{name_c};'>"
        f"Improve<span style='color:{dot_c};'>YourSite</span></span>"
        f"<span style='font-size:26px;font-weight:500;color:{url_c};'>"
        f"improveyoursite.com</span>"
        f"</div>"
    )


def wrap(content, bg=WHITE):
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{bg};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 140px;'>"
        f"{content}"
        f"</div></body></html>"
    )


# ── Slides ────────────────────────────────────────────────────────────────────

def slide_01():
    """White cover — hook statement"""
    content = (
        # Glow accents
        f"<div style='position:absolute;top:-80px;right:-60px;width:480px;height:480px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(91,77,255,.1) 0%,transparent 65%);'></div>"
        f"<div style='position:absolute;bottom:-100px;left:-60px;width:420px;height:420px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(45,212,191,.08) 0%,transparent 65%);'></div>"

        # Eyebrow
        f"<div style='position:relative;z-index:1;display:flex;flex-direction:column;"
        f"align-items:center;text-align:center;'>"
        f"<div style='display:inline-block;background:rgba(45,212,191,.12);"
        f"border:1px solid rgba(45,212,191,.3);border-radius:100px;"
        f"padding:14px 36px;margin-bottom:44px;'>"
        f"<span style='font-size:24px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{MINT};'>Free for local businesses</span>"
        f"</div>"

        # Headline
        f"<p style='font-size:68px;font-weight:900;line-height:1.05;letter-spacing:-.04em;"
        f"color:rgba(15,23,42,.35);margin:0 0 6px;'>Having a website</p>"
        f"<p style='font-size:80px;font-weight:900;line-height:1.0;letter-spacing:-.05em;"
        f"color:{DARK};margin:0 0 48px;'>isn&rsquo;t enough anymore.</p>"

        f"<div style='width:68px;height:5px;background:{MINT};border-radius:4px;"
        f"margin:0 auto 44px;'></div>"

        f"<p style='font-size:44px;font-weight:600;line-height:1.45;"
        f"color:{MUTED};margin:0;'>Swipe to see what&rsquo;s holding yours back.</p>"
        f"</div>"

        + brand_bar(on_dark=False)
    )
    return wrap(content, WHITE)


def slide_02():
    """Indigo — Google scores your site right now"""
    content = (
        f"<div style='position:absolute;top:-80px;right:-60px;width:480px;height:480px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(45,212,191,.15) 0%,transparent 65%);'></div>"

        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(255,255,255,.15);"
        f"border:1px solid rgba(255,255,255,.25);border-radius:100px;"
        f"padding:14px 36px;margin-bottom:40px;'>"
        f"<span style='font-size:24px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{WHITE};'>Right now</span>"
        f"</div>"

        f"<p style='font-size:72px;font-weight:900;line-height:1.0;letter-spacing:-.04em;"
        f"color:rgba(255,255,255,.5);margin:0 0 6px;'>Google is scoring</p>"
        f"<p style='font-size:88px;font-weight:900;line-height:1.0;letter-spacing:-.05em;"
        f"color:{WHITE};margin:0 0 48px;'>your website.</p>"

        f"<div style='width:68px;height:5px;background:{MINT};border-radius:4px;margin-bottom:40px;'></div>"

        f"<p style='font-size:44px;font-weight:500;line-height:1.55;"
        f"color:rgba(255,255,255,.65);margin:0;'>"
        f"Speed. Mobile. User experience.<br>"
        f"A score below 50 means Google is actively<br>"
        f"pushing you down in search results.</p>"
        f"</div>"

        + brand_bar(on_dark=True)
    )
    return wrap(content, BLUE)


def slide_03():
    """White — 3 things a free audit covers"""
    checks = [
        "Your live Google performance score",
        "What&rsquo;s holding your rankings back",
        "Exactly what to fix — and in what order",
    ]
    bullets = "".join(
        f"<div style='display:flex;align-items:flex-start;gap:20px;margin-bottom:22px;'>"
        f"<span style='flex-shrink:0;margin-top:8px;width:16px;height:16px;"
        f"border-radius:50%;background:{MINT};'></span>"
        f"<span style='font-size:40px;font-weight:600;line-height:1.35;"
        f"color:{DARK};'>{item}</span>"
        f"</div>"
        for item in checks
    )
    content = (
        f"<div style='position:absolute;top:0;left:0;width:6px;height:100%;background:{MINT};'></div>"

        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(91,77,255,.1);"
        f"border:1px solid rgba(91,77,255,.2);border-radius:100px;"
        f"padding:14px 36px;margin-bottom:40px;'>"
        f"<span style='font-size:24px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{BLUE};'>Your free audit includes</span>"
        f"</div>"

        f"<p style='font-size:80px;font-weight:900;line-height:1.0;letter-spacing:-.04em;"
        f"color:{DARK};margin:0 0 44px;'>Here&rsquo;s what<br>you&rsquo;ll get.</p>"

        f"{bullets}"
        f"</div>"

        + brand_bar(on_dark=False)
    )
    return wrap(content, WHITE)


def slide_04():
    """Indigo — why your competitors are ahead"""
    content = (
        f"<div style='position:absolute;bottom:-100px;left:-60px;width:460px;height:460px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(45,212,191,.12) 0%,transparent 65%);'></div>"

        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(255,255,255,.15);"
        f"border:1px solid rgba(255,255,255,.25);border-radius:100px;"
        f"padding:14px 36px;margin-bottom:40px;'>"
        f"<span style='font-size:24px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{WHITE};'>The hard truth</span>"
        f"</div>"

        f"<p style='font-size:72px;font-weight:900;line-height:1.0;letter-spacing:-.04em;"
        f"color:rgba(255,255,255,.5);margin:0 0 6px;'>Your competitors</p>"
        f"<p style='font-size:88px;font-weight:900;line-height:1.0;letter-spacing:-.05em;"
        f"color:{WHITE};margin:0 0 48px;'>are not waiting.</p>"

        f"<div style='width:68px;height:5px;background:{MINT};border-radius:4px;margin-bottom:40px;'></div>"

        f"<p style='font-size:44px;font-weight:500;line-height:1.55;"
        f"color:rgba(255,255,255,.65);margin:0;'>"
        f"Every month your site sits stale, someone<br>"
        f"in your area is moving up Google.<br><br>"
        f"<span style='color:{WHITE};font-weight:700;'>"
        f"A 30-minute audit changes that.</span></p>"
        f"</div>"

        + brand_bar(on_dark=True)
    )
    return wrap(content, BLUE)


def slide_05():
    """White CTA — DM us AUDIT"""
    content = (
        f"<div style='position:absolute;top:-80px;right:-60px;width:480px;height:480px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(91,77,255,.08) 0%,transparent 65%);'></div>"
        f"<div style='position:absolute;bottom:-80px;left:-60px;width:420px;height:420px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(45,212,191,.07) 0%,transparent 65%);'></div>"

        f"<div style='position:relative;z-index:1;display:flex;flex-direction:column;"
        f"align-items:center;text-align:center;'>"

        f"<div style='display:inline-block;background:rgba(45,212,191,.12);"
        f"border:1px solid rgba(45,212,191,.3);border-radius:100px;"
        f"padding:14px 36px;margin-bottom:44px;'>"
        f"<span style='font-size:24px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{MINT};'>Free. No obligation.</span>"
        f"</div>"

        f"<p style='font-size:68px;font-weight:900;line-height:1.05;letter-spacing:-.04em;"
        f"color:rgba(15,23,42,.35);margin:0 0 6px;'>Ready to find out</p>"
        f"<p style='font-size:80px;font-weight:900;line-height:1.0;letter-spacing:-.05em;"
        f"color:{DARK};margin:0 0 48px;'>what&rsquo;s holding you back?</p>"

        f"<div style='width:68px;height:5px;background:{MINT};border-radius:4px;"
        f"margin:0 auto 44px;'></div>"

        f"<div style='background:{BLUE};padding:28px 56px;border-radius:16px;'>"
        f"<span style='font-size:40px;font-weight:900;color:{WHITE};letter-spacing:-.02em;'>"
        f"DM us &ldquo;AUDIT&rdquo; &rarr;</span>"
        f"</div>"
        f"<p style='font-size:32px;font-weight:500;color:{MUTED};margin-top:24px;'>"
        f"Takes 30 minutes. Completely free.</p>"
        f"</div>"

        + brand_bar(on_dark=False)
    )
    return wrap(content, WHITE)


SLIDES = [
    (f"{TODAY}-audit-slide-1.png", slide_01()),
    (f"{TODAY}-audit-slide-2.png", slide_02()),
    (f"{TODAY}-audit-slide-3.png", slide_03()),
    (f"{TODAY}-audit-slide-4.png", slide_04()),
    (f"{TODAY}-audit-slide-5.png", slide_05()),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"\nGenerating {len(SLIDES)} slides → {OUT}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page(viewport={"width": 1080, "height": 1080})

        for filename, html in SLIDES:
            with tempfile.NamedTemporaryFile(
                suffix=".html", mode="w", delete=False, encoding="utf-8"
            ) as f:
                f.write(html)
                tmp = Path(f.name)

            out = OUT / filename
            page.goto(f"file://{tmp}", wait_until="networkidle")
            page.wait_for_timeout(600)
            page.query_selector("body > div").screenshot(path=str(out), type="png")
            tmp.unlink()
            print(f"    done  {filename}")

        browser.close()

    print(f"\n{len(SLIDES)} slides saved to {OUT}\n")


if __name__ == "__main__":
    main()
