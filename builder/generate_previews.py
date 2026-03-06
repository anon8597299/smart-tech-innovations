"""
generate_previews.py
Generates AI preview images for each demo site using Gemini Imagen.
Saves to our-work/previews/{slug}.png

Usage:
  python3 builder/generate_previews.py            # generate all 8
  python3 builder/generate_previews.py trades-rapid  # single site
"""

import os
import sys
import time
import base64
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from google import genai
from google.genai import types

API_KEY  = os.getenv("GEMINI_API_KEY")
OUT_DIR  = Path(__file__).parent.parent / "our-work" / "previews"
OUT_DIR.mkdir(parents=True, exist_ok=True)

client = genai.Client(api_key=API_KEY)

# ── Site definitions ──────────────────────────────────────────────────────────
SITES = {
    "trades-rapid": {
        "name": "Bathurst Plumbing Co.",
        "prompt": (
            "A professional website screenshot for a plumbing company called 'Bathurst Plumbing Co.' "
            "shown in a desktop browser. Dark orange and white colour scheme. "
            "Navigation bar at top with the company name and a bright orange 'Book Now' button. "
            "Large hero section with headline 'Fast, reliable plumbing — Central West NSW' on a white background "
            "with a subtle warm texture. Orange accent colour #ea580c. "
            "Below the hero: a 3-column grid of service cards (Emergency Callouts, Blocked Drains, Hot Water). "
            "Clean, modern, trustworthy design. Realistic browser chrome at top. "
            "Photorealistic UI design, not a cartoon or illustration."
        ),
    },
    "clinic-trust": {
        "name": "Hillcrest Family Clinic",
        "prompt": (
            "A professional medical clinic website screenshot for 'Hillcrest Family Clinic' shown in a desktop browser. "
            "Teal and white colour scheme, colour #0f766e. "
            "Clean navigation with clinic logo and 'Book Appointment' button in teal. "
            "Hero section with headline 'Your local GP and allied health team in Orange NSW' on a light green-white gradient. "
            "Trust strip below hero showing 'Bulk billing', 'Same-day appointments', '4.9 Google rating'. "
            "Below: a clean grid of service cards (GP, Psychology, Physio, Nutrition). "
            "Professional healthcare aesthetic, reassuring and clean. Realistic browser chrome. "
            "Photorealistic UI design."
        ),
    },
    "retail-pulse": {
        "name": "The Loft Boutique",
        "prompt": (
            "A premium women's fashion boutique website screenshot for 'The Loft Boutique' shown in a desktop browser. "
            "Warm amber, cream and white colour scheme. Elegant serif-influenced branding. "
            "Navigation with boutique name and 'Shop Now' button. "
            "Full-width hero with warm golden gradient background, headline 'Curated women's fashion — Bathurst NSW', "
            "elegant script-style typography. "
            "Below: horizontal product collection cards showing clothing categories (New Arrivals, Dresses, Accessories). "
            "Luxury boutique aesthetic, warm and inviting. Realistic browser chrome at top. "
            "Photorealistic UI design."
        ),
    },
    "advisor-prime": {
        "name": "Pinnacle Financial Advice",
        "prompt": (
            "A professional financial advisory firm website screenshot for 'Pinnacle Financial Advice' shown in a desktop browser. "
            "Deep navy blue and white colour scheme, colour #1e3a5f. "
            "Professional navigation with firm name and 'Book Free Consultation' button in navy. "
            "Two-column hero: left has headline 'Independent financial advice for Central West NSW' with trust badges, "
            "right has a white panel card showing client stats (SMSF, Retirement, $40M+ managed). "
            "Below: service grid cards (SMSF, Retirement Planning, Business Exit). "
            "Sophisticated, trustworthy financial services aesthetic. Realistic browser chrome. "
            "Photorealistic UI design."
        ),
    },
    "solar-spark": {
        "name": "SunVolt Solar",
        "prompt": (
            "A professional solar installation company website screenshot for 'SunVolt Solar' shown in a desktop browser. "
            "Blue and warm orange colour scheme, primary colour #1d4ed8 with warm orange accents. "
            "Navigation with company name and 'Get Free Quote' button in blue. "
            "Hero section on warm gradient background (light blue to warm cream), "
            "headline 'CEC accredited solar installers — Orange NSW' with a green savings badge. "
            "Below the hero: a 4-column KPI strip showing (500+ systems, 4.9 stars, 25yr warranty, 9+ years). "
            "Below: service cards (Residential Solar, Commercial, Battery Storage, STC Rebates). "
            "Clean, professional, energy-focused aesthetic. Realistic browser chrome. "
            "Photorealistic UI design."
        ),
    },
    "hospitality-events": {
        "name": "The Stonebridge Estate",
        "prompt": (
            "A luxury wedding venue website screenshot for 'The Stonebridge Estate' shown in a desktop browser. "
            "Warm cream, gold and deep amber colour scheme. Elegant typography mixing serif and sans-serif. "
            "Navigation with estate name in elegant font and 'Enquire Now' button. "
            "Full-width hero with warm parchment background, "
            "elegant headline 'Where Central West love stories begin' in large serif font, "
            "soft golden gradient overlay suggesting a warm afternoon. "
            "Below: two hero info cards showing venue details and availability. "
            "Then a KPI bar: 15 years, 5.0 stars, 42 acres, 280+ weddings. "
            "Romantic, luxurious, heritage estate aesthetic. Realistic browser chrome. "
            "Photorealistic UI design."
        ),
    },
    "consulting-authority": {
        "name": "Apex Strategy Group",
        "prompt": (
            "A premium business consulting firm website screenshot for 'Apex Strategy Group' shown in a desktop browser. "
            "Dark charcoal and white colour scheme with indigo blue accents. "
            "Professional navigation with firm name and 'Book Free Strategy Session' button. "
            "Two-column hero: left has bold headline 'Strategy that moves Central West businesses forward', "
            "trust chips and CTA buttons; right has a white statistics panel card showing client outcomes. "
            "Below: a 3-column services grid (Strategic Planning, Business Review, Exit Planning). "
            "Authority-focused, corporate, serious professional aesthetic. Realistic browser chrome. "
            "Photorealistic UI design."
        ),
    },
    "accounting-conversion": {
        "name": "Clearview Accounting",
        "prompt": (
            "A professional accounting firm website screenshot for 'Clearview Accounting' shown in a desktop browser. "
            "Teal and fresh green colour scheme, primary colour #0d9488. "
            "Navigation with firm name, 'Book Free Consult' button and phone number. "
            "Hero section on light green gradient, headline 'Clear advice. Maximum returns. No surprises.' "
            "Trust strip showing CPA Australia, Xero Gold Partner, MYOB Partner badges. "
            "Below: a 3-column services grid (Individual Tax, Business Accounting, SMSF). "
            "Then a savings highlight section showing '3 ways a good accountant pays for itself'. "
            "Professional, trustworthy, clean accounting aesthetic. Realistic browser chrome. "
            "Photorealistic UI design."
        ),
    },
}


def generate_preview(slug: str, site: dict) -> Path:
    """Generate a preview image using Gemini 2.0 Flash experimental image generation."""
    out_path = OUT_DIR / f"{slug}.png"

    print(f"  Generating: {site['name']} ({slug})...")

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp-image-generation",
            contents=site["prompt"],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )
        img_bytes = None
        for part in response.candidates[0].content.parts:
            if (hasattr(part, "inline_data") and part.inline_data
                    and part.inline_data.mime_type.startswith("image/")):
                img_bytes = part.inline_data.data
                break

        if img_bytes is None:
            print(f"    No image returned for {slug}")
            return None

    except Exception as e:
        print(f"    Failed: {e}")
        return None

    out_path.write_bytes(img_bytes)
    print(f"    Saved: {out_path} ({len(img_bytes) // 1024}KB)")
    return out_path


def main():
    if not API_KEY:
        print("ERROR: GEMINI_API_KEY not set in builder/.env")
        sys.exit(1)

    # Filter to specific slug if provided
    targets = {}
    if len(sys.argv) > 1:
        slug = sys.argv[1]
        if slug not in SITES:
            print(f"Unknown site: {slug}. Options: {', '.join(SITES.keys())}")
            sys.exit(1)
        targets[slug] = SITES[slug]
    else:
        targets = SITES

    print(f"\nGenerating {len(targets)} preview image(s)...")
    print(f"Output: {OUT_DIR}\n")

    success = 0
    for slug, site in targets.items():
        path = generate_preview(slug, site)
        if path:
            success += 1
        # Rate limit pause between requests
        if len(targets) > 1:
            time.sleep(2)

    print(f"\nDone: {success}/{len(targets)} generated successfully.")
    if success > 0:
        print(f"Images saved to: {OUT_DIR}")
        print("Run the our-work.html updater to swap in the new images.")


if __name__ == "__main__":
    main()
