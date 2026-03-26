"""
agents/ads_onboard.py — Interactive CLI to onboard a new Google Ads client.

Usage:
    python agents/ads_onboard.py [--list] [--remove SLUG] [--run SLUG]

Options:
    (no args)       Walk through the full onboarding wizard
    --list          List all onboarded clients
    --remove SLUG   Deactivate a client by slug
    --run SLUG      Manually trigger ads agent for a specific client
    --run-all       Run the agent for all active clients right now

The wizard collects:
  1. Company details (name, slug, contact email)
  2. Google Ads credentials (developer token, customer ID)
  3. OAuth credentials (client ID, client secret)
  4. Refresh token (generated via browser OAuth flow or pasted manually)
  5. KPI threshold customisation (optional — press Enter to keep defaults)
  6. Saves to DB and runs first report

Credentials are stored in the local SQLite DB (dashboard/iys_agents.db).
They never touch builder/.env — each client is fully isolated.
"""

from __future__ import annotations

import json
import re
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "builder" / ".env")

from dashboard import db


# ── Colour helpers (terminal only, falls back gracefully) ─────────────────────

def _c(text, code): return f"\033[{code}m{text}\033[0m"
def bold(t):   return _c(t, "1")
def green(t):  return _c(t, "32")
def yellow(t): return _c(t, "33")
def red(t):    return _c(t, "31")
def cyan(t):   return _c(t, "36")
def dim(t):    return _c(t, "2")


def _hr(char="─", width=62):
    print(dim(char * width))


def _ask(prompt: str, default: str = "", required: bool = True) -> str:
    """Prompt user for input. Returns default if Enter pressed (when default set)."""
    display = f"  {prompt}"
    if default:
        display += f" [{dim(default)}]"
    display += " : "
    while True:
        val = input(display).strip()
        if not val and default:
            return default
        if val:
            return val
        if not required:
            return ""
        print(red("  ✗ Required — please enter a value"))


def _ask_float(prompt: str, default: float) -> float:
    while True:
        raw = _ask(prompt, str(default), required=False)
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            print(red("  ✗ Must be a number"))


def _ask_int(prompt: str, default: int) -> int:
    while True:
        raw = _ask(prompt, str(default), required=False)
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print(red("  ✗ Must be a whole number"))


def _slugify(text: str) -> str:
    """Convert company name to a safe slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:40]


# ── OAuth refresh token generation ────────────────────────────────────────────

def _generate_refresh_token(client_id: str, client_secret: str) -> Optional[str]:
    """
    Guide user through OAuth flow to obtain a refresh token.
    Returns the refresh token string, or None on failure.
    """
    print()
    print(bold("  Generating refresh token via browser OAuth flow..."))
    print(dim("  (This opens Google's consent screen — approve access to Google Ads)"))
    print()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        client_config = {
            "installed": {
                "client_id":     client_id,
                "client_secret": client_secret,
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(
            client_config,
            scopes=["https://www.googleapis.com/auth/adwords"],
        )
        credentials = flow.run_local_server(port=0, open_browser=True)
        return credentials.refresh_token

    except ImportError:
        print(yellow("  ⚠  google-auth-oauthlib not installed."))
        print(dim("     Install with: pip install google-auth-oauthlib"))
        print()
        print("  Alternatively, paste your refresh token manually:")
        return _ask("Refresh token", required=True)

    except Exception as exc:
        print(red(f"  ✗ OAuth flow failed: {exc}"))
        print()
        print("  Paste your refresh token manually instead:")
        return _ask("Refresh token", required=True)


# ── Connection test ───────────────────────────────────────────────────────────

def _test_connection(creds: dict) -> list[dict] | None:
    """
    Test credentials by listing active campaigns.
    Returns list of campaign dicts, or None on failure.
    """
    print()
    print(dim("  Testing connection to Google Ads API..."))
    try:
        import warnings
        warnings.filterwarnings("ignore")
        from google.ads.googleads.client import GoogleAdsClient

        client = GoogleAdsClient.load_from_dict({
            "developer_token": creds["dev_token"],
            "client_id":       creds["client_id"],
            "client_secret":   creds["client_secret"],
            "refresh_token":   creds["refresh_token"],
            "use_proto_plus":  True,
        })
        ga = client.get_service("GoogleAdsService")
        campaigns = []
        for row in ga.search(
            customer_id=creds["customer_id"],
            query="""
                SELECT campaign.id, campaign.name, campaign.status
                FROM campaign
                ORDER BY campaign.name
                LIMIT 20
            """
        ):
            campaigns.append({
                "id":     row.campaign.id,
                "name":   row.campaign.name,
                "status": row.campaign.status.name,
            })
        return campaigns
    except Exception as exc:
        print(red(f"  ✗ Connection failed: {exc}"))
        return None


# ── KPI customisation ─────────────────────────────────────────────────────────

def _collect_kpi_config() -> dict:
    print()
    print(bold("  KPI Thresholds"))
    print(dim("  Press Enter to keep the default (AU professional services benchmarks)"))
    print()
    return {
        "target_ctr":           _ask_float("Target CTR (%)",                 2.5),
        "target_conv_rate":     _ask_float("Target conversion rate (%)",     4.0),
        "target_cost_conv":     _ask_float("Target max cost/conversion (AUD)", 80.0),
        "target_leads_daily":   _ask_float("Target leads/day (7-day avg)",   1.5),
        "spend_alert_aud":      _ask_float("7-day spend alert threshold (AUD)", 50.0),
        "auto_pause_min_spend": _ask_float("Auto-pause: min spend before pausing (AUD)", 15.0),
        "auto_pause_min_clicks":_ask_int(  "Auto-pause: min clicks before pausing",      20),
        "budget_overpace_pct":  _ask_float("Budget overpace alert (0.15 = 15%)",         0.15),
    }


# ── Main wizard ───────────────────────────────────────────────────────────────

def wizard():
    db.init_db()

    print()
    _hr("═")
    print(bold("  IYS Google Ads Client Onboarding"))
    print(dim("  Credentials are stored in the local DB — never in .env"))
    _hr("═")

    # ── 1. Company details ────────────────────────────────────────────────
    print()
    print(bold("  Step 1 — Company Details"))
    _hr()

    company_name  = _ask("Company name (e.g. 'Acme Plumbing Co.')")
    default_slug  = _slugify(company_name)
    slug          = _ask("Slug (URL-safe ID)", default=default_slug)
    slug          = re.sub(r"[^\w-]", "-", slug).strip("-").lower()
    contact_email = _ask("Client contact email (reports go here)")

    # Check for duplicate
    existing = db.ads_client_get(slug)
    if existing:
        print()
        print(yellow(f"  ⚠  A client with slug '{slug}' already exists:"))
        print(f"     {existing['company_name']} <{existing['contact_email']}>")
        choice = _ask("  Overwrite? (yes/no)", default="no")
        if choice.lower() not in ("yes", "y"):
            print(red("  Aborted."))
            return

    # ── 2. Google Ads credentials ─────────────────────────────────────────
    print()
    print(bold("  Step 2 — Google Ads Account"))
    print(dim("  Find these at ads.google.com → Tools → API Centre"))
    _hr()

    dev_token   = _ask("Developer token")
    customer_id = _ask("Customer ID (10 digits, no dashes)")
    customer_id = customer_id.replace("-", "").replace(" ", "")

    login_customer_id = _ask(
        "Login customer ID (same as Customer ID for self-managed)",
        default=customer_id
    ).replace("-", "").replace(" ", "")

    # ── 3. OAuth credentials ──────────────────────────────────────────────
    print()
    print(bold("  Step 3 — OAuth 2.0 Credentials"))
    print(dim("  Find these at console.cloud.google.com → Credentials → OAuth 2.0 Client IDs"))
    _hr()

    oauth_client_id     = _ask("OAuth Client ID")
    oauth_client_secret = _ask("OAuth Client Secret")

    # ── 4. Refresh token ──────────────────────────────────────────────────
    print()
    print(bold("  Step 4 — Refresh Token"))
    _hr()
    print("  Options:")
    print(f"  {cyan('1')}  Generate automatically via browser (recommended)")
    print(f"  {cyan('2')}  Paste an existing refresh token")
    print()
    method = _ask("Choose", default="1")

    if method == "2":
        refresh_token = _ask("Refresh token")
    else:
        refresh_token = _generate_refresh_token(oauth_client_id, oauth_client_secret)
        if not refresh_token:
            print(red("  ✗ Could not obtain refresh token. Aborted."))
            return

    # ── 5. Test connection ────────────────────────────────────────────────
    print()
    print(bold("  Step 5 — Connection Test"))
    _hr()

    creds = {
        "dev_token":     dev_token,
        "client_id":     oauth_client_id,
        "client_secret": oauth_client_secret,
        "refresh_token": refresh_token,
        "customer_id":   customer_id,
    }
    campaigns = _test_connection(creds)
    if campaigns is None:
        print()
        cont = _ask("Connection failed. Save anyway? (yes/no)", default="no")
        if cont.lower() not in ("yes", "y"):
            print(red("  Aborted."))
            return
    else:
        print(green(f"  ✓ Connected — found {len(campaigns)} campaign(s):"))
        for c in campaigns:
            status_icon = "✓" if c["status"] == "ENABLED" else "⏸"
            print(f"     {status_icon}  {c['name']}  (ID: {c['id']}, status: {c['status']})")

    # ── 6. KPI customisation ──────────────────────────────────────────────
    print()
    print(bold("  Step 6 — KPI Thresholds"))
    _hr()
    kpi_choice = _ask("Customise KPI thresholds? (yes/no)", default="no")
    kpi_config = _collect_kpi_config() if kpi_choice.lower() in ("yes", "y") else {}

    # ── 7. Save to DB ─────────────────────────────────────────────────────
    print()
    print(bold("  Saving to database..."))
    _hr()

    if existing:
        db.ads_client_delete(slug)

    db.ads_client_add(
        slug=slug,
        company_name=company_name,
        contact_email=contact_email,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        dev_token=dev_token,
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
        refresh_token=refresh_token,
        kpi_config=kpi_config or None,
    )

    print(green(f"  ✓ Client '{slug}' saved successfully."))
    print()

    # ── 8. Run first report ───────────────────────────────────────────────
    run_now = _ask("Run first ads report now? (yes/no)", default="yes")
    if run_now.lower() in ("yes", "y"):
        print()
        print(dim("  Running ads agent..."))
        from agents.ads import AdsAgent
        client_cfg = db.ads_client_get(slug)
        AdsAgent(client_config=client_cfg).execute()
        print(green("  ✓ Done — check the dashboard or inbox for the report."))
    else:
        print(dim(f"  Skipped. The agent will run automatically during the next scheduled cycle."))

    print()
    _hr("═")
    print(bold("  Onboarding complete!"))
    _hr("═")
    print()
    print(f"  Client slug : {cyan(slug)}")
    print(f"  Report to   : {cyan(contact_email)}")
    print(f"  Next auto-run: daily 9:00 AM AEST")
    print()
    print(dim("  To manage clients:"))
    print(dim(f"    python agents/ads_onboard.py --list"))
    print(dim(f"    python agents/ads_onboard.py --run {slug}"))
    print(dim(f"    python agents/ads_onboard.py --remove {slug}"))
    print()


# ── CLI commands ──────────────────────────────────────────────────────────────

def cmd_list():
    db.init_db()
    clients = db.ads_client_list(active_only=False)
    if not clients:
        print("\n  No clients onboarded yet.\n")
        return
    print()
    _hr("═")
    print(bold(f"  Onboarded Ads Clients  ({len(clients)} total)"))
    _hr("═")
    for c in clients:
        status = green("active") if c["active"] else red("inactive")
        kpi_note = f"  [{len(c['kpi_config'])} custom KPIs]" if c["kpi_config"] else ""
        print(f"\n  {bold(c['slug'])} — {c['company_name']}{kpi_note}")
        print(f"     Status  : {status}")
        print(f"     Email   : {c['contact_email']}")
        print(f"     Cust ID : {c['customer_id']}")
        print(f"     Added   : {c['created_at'][:10]}")
    print()


def cmd_remove(slug: str):
    db.init_db()
    existing = db.ads_client_get(slug)
    if not existing:
        print(red(f"\n  ✗ No client found with slug '{slug}'\n"))
        return
    confirm = _ask(f"  Deactivate '{slug}' ({existing['company_name']})? (yes/no)", default="no")
    if confirm.lower() in ("yes", "y"):
        db.ads_client_set_active(slug, False)
        print(green(f"\n  ✓ Client '{slug}' deactivated (data retained in DB).\n"))
    else:
        print(dim("\n  Cancelled.\n"))


def cmd_run(slug: str):
    db.init_db()
    client_cfg = db.ads_client_get(slug)
    if not client_cfg:
        print(red(f"\n  ✗ No client found with slug '{slug}'\n"))
        return
    if not client_cfg["active"]:
        print(yellow(f"\n  ⚠  Client '{slug}' is inactive. Activate it first.\n"))
        return
    print(f"\n  Running ads agent for {bold(client_cfg['company_name'])}...")
    from agents.ads import AdsAgent
    AdsAgent(client_config=client_cfg).execute()
    print(green("\n  ✓ Done.\n"))


def cmd_create_campaign(slug: str):
    """Interactive wizard to build a Google Search campaign from scratch."""
    db.init_db()
    client_cfg = db.ads_client_get(slug)
    if not client_cfg:
        print(red(f"\n  ✗ No client found with slug '{slug}'\n"))
        return
    if not client_cfg["active"]:
        print(yellow(f"\n  ⚠  Client '{slug}' is inactive. Activate it first.\n"))
        return

    print()
    _hr("═")
    print(bold(f"  Create Campaign — {client_cfg['company_name']}"))
    print(dim("  Campaign starts PAUSED so you can review before enabling"))
    _hr("═")

    # ── Campaign basics ───────────────────────────────────────────────────────
    print()
    print(bold("  Step 1 — Campaign Details"))
    _hr()
    campaign_name = _ask("Campaign name (e.g. 'Sydney Emergency Plumbing')")
    daily_budget  = _ask_float("Daily budget (AUD)", 20.0)
    print()
    print(dim("  Location — type a city or 'australia' for nationwide"))
    location = _ask("Target location", default="australia")

    # ── Ad group ──────────────────────────────────────────────────────────────
    print()
    print(bold("  Step 2 — Ad Group"))
    _hr()
    ad_group_name = _ask("Ad group name (e.g. 'Emergency Plumbing')", default=campaign_name)

    # ── Keywords ──────────────────────────────────────────────────────────────
    print()
    print(bold("  Step 3 — Keywords"))
    print(dim("  Enter one keyword per line. Format: keyword text | MATCH_TYPE"))
    print(dim("  Match types: BROAD / PHRASE / EXACT  (default: PHRASE)"))
    print(dim("  Press Enter on a blank line when done."))
    print()
    keywords = []
    idx = 1
    while True:
        raw = input(f"  Keyword {idx} (or Enter to finish): ").strip()
        if not raw:
            if not keywords:
                print(red("  ✗ Add at least one keyword"))
                continue
            break
        parts = [p.strip() for p in raw.split("|")]
        text  = parts[0]
        match = parts[1].upper() if len(parts) > 1 else "PHRASE"
        if match not in ("BROAD", "PHRASE", "EXACT"):
            match = "PHRASE"
        keywords.append({"text": text, "match": match})
        idx += 1

    # ── Ad copy ───────────────────────────────────────────────────────────────
    print()
    print(bold("  Step 4 — Ad Headlines"))
    print(dim("  3 required, up to 15. Max 30 characters each."))
    print(dim("  First two are pinned to headline positions 1 & 2."))
    print()
    headlines = []
    idx = 1
    while True:
        raw = input(f"  Headline {idx} (or Enter to finish): ").strip()
        if not raw:
            if len(headlines) < 3:
                print(red(f"  ✗ Need at least 3 headlines ({len(headlines)} so far)"))
                continue
            break
        if len(raw) > 30:
            print(yellow(f"  ⚠  Truncated to 30 chars: '{raw[:30]}'"))
            raw = raw[:30]
        headlines.append(raw)
        idx += 1
        if idx > 15:
            print(dim("  Max 15 headlines reached."))
            break

    print()
    print(bold("  Step 5 — Ad Descriptions"))
    print(dim("  2 required, up to 4. Max 90 characters each."))
    print()
    descriptions = []
    idx = 1
    while True:
        raw = input(f"  Description {idx} (or Enter to finish): ").strip()
        if not raw:
            if len(descriptions) < 2:
                print(red(f"  ✗ Need at least 2 descriptions ({len(descriptions)} so far)"))
                continue
            break
        if len(raw) > 90:
            print(yellow(f"  ⚠  Truncated to 90 chars: '{raw[:90]}'"))
            raw = raw[:90]
        descriptions.append(raw)
        idx += 1
        if idx > 4:
            print(dim("  Max 4 descriptions reached."))
            break

    # ── URL ───────────────────────────────────────────────────────────────────
    print()
    print(bold("  Step 6 — Landing Page"))
    _hr()
    final_url = _ask("Final URL (landing page, e.g. https://example.com/plumbing)")
    path1 = _ask("Display path 1 (optional, e.g. 'Plumbing')", required=False)
    path2 = _ask("Display path 2 (optional, e.g. 'Sydney')",   required=False)

    # ── Confirm ───────────────────────────────────────────────────────────────
    print()
    _hr("═")
    print(bold("  Campaign Summary"))
    _hr("═")
    print(f"  Campaign : {campaign_name}")
    print(f"  Budget   : ${daily_budget:.2f}/day AUD")
    print(f"  Location : {location}")
    print(f"  Ad group : {ad_group_name}")
    print(f"  Keywords : {len(keywords)}")
    for k in keywords:
        print(f"             [{k['match'][:2]}] {k['text']}")
    print(f"  Headlines: {len(headlines)}")
    print(f"  Descs    : {len(descriptions)}")
    print(f"  URL      : {final_url}")
    print()
    print(yellow("  ⚠  Campaign will be created in PAUSED state."))
    print(dim("     Enable it in Google Ads after reviewing the setup."))
    print()
    confirm = _ask("Create campaign now? (yes/no)", default="no")
    if confirm.lower() not in ("yes", "y"):
        print(dim("\n  Cancelled.\n"))
        return

    # ── Create ────────────────────────────────────────────────────────────────
    print()
    print(dim("  Creating campaign via Google Ads API..."))
    from agents.ads import AdsAgent
    agent = AdsAgent(client_config=client_cfg)
    brief = {
        "campaign_name": campaign_name,
        "daily_budget":  daily_budget,
        "location":      location,
        "ad_group_name": ad_group_name,
        "keywords":      keywords,
        "headlines":     headlines,
        "descriptions":  descriptions,
        "final_url":     final_url,
        "path1":         path1,
        "path2":         path2,
    }
    try:
        result = agent.create_campaign(brief)
        print()
        print(green("  ✓ Campaign created successfully!"))
        print(f"     Keywords added : {result['keywords']}")
        print(f"     Status         : {result['status']} (enable in Google Ads when ready)")
        print()
        print(dim("  Next steps:"))
        print(dim("  1. Review the campaign in Google Ads (ads.google.com)"))
        print(dim("  2. Check keywords, bids, and ad copy"))
        print(dim("  3. Enable the campaign when satisfied"))
        print(dim(f"  4. The agent will monitor it daily from tomorrow"))
        print(dim(f"  5. KPI targets kick in after the 14-day learning period"))
    except Exception as exc:
        print(red(f"\n  ✗ Campaign creation failed: {exc}\n"))


def cmd_run_all():
    db.init_db()
    from agents.ads import run_all_clients
    print("\n  Running ads agent for all active clients...")
    run_all_clients()
    print(green("\n  ✓ Done.\n"))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        wizard()
    elif args[0] == "--list":
        cmd_list()
    elif args[0] == "--remove" and len(args) >= 2:
        cmd_remove(args[1])
    elif args[0] == "--run" and len(args) >= 2:
        cmd_run(args[1])
    elif args[0] == "--run-all":
        cmd_run_all()
    elif args[0] == "--create-campaign" and len(args) >= 2:
        cmd_create_campaign(args[1])
    else:
        print(f"\nUsage:")
        print(f"  python agents/ads_onboard.py                          — onboard a new client")
        print(f"  python agents/ads_onboard.py --list                   — list all clients")
        print(f"  python agents/ads_onboard.py --remove SLUG")
        print(f"  python agents/ads_onboard.py --run SLUG")
        print(f"  python agents/ads_onboard.py --run-all")
        print(f"  python agents/ads_onboard.py --create-campaign SLUG   — build a campaign from scratch")
        print()
