# Ads + Analytics Arsenal (Activated)

## Installed Skills/Tools

- ✅ `check-analytics`
- ✅ `add-analytics`
- ✅ `remove-analytics`
- ✅ `ga4-analytics` (installed)
- ✅ `gsc` (installed)
- ✅ `meta-ads` (installed)
- ⚠️ `google-ads` installed but needs `~/.google-ads.yaml` to become eligible

## Site Instrumentation Added

- `analytics-config.js` (single config source for IDs)
- `src/js/analytics.js` (loads GA4/GTM/Meta Pixel/Clarity)
- `src/js/main.js` lead + ROI + CTA event hooks:
  - `lead_form_submit_attempt`
  - `generate_lead` (GA4)
  - `Lead` (Meta Pixel)
  - `lead_form_submit_fallback`
  - `roi_calculated`
  - `sticky_cta_click`

Integrated pages:
- `index.html`
- `our-work.html`
- `showcase/*.html`

## IDs/Secrets Needed Next

Edit `analytics-config.js` with:

- `ga4MeasurementId`: `G-XXXXXXXXXX`
- `gtmId`: `GTM-XXXXXXX` (optional if using direct GA4)
- `metaPixelId`: Pixel ID
- `clarityId`: Microsoft Clarity project ID
- `googleAdsId`: `AW-XXXXXXXXX`
- `googleAdsLabel`: conversion label

## Recommended Tracking Targets

- Form submit success (primary lead)
- Form fallback mailto path (backup lead)
- Sticky CTA clicks
- ROI calculator usage
- QR campaign source attribution (already embedded via UTMs)

## Next Milestones

1. Add GA4 + GTM IDs and verify in GA4 Realtime
2. Add Meta Pixel + test in Meta Events Manager
3. Add Clarity for session recordings/heatmaps
4. Configure Google Ads conversion action and label
5. Connect Search Console + GA4 service account for reporting automation
