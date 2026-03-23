#!/usr/bin/env python3
"""
make_jarvis_usb_carousel.py
"Jarvis USB — $250. Plug in. AI starts working." — Product launch carousel.
Black cover theme, 6 slides.
Output: ~/Documents/ImproveYourSite - Social Media/Tiles/

Usage:
    python3 social/make_jarvis_usb_carousel.py
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


def brand_bar(light=False):
    name_color  = "rgba(255,255,255,.4)" if not light else "rgba(30,41,59,.45)"
    url_color   = "rgba(255,255,255,.25)" if not light else "rgba(30,41,59,.3)"
    dot_color   = MINT if not light else INDIGO
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
        f"<div style='width:1080px;height:1080px;background:{DARK};position:relative;"
        f"display:flex;flex-direction:column;align-items:flex-start;justify-content:center;"
        f"padding:80px 88px 160px;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
        f"<div style='position:absolute;top:-120px;right:-120px;width:600px;height:600px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(91,77,255,.25) 0%,transparent 65%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(45,212,191,.12);"
        f"border:1px solid rgba(45,212,191,.25);border-radius:100px;"
        f"padding:12px 32px;margin-bottom:48px;'>"
        f"<span style='font-size:20px;font-weight:700;letter-spacing:.1em;"
        f"text-transform:uppercase;color:{MINT};'>New Product</span></div>"
        f"<p style='font-size:96px;font-weight:900;line-height:.9;letter-spacing:-.04em;"
        f"color:{WHITE};margin:0 0 24px;'>Jarvis USB.</p>"
        f"<p style='font-size:96px;font-weight:900;line-height:.9;letter-spacing:-.04em;"
        f"color:{INDIGO};margin:0 0 48px;'>$250.</p>"
        f"<p style='font-size:34px;font-weight:500;color:rgba(255,255,255,.6);margin:0;line-height:1.4;'>"
        f"Plug in. OpenClaw + Claude<br>start running your business.</p>"
        f"</div>"
        f"{swipe_arrow(INDIGO, DARK)}"
        f"{brand_bar()}"
        f"</div></body></html>"
    )


def slide_02_what():
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{WHITE};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 160px;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(91,77,255,.08);"
        f"border:1px solid rgba(91,77,255,.2);border-radius:100px;"
        f"padding:13px 34px;margin-bottom:40px;'>"
        f"<span style='font-size:22px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{INDIGO};'>What&apos;s on it</span></div>"
        f"<p style='font-size:58px;font-weight:900;line-height:1.0;letter-spacing:-.03em;"
        f"color:{DARK};margin:0 0 40px;'>10 AI agents.<br>Pre-loaded. Ready.</p>"
        f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:16px;'>"
        + "".join([
            f"<div style='background:#f8f7ff;border-radius:14px;padding:20px 24px;"
            f"border-left:4px solid {INDIGO};'>"
            f"<span style='font-size:24px;font-weight:700;color:{DARK};'>{item}</span></div>"
            for item in ["Lead follow-up", "Email triage", "Social media", "Blog writing",
                         "SEO monitoring", "Google Ads", "Morning digest", "Competitor watch",
                         "Customer alerts", "Job bookings"]
        ])
        + f"</div>"
        f"</div>"
        f"{swipe_arrow(DARK, WHITE)}"
        f"{brand_bar(light=True)}"
        f"</div></body></html>"
    )


def slide_03_how():
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
        f"text-transform:uppercase;color:{MINT};'>How it works</span></div>"
        f"<p style='font-size:58px;font-weight:900;line-height:1.05;letter-spacing:-.03em;"
        f"color:{WHITE};margin:0 0 48px;'>Three steps.<br>That&apos;s it.</p>"
        + "".join([
            f"<div style='display:flex;align-items:flex-start;gap:28px;margin-bottom:28px;'>"
            f"<div style='min-width:56px;height:56px;border-radius:50%;"
            f"background:{bg};display:flex;align-items:center;justify-content:center;'>"
            f"<span style='font-size:26px;font-weight:900;color:{tc};'>{n}</span></div>"
            f"<div>"
            f"<p style='font-size:30px;font-weight:800;color:{WHITE};margin:0 0 4px;'>{title}</p>"
            f"<p style='font-size:24px;font-weight:400;color:rgba(255,255,255,.55);margin:0;'>{sub}</p>"
            f"</div></div>"
            for n, bg, tc, title, sub in [
                ("1", INDIGO, WHITE, "Plug in the USB", "Mac or Windows — runs automatically"),
                ("2", MINT,   DARK,  "We set up your API keys", "We walk you through it. 5 minutes."),
                ("3", WHITE,  DARK,  "Jarvis runs your business", "Every day, in the background"),
            ]
        ])
        + f"</div>"
        f"{swipe_arrow(MINT, DARK)}"
        f"{brand_bar()}"
        f"</div></body></html>"
    )


def slide_04_api():
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:#f8f7ff;position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 160px;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(91,77,255,.08);"
        f"border:1px solid rgba(91,77,255,.2);border-radius:100px;"
        f"padding:13px 34px;margin-bottom:40px;'>"
        f"<span style='font-size:22px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{INDIGO};'>Honest pricing</span></div>"
        f"<p style='font-size:58px;font-weight:900;line-height:1.05;letter-spacing:-.03em;"
        f"color:{DARK};margin:0 0 40px;'>$250 once.<br>Then you pay<br>Anthropic direct.</p>"
        f"<div style='background:{WHITE};border-radius:20px;padding:32px 40px;"
        f"border:2px solid rgba(91,77,255,.15);'>"
        f"<p style='font-size:28px;font-weight:600;color:{DARK};margin:0 0 12px;'>"
        f"API usage goes straight to your Anthropic account.</p>"
        f"<p style='font-size:26px;font-weight:400;color:{SLATE};margin:0;line-height:1.5;'>"
        f"Typically $10&ndash;30/month. We don&apos;t touch your billing &mdash; ever.</p>"
        f"</div>"
        f"</div>"
        f"{swipe_arrow(DARK, WHITE)}"
        f"{brand_bar(light=True)}"
        f"</div></body></html>"
    )


def slide_05_proof():
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{DARK};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 160px;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
        f"<div style='position:absolute;bottom:-100px;right:-80px;width:500px;height:500px;"
        f"border-radius:50%;background:radial-gradient(circle,rgba(45,212,191,.15) 0%,transparent 65%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(45,212,191,.12);"
        f"border:1px solid rgba(45,212,191,.25);border-radius:100px;"
        f"padding:13px 34px;margin-bottom:48px;'>"
        f"<span style='font-size:22px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{MINT};'>Powered by</span></div>"
        f"<p style='font-size:72px;font-weight:900;line-height:.95;letter-spacing:-.04em;"
        f"color:{WHITE};margin:0 0 16px;'>OpenClaw</p>"
        f"<p style='font-size:72px;font-weight:900;line-height:.95;letter-spacing:-.04em;"
        f"color:{INDIGO};margin:0 0 48px;'>+ Claude AI</p>"
        f"<div style='width:72px;height:5px;background:{MINT};border-radius:4px;margin-bottom:40px;'></div>"
        f"<p style='font-size:30px;font-weight:500;color:rgba(255,255,255,.6);margin:0;line-height:1.5;'>"
        f"The same AI stack we use to run<br>our own business &mdash; now in a USB.</p>"
        f"</div>"
        f"{swipe_arrow(INDIGO, WHITE)}"
        f"{brand_bar()}"
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
        f"<p style='font-size:80px;font-weight:900;line-height:.95;letter-spacing:-.04em;"
        f"color:{WHITE};margin:0 0 48px;'>$250.<br>AI running<br>your biz.</p>"
        f"<div style='width:72px;height:5px;background:{MINT};border-radius:4px;margin-bottom:48px;'></div>"
        f"<p style='font-size:28px;font-weight:500;color:rgba(255,255,255,.65);margin:0 0 40px;'>"
        f"DM &ldquo;USB&rdquo; to order. Ships anywhere in Australia.</p>"
        f"<div style='display:inline-block;background:{WHITE};padding:18px 40px;border-radius:14px;'>"
        f"<span style='font-size:28px;font-weight:800;color:{INDIGO};'>"
        f"improveyoursite.com/jarvis</span>"
        f"</div>"
        f"</div>"
        f"{brand_bar()}"
        f"</div></body></html>"
    )


SLIDES = [
    (f"{TODAY}-jarvis-usb-01-cover.png",  slide_01_cover()),
    (f"{TODAY}-jarvis-usb-02-what.png",   slide_02_what()),
    (f"{TODAY}-jarvis-usb-03-how.png",    slide_03_how()),
    (f"{TODAY}-jarvis-usb-04-api.png",    slide_04_api()),
    (f"{TODAY}-jarvis-usb-05-proof.png",  slide_05_proof()),
    (f"{TODAY}-jarvis-usb-06-cta.png",    slide_06_cta()),
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
