#!/usr/bin/env python3
"""
make_seo_mistake_carousel.py — "3 reasons your website isn't getting enquiries" carousel.
Output: ~/Documents/ImproveYourSite - Social Media/Tiles/

Usage:
    python3 social/make_seo_mistake_carousel.py
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
MUTED = "#64748b"
RED   = "#ef4444"
AMBER = "#f59e0b"
FONT  = ("<link href='https://fonts.googleapis.com/css2?family=Inter:"
         "wght@400;500;600;700;800;900&display=swap' rel='stylesheet'>")


def brand_bar(on_dark=True):
    name_color = "rgba(255,255,255,.45)" if on_dark else MUTED
    dot_color  = MINT                    if on_dark else BLUE
    url_color  = "rgba(255,255,255,.25)" if on_dark else "rgba(0,0,0,.2)"
    return (
        f"<div style='position:absolute;bottom:48px;left:88px;right:88px;"
        f"display:flex;align-items:center;justify-content:space-between;z-index:10;'>"
        f"<span style='font-size:30px;font-weight:800;color:{name_color};'>"
        f"Improve<span style='color:{dot_color};'>YourSite</span></span>"
        f"<span style='font-size:26px;font-weight:500;color:{url_color};'>"
        f"improveyoursite.com</span>"
        f"</div>"
    )


def eyebrow(label, on_dark=True):
    bg  = "rgba(45,212,191,.15)" if on_dark else "rgba(91,77,255,.1)"
    txt = MINT                   if on_dark else BLUE
    bdr = "rgba(45,212,191,.3)"  if on_dark else "rgba(91,77,255,.25)"
    return (
        f"<div style='display:inline-block;background:{bg};border:1px solid {bdr};"
        f"border-radius:100px;padding:14px 36px;margin-bottom:40px;'>"
        f"<span style='font-size:24px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{txt};'>{label}</span>"
        f"</div>"
    )


# ── Slides ──────────────────────────────────────────────────────────────────────

def slide_01_hook():
    """White — SEO mistake 90% hook, centred"""
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{WHITE};"
        f"position:relative;display:flex;flex-direction:column;"
        f"justify-content:center;align-items:center;padding:80px 88px 140px;'>"

        f"<div style='position:absolute;top:-100px;right:-80px;width:500px;height:500px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(91,77,255,.1) 0%,transparent 65%);'></div>"
        f"<div style='position:absolute;bottom:-120px;left:-80px;width:460px;height:460px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(45,212,191,.08) 0%,transparent 65%);'></div>"

        f"<div style='position:relative;z-index:1;"
        f"display:flex;flex-direction:column;align-items:center;text-align:center;'>"

        f"<div style='display:inline-block;background:rgba(239,68,68,.08);"
        f"border:1px solid rgba(239,68,68,.25);border-radius:100px;"
        f"padding:14px 36px;margin-bottom:44px;'>"
        f"<span style='font-size:24px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{RED};'>Common mistake</span>"
        f"</div>"

        f"<p style='font-size:58px;font-weight:900;line-height:1.1;letter-spacing:-.03em;"
        f"color:rgba(15,23,42,.35);margin:0 0 8px;'>The SEO mistake</p>"
        f"<p style='font-size:140px;font-weight:900;line-height:1.0;letter-spacing:-.06em;"
        f"color:{BLUE};margin:0 0 8px;'>90%</p>"
        f"<p style='font-size:58px;font-weight:900;line-height:1.1;letter-spacing:-.03em;"
        f"color:rgba(15,23,42,.35);margin:0 0 52px;'>of small businesses make.</p>"

        f"<div style='width:68px;height:5px;background:{MINT};border-radius:4px;"
        f"margin:0 auto 44px;'></div>"

        f"<p style='font-size:44px;font-weight:600;line-height:1.45;"
        f"color:{MUTED};margin:0;'>Swipe to see if you&rsquo;re making it.</p>"

        f"</div>"
        f"{brand_bar(on_dark=False)}"
        f"</div></body></html>"
    )


def slide_02_reason1():
    """Indigo blue — Reason 1: Google can't rank it"""
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{BLUE};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 140px;'>"

        f"<div style='position:absolute;top:-100px;right:-80px;width:500px;height:500px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(45,212,191,.15) 0%,transparent 65%);'></div>"
        f"<div style='position:absolute;bottom:-100px;left:-80px;width:420px;height:420px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(255,255,255,.07) 0%,transparent 65%);'></div>"

        f"<div style='position:relative;z-index:1;'>"

        f"<div style='display:inline-block;background:rgba(45,212,191,.18);"
        f"border:1px solid rgba(45,212,191,.35);border-radius:100px;"
        f"padding:14px 36px;margin-bottom:40px;'>"
        f"<span style='font-size:24px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{MINT};'>Reason 01</span>"
        f"</div>"

        f"<p style='font-size:80px;font-weight:900;line-height:1.0;letter-spacing:-.04em;"
        f"color:rgba(255,255,255,.45);margin:0 0 6px;'>Google can&rsquo;t</p>"
        f"<p style='font-size:96px;font-weight:900;line-height:1.0;letter-spacing:-.05em;"
        f"color:{WHITE};margin:0 0 48px;'>rank your site.</p>"

        f"<div style='width:68px;height:5px;background:{MINT};border-radius:4px;margin-bottom:40px;'></div>"

        f"<p style='font-size:44px;font-weight:500;line-height:1.55;"
        f"color:rgba(255,255,255,.6);margin:0 0 20px;'>"
        f"Google scores every website on speed, mobile<br>"
        f"performance and user experience.</p>"
        f"<p style='font-size:48px;font-weight:700;line-height:1.4;"
        f"color:{WHITE};margin:0;'>"
        f"A score below 50 means Google<br>is actively pushing you down<br>in search results.</p>"

        f"</div>"
        f"{brand_bar(on_dark=True)}"
        f"</div></body></html>"
    )


def slide_03_reason2():
    """White — Reason 2: Visitors leave before they act"""
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{WHITE};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 140px;'>"

        f"<div style='position:absolute;top:0;left:0;width:6px;height:100%;background:{BLUE};'></div>"

        f"<div style='position:relative;z-index:1;'>"

        f"<div style='display:inline-block;background:rgba(91,77,255,.1);"
        f"border:1px solid rgba(91,77,255,.25);border-radius:100px;"
        f"padding:14px 36px;margin-bottom:40px;'>"
        f"<span style='font-size:24px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{BLUE};'>Reason 02</span>"
        f"</div>"

        f"<p style='font-size:80px;font-weight:900;line-height:1.0;letter-spacing:-.04em;"
        f"color:rgba(15,23,42,.4);margin:0 0 6px;'>Visitors arrive.</p>"
        f"<p style='font-size:96px;font-weight:900;line-height:1.0;letter-spacing:-.05em;"
        f"color:{DARK};margin:0 0 48px;'>Then they leave.</p>"

        f"<div style='width:68px;height:5px;background:{BLUE};border-radius:4px;margin-bottom:40px;'></div>"

        f"<p style='font-size:44px;font-weight:500;line-height:1.55;"
        f"color:{MUTED};margin:0 0 20px;'>"
        f"A slow site loses visitors in the first 3 seconds.<br>"
        f"A confusing site loses them in the first 10.</p>"
        f"<p style='font-size:48px;font-weight:700;line-height:1.4;"
        f"color:{DARK};margin:0;'>"
        f"If they can&rsquo;t find what they need fast,<br>they go to your competitor.</p>"

        f"</div>"
        f"{brand_bar(on_dark=False)}"
        f"</div></body></html>"
    )


def slide_04_reason3():
    """Indigo — Reason 3: No clear path to enquire"""
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{BLUE};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 140px;'>"

        f"<div style='position:absolute;bottom:-120px;right:-80px;width:500px;height:500px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(239,68,68,.1) 0%,transparent 65%);'></div>"
        f"<div style='position:absolute;top:-80px;left:-60px;width:400px;height:400px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(91,77,255,.15) 0%,transparent 65%);'></div>"

        f"<div style='position:relative;z-index:1;'>"

        f"<div style='display:inline-block;background:rgba(45,212,191,.15);"
        f"border:1px solid rgba(45,212,191,.3);border-radius:100px;"
        f"padding:14px 36px;margin-bottom:40px;'>"
        f"<span style='font-size:24px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{MINT};'>Reason 03</span>"
        f"</div>"

        f"<p style='font-size:80px;font-weight:900;line-height:1.0;letter-spacing:-.04em;"
        f"color:rgba(255,255,255,.45);margin:0 0 6px;'>There&rsquo;s no clear</p>"
        f"<p style='font-size:96px;font-weight:900;line-height:1.0;letter-spacing:-.05em;"
        f"color:{WHITE};margin:0 0 48px;'>next step.</p>"

        f"<div style='width:68px;height:5px;background:{MINT};border-radius:4px;margin-bottom:40px;'></div>"

        f"<p style='font-size:44px;font-weight:500;line-height:1.55;"
        f"color:rgba(255,255,255,.55);margin:0 0 20px;'>"
        f"Most business websites tell people what they do.<br>"
        f"Very few have a landing page built to convert.</p>"
        f"<p style='font-size:48px;font-weight:700;line-height:1.4;"
        f"color:rgba(255,255,255,.85);margin:0;'>"
        f"No strong landing page<br>= no enquiry.</p>"

        f"</div>"
        f"{brand_bar(on_dark=True)}"
        f"</div></body></html>"
    )


def slide_05_cta():
    """White — educational close, how we fix all 3"""
    fixes = [
        ("We audit your Google score", "and show you exactly what Google sees when it grades your site."),
        ("We rebuild for speed and mobile", "because those are the two biggest ranking factors in 2026."),
        ("We build landing pages that convert", "structured to turn visitors into calls, bookings and enquiries."),
    ]
    bullets = "".join(
        f"<div style='display:flex;align-items:flex-start;gap:22px;margin-bottom:24px;"
        f"background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);"
        f"border-radius:14px;padding:22px 26px;'>"
        f"<span style='flex-shrink:0;margin-top:6px;font-size:26px;color:{MINT};'>✓</span>"
        f"<div>"
        f"<p style='font-size:36px;font-weight:800;color:{WHITE};margin:0 0 4px;"
        f"letter-spacing:-.01em;'>{title}</p>"
        f"<p style='font-size:28px;font-weight:500;color:rgba(255,255,255,.55);margin:0;"
        f"line-height:1.4;'>{desc}</p>"
        f"</div></div>"
        for title, desc in fixes
    )
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{WHITE};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:72px 88px 130px;'>"

        f"<div style='position:absolute;top:0;left:0;width:6px;height:100%;background:{BLUE};'></div>"
        f"<div style='position:absolute;bottom:-180px;right:-120px;width:650px;height:650px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(91,77,255,.06) 0%,transparent 65%);'></div>"

        f"<div style='position:relative;z-index:1;'>"
        f"{eyebrow('How We Fix It', on_dark=False)}"

        f"<p style='font-size:72px;font-weight:900;line-height:1.0;letter-spacing:-.04em;"
        f"color:{DARK};margin:0 0 36px;'>Here&rsquo;s exactly<br>what we do.</p>"

        f"<div style='margin-bottom:32px;'>{bullets}</div>"

        f"<div style='display:inline-block;background:{BLUE};padding:20px 44px;"
        f"border-radius:14px;'>"
        f"<span style='font-size:32px;font-weight:800;color:{WHITE};letter-spacing:-.01em;'>"
        f"DM us AUDIT &rarr; free check on your site</span>"
        f"</div>"

        f"</div>"
        f"{brand_bar(on_dark=False)}"
        f"</div></body></html>"
    )


SLIDES = [
    (f"{TODAY}-enquiries-01-hook.png",     slide_01_hook()),
    (f"{TODAY}-enquiries-02-reason1.png",  slide_02_reason1()),
    (f"{TODAY}-enquiries-03-reason2.png",  slide_03_reason2()),
    (f"{TODAY}-enquiries-04-reason3.png",  slide_04_reason3()),
    (f"{TODAY}-enquiries-05-cta.png",      slide_05_cta()),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"\n🖼   Generating {len(SLIDES)} slides → {OUT}\n")

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
            page.wait_for_timeout(700)
            page.query_selector("body > div").screenshot(path=str(out), type="png")
            tmp.unlink()
            print(f"    ✓  {filename}")

        browser.close()

    print(f"\n✅  {len(SLIDES)} PNGs saved to:\n    {OUT}\n")


if __name__ == "__main__":
    main()
