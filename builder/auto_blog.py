#!/usr/bin/env python3
"""
auto_blog.py — Scheduled auto-generator for customer blog posts.

Reads customers/registry.json, calls Perplexity AI (sonar — web-search
grounded) for each blog-enabled customer, renders the shared post template,
and injects a card into the customer's blog/index.html.

Designed to run via GitHub Actions (blog-autogen.yml) weekly.

Environment variables:
    PERPLEXITY_KEY  — Perplexity API key (GitHub Secret)
    TARGET_SLUG     — Limit to one customer slug (optional, for manual runs)

Usage (local test):
    PERPLEXITY_KEY=pplx-... python builder/auto_blog.py
    PERPLEXITY_KEY=pplx-... TARGET_SLUG=smiths-plumbing python builder/auto_blog.py
"""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

try:
    import requests
except ImportError:
    print("❌ Missing 'requests'. Run: pip install requests")
    sys.exit(1)

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT  = Path(__file__).parent.parent
REGISTRY      = PROJECT_ROOT / "customers" / "registry.json"
POST_TEMPLATE = PROJECT_ROOT / "templates" / "shared" / "auto-blog-post.html"
CUSTOMERS_DIR = PROJECT_ROOT / "customers"

# ── Config ─────────────────────────────────────────────────────────────────────
PERPLEXITY_KEY = os.environ.get("PERPLEXITY_KEY", "").strip()
TARGET_SLUG    = os.environ.get("TARGET_SLUG", "").strip()

# Category label displayed as the post tag, keyed by template ID
CATEGORY_MAP = {
    "trades-rapid":          "Trade Tips",
    "clinic-trust":          "Health Tips",
    "advisor-prime":         "Business Insights",
    "accounting-conversion": "Finance Tips",
    "retail-pulse":          "Style & Shopping",
    "solar-spark":           "Energy Tips",
    "hospitality-events":    "Events & Dining",
    "consulting-authority":  "Business Insights",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_registry() -> list:
    if not REGISTRY.exists():
        return []
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def post_slug(title: str, max_len: int = 60) -> str:
    """Convert a title to a URL-safe slug, capped at max_len chars."""
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:max_len]


def read_time(html: str) -> str:
    words = len(re.sub(r"<[^>]+>", " ", html).split())
    return f"{max(1, round(words / 200))} min"


# ── Perplexity API ─────────────────────────────────────────────────────────────

def call_perplexity(customer: dict, month_year: str) -> dict:
    """
    Call Perplexity sonar (web-search grounded) to generate a blog post.

    Returns a dict with:
        title        — SEO blog title
        excerpt      — 1-2 sentence card summary
        category     — tag label (e.g. "Trade Tips")
        cta_text     — call-to-action sentence for the CTA box
        content_html — HTML body (<p>, <h2>, <h3>, <ul>, <li>, <strong>, <em>)
    """
    biz      = customer.get("biz", "local business")
    name     = customer["name"]
    suburb   = customer.get("suburb", "")
    state    = customer.get("state", "Australia")
    extras   = customer.get("topics_extra", "").strip()
    template = customer.get("template", "trades-rapid")
    category = CATEGORY_MAP.get(template, "Local Tips")

    prompt = f"""Write a Google SEO-optimised blog post for {name}, a {biz} based in {suburb}, {state}, Australia.

The PRIMARY goal is to rank on Google for local search terms like "{biz} {suburb}", "{biz} {state}", and related questions people search for.

The post is for {month_year}. Requirements:

SEO requirements (most important):
- Choose a title targeting a specific search query people actually Google — e.g. "How Much Does a Solar System Cost on the Gold Coast in 2026?" or "Best Plumber in Bathurst: What to Look For"
- Include the primary keyword ({biz} + {suburb} or {state}) naturally in the first paragraph
- Each h2 subheading should target a related search question (e.g. "How long does solar installation take in {suburb}?")
- Use specific local details — street names, landmarks, local councils, regional weather, local regulations — so Google recognises it as genuinely local content
- Include real numbers, costs, timeframes, or stats where relevant (use current {month_year} data from your web search)
- 700–900 words — longer posts rank better for competitive local keywords

Content requirements:
- Answer the question the title asks — genuinely useful, not waffle
- Reflect current trends or news relevant to {biz} in {state} for {month_year}
- Friendly, trustworthy Australian voice — not salesy, not generic
- End with a natural call-to-action mentioning {name} and {suburb}
{f'- Prioritise these specific topics/services: {extras}' if extras else ''}

Return ONLY a JSON object with no markdown code fences and no extra text before or after:
{{
  "title": "Keyword-targeted title a {suburb} resident would actually Google",
  "excerpt": "1-2 sentence summary suitable for a blog listing card.",
  "category": "{category}",
  "cta_text": "One sentence specific to this {biz}, encouraging the reader to call or book.",
  "content_html": "<p>Intro paragraph...</p><h2>First Subheading</h2><p>...</p>"
}}

content_html may ONLY use these HTML tags: <p> <h2> <h3> <ul> <ol> <li> <strong> <em>
Do not use any other tags. Do not use markdown."""

    response = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={
            "Authorization": f"Bearer {PERPLEXITY_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "model": "sonar",
            "messages": [
                {
                    "role":    "system",
                    "content": (
                        "You are an expert content writer for Australian small businesses. "
                        "Return only valid JSON. Never use markdown code fences."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        },
        timeout=90,
    )
    response.raise_for_status()

    raw = response.json()["choices"][0]["message"]["content"].strip()
    # Strip markdown fences in case the model includes them anyway
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$",        "", raw, flags=re.MULTILINE)

    return json.loads(raw)


# ── Template rendering ─────────────────────────────────────────────────────────

def render(template_html: str, tokens: dict) -> str:
    return re.sub(
        r"\{\{([A-Z0-9_]+)\}\}",
        lambda m: str(tokens.get(m.group(1), m.group(0))),
        template_html,
    )


# ── Blog index card injection ──────────────────────────────────────────────────

def inject_post_card(index_html: str, card_html: str) -> str | None:
    """
    Prepend a new post card into the post-grid.
    Tries the explicit <!-- AUTO_POSTS_START --> marker first,
    then falls back to a regex on the post-grid opening tag.
    Returns updated HTML, or None if no injection point was found.
    """
    marker = "<!-- AUTO_POSTS_START -->"
    if marker in index_html:
        return index_html.replace(marker, marker + "\n" + card_html, 1)

    # Fallback: insert directly after the post-grid opening div
    m = re.search(r'(<div[^>]+class="post-grid"[^>]*>)', index_html)
    if m:
        idx = m.end()
        return index_html[:idx] + "\n" + card_html + index_html[idx:]

    return None  # couldn't find an injection point


# ── Per-customer generation ────────────────────────────────────────────────────

def generate_for_customer(customer: dict, template_html: str, month_year: str) -> str:
    """Generate one blog post for the customer and inject its card into blog/index.html."""
    slug          = customer["slug"]
    name          = customer["name"]
    color_primary = customer.get("color_primary", "#5b4dff")
    color_bg      = customer.get("color_bg",      "#f8fafc")
    phone         = customer.get("phone",  "")
    email         = customer.get("email",  "")
    suburb        = customer.get("suburb", "")
    state         = customer.get("state",  "NSW")

    blog_dir = CUSTOMERS_DIR / slug / "blog"
    blog_dir.mkdir(parents=True, exist_ok=True)

    today        = date.today()
    date_str     = today.strftime("%Y-%m-%d")
    date_display = today.strftime("%-d %B %Y")

    print(f"\n  [{slug}] Calling Perplexity for {month_year}...")
    post_data = call_perplexity(customer, month_year)

    title    = post_data["title"]
    excerpt  = post_data["excerpt"]
    category = post_data.get("category", CATEGORY_MAP.get(customer.get("template", ""), "Local Tips"))
    cta_text = post_data.get("cta_text", f"Get in touch with {name} today.")
    content  = post_data["content_html"]

    print(f'  [{slug}] ✓ "{title}"')

    filename = f"{date_str}-{post_slug(title)}.html"

    tokens = {
        "BUSINESS_NAME":  name,
        "POST_TITLE":     title,
        "POST_EXCERPT":   excerpt,
        "POST_CONTENT":   content,
        "POST_DATE":      date_display,
        "POST_DATE_ISO":  date_str,
        "POST_CATEGORY":  category,
        "POST_CTA_TEXT":  cta_text,
        "POST_READ_TIME": read_time(content),
        "COLOR_PRIMARY":  color_primary,
        "COLOR_BG":       color_bg,
        "PHONE":          phone,
        "EMAIL":          email,
        "SUBURB":         suburb,
        "STATE":          state,
    }

    rendered  = render(template_html, tokens)
    post_path = blog_dir / filename
    post_path.write_text(rendered, encoding="utf-8")
    print(f"  [{slug}] ✓ Saved: customers/{slug}/blog/{filename}")

    # ── Inject card into blog/index.html ──────────────────────────────────────
    index_path = blog_dir / "index.html"
    if index_path.exists():
        card_html = (
            f'      <div class="post-card">\n'
            f'        <span class="tag">{category}</span>\n'
            f'        <h3>{title}</h3>\n'
            f'        <p>{excerpt}</p>\n'
            f'        <a class="read" href="{filename}">Read article &rarr;</a>\n'
            f'      </div>'
        )
        updated = inject_post_card(index_path.read_text(encoding="utf-8"), card_html)
        if updated:
            index_path.write_text(updated, encoding="utf-8")
            print(f"  [{slug}] ✓ Updated blog/index.html")
        else:
            print(
                f"  [{slug}] ⚠ Could not inject card into blog/index.html "
                f"— post accessible at /blog/{filename}"
            )
    else:
        print(f"  [{slug}] ℹ No blog/index.html — post at /blog/{filename}")

    return filename


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    if not PERPLEXITY_KEY:
        print("❌ PERPLEXITY_KEY environment variable not set.")
        print("   Add it as a GitHub Actions secret:")
        print("   Settings → Secrets and variables → Actions → New repository secret")
        sys.exit(1)

    if not POST_TEMPLATE.exists():
        print(f"❌ Post template not found: {POST_TEMPLATE}")
        sys.exit(1)

    template_html = POST_TEMPLATE.read_text(encoding="utf-8")
    registry      = load_registry()

    if not registry:
        print("ℹ customers/registry.json is empty — no customers to update.")
        print("  Customers are added automatically when deployed via fix.html.")
        return

    month_year = date.today().strftime("%B %Y")
    print(f"\n🤖  IYS Auto Blog — {month_year}")

    # Filter: blog-enabled, optionally only one slug
    customers = [c for c in registry if c.get("blog")]
    if TARGET_SLUG:
        customers = [c for c in customers if c["slug"] == TARGET_SLUG]
        if not customers:
            print(f'ℹ No blog-enabled customer with slug "{TARGET_SLUG}".')
            print(f'  Check registry.json — slug must exist and have "blog": true.')
            return
        print(f"   Targeting slug: {TARGET_SLUG}")
    else:
        print(f"   {len(customers)} blog-enabled customer(s)")

    if not customers:
        print('ℹ No blog-enabled customers. Set "blog": true in customers/registry.json.')
        return

    errors = []
    for customer in customers:
        try:
            generate_for_customer(customer, template_html, month_year)
        except Exception as exc:
            print(f"  ❌ Error [{customer['slug']}]: {exc}")
            errors.append(customer["slug"])

    print(f"\n{'✅' if not errors else '⚠'} Done — {len(customers) - len(errors)}/{len(customers)} succeeded.")
    if errors:
        print(f"   Failed slugs: {', '.join(errors)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
