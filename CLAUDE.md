# improveyoursite.com — Project Brief for Claude

## What this is
James Burke's web agency selling website packages to Australian small businesses.
**Business rule: Customers pay first, site gets built after.**

Live site: `https://improveyoursite.com`
Repo: `https://github.com/anon8597299/smart-tech-innovations`
Deploy: GitHub Pages via `.github/workflows/deploy-pages.yml` (auto-deploys on push to `main`)
~90 seconds from `git push` to live.

## Packages & Pricing (CORRECT — do not change without James confirming)
| Package | Price | Slug |
|---------|-------|------|
| Scan & Fix | $3,000 | `scanfix` |
| Complete Build | $5,000 | `build` |
| Premium Growth | $10,000 | `premium` |

## Stripe Payment Links
Currently using **test links** while ABN verification clears (3–5 business days from ~Feb 2026).
When production links are ready, swap these 3 URLs in `packages.html`:
- Scan & Fix: `https://buy.stripe.com/test_4gMeV52YA0q37UM3Su1wY02`
- Complete Build: `https://buy.stripe.com/test_fZu28j0Qs0q3gri74G1wY01`
- Premium Growth: `https://buy.stripe.com/test_14A5kvfLm4Gj3Ew0Gi1wY00`

After payment, Stripe redirects to `/order.html?package=scanfix` (or `build` / `premium`).

## Customer Journey
```
Visit improveyoursite.com
→ Browse showcase demos (our-work.html)
→ packages.html → Stripe checkout → order.html (intake form)
→ formsubmit.co emails James at admin@improveyoursite.com
→ James runs: python builder/generate.py --config customer.json
→ Site pushed to GitHub Pages at:
  anon8597299.github.io/smart-tech-innovations/customers/{slug}/
→ James emails customer their URL
```

## Key Files
| File | Purpose |
|------|---------|
| `index.html` | Main homepage |
| `packages.html` | 3-tier pricing page with Stripe buy buttons |
| `order.html` | Post-payment business details intake form |
| `admin.html` | Password-protected browser admin panel (generate & push customer sites) |
| `our-work.html` | Portfolio / showcase gallery |
| `thanks.html` | Order confirmation page |
| `builder/generate.py` | CLI: reads customer JSON → renders template → pushes to GitHub |
| `builder/renderer.py` | `{{TOKEN}}` substitution engine |
| `builder/github_client.py` | Single Git Tree commit push via PyGithub |
| `builder/config-example.json` | Example customer config |
| `builder/.env.example` | `GITHUB_PAT=...` |
| `templates/` | Tokenised `{{TOKEN}}` versions of each showcase template |

## Showcase Demo Sites (all live under `/showcase/sites/`)
| Folder | Business | Industry |
|--------|----------|----------|
| `clinic-trust` | Hillcrest Family Clinic | Healthcare / GP |
| `trades-rapid` | Bathurst Plumbing Co. | Trades |
| `advisor-prime` | Pinnacle Financial Advice | Finance |
| `retail-pulse` | The Loft Boutique | Retail fashion |
| `solar-spark` | SunVolt Solar | Solar / energy |
| `hospitality-events` | The Stonebridge Estate | Hospitality / weddings |
| `consulting-authority` | Apex Strategy Group | Business consulting |
| `accounting-conversion` | Clearview Accounting | Accounting / CPA |

All demos have: demo banner → "Get a site like this" → `/packages.html`

## Admin Panel (`admin.html`)
- Password protected (SHA-256). Default password: `improveyoursite2025`
- Stores GitHub PAT in `sessionStorage` (never persisted to disk)
- Browser-based: generates customer sites via GitHub API directly, no Python needed
- Future plan: add customer UAT flow — customer previews site, approves, gets handed repo access

## Template Token System
Templates in `templates/{template-id}/` use `{{TOKEN}}` placeholders.
Key tokens: `{{BUSINESS_NAME}}`, `{{TAGLINE}}`, `{{PHONE}}`, `{{EMAIL}}`,
`{{ADDRESS}}`, `{{SUBURB}}`, `{{STATE}}`, `{{HERO_HEADLINE}}`,
`{{SERVICE_1_NAME}}`, `{{SERVICE_1_DESC}}` (up to 3),
`{{META_TITLE}}`, `{{META_DESCRIPTION}}`, `{{COLOR_PRIMARY}}`, `{{COLOR_BG}}`

CSS uses `:root` custom properties so colour theming only requires changing the `:root {}` block.

## Generated Customer Sites
Pushed to: `customers/{slug}/` in the repo
Include `<meta name="robots" content="noindex, nofollow">` to protect improveyoursite.com SEO.

## Brand Colours
- Electric Indigo: `#5b4dff`
- Neon Mint: `#2dd4bf`
- Font: Inter (Google Fonts)

## Git Workflow
Always commit specific files (not `git add -A`) to avoid accidentally staging
pre-existing uncommitted changes in showcase sub-pages.
`advisor-prime/about.html`, `contact.html`, `services.html` have pre-existing
uncommitted changes — leave them alone unless specifically working on them.

## Pending / Future Work
- Swap Stripe test links for production links once ABN clears
- Customer UAT flow: preview page + feedback form + handover step in admin.html
- `thanks.html` may need styling pass to match site brand
