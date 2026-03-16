"""
agents/tag_projects_watcher.py

Monitors hello@improveyoursite.com for a reply from tim@tagprojectsco.com.au
that contains image attachments.

When found:
  1. Downloads all image attachments
  2. Saves them to customers/tag-projects/works/
  3. Updates customers/tag-projects/index.html to use real images in the Works grid
  4. Git commits and pushes to GitHub Pages (~90s to live)
  5. Sends a confirmation email to james.burke290@gmail.com

Run standalone:
  python3 agents/tag_projects_watcher.py

Runs automatically via scheduler.py every 30 minutes.

Required in builder/.env (already set):
  HELLO_EMAIL_USER   — hello@improveyoursite.com
  HELLO_EMAIL_PASS   — Google Workspace app password
  GITHUB_PAT         — already set
  GMAIL_USER         — already set (for sending confirmation)
  GMAIL_APP_PASS     — already set
"""

from __future__ import annotations

import base64
import email as email_lib
import imaplib
import mimetypes
import os
import re
import shutil
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.header import decode_header as _decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "builder" / ".env")

# ── Config ──────────────────────────────────────────────────────────────────
WATCH_EMAIL    = os.environ.get("HELLO_EMAIL_USER", "hello@improveyoursite.com")
WATCH_PASS     = os.environ.get("HELLO_EMAIL_PASS", "")
TIM_EMAIL      = "tim@tagprojectsco.com.au"
NOTIFY_EMAIL   = "james.burke290@gmail.com"
IMAP_HOST      = "imap.gmail.com"

PROJECT_ROOT   = Path(__file__).parent.parent
CUSTOMER_DIR   = PROJECT_ROOT / "customers" / "tag-projects"
WORKS_IMG_DIR  = CUSTOMER_DIR / "works"
HTML_FILE      = CUSTOMER_DIR / "index.html"

GMAIL_USER     = os.environ.get("GMAIL_USER", "")
GMAIL_PASS     = os.environ.get("GMAIL_APP_PASS", "")
GITHUB_PAT     = os.environ.get("GITHUB_PAT", "")

POLL_INTERVAL  = 120  # seconds between inbox checks
MAX_IMAGES     = 12   # max images to pull from email
# ─────────────────────────────────────────────────────────────────────────────


def _decode_str(val: str | bytes | None) -> str:
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    parts = _decode_header(val)
    out = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def check_inbox() -> list[dict]:
    """
    Connect to james.burke290@gmail.com and return list of unseen messages
    from tim@tagprojectsco.com.au that contain image attachments.
    Returns list of dicts: {uid, subject, images: [{"filename", "data"}]}
    """
    if not WATCH_PASS:
        print("ERROR: HELLO_EMAIL_PASS not set in builder/.env")
        return []

    results = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(WATCH_EMAIL, WATCH_PASS)
        mail.select("INBOX")

        # Search for unseen messages from Tim
        _, data = mail.search(None, f'(UNSEEN FROM "{TIM_EMAIL}")')
        uids = data[0].split() if data[0] else []

        if not uids:
            # Also check seen messages in case we missed one
            _, data = mail.search(None, f'(FROM "{TIM_EMAIL}")')
            uids = data[0].split() if data[0] else []

        for uid in uids:
            _, msg_data = mail.fetch(uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)
            subject = _decode_str(msg.get("Subject", ""))
            images = []

            for part in msg.walk():
                ct = part.get_content_type()
                cd = part.get("Content-Disposition", "")
                if ct.startswith("image/") or ("attachment" in cd and ct.startswith("image/")):
                    filename = part.get_filename()
                    if not filename:
                        ext = mimetypes.guess_extension(ct) or ".jpg"
                        filename = f"work_{len(images)+1}{ext}"
                    filename = _decode_str(filename)
                    # Sanitise filename
                    filename = re.sub(r"[^\w.\-]", "_", filename)
                    data_bytes = part.get_payload(decode=True)
                    if data_bytes:
                        images.append({"filename": filename, "data": data_bytes})

            if images:
                results.append({"uid": uid, "subject": subject, "images": images[:MAX_IMAGES]})
                # Mark as seen
                mail.store(uid, "+FLAGS", "\\Seen")

        mail.logout()
    except Exception as exc:
        print(f"IMAP error: {exc}")

    return results


def save_images(images: list[dict]) -> list[str]:
    """Save images to works/ dir, return list of relative paths."""
    WORKS_IMG_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, img in enumerate(images):
        # Prefix with index to guarantee ordering
        name = f"{i+1:02d}-{img['filename']}"
        dest = WORKS_IMG_DIR / name
        dest.write_bytes(img["data"])
        saved.append(f"works/{name}")
        print(f"  Saved: {dest}")
    return saved


# ── Project card definitions (9 slots match the existing HTML cards) ──────────
_CARD_DEFS = [
    {"cat": "handrail",    "label": "Handrails & Balustrades",  "title": "Multi-Level Staircase Handrail System",          "loc": "Brisbane CBD, QLD"},
    {"cat": "hospitality", "label": "Restaurant Fit-Out",        "title": "Bar Front & Feature Balustrade",                 "loc": "South Bank, QLD"},
    {"cat": "screen",      "label": "Decorative Screen",         "title": "Perforated Aluminium Privacy Screen",            "loc": "Gold Coast, QLD"},
    {"cat": "hospital",    "label": "Hospital Fit-Out",          "title": "Corridor Handrail & Grab Rail Installation",     "loc": "Logan, QLD"},
    {"cat": "school",      "label": "School Fit-Out",            "title": "Staircase Balustrade Upgrade — State High School","loc": "Ipswich, QLD"},
    {"cat": "hospitality", "label": "Club & Entertainment",      "title": "Balcony Balustrade & Crowd Rail System",         "loc": "Fortitude Valley, QLD"},
    {"cat": "handrail",    "label": "Handrails & Balustrades",   "title": "Pool Fence & Deck Balustrade",                   "loc": "Springwood, QLD"},
    {"cat": "custom",      "label": "Custom Fabrication",        "title": "Structural Mezzanine Support Frames",            "loc": "Slacks Creek, QLD"},
    {"cat": "screen",      "label": "Feature Screen",            "title": "Laser-Cut Feature Wall Panel — Hotel Lobby",     "loc": "Broadbeach, QLD"},
]

_CAT_COLOURS = {
    "handrail":    ("Handrails", "Stainless 316"),
    "hospitality": ("Hospitality", "Mild Steel / SS"),
    "screen":      ("Screen", "Aluminium"),
    "hospital":    ("Healthcare", "Stainless 304"),
    "school":      ("Education", "Mild Steel"),
    "custom":      ("Custom Fab", "Mild Steel"),
}

_DARK_CATS  = {"handrail", "hospitality", "screen", "school", "custom"}


def _build_card_html(idx: int, img_path: str | None, card: dict) -> str:
    cat   = card["cat"]
    label = card["label"]
    title = card["title"]
    loc   = card["loc"]
    cat_tag, mat_tag = _CAT_COLOURS.get(cat, (cat.title(), "Steel"))
    loc_svg = '<svg viewBox="0 0 24 24"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>'

    if img_path:
        visual = f'''<div class="work-visual" style="background:#0f172a;">
          <img src="{img_path}" alt="{title}" style="width:100%;height:100%;object-fit:cover;display:block;">
          <div class="wv-label">
            <span class="wv-tag wv-cat">{cat_tag}</span>
            <span class="wv-tag wv-mat">{mat_tag}</span>
          </div>
        </div>'''
    else:
        # Fallback to CSS placeholder
        css_cls = f"wv-{cat}"
        bg_icons = {
            "handrail":    '<svg class="bg-icon" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1" stroke-linecap="round"><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/></svg>',
            "hospitality": '<svg class="bg-icon" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1" stroke-linecap="round"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/></svg>',
            "screen":      '<svg class="bg-icon" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>',
            "hospital":    '<svg class="bg-icon" viewBox="0 0 24 24" fill="none" stroke="#1e40af" stroke-width="1" stroke-linecap="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
            "school":      '<svg class="bg-icon" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1" stroke-linecap="round"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>',
            "custom":      '<svg class="bg-icon" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1" stroke-linecap="round"><circle cx="12" cy="12" r="3"/></svg>',
        }
        mat_style = "" if cat in _DARK_CATS else ' style="background:rgba(37,99,235,.15);color:#1d4ed8;border-color:rgba(37,99,235,.25);"'
        visual = f'''<div class="work-visual {css_cls}">
          {bg_icons.get(cat, "")}
          <div class="wv-label">
            <span class="wv-tag wv-cat">{cat_tag}</span>
            <span class="wv-tag wv-mat"{mat_style}>{mat_tag}</span>
          </div>
        </div>'''

    return f'''
      <div class="work-card" data-cat="{cat}">
        {visual}
        <div class="work-body">
          <span class="work-cat-pill">{label}</span>
          <h3>{title}</h3>
          <p class="work-loc">{loc_svg}{loc}</p>
        </div>
      </div>'''


def _rebuild_works_grid(img_paths: list[str]) -> None:
    """Replace the works-grid content in index.html with new cards."""
    html = HTML_FILE.read_text(encoding="utf-8")

    # Build new grid content
    cards_html = ""
    for i, card_def in enumerate(_CARD_DEFS):
        img = img_paths[i] if i < len(img_paths) else None
        cards_html += _build_card_html(i, img, card_def)

    # Replace between <div class="works-grid"> and </div>\n\n<!-- CONTACT -->
    pattern = r'(<div class="works-grid">)(.*?)(</div>\s*\n\s*</div>\s*\n</section>\s*\n\s*<!-- CONTACT -->)'
    replacement = r'\g<1>\n' + cards_html + r'\n\n    \g<3>'
    new_html, n = re.subn(pattern, replacement, html, flags=re.DOTALL)

    if n == 0:
        print("WARNING: Could not find works-grid pattern — HTML not updated")
        return

    HTML_FILE.write_text(new_html, encoding="utf-8")
    print(f"  Updated HTML with {len(img_paths)} real image(s)")


def git_push(img_paths: list[str]) -> bool:
    """Stage, commit, and push the updated files."""
    repo = PROJECT_ROOT
    try:
        # Stage images + HTML
        files_to_add = [str(CUSTOMER_DIR.relative_to(repo))]
        subprocess.run(["git", "-C", str(repo), "add"] + files_to_add, check=True)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = f"TAG Projects: add {len(img_paths)} real works photo(s) from Tim [{ts}]\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
        subprocess.run(["git", "-C", str(repo), "commit", "-m", msg], check=True)

        # Pull rebase then push
        subprocess.run(["git", "-C", str(repo), "pull", "--rebase", "origin", "main"], check=True)
        subprocess.run(["git", "-C", str(repo), "push", "origin", "main"], check=True)
        print("  Pushed to GitHub — live in ~90s")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"  Git error: {exc}")
        return False


def send_confirmation(n_images: int, pushed: bool) -> None:
    """Email James confirming what happened."""
    if not GMAIL_USER or not GMAIL_PASS:
        return
    status = "published live" if pushed else "saved locally (push failed — check git)"
    site_url = "https://anon8597299.github.io/smart-tech-innovations/customers/tag-projects/"
    body = (
        f"Tim's email arrived with {n_images} photo(s).\n\n"
        f"They've been {status} to the TAG Projects Works section.\n\n"
        f"Live URL: {site_url}\n\n"
        f"— IYS automation"
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"TAG Projects — {n_images} photo(s) uploaded to Works section"
    msg["From"]    = f"IYS Automation <{GMAIL_USER}>"
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
        print(f"  Confirmation sent to {NOTIFY_EMAIL}")
    except Exception as exc:
        print(f"  Could not send confirmation: {exc}")


def run_once() -> bool:
    """Check inbox once. Returns True if photos were processed."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking {JAMES_EMAIL} for Tim's reply...")
    messages = check_inbox()

    if not messages:
        print("  No matching emails yet.")
        return False

    all_images = []
    for msg_info in messages:
        print(f"  Found: '{msg_info['subject']}' — {len(msg_info['images'])} image(s)")
        all_images.extend(msg_info["images"])

    if not all_images:
        print("  Emails found but no image attachments.")
        return False

    print(f"  Processing {len(all_images)} image(s)...")
    img_paths = save_images(all_images)
    _rebuild_works_grid(img_paths)
    pushed = git_push(img_paths)
    send_confirmation(len(img_paths), pushed)
    return True


def watch(poll_seconds: int = POLL_INTERVAL) -> None:
    """Poll inbox until photos arrive, then exit."""
    if not WATCH_PASS:
        print(
            "\n── SETUP REQUIRED ─────────────────────────────────────────────\n"
            "HELLO_EMAIL_PASS not set in builder/.env\n"
            "────────────────────────────────────────────────────────────────\n"
        )
        return

    print(f"Watching {WATCH_EMAIL} for photos from {TIM_EMAIL}")
    print(f"Polling every {poll_seconds}s — Ctrl+C to stop\n")
    while True:
        done = run_once()
        if done:
            print("\nDone — photos uploaded and pushed live.")
            break
        time.sleep(poll_seconds)


if __name__ == "__main__":
    watch()
