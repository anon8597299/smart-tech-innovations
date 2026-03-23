# Jarvis — AI Staff in a Box

**Tagline:** Plug in. Switch on. Done.

---

## What it is

Jarvis is a pre-configured AI assistant that runs on your computer and handles the admin work of running a small business — answering leads, booking jobs, responding to enquiries, and posting to social media. It works 24/7 in the background, starts automatically when you log in, and costs a fraction of a part-time admin hire.

It is sold on a USB drive for plug-and-play setup, or as a digital download.

---

## Who it's for

Australian small business owners who want to stop drowning in admin but don't have the time, money, or technical knowledge for custom software.

**Primary industries:**
- Trades: plumbers, electricians, builders, landscapers
- Healthcare: GP clinics, physio, dental, allied health
- Finance: accountants, mortgage brokers, financial planners
- Retail: independent stores, e-commerce operators
- Hospitality: cafes, restaurants, accommodation

**Customer profile:** Owner-operator, 1–15 staff, using a phone and a laptop, no dedicated IT person. Sick of missing calls and losing jobs to competitors.

---

## What's included

| Item | Notes |
|---|---|
| macOS setup script | `setup-mac.sh` — runs from the USB, auto-installs all dependencies |
| Windows setup script | `setup-windows.ps1` — PowerShell, auto-elevates to Administrator |
| Setup wizard | Browser-based, guides through API key entry and business details |
| Agent stack | Pre-built AI agents for leads, scheduling, email, and social |
| Background service | Installs as a LaunchAgent (Mac) or Scheduled Task (Windows) |
| OpenClaw engine | The AI orchestration layer that runs the agents |

---

## Pricing

| Format | Price |
|---|---|
| USB drive (physical) | $50 AUD |
| Digital download | $30 AUD |
| Managed plan (upsell) | $199/month |

**Ongoing costs to the customer:** Anthropic API usage, typically $5–20/month depending on volume. No other subscriptions required.

---

## Setup time

**10 minutes end-to-end.**

1. Plug in the USB (or unzip the download)
2. Double-click `setup-mac.sh` or `setup-windows.ps1`
3. Complete the browser wizard (enter API key, business name, done)
4. Jarvis launches automatically

No command line knowledge required. No developer needed.

---

## What Jarvis does out of the box

- **Lead follow-up:** Monitors a designated email inbox and responds to new enquiries with a personalised reply within minutes
- **Job booking:** Integrates with Google Calendar to check availability and confirm bookings via email or SMS
- **Social media:** Generates and schedules weekly posts tailored to the business's industry and recent activity
- **Competitor research:** Pulls local competitor data and pricing signals (requires Google Places API key)
- **Market intelligence:** Summarises industry news and trends weekly (requires Perplexity API key)

All agent behaviour is customisable through the dashboard at `http://localhost:8080`.

---

## How it works technically

Jarvis runs entirely on the customer's own computer. There is no cloud subscription, no data sent to a third party except the Anthropic API (which processes AI requests). The engine is OpenClaw — an open AI orchestration runtime. OpenClaw is the engine under the hood; the customer only ever sees "Jarvis."

- **Mac:** Installed as a `launchd` LaunchAgent at `~/Library/LaunchAgents/com.improveyoursite.jarvis.plist`
- **Windows:** Installed as a Scheduled Task (`JarvisAI`) that runs at login
- **Config:** Stored at `~/.openclaw/openclaw.json` and `~/jarvis-workspace/builder/.env`

---

## Differentiation

| Feature | Jarvis | Typical SaaS tools |
|---|---|---|
| Monthly fee | None (API costs only) | $50–$500/month |
| Setup complexity | 10 minutes, wizard-guided | Days to weeks |
| Tech skills required | None | Moderate to high |
| Data stays on your machine | Yes | No |
| Works on Mac + Windows | Yes | Varies |
| Custom to your business | Yes (via wizard) | Template-based |

---

## Upsell: Managed Plan — $199/month

For businesses that want IYS to handle everything:

- We monitor Jarvis 24/7 and fix issues before the customer notices
- Monthly agent updates as new AI capabilities are released
- Custom prompt engineering for the customer's specific workflows
- Priority support (phone + email, 1-hour response)
- Quarterly strategy call with an IYS consultant

Target conversion: sell the USB at checkout, then follow up at 30 days with the managed plan offer once the customer has seen results.

---

## Sales channels

- Direct from improveyoursite.com/jarvis
- In-person at trades expos and business events (USB physical sale)
- Referral from existing IYS web clients
- Google Ads targeting "AI for small business Australia"

---

## Support

- Setup guide: https://improveyoursite.com/jarvis/guide
- Email: hello@improveyoursite.com
- Phone support available on managed plan
