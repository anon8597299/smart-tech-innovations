#!/usr/bin/env python3
"""
make_value_comparison_carousel.py
"Your competitor quoted $15K+?" — Price comparison carousel.
Light theme, 6 slides.
Output: ~/Documents/ImproveYourSite - Social Media/Tiles/

Usage:
    python3 social/make_value_comparison_carousel.py
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
DARK   = "#1e293b"
SLATE  = "#475569"
WHITE  = "#ffffff"
CREAM  = "#f8f7ff"
PALE   = "#f0f4ff"
BORDER = "#e2e8f0"
RED    = "#ef4444"
GREEN  = "#22c55e"
FONT   = ("<link href='https://fonts.googleapis.com/css2?family=Inter:"
          "wght@400;500;600;700;800;900&display=swap' rel='stylesheet'>")


def brand_bar():
    return (
        f"<div style='position:absolute;bottom:48px;left:72px;right:72px;"
        f"display:flex;align-items:center;justify-content:space-between;z-index:10;'>"
        f"<span style='font-size:28px;font-weight:800;color:rgba(30,41,59,.45);'>"
        f"Improve<span style='color:{INDIGO};'>YourSite</span></span>"
        f"<span style='font-size:24px;font-weight:500;color:rgba(30,41,59,.3);'>"
        f"improveyoursite.com</span>"
        f"</div>"
    )


def eyebrow(label, color=INDIGO, bg="rgba(91,77,255,.08)", border="rgba(91,77,255,.2)"):
    return (
        f"<div style='display:inline-block;background:{bg};border:1px solid {border};"
        f"border-radius:100px;padding:13px 34px;margin-bottom:40px;'>"
        f"<span style='font-size:22px;font-weight:700;letter-spacing:.08em;"
        f"text-transform:uppercase;color:{color};'>{label}</span>"
        f"</div>"
    )


def base(bg=CREAM):
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{bg};position:relative;"
        f"display:flex;flex-direction:column;justify-content:center;padding:80px 88px 160px;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
    )


def slide_01_cover():
    return (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{FONT}</head>"
        f"<body style='margin:0;padding:0;width:1080px;height:1080px;overflow:hidden;"
        f"font-family:Inter,-apple-system,sans-serif;'>"
        f"<div style='width:1080px;height:1080px;background:{CREAM};position:relative;"
        f"display:flex;flex-direction:column;align-items:center;justify-content:center;"
        f"padding:80px 88px 160px;text-align:center;'>"
        f"<div style='position:absolute;top:0;left:0;right:0;height:7px;"
        f"background:linear-gradient(90deg,{INDIGO} 0%,{MINT} 100%);'></div>"
        f"<div style='position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);"
        f"width:900px;height:900px;border-radius:50%;"
        f"background:radial-gradient(circle,rgba(91,77,255,.06) 0%,transparent 65%);'></div>"
        f"<div style='position:relative;z-index:1;'>"
        f"<div style='display:inline-block;background:rgba(91,77,255,.08);border:1px solid rgba(91,77,255,.2);"
        f"border-radius:100px;padding:12px 32px;margin-bottom:52px;'>"
        f"<span style='font-size:20px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:{INDIGO};'>"
        f"Reality check</span></div>"
        f"<p style='font-size:130px;font-weight:900;line-height:.9;letter-spacing:-.05em;"
        f"color:{INDIGO};margin:0 0 36px;'>$15K+?</p>"
        f"<p style='font-size:40px;font-weight:700;color:{DARK};margin:0 0 16px;line-height:1.2;'>"
        f"Your competitor just quoted that.</p>"
        f"<p style='font-size:28px;font-weight:500;color:{SLATE};margin:0;'>"
        f"Swipe to see what it actually costs. &#8594;</p>"
        f"</div>"
        f"<div style='position:absolute;bottom:48px;left:72px;right:72px;"
        f"display:flex;align-items:center;justify-content:space-between;z-index:10;'>"
        f"<span style='font-size:28px;font-weight:800;color:rgba(30,41,59,.45);'>"
        f"Improve<span style='color:{INDIGO};'>YourSite</span></span>"
        f"<span style='font-size:24px;font-weight:500;color:rgba(30,41,59,.3);'>improveyoursite.com</span>"
        f"</div>"
        f"</div></body></html>"
    )


def slide_02_scan_fix():
    return (
        base(WHITE)
        + f"<div style='position:relative;z-index:1;'>"
        + eyebrow("Scan &amp; Fix")
        + f"<p style='font-size:140px;font-weight:900;line-height:.9;letter-spacing:-.05em;"
          f"color:{INDIGO};margin:0 0 28px;'>$3,000</p>"
        + f"<p style='font-size:34px;font-weight:700;color:{DARK};margin:0 0 18px;'>Fix what's broken. Fast.</p>"
        + f"<p style='font-size:28px;font-weight:400;color:{SLATE};line-height:1.5;margin:0;'>"
          f"Speed, SEO, calls to action, mobile layout &mdash; everything that costs you enquiries today.</p>"
        + f"</div>"
        + brand_bar()
        + f"</div></body></html>"
    )


def slide_03_complete_build():
    return (
        base(PALE)
        + f"<div style='position:relative;z-index:1;'>"
        + eyebrow("Complete Build")
        + f"<p style='font-size:140px;font-weight:900;line-height:.9;letter-spacing:-.05em;"
          f"color:{DARK};margin:0 0 28px;'>$5,000</p>"
        + f"<p style='font-size:34px;font-weight:700;color:{DARK};margin:0 0 18px;'>A new site. Done right.</p>"
        + f"<p style='font-size:28px;font-weight:400;color:{SLATE};line-height:1.5;margin:0;'>"
          f"Lead-generating layout, automated blog, 2&ndash;4 week delivery. You own it outright.</p>"
        + f"</div>"
        + brand_bar()
        + f"</div></body></html>"
    )


def slide_04_premium():
    return (
        base(DARK)
        + f"<div style='position:absolute;top:-80px;right:-80px;width:480px;height:480px;"
          f"border-radius:50%;background:radial-gradient(circle,rgba(91,77,255,.2) 0%,transparent 65%);'></div>"
        + f"<div style='position:relative;z-index:1;'>"
        + f"<div style='display:inline-block;background:rgba(45,212,191,.12);border:1px solid rgba(45,212,191,.25);"
          f"border-radius:100px;padding:13px 34px;margin-bottom:40px;'>"
        + f"<span style='font-size:22px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{MINT};'>"
          f"Premium Growth</span></div>"
        + f"<p style='font-size:140px;font-weight:900;line-height:.9;letter-spacing:-.05em;"
          f"color:{WHITE};margin:0 0 28px;'>$10,000</p>"
        + f"<p style='font-size:34px;font-weight:700;color:{WHITE};margin:0 0 18px;'>The full strategy.</p>"
        + f"<p style='font-size:28px;font-weight:400;color:rgba(255,255,255,.6);line-height:1.5;margin:0;'>"
          f"Content pipeline, ads integration, ongoing growth. Built for businesses ready to scale.</p>"
        + f"</div>"
        + f"<div style='position:absolute;bottom:48px;left:72px;right:72px;"
          f"display:flex;align-items:center;justify-content:space-between;z-index:10;'>"
        + f"<span style='font-size:28px;font-weight:800;color:rgba(255,255,255,.4);'>"
          f"Improve<span style='color:{MINT};'>YourSite</span></span>"
        + f"<span style='font-size:24px;font-weight:500;color:rgba(255,255,255,.25);'>improveyoursite.com</span>"
        + f"</div>"
        + f"</div></body></html>"
    )


def slide_05_comparison():
    def row(label, them, us, them_bad=True):
        them_color = RED if them_bad else SLATE
        return (
            f"<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:0;"
            f"padding:22px 32px;border-bottom:1px solid {BORDER};align-items:center;'>"
            f"<span style='font-size:26px;font-weight:600;color:{DARK};'>{label}</span>"
            f"<span style='font-size:26px;font-weight:700;color:{them_color};text-align:center;'>{them}</span>"
            f"<span style='font-size:26px;font-weight:700;color:{GREEN};text-align:center;'>{us}</span>"
            f"</div>"
        )

    return (
        base(WHITE)
        + f"<div style='position:relative;z-index:1;width:100%;'>"
        + eyebrow("Vs. the market")
        + f"<p style='font-size:42px;font-weight:900;color:{DARK};margin:0 0 36px;line-height:1.1;'>"
          f"What others charge<br>vs. what we charge.</p>"
        + f"<div style='border:1px solid {BORDER};border-radius:16px;overflow:hidden;'>"
        + f"<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:0;"
          f"padding:18px 32px;background:{PALE};border-bottom:1px solid {BORDER};'>"
        + f"<span style='font-size:22px;font-weight:700;color:{SLATE};text-transform:uppercase;letter-spacing:.06em;'></span>"
        + f"<span style='font-size:22px;font-weight:700;color:{SLATE};text-align:center;'>Others</span>"
        + f"<span style='font-size:22px;font-weight:700;color:{INDIGO};text-align:center;'>IYS</span>"
        + f"</div>"
        + row("Agency", "$10K&ndash;$30K+", "from $3K")
        + row("Freelancer", "Unpredictable", "Fixed price")
        + row("Website builder", "$300/mo forever", "You own it")
        + row("Timeline", "3&ndash;6 months", "2&ndash;4 weeks", them_bad=True)
        + f"</div>"
        + f"</div>"
        + brand_bar()
        + f"</div></body></html>"
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
        f"<p style='font-size:72px;font-weight:900;line-height:1.1;letter-spacing:-.04em;"
        f"color:rgba(255,255,255,.8);margin:0 0 6px;'>Same result.</p>"
        f"<p style='font-size:72px;font-weight:900;line-height:1.1;letter-spacing:-.04em;"
        f"color:{WHITE};margin:0 0 6px;'>Fraction of</p>"
        f"<p style='font-size:72px;font-weight:900;line-height:1.1;letter-spacing:-.04em;"
        f"color:{WHITE};margin:0 0 60px;'>the price.</p>"
        f"<div style='width:72px;height:5px;background:{MINT};border-radius:4px;margin-bottom:52px;'></div>"
        f"<p style='font-size:30px;font-weight:500;color:rgba(255,255,255,.65);margin:0 0 40px;'>"
        f"Book a free 15-minute discovery call.</p>"
        f"<div style='display:inline-block;background:{WHITE};padding:18px 40px;border-radius:14px;'>"
        f"<span style='font-size:28px;font-weight:800;color:{INDIGO};letter-spacing:-.01em;'>"
        f"improveyoursite.com/book</span>"
        f"</div>"
        f"</div>"
        f"<div style='position:absolute;bottom:48px;left:72px;right:72px;"
        f"display:flex;align-items:center;justify-content:space-between;z-index:10;'>"
        f"<span style='font-size:28px;font-weight:800;color:rgba(255,255,255,.4);'>"
        f"Improve<span style='color:{MINT};'>YourSite</span></span>"
        f"<span style='font-size:24px;font-weight:500;color:rgba(255,255,255,.25);'>improveyoursite.com</span>"
        f"</div>"
        f"</div></body></html>"
    )


SLIDES = [
    (f"{TODAY}-value-01-cover.png",   slide_01_cover()),
    (f"{TODAY}-value-02-scanfix.png", slide_02_scan_fix()),
    (f"{TODAY}-value-03-build.png",   slide_03_complete_build()),
    (f"{TODAY}-value-04-premium.png", slide_04_premium()),
    (f"{TODAY}-value-05-compare.png", slide_05_comparison()),
    (f"{TODAY}-value-06-cta.png",     slide_06_cta()),
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
