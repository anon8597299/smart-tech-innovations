"""
renderer.py — Token substitution engine for customer site generation.

Replaces {{TOKEN}} placeholders in template files with values from
a customer config dictionary.
"""

import re
from pathlib import Path


# All tokens recognised by the template system
KNOWN_TOKENS = [
    "BUSINESS_NAME",
    "TAGLINE",
    "PHONE",
    "EMAIL",
    "ADDRESS",
    "SUBURB",
    "STATE",
    "POSTCODE",
    "HERO_HEADLINE",
    "SERVICE_1_NAME",
    "SERVICE_1_DESC",
    "SERVICE_2_NAME",
    "SERVICE_2_DESC",
    "SERVICE_3_NAME",
    "SERVICE_3_DESC",
    "META_TITLE",
    "META_DESCRIPTION",
    "COLOR_PRIMARY",
    "COLOR_BG",
]

TOKEN_PATTERN = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def render(template_content: str, config: dict) -> str:
    """
    Replace all {{TOKEN}} placeholders in template_content with values
    from config. Unknown tokens are left in place (with a warning).

    Args:
        template_content: Raw HTML string with {{TOKEN}} placeholders.
        config: Dict mapping token names to replacement values.

    Returns:
        Rendered HTML string.
    """
    warnings = []

    def replace_token(match):
        token = match.group(1)
        if token in config:
            return str(config[token])
        warnings.append(f"  ⚠ No value for token: {{{{{token}}}}}")
        return match.group(0)  # leave unreplaced

    result = TOKEN_PATTERN.sub(replace_token, template_content)

    for w in warnings:
        print(w)

    return result


def render_file(template_path: Path, config: dict) -> str:
    """Read a template file and render it with config values."""
    content = template_path.read_text(encoding="utf-8")
    return render(content, config)


def derive_tokens(config: dict) -> dict:
    """
    Build the full token dict from a customer config.
    Fills in defaults for tokens not explicitly set.
    """
    tokens = dict(config)  # copy

    # Derive META_TITLE if not set
    if "META_TITLE" not in tokens:
        name = tokens.get("BUSINESS_NAME", "")
        suburb = tokens.get("SUBURB", "")
        state = tokens.get("STATE", "")
        tokens["META_TITLE"] = f"{name} — {suburb} {state}".strip(" —")

    # Derive META_DESCRIPTION if not set
    if "META_DESCRIPTION" not in tokens:
        name = tokens.get("BUSINESS_NAME", "")
        tagline = tokens.get("TAGLINE", "")
        suburb = tokens.get("SUBURB", "")
        tokens["META_DESCRIPTION"] = f"{name}. {tagline} Based in {suburb}.".strip()

    # Default COLOR_BG based on template
    if "COLOR_BG" not in tokens:
        template_defaults = {
            "clinic-trust":   "#f4fbfb",
            "trades-rapid":   "#fffaf5",
            "advisor-prime":  "#f6f8ff",
            "retail-pulse":   "#f8f7ff",
        }
        template_id = tokens.get("TEMPLATE_ID", "")
        tokens["COLOR_BG"] = template_defaults.get(template_id, "#f8fafc")

    # Default COLOR_PRIMARY based on template
    if "COLOR_PRIMARY" not in tokens:
        primary_defaults = {
            "clinic-trust":   "#0f766e",
            "trades-rapid":   "#d97706",
            "advisor-prime":  "#1d4ed8",
            "retail-pulse":   "#7c3aed",
        }
        template_id = tokens.get("TEMPLATE_ID", "")
        tokens["COLOR_PRIMARY"] = primary_defaults.get(template_id, "#5b4dff")

    return tokens
