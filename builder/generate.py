#!/usr/bin/env python3
"""
generate.py — Customer site generator for ImproveYourSite.

Usage:
    python generate.py --config path/to/customer.json

Workflow:
    1. Read customer config JSON
    2. Load template files from templates/{template-id}/
    3. Replace {{TOKENS}} with customer values
    4. Push all files in a single Git Tree commit via GitHub API
    5. Print the live URL

Requirements:
    pip install -r requirements.txt
    Copy .env.example to .env and set GITHUB_PAT
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Ensure builder/ is on the path when run from project root
sys.path.insert(0, str(Path(__file__).parent))

from renderer import derive_tokens, render
from github_client import push_customer_site

# Templates live at project_root/templates/
PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
GITHUB_PAGES_BASE = "https://anon8597299.github.io/smart-tech-innovations/customers"

SUPPORTED_TEMPLATES = [
    "clinic-trust", "trades-rapid", "advisor-prime", "retail-pulse",
    "solar-spark", "accounting-conversion", "consulting-authority", "hospitality-events",
]

PACKAGE_TIERS = ["starter", "growth", "premium"]


def generate_sitemap(site_url: str, html_files: list) -> str:
    """Generate a sitemap.xml listing all HTML pages in the customer site."""
    today = date.today().strftime("%Y-%m-%d")
    # index.html gets priority 1.0, everything else 0.8
    sorted_files = sorted(html_files, key=lambda f: (0 if f == "index.html" else 1, f))
    urls = []
    for filename in sorted_files:
        if filename == "index.html":
            loc = f"{site_url}/"
            priority = "1.0"
        else:
            loc = f"{site_url}/{filename}"
            priority = "0.8"
        urls.append(
            f"  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"    <changefreq>monthly</changefreq>\n"
            f"    <priority>{priority}</priority>\n"
            f"  </url>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )


def generate_robots(site_url: str) -> str:
    """Generate a robots.txt for the customer site."""
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {site_url}/sitemap.xml\n"
    )


def slugify(name: str) -> str:
    """Convert business name to a URL-safe slug."""
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        print(f"❌ Config file not found: {config_path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_config(config: dict) -> None:
    required = ["BUSINESS_NAME", "TEMPLATE_ID", "PHONE", "EMAIL", "SUBURB", "STATE"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        print(f"❌ Config is missing required fields: {', '.join(missing)}")
        sys.exit(1)
    if config["TEMPLATE_ID"] not in SUPPORTED_TEMPLATES:
        print(f"❌ Unknown TEMPLATE_ID '{config['TEMPLATE_ID']}'. "
              f"Must be one of: {', '.join(SUPPORTED_TEMPLATES)}")
        sys.exit(1)
    tier = config.get("PACKAGE_TIER", "starter").lower()
    if tier not in PACKAGE_TIERS:
        print(f"❌ Unknown PACKAGE_TIER '{tier}'. Must be one of: {', '.join(PACKAGE_TIERS)}")
        sys.exit(1)


def load_template_files(template_id: str, include_blog: bool = False) -> dict[str, str]:
    """Load all HTML/CSS files from the template directory.
    Blog folder is only included for premium package customers.
    """
    template_dir = TEMPLATES_DIR / template_id
    if not template_dir.exists():
        print(f"❌ Template directory not found: {template_dir}")
        sys.exit(1)

    files = {}
    for filepath in sorted(template_dir.rglob("*")):
        if not filepath.is_file():
            continue
        if filepath.suffix not in (".html", ".css", ".js"):
            continue
        rel = filepath.relative_to(template_dir)
        # Skip blog/ unless this is a premium customer
        if rel.parts[0] == "blog" and not include_blog:
            continue
        files[str(rel)] = filepath.read_text(encoding="utf-8")

    if not files:
        print(f"❌ No template files found in {template_dir}")
        sys.exit(1)

    return files


def generate(config_path: str, dry_run: bool = False) -> None:
    print(f"\n🏗  ImproveYourSite — Customer Site Generator")
    print(f"   Config: {config_path}\n")

    # 1. Load and validate config
    config = load_config(config_path)
    validate_config(config)

    template_id = config["TEMPLATE_ID"]
    business_name = config["BUSINESS_NAME"]
    slug = config.get("SLUG") or slugify(business_name)
    package_tier = config.get("PACKAGE_TIER", "starter").lower()
    include_blog = (package_tier == "premium")
    site_url = config.get("SITE_URL", f"{GITHUB_PAGES_BASE}/{slug}").rstrip("/")

    print(f"  Business : {business_name}")
    print(f"  Template : {template_id}")
    print(f"  Package  : {package_tier.upper()}")
    print(f"  Blog     : {'✓ included' if include_blog else '✗ not included (premium only)'}")
    print(f"  Slug     : {slug}")
    print(f"  Site URL : {site_url}")
    print()

    # 2. Derive all tokens from config
    tokens = derive_tokens(config)

    # 3. Load template files
    print(f"  Loading template: templates/{template_id}/")
    template_files = load_template_files(template_id, include_blog=include_blog)
    print(f"  Found {len(template_files)} template file(s): {', '.join(template_files.keys())}")
    print()

    # 4. Render each file
    print("  Rendering tokens...")
    rendered_files = {}
    for filename, content in template_files.items():
        rendered = render(content, tokens)
        rendered_files[filename] = rendered
        print(f"    ✓ {filename}")
    print()

    # 5. Generate sitemap.xml and robots.txt
    html_pages = [f for f in rendered_files if f.endswith(".html")]
    rendered_files["sitemap.xml"] = generate_sitemap(site_url, html_pages)
    rendered_files["robots.txt"] = generate_robots(site_url)
    print(f"  Generated sitemap.xml ({len(html_pages)} page(s))")
    print(f"  Generated robots.txt")
    print()

    if dry_run:
        print("  [DRY RUN] — files rendered but not pushed.")
        output_dir = PROJECT_ROOT / "customers" / slug
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in rendered_files.items():
            out_path = output_dir / filename
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            print(f"    Saved: {out_path.relative_to(PROJECT_ROOT)}")
        print(f"\n  Files saved to: customers/{slug}/")
        return

    # 6. Push to GitHub
    print("  Pushing to GitHub...")
    live_url = push_customer_site(
        slug=slug,
        files=rendered_files,
        commit_message=f"Add customer site: {business_name} ({template_id})",
    )

    print()
    print("=" * 58)
    print(f"  ✅ Done! Site will be live in ~90 seconds:")
    print(f"  🌐 {live_url}")
    print("=" * 58)
    print()
    print("  Next steps:")
    print("  1. Wait ~90 seconds for GitHub Pages to deploy")
    print("  2. Visit the URL above to verify the site")
    print(f"  3. Email the customer their URL: {config.get('EMAIL', '—')}")
    print(f"  4. GSC: search.google.com/search-console → Add property → HTML tag method")
    print(f"     Copy verification code → add GSC_VERIFICATION_CODE to config → re-run generator")
    print(f"     Then submit: {site_url}/sitemap.xml")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Generate a customer site from a JSON config and push to GitHub Pages."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the customer JSON config file (e.g. builder/config-example.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render files locally without pushing to GitHub",
    )
    args = parser.parse_args()
    generate(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
