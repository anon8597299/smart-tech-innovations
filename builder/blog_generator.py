#!/usr/bin/env python3
"""
blog_generator.py — AI-powered blog post generator for ImproveYourSite customers.

Usage:
    python blog_generator.py --config customer.json --topic "5 signs your hot water system needs replacing"
    python blog_generator.py --config customer.json --auto   # generates all 3 default posts for the industry

Requires:
    ANTHROPIC_API_KEY in .env
    pip install anthropic python-dotenv
"""

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure builder/ is on the path when run from project root
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Industry default topics — used in --auto mode
# ---------------------------------------------------------------------------

INDUSTRY_TOPICS = {
    "trades-rapid": [
        "5 signs your plumbing needs urgent attention in {SUBURB}",
        "How much does a plumber cost in {SUBURB}, {STATE}? A 2026 guide",
        "How to choose a licensed tradie in {SUBURB}: what to look for",
    ],
    "clinic-trust": [
        "When to see a GP vs wait it out: a guide for {SUBURB} residents",
        "How to find the right doctor in {SUBURB}: a local guide",
        "Understanding bulk billing in {SUBURB}: what patients need to know",
    ],
    "solar-spark": [
        "Is solar worth it in {SUBURB}, {STATE}? A 2026 honest guide",
        "Solar rebates and incentives available to {SUBURB} homeowners in 2026",
        "How much can solar panels save you in {SUBURB}? Real numbers explained",
    ],
    "accounting-conversion": [
        "Tax tips for small business owners in {SUBURB}, {STATE}: 2026 edition",
        "BAS lodgement guide for {SUBURB} business owners",
        "Signs you need an accountant: a practical guide for {SUBURB} businesses",
    ],
    "consulting-authority": [
        "Business growth strategies for {SUBURB} SMEs in 2026",
        "When to hire a business consultant: a guide for {SUBURB} business owners",
        "How to improve profit margins: practical advice for {SUBURB} businesses",
    ],
    "hospitality-events": [
        "Planning the perfect wedding in {SUBURB}: a complete venue guide",
        "Corporate event planning in {SUBURB}: what to look for in a venue",
        "Top questions to ask your event venue in {SUBURB} before booking",
    ],
    "advisor-prime": [
        "Retirement planning in {SUBURB}, {STATE}: when to start and what to consider",
        "Investment strategies for {SUBURB} professionals in 2026",
        "How to choose a financial adviser in {SUBURB}: a practical guide",
    ],
    "retail-pulse": [
        "Supporting local fashion in {SUBURB}: why shopping local matters in 2026",
        "Autumn fashion trends 2026: what to look for at your local {SUBURB} boutique",
        "Gift ideas from {SUBURB}: styling tips for every occasion",
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent


def slugify(text: str) -> str:
    """Convert a string to a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_slug(config: dict) -> str:
    """Return the customer slug, derived from SLUG field or BUSINESS_NAME."""
    return config.get("SLUG") or slugify(config.get("BUSINESS_NAME", "customer"))


def interpolate_topic(topic_template: str, config: dict) -> str:
    """Replace {SUBURB} and {STATE} placeholders in a topic template string."""
    return topic_template.format(
        SUBURB=config.get("SUBURB", "your area"),
        STATE=config.get("STATE", ""),
    )


def derive_color_primary(config: dict) -> str:
    primary_defaults = {
        "clinic-trust":         "#0f766e",
        "trades-rapid":         "#d97706",
        "advisor-prime":        "#1d4ed8",
        "retail-pulse":         "#7c3aed",
        "solar-spark":          "#16a34a",
        "accounting-conversion": "#0369a1",
        "consulting-authority": "#1e40af",
        "hospitality-events":   "#9f1239",
    }
    if "COLOR_PRIMARY" in config:
        return config["COLOR_PRIMARY"]
    return primary_defaults.get(config.get("TEMPLATE_ID", ""), "#5b4dff")


def derive_color_bg(config: dict) -> str:
    bg_defaults = {
        "clinic-trust":         "#f4fbfb",
        "trades-rapid":         "#fffaf5",
        "advisor-prime":        "#f6f8ff",
        "retail-pulse":         "#f8f7ff",
        "solar-spark":          "#f0fdf4",
        "accounting-conversion": "#f0f9ff",
        "consulting-authority": "#f5f8ff",
        "hospitality-events":   "#fff1f2",
    }
    if "COLOR_BG" in config:
        return config["COLOR_BG"]
    return bg_defaults.get(config.get("TEMPLATE_ID", ""), "#f8fafc")


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def generate_article_html(topic: str, config: dict, client) -> str:
    """
    Call the Claude API and return the raw <article> HTML for the blog post.
    """
    business_name = config.get("BUSINESS_NAME", "the business")
    suburb = config.get("SUBURB", "your area")
    state = config.get("STATE", "")
    phone = config.get("PHONE", "")
    location = f"{suburb}, {state}".strip(", ")

    system_prompt = (
        "You are an expert SEO copywriter for Australian small businesses. "
        "You write clear, helpful, locally-relevant blog posts in clean HTML. "
        "You never use markdown — only HTML tags. "
        "You do not wrap the output in a full HTML page; you output only the content "
        "that belongs inside an <article> element."
    )

    user_prompt = f"""Write a blog post with the following details:

Topic: {topic}
Business name: {business_name}
Location: {location}
Phone number: {phone}

Requirements:
- Output ONLY the HTML content that would go inside an <article> element.
- Do NOT include <html>, <head>, <body>, <article> wrapper tags — just the inner content.
- 600–800 words total.
- Start with an <h1> that is the blog post title (can be slightly reworded from the topic for SEO).
- Use <h2> and <h3> subheadings to structure the post logically.
- Use <p>, <ul>, <li>, <strong> tags as appropriate — no markdown, no asterisks.
- Naturally weave in {suburb}{(', ' + state) if state else ''} and {business_name} throughout.
- End with a call-to-action <p> that references {business_name} and encourages the reader to get in touch.
- Write in a friendly, trustworthy Australian voice — helpful and informative, not salesy.
- Do NOT include any markdown, backticks, code fences, or commentary outside the HTML tags.
"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt,
    )

    return message.content[0].text.strip()


# ---------------------------------------------------------------------------
# HTML page wrapper
# ---------------------------------------------------------------------------

def build_full_page(article_html: str, topic: str, config: dict) -> str:
    """
    Wrap the raw article HTML in a full, standalone HTML page.
    Fills in real values from config — no {{TOKEN}} placeholders remain.
    """
    business_name = config.get("BUSINESS_NAME", "")
    phone = config.get("PHONE", "")
    suburb = config.get("SUBURB", "")
    state = config.get("STATE", "")
    email = config.get("EMAIL", "")
    address = config.get("ADDRESS", "")
    postcode = config.get("POSTCODE", "")
    color_primary = derive_color_primary(config)
    color_bg = derive_color_bg(config)
    today = date.today().isoformat()
    year = date.today().year

    # Derive a sensible meta title and description from the topic
    meta_title = f"{topic} | {business_name}"
    meta_description = (
        f"{business_name} shares expert advice: {topic.lower()}. "
        f"Serving {suburb}{(', ' + state) if state else ''}."
    )
    # Truncate meta description to 160 chars
    if len(meta_description) > 160:
        meta_description = meta_description[:157].rstrip() + "..."

    # Schema.org structured data
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": topic,
        "author": {
            "@type": "Organization",
            "name": business_name,
        },
        "publisher": {
            "@type": "Organization",
            "name": business_name,
        },
        "datePublished": today,
        "dateModified": today,
        "description": meta_description,
    }

    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)

    # Build a light address string for the footer
    address_parts = [p for p in [address, suburb, state, postcode] if p]
    address_str = ", ".join(address_parts)

    # Pre-compute phone/email links (backslashes not allowed inside f-string expressions)
    phone_digits = re.sub(r"\s", "", phone)
    phone_link = f'<a href="tel:{phone_digits}">{phone}</a>' if phone else ""
    email_link = f'<a href="mailto:{email}">{email}</a>' if email else ""
    footer_phone = phone_link
    footer_email = f" &mdash; {email_link}" if email_link else ""
    footer_address = f"{address_str} &mdash;" if address_str else ""

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="robots" content="index, follow">
  <title>{meta_title}</title>
  <meta name="description" content="{meta_description}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script type="application/ld+json">
{schema_json}
  </script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --primary: {color_primary};
      --bg: {color_bg};
      --text: #1a1a2e;
      --muted: #6b7280;
      --border: #e5e7eb;
      --max-w: 720px;
    }}

    body {{
      font-family: 'Inter', sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.7;
      font-size: 1rem;
    }}

    /* ---- Nav ---- */
    .site-nav {{
      background: #fff;
      border-bottom: 1px solid var(--border);
      padding: 0 1.5rem;
    }}
    .nav-inner {{
      max-width: var(--max-w);
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 56px;
    }}
    .nav-brand {{
      font-weight: 700;
      font-size: 1rem;
      color: var(--text);
      text-decoration: none;
    }}
    .nav-links a {{
      font-size: 0.875rem;
      color: var(--muted);
      text-decoration: none;
      margin-left: 1.25rem;
      transition: color 0.15s;
    }}
    .nav-links a:hover {{ color: var(--primary); }}

    /* ---- Article layout ---- */
    .article-wrap {{
      max-width: var(--max-w);
      margin: 0 auto;
      padding: 3rem 1.5rem 4rem;
    }}

    .article-meta {{
      font-size: 0.8125rem;
      color: var(--muted);
      margin-bottom: 2rem;
      display: flex;
      gap: 1rem;
      flex-wrap: wrap;
    }}

    article h1 {{
      font-size: clamp(1.5rem, 4vw, 2.125rem);
      font-weight: 700;
      line-height: 1.25;
      color: var(--text);
      margin-bottom: 0.75rem;
    }}

    article h2 {{
      font-size: 1.375rem;
      font-weight: 700;
      color: var(--text);
      margin: 2rem 0 0.6rem;
    }}

    article h3 {{
      font-size: 1.125rem;
      font-weight: 600;
      color: var(--text);
      margin: 1.5rem 0 0.5rem;
    }}

    article p {{
      margin-bottom: 1.1rem;
      color: var(--text);
    }}

    article ul, article ol {{
      margin: 0.5rem 0 1.25rem 1.5rem;
    }}

    article li {{
      margin-bottom: 0.4rem;
    }}

    article strong {{
      font-weight: 600;
      color: var(--text);
    }}

    article a {{
      color: var(--primary);
      text-decoration: underline;
    }}

    /* ---- CTA box ---- */
    .cta-box {{
      background: var(--primary);
      color: #fff;
      border-radius: 10px;
      padding: 2rem 1.75rem;
      margin-top: 3rem;
      text-align: center;
    }}
    .cta-box p {{
      color: #fff;
      font-size: 1.0625rem;
      margin-bottom: 1rem;
    }}
    .cta-box a.cta-btn {{
      display: inline-block;
      background: #fff;
      color: var(--primary);
      font-weight: 700;
      font-size: 0.9375rem;
      padding: 0.65rem 1.5rem;
      border-radius: 6px;
      text-decoration: none;
      transition: opacity 0.15s;
    }}
    .cta-box a.cta-btn:hover {{ opacity: 0.9; }}

    /* ---- Footer ---- */
    .site-footer {{
      border-top: 1px solid var(--border);
      background: #fff;
      padding: 2rem 1.5rem;
      text-align: center;
      font-size: 0.8125rem;
      color: var(--muted);
    }}
    .site-footer a {{
      color: var(--muted);
      text-decoration: none;
    }}

    /* ---- Back to blog link ---- */
    .back-link {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.875rem;
      color: var(--muted);
      text-decoration: none;
      margin-bottom: 1.75rem;
      transition: color 0.15s;
    }}
    .back-link:hover {{ color: var(--primary); }}

    @media (max-width: 600px) {{
      .article-wrap {{ padding: 2rem 1rem 3rem; }}
    }}
  </style>
</head>
<body>

  <nav class="site-nav" aria-label="Site navigation">
    <div class="nav-inner">
      <a class="nav-brand" href="../index.html">{business_name}</a>
      <div class="nav-links">
        <a href="../index.html">Home</a>
        <a href="index.html">Blog</a>
        <a href="../index.html#contact">Contact</a>
      </div>
    </div>
  </nav>

  <main>
    <div class="article-wrap">

      <a class="back-link" href="index.html">
        &#8592; Back to blog
      </a>

      <div class="article-meta">
        <span>Published {today}</span>
        <span>By {business_name}</span>
        <span>{suburb}{(', ' + state) if state else ''}</span>
      </div>

      <article>
{article_html}
      </article>

      <div class="cta-box">
        <p>Ready to work with <strong>{business_name}</strong>?
           Give us a call on <strong>{phone}</strong> or visit our website to learn more.</p>
        <a class="cta-btn" href="../index.html">Visit our website</a>
      </div>

    </div>
  </main>

  <footer class="site-footer">
    <p>
      &copy; {year} {business_name}.
      {footer_address}
      {footer_phone}{footer_email}
    </p>
  </footer>

</body>
</html>"""

    return page


# ---------------------------------------------------------------------------
# Blog index page builder
# ---------------------------------------------------------------------------

def build_blog_index(blog_dir: Path, config: dict) -> str:
    """
    Scan the blog directory for .html files (excluding index.html itself)
    and build a listing page.
    """
    business_name = config.get("BUSINESS_NAME", "")
    suburb = config.get("SUBURB", "")
    state = config.get("STATE", "")
    phone = config.get("PHONE", "")
    email = config.get("EMAIL", "")
    address = config.get("ADDRESS", "")
    postcode = config.get("POSTCODE", "")
    color_primary = derive_color_primary(config)
    color_bg = derive_color_bg(config)
    year = date.today().year

    address_parts = [p for p in [address, suburb, state, postcode] if p]
    address_str = ", ".join(address_parts)

    # Pre-compute phone/email links (backslashes not allowed inside f-string expressions)
    phone_digits = re.sub(r"\s", "", phone)
    phone_link = f'<a href="tel:{phone_digits}">{phone}</a>' if phone else ""
    email_link = f'<a href="mailto:{email}">{email}</a>' if email else ""
    footer_phone = phone_link
    footer_email = f" &mdash; {email_link}" if email_link else ""
    footer_address = f"{address_str} &mdash;" if address_str else ""

    # Collect post files
    post_files = sorted(
        [f for f in blog_dir.glob("*.html") if f.name != "index.html"],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    # Build list items
    post_items_html = ""
    if post_files:
        for post_file in post_files:
            # Derive a human-readable title from the filename slug
            slug = post_file.stem
            title = slug.replace("-", " ").title()

            # Try to read the actual <h1> from the file for a better title
            try:
                content = post_file.read_text(encoding="utf-8")
                h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.IGNORECASE | re.DOTALL)
                if h1_match:
                    title = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
            except Exception:
                pass

            post_items_html += f"""
      <li class="post-item">
        <a href="{post_file.name}" class="post-link">
          <span class="post-title">{title}</span>
          <span class="post-arrow">&#8594;</span>
        </a>
      </li>"""
    else:
        post_items_html = "\n      <li class=\"no-posts\">No posts yet — check back soon.</li>"

    meta_title = f"Blog | {business_name}"
    meta_desc = (
        f"Expert tips and local guides from {business_name} in "
        f"{suburb}{(', ' + state) if state else ''}."
    )
    if len(meta_desc) > 160:
        meta_desc = meta_desc[:157].rstrip() + "..."

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="robots" content="index, follow">
  <title>{meta_title}</title>
  <meta name="description" content="{meta_desc}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --primary: {color_primary};
      --bg: {color_bg};
      --text: #1a1a2e;
      --muted: #6b7280;
      --border: #e5e7eb;
      --max-w: 720px;
    }}

    body {{
      font-family: 'Inter', sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.7;
      font-size: 1rem;
    }}

    .site-nav {{
      background: #fff;
      border-bottom: 1px solid var(--border);
      padding: 0 1.5rem;
    }}
    .nav-inner {{
      max-width: var(--max-w);
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 56px;
    }}
    .nav-brand {{
      font-weight: 700;
      font-size: 1rem;
      color: var(--text);
      text-decoration: none;
    }}
    .nav-links a {{
      font-size: 0.875rem;
      color: var(--muted);
      text-decoration: none;
      margin-left: 1.25rem;
      transition: color 0.15s;
    }}
    .nav-links a:hover {{ color: var(--primary); }}

    .page-wrap {{
      max-width: var(--max-w);
      margin: 0 auto;
      padding: 3rem 1.5rem 4rem;
    }}

    .page-heading {{
      font-size: clamp(1.5rem, 4vw, 2rem);
      font-weight: 700;
      margin-bottom: 0.5rem;
    }}

    .page-subheading {{
      font-size: 1rem;
      color: var(--muted);
      margin-bottom: 2.5rem;
    }}

    .post-list {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }}

    .post-item {{
      background: #fff;
      border: 1px solid var(--border);
      border-radius: 8px;
      transition: border-color 0.15s, box-shadow 0.15s;
    }}
    .post-item:hover {{
      border-color: var(--primary);
      box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    }}

    .post-link {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 1.1rem 1.25rem;
      text-decoration: none;
      color: var(--text);
      gap: 1rem;
    }}

    .post-title {{
      font-weight: 500;
      font-size: 0.9375rem;
    }}

    .post-arrow {{
      color: var(--primary);
      font-size: 1rem;
      flex-shrink: 0;
    }}

    .no-posts {{
      color: var(--muted);
      font-size: 0.9375rem;
      padding: 1rem 0;
    }}

    .site-footer {{
      border-top: 1px solid var(--border);
      background: #fff;
      padding: 2rem 1.5rem;
      text-align: center;
      font-size: 0.8125rem;
      color: var(--muted);
    }}
    .site-footer a {{
      color: var(--muted);
      text-decoration: none;
    }}

    @media (max-width: 600px) {{
      .page-wrap {{ padding: 2rem 1rem 3rem; }}
    }}
  </style>
</head>
<body>

  <nav class="site-nav" aria-label="Site navigation">
    <div class="nav-inner">
      <a class="nav-brand" href="../index.html">{business_name}</a>
      <div class="nav-links">
        <a href="../index.html">Home</a>
        <a href="index.html">Blog</a>
        <a href="../index.html#contact">Contact</a>
      </div>
    </div>
  </nav>

  <main>
    <div class="page-wrap">
      <h1 class="page-heading">Blog</h1>
      <p class="page-subheading">
        Expert tips and local guides from {business_name}
        {(' in ' + suburb + (', ' + state if state else '')) if suburb else ''}.
      </p>

      <ul class="post-list">{post_items_html}
      </ul>
    </div>
  </main>

  <footer class="site-footer">
    <p>
      &copy; {year} {business_name}.
      {footer_address}
      {footer_phone}{footer_email}
    </p>
  </footer>

</body>
</html>"""

    return page


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------

def generate_post(topic: str, config: dict, client, dry_run: bool = False) -> Path:
    """
    Generate a single blog post for the given topic and save it.
    Returns the path of the saved file.
    """
    slug = resolve_slug(config)
    topic_slug = slugify(topic)

    blog_dir = PROJECT_ROOT / "customers" / slug / "blog"
    blog_dir.mkdir(parents=True, exist_ok=True)

    out_path = blog_dir / f"{topic_slug}.html"

    print(f"  Generating: {topic}")

    if dry_run:
        article_html = (
            "<h1>Dry run — no API call made</h1>\n"
            f"<p>Topic: {topic}</p>\n"
            f"<p>This file would be saved to: {out_path}</p>"
        )
        print("    [DRY RUN] Skipping Claude API call.")
    else:
        print("    Calling Claude API...", end="", flush=True)
        article_html = generate_article_html(topic, config, client)
        print(" done.")

    full_page = build_full_page(article_html, topic, config)
    out_path.write_text(full_page, encoding="utf-8")
    print(f"    Saved: {out_path.relative_to(PROJECT_ROOT)}")

    return out_path


def update_blog_index(config: dict) -> Path:
    """Regenerate the blog/index.html listing page."""
    slug = resolve_slug(config)
    blog_dir = PROJECT_ROOT / "customers" / slug / "blog"
    blog_dir.mkdir(parents=True, exist_ok=True)

    index_path = blog_dir / "index.html"
    content = build_blog_index(blog_dir, config)
    index_path.write_text(content, encoding="utf-8")
    print(f"    Updated: {index_path.relative_to(PROJECT_ROOT)}")

    return index_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate AI-powered SEO blog posts for ImproveYourSite customers."
        )
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the customer JSON config file (e.g. builder/config-example.json)",
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--topic",
        metavar="TOPIC",
        help='Blog post topic, e.g. "5 signs your hot water system needs replacing"',
    )
    mode_group.add_argument(
        "--auto",
        action="store_true",
        help="Generate all 3 default posts for the customer's TEMPLATE_ID industry",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the Claude API call and save placeholder HTML only",
    )

    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load environment variables
    # ------------------------------------------------------------------
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        print(
            "Error: ANTHROPIC_API_KEY not found.\n"
            f"Add it to {env_path} or set it as an environment variable."
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # Load customer config
    # ------------------------------------------------------------------
    config = load_config(args.config)

    business_name = config.get("BUSINESS_NAME", "Unknown")
    template_id = config.get("TEMPLATE_ID", "")
    slug = resolve_slug(config)

    print(f"\nImproveYourSite — Blog Generator")
    print(f"  Business : {business_name}")
    print(f"  Template : {template_id}")
    print(f"  Slug     : {slug}")
    print(f"  Output   : customers/{slug}/blog/")
    if args.dry_run:
        print("  Mode     : DRY RUN (no API calls)")
    print()

    # ------------------------------------------------------------------
    # Initialise the Anthropic client (lazily, so --dry-run never imports it)
    # ------------------------------------------------------------------
    client = None
    if not args.dry_run:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            print(
                "Error: The 'anthropic' package is not installed.\n"
                "Run: pip install anthropic"
            )
            sys.exit(1)

    # ------------------------------------------------------------------
    # Determine topics to generate
    # ------------------------------------------------------------------
    if args.auto:
        if template_id not in INDUSTRY_TOPICS:
            print(
                f"Error: No default topics defined for TEMPLATE_ID '{template_id}'.\n"
                f"Available: {', '.join(INDUSTRY_TOPICS.keys())}"
            )
            sys.exit(1)
        topics = [
            interpolate_topic(t, config)
            for t in INDUSTRY_TOPICS[template_id]
        ]
        print(f"  Auto mode: generating {len(topics)} posts for '{template_id}'\n")
    else:
        topics = [args.topic]

    # ------------------------------------------------------------------
    # Generate each post
    # ------------------------------------------------------------------
    generated = []
    for topic in topics:
        try:
            path = generate_post(topic, config, client, dry_run=args.dry_run)
            generated.append(path)
        except Exception as exc:
            print(f"    Error generating '{topic}': {exc}")
            if not args.auto:
                sys.exit(1)

    # ------------------------------------------------------------------
    # Update the blog index page
    # ------------------------------------------------------------------
    print()
    print("  Updating blog index...")
    update_blog_index(config)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print(f"  Done! {len(generated)} post(s) generated.")
    for p in generated:
        print(f"  - {p.relative_to(PROJECT_ROOT)}")
    blog_rel = f"customers/{slug}/blog/index.html"
    print(f"  - {blog_rel}  (index updated)")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
