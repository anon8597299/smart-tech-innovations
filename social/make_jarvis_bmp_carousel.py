#!/usr/bin/env python3
"""
make_jarvis_bmp_carousel.py
"Business Manager Pro — Mac Mini with Jarvis. $3,000. Ships Australia-wide." carousel.
White cover theme, 6 slides.
Output: ~/Documents/ImproveYourSite - Social Media/Tiles/

Usage:
    python3 social/make_jarvis_bmp_carousel.py
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

INDIGO = "#5b4dff"
MINT   = "#2dd4bf"
DARK   = "#0f172a"
SLATE  = "#475569"
WHITE  = "#ffffff"
CREAM  = "#f8f7ff"
PALE   = "#f0f4ff"
FONT   = ("<link href='https://fonts.googleapis.com/css2?family=Inter:"
          "wght@400;500;600;700;800;900&display=swap' rel='stylesheet'>")


def swipe_arrow(bg, text_color):
    return (
        f"<div style='position:absolute;bottom:52px;right:72px;"
        f"background:{bg};border-radius:100px;padding:10px 28px 10px 24px;"
        f"display:flex;align-items:center;gap:10px;"
        f"clip-path:polygon(0 0,calc(100% - 18px) 0,100% 50%,calc(100% - 18px) 100%,0 100%);'>"
        f"<span style='font-size:22px;font-weight:900;color:{text_color};"
        f"letter-spacing:.06em;text-transform:uppercase;'>SWIPE</span>"
        f"</div>"
    )


def brand_bar(light=True):
    name_color = "rgba(30,41,59,.45)" if light else "rgba(255,255,255,.4)"
    url_color  = "rgba(30,41,59,.3)"  if light else "rgba(255,255,255,.25)"
    dot_color  = INDIGO if light else MINT
    return (
        f"<div style='position:absolute;bottom:48px;left:72px;right:72px;"
        f"display:flex;align-items:center;justify-content:space-between;z-index:10;'>"
        f"<span style='font-size:28px;font-weight:800;color:{name_color};'>"
        f"Improve<span style='color:{dot_color};'>YourSite</span></span>"
        f"<span style='font-size:24px;font-weight:500;color:{url_color};'>"
        f"improveyoursite.com/jarvis</span>"
        f"</div>"
    )


def slide_01_cover():
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{WHITE};position:relative;"
        f"display:flex;flex-direction:column;align-items:flex-start;justify-content:center;"
        f"padding:80px 88px 160px;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
        f"<div style='position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);"
        f"width:900px;height:900px;border-radius:50%;"
        f"background:radial-gradient(circle,rgba(91,77,255,.05) 0%,transparent 65%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(91,77,255,.08);"
        f"border:1px solid rgba(91,77,255,.2);border-radius:100px;"
        f"padding:12px 32px;margin-bottom:48px;'>"
        f"<span style='font-size:20px;font-weight:700;letter-spacing:.1em;"
        f"text-transform:uppercase;color:{INDIGO};'>Hardware Launch</span></div>"
        f"<p style='font-size:72px;font-weight:900;line-height:.95;letter-spacing:-.04em;"
        f"color:{DARK};margin:0 0 16px;'>Business</p>"
        f"<p style='font-size:72px;font-weight:900;line-height:.95;letter-spacing:-.04em;"
        f"color:{DARK};margin:0 0 16px;'>Manager Pro.</p>"
        f"<p style='font-size:72px;font-weight:900;line-height:.95;letter-spacing:-.04em;"
        f"color:{INDIGO};margin:0 0 48px;'>$3,000.</p>"
        f"<p style='font-size:32px;font-weight:500;color:{SLATE};margin:0;line-height:1.4;'>"
        f"Mac Mini. Jarvis pre-installed.<br>Ships anywhere in Australia.</p>"
        f"</div>"
        f"{swipe_arrow(DARK, WHITE)}"
        f"{brand_bar(light=True)}"
        f"</div></body></html>"
    )


def slide_02_whatis():
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{DARK};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 160px;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(45,212,191,.12);"
        f"border:1px solid rgba(45,212,191,.25);border-radius:100px;"
        f"padding:13px 34px;margin-bottom:40px;'>"
        f"<span style='font-size:22px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{MINT};'>What you get</span></div>"
        f"<p style='font-size:56px;font-weight:900;line-height:1.0;letter-spacing:-.03em;"
        f"color:{WHITE};margin:0 0 44px;'>A Mac Mini.<br>With your AI<br>team inside.</p>"
        + "".join([
            f"<div style='display:flex;align-items:center;gap:20px;margin-bottom:22px;'>"
            f"<div style='width:10px;height:10px;border-radius:50%;background:{MINT};flex-shrink:0;'></div>"
            f"<span style='font-size:28px;font-weight:600;color:rgba(255,255,255,.85);'>{item}</span></div>"
            for item in [
                "Mac Mini hardware included",
                "Jarvis pre-installed &amp; configured",
                "OpenClaw + Claude ready to go",
                "We set up your API keys remotely",
                "All 10 AI agents activated",
                "Priority phone + email support",
            ]
        ])
        + f"</div>"
        f"{swipe_arrow(INDIGO, WHITE)}"
        f"{brand_bar(light=False)}"
        f"</div></body></html>"
    )


def slide_03_setup():
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{PALE};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 160px;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(91,77,255,.08);"
        f"border:1px solid rgba(91,77,255,.2);border-radius:100px;"
        f"padding:13px 34px;margin-bottom:40px;'>"
        f"<span style='font-size:22px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{INDIGO};'>Setup</span></div>"
        f"<p style='font-size:60px;font-weight:900;line-height:1.0;letter-spacing:-.03em;"
        f"color:{DARK};margin:0 0 48px;'>Power it on.<br>We do the rest.</p>"
        + "".join([
            f"<div style='display:flex;align-items:flex-start;gap:28px;margin-bottom:24px;'>"
            f"<div style='min-width:52px;height:52px;border-radius:50%;"
            f"background:{bg};display:flex;align-items:center;justify-content:center;flex-shrink:0;'>"
            f"<span style='font-size:24px;font-weight:900;color:{tc};'>{n}</span></div>"
            f"<div style='padding-top:8px;'>"
            f"<p style='font-size:28px;font-weight:800;color:{DARK};margin:0 0 4px;'>{title}</p>"
            f"<p style='font-size:23px;font-weight:400;color:{SLATE};margin:0;'>{sub}</p>"
            f"</div></div>"
            for n, bg, tc, title, sub in [
                ("1", INDIGO, WHITE, "We ship it to your address", "Anywhere in Australia"),
                ("2", DARK,   WHITE, "Plug it in &amp; power on", "Mac Mini boots Jarvis automatically"),
                ("3", MINT,   DARK,  "We configure your API keys", "Remote setup — we walk you through it"),
                ("4", INDIGO, WHITE, "Your business runs itself", "10 agents working every day"),
            ]
        ])
        + f"</div>"
        f"{swipe_arrow(DARK, WHITE)}"
        f"{brand_bar(light=True)}"
        f"</div></body></html>"
    )


def slide_04_why():
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{DARK};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 160px;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
        f"<div style='position:absolute;top:-80px;right:-80px;width:480px;height:480px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(91,77,255,.2) 0%,transparent 65%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(45,212,191,.12);"
        f"border:1px solid rgba(45,212,191,.25);border-radius:100px;"
        f"padding:13px 34px;margin-bottom:40px;'>"
        f"<span style='font-size:22px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{MINT};'>Why hardware</span></div>"
        f"<p style='font-size:56px;font-weight:900;line-height:1.0;letter-spacing:-.03em;"
        f"color:{WHITE};margin:0 0 48px;'>No setup.<br>No IT guy.<br>Just results.</p>"
        f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:20px;'>"
        + "".join([
            f"<div style='background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);"
            f"border-radius:16px;padding:24px 28px;'>"
            f"<p style='font-size:26px;font-weight:800;color:{color};margin:0 0 8px;'>{title}</p>"
            f"<p style='font-size:22px;font-weight:400;color:rgba(255,255,255,.55);margin:0;'>{sub}</p>"
            f"</div>"
            for title, sub, color in [
                ("Always on", "Runs 24/7 at the office", MINT),
                ("Dedicated", "Not your personal laptop", WHITE),
                ("Pre-configured", "Zero setup on your end", MINT),
                ("Full control", "Your hardware, your data", WHITE),
            ]
        ])
        + f"</div>"
        f"</div>"
        f"{swipe_arrow(MINT, DARK)}"
        f"{brand_bar(light=False)}"
        f"</div></body></html>"
    )


def slide_05_openclaw():
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{CREAM};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 160px;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(91,77,255,.08);"
        f"border:1px solid rgba(91,77,255,.2);border-radius:100px;"
        f"padding:13px 34px;margin-bottom:40px;'>"
        f"<span style='font-size:22px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{INDIGO};'>The tech inside</span></div>"
        f"<p style='font-size:56px;font-weight:900;line-height:1.0;letter-spacing:-.03em;"
        f"color:{DARK};margin:0 0 16px;'>OpenClaw.</p>"
        f"<p style='font-size:56px;font-weight:900;line-height:1.0;letter-spacing:-.03em;"
        f"color:{INDIGO};margin:0 0 48px;'>Claude AI.</p>"
        f"<div style='width:72px;height:5px;background:{MINT};border-radius:4px;margin-bottom:40px;'></div>"
        f"<p style='font-size:30px;font-weight:500;color:{SLATE};margin:0 0 20px;line-height:1.5;'>"
        f"The same stack we use to automate<br>our own business &mdash; pre-loaded on<br>a Mac Mini and shipped to you.</p>"
        f"<p style='font-size:26px;font-weight:600;color:{INDIGO};margin:0;'>"
        f"You own it. Full control. No lock-in.</p>"
        f"</div>"
        f"{swipe_arrow(DARK, WHITE)}"
        f"{brand_bar(light=True)}"
        f"</div></body></html>"
    )


def slide_06_cta():
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{INDIGO};position:relative;"
        f"display:flex;flex-direction:column;align-items:flex-start;justify-content:center;"
        f"padding:80px 88px 160px;'>"
        f"<div style='position:absolute;bottom:-160px;right:-100px;width:600px;height:600px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(45,212,191,.18) 0%,transparent 65%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<p style='font-size:76px;font-weight:900;line-height:.95;letter-spacing:-.04em;"
        f"color:{WHITE};margin:0 0 48px;'>$3,000.<br>Your AI office<br>in a box.</p>"
        f"<div style='width:72px;height:5px;background:{MINT};border-radius:4px;margin-bottom:48px;'></div>"
        f"<p style='font-size:28px;font-weight:500;color:rgba(255,255,255,.65);margin:0 0 40px;'>"
        f"DM &ldquo;PRO&rdquo; for more info.<br>Ships anywhere in Australia.</p>"
        f"<div style='display:inline-block;background:{WHITE};padding:18px 40px;border-radius:14px;'>"
        f"<span style='font-size:28px;font-weight:800;color:{INDIGO};'>"
        f"improveyoursite.com/jarvis</span>"
        f"</div>"
        f"</div>"
        f"<div style='position:absolute;bottom:48px;left:72px;right:72px;"
        f"display:flex;align-items:center;justify-content:space-between;z-index:10;'>"
        f"<span style='font-size:28px;font-weight:800;color:rgba(255,255,255,.4);'>"
        f"Improve<span style='color:{MINT};'>YourSite</span></span>"
        f"<span style='font-size:24px;font-weight:500;color:rgba(255,255,255,.25);'>"
        f"improveyoursite.com/jarvis</span>"
        f"</div>"
        f"</div></body></html>"
    )


SLIDES = [
    (f"{TODAY}-bmp-01-cover.png",   slide_01_cover()),
    (f"{TODAY}-bmp-02-whatis.png",  slide_02_whatis()),
    (f"{TODAY}-bmp-03-setup.png",   slide_03_setup()),
    (f"{TODAY}-bmp-04-why.png",     slide_04_why()),
    (f"{TODAY}-bmp-05-tech.png",    slide_05_openclaw()),
    (f"{TODAY}-bmp-06-cta.png",     slide_06_cta()),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"\nGenerating {len(SLIDES)} slides → {OUT}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page(viewport={"width": 1120, "height": 1120})

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
            print(f"    ok  {filename}")

        browser.close()

    print(f"\n{len(SLIDES)} PNGs saved to:\n    {OUT}\n")


if __name__ == "__main__":
    main()
