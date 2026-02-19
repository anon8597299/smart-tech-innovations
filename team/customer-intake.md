# Customer Intake — Questions for New Clients
**ImproveYourSite | Team Reference**

Use this checklist on the onboarding call or via email after payment.
Everything marked * is required to build the site. Everything else improves the result.

---

## 1. Business Basics

| Question | Why we need it |
|---|---|
| * Full business name (as it appears to customers) | Goes on the site, meta title, footer |
| * Trading name if different from legal name | — |
| ABN | For our records / invoicing |
| * Main phone number | On every page, click-to-call |
| * Main email address (for enquiries) | Contact forms, footer |
| * Street address | Footer, Google Maps, schema markup |
| * Suburb, State, Postcode | Local SEO — critical |
| Serviced areas (other suburbs/regions you cover) | We mention these in copy for SEO |
| Business hours | Contact page, footer |

---

## 2. Owner / Team

| Question | Why we need it |
|---|---|
| Owner's full name | About page, trust signals |
| Owner's title (e.g. "Licensed Plumber & Owner") | Credibility |
| Year the business was established | "Serving Bathurst since 2015" |
| Number of staff / team size (optional) | Social proof |

---

## 3. Services

Ask them to list their **top 3–6 services** — for each one:

- **Name** (e.g. "Emergency Callouts")
- **Short description, 1–2 sentences** (e.g. "Available 24/7 for burst pipes, flooding and urgent repairs across Bathurst and surrounds.")

> **Tip:** If they struggle, ask: *"What do most of your customers call you for?"* then *"What else do you offer that you'd like more work in?"*

Services 1–3 appear on the homepage. Services 4–6 appear on the services sub-page (Complete Build and Premium only).

---

## 4. Brand & Design

| Question | Notes |
|---|---|
| * Do they have a logo? | Ask for PNG or SVG on a transparent background. If no logo, note it — we can discuss. |
| * Preferred primary colour | Ask for a hex code if they know it. Otherwise describe — "navy blue", "forest green", etc. Show them the template colour options. |
| Any colours to avoid | — |
| 1–3 websites they like the look of | Gives us style direction |
| * Which industry template suits them best | Show them the 8 live demos: Clinic, Trades, Advisor, Retail, Solar, Accounting, Consulting, Hospitality |

---

## 5. Copy & Content

| Question | Notes |
|---|---|
| * Tagline / motto | One line. e.g. "Fast, reliable plumbers in Bathurst and surrounds." |
| * Hero headline | What's the first thing visitors should know? e.g. "Trusted plumbers in Bathurst — fast response, fair prices." If blank, we'll write one. |
| What makes you different from competitors? | Feed this into the about page and homepage copy |
| Any testimonials or reviews? | Ask them to paste 2–3 written reviews (not just a Google link) |
| Awards, certifications, trade licences | e.g. QBCC, Master Electricians, AHPRAregistered — big trust signals |

---

## 6. Online Presence

| Question | Why we need it |
|---|---|
| Existing website URL | Required for Scan & Fix. Useful for all packages — we review it. |
| Google Business Profile URL | We check consistency of NAP (name, address, phone) |
| Facebook page URL | Footer links |
| Instagram handle | Footer links |
| Any other directories they're listed in (Hipages, Yellow Pages, etc.) | NAP consistency check |

---

## 7. Package-Specific Questions

### Scan & Fix ($3,000)
- What's frustrating you about the current site?
- Have you noticed it's slow, or heard that from customers?
- Are enquiries coming through the site? If not, when did they stop?
- Any specific pages or sections to prioritise?

### Complete Build ($5,000)
- Do you own a domain? What is it? (e.g. smithsplumbing.com.au)
- Do you want to keep the old site live while we build, then switch over?
- Any pages beyond the standard 4–6? (e.g. Gallery, Careers, FAQ)
- What action do you most want visitors to take? (Call, fill a form, book online)

### Premium Growth ($10,000)
- Everything above, plus:
- What search terms do you want to rank for? (e.g. "plumber Bathurst", "emergency plumber Central West NSW")
- Who are your main 2–3 competitors? (We'll review their sites)
- Are you open to a professional photo shoot at your business? If yes — best days/times?
- Do you have any existing blog content or FAQs we can repurpose?
- Is there a seasonal angle to your business? (e.g. "hot water systems spike in winter")

---

## 8. Logistics

| Question | Notes |
|---|---|
| Best way to reach you during the build? | Phone / email / text |
| Best time to contact | Morning / afternoon / weekdays only |
| Who needs to approve the site? | Owner only, or does a partner/manager also sign off? |
| Any hard deadline? | Grand opening, campaign launch, etc. |
| Do you want to receive the blog posts by email for approval before they go live? | Premium only |

---

## What to Collect Before Hanging Up

- [ ] Logo file (PNG/SVG) — ask them to email to admin@improveyoursite.com
- [ ] 1–3 existing photos of the business, team, or work (optional but helpful)
- [ ] Written testimonials (copy-paste from Google if needed)
- [ ] Confirmation of template choice
- [ ] Confirmation of primary colour
- [ ] Stripe payment reference number (from their receipt email) — for our records

---

## After the Call

1. Fill in `builder/customer-name.json` using the answers above
2. Run `python3 builder/generate.py --config builder/customer-name.json`
3. Site is live in ~90 seconds
4. Open `admin.html` → pipeline → hit **✉ Email** to send them the preview link
5. For Premium: run `blog_generator.py --auto` after the site is live
6. Mark pipeline status as **Preview Sent**, then **Approved** once they confirm
