// ================================================================
// ImproveYourSite — Auto Negative Keyword Script
// Reads search terms from Campaign 1, flags irrelevant ones,
// and adds them as negative keywords automatically.
//
// HOW TO USE:
// 1. Google Ads → Tools → Scripts → + New Script
// 2. Paste this script, Authorize, then Run
// 3. Check Logs tab to see what was added
//
// Run this weekly to keep wasted spend low.
// ================================================================

var CONFIG = {
  CAMPAIGN_NAME:        'Campaign 1',
  LOOKBACK_DAYS:        'LAST_30_DAYS',

  // Add as negative if impressions >= this but zero clicks (nobody clicking = irrelevant)
  MIN_IMPRESSIONS_NO_CLICK: 3,

  // Add as negative if clicks >= this but zero conversions (clicking but not converting)
  MIN_CLICKS_NO_CONVERSION: 5,

  // Add as negative if cost >= this AUD with zero conversions
  MAX_COST_NO_CONVERSION: 10.00,

  DRY_RUN: false,  // Set true to see what WOULD be added without actually adding
};

// Known irrelevant patterns — any search term containing these gets auto-negated
var BAD_PATTERNS = [
  'free',
  'diy',
  'wix',
  'squarespace',
  'shopify',
  'wordpress',
  'godaddy',
  'template',
  'course',
  'learn',
  'tutorial',
  'how to',
  'youtube',
  'job',
  'jobs',
  'career',
  'careers',
  'hire',
  'salary',
  'cheap',
  'reddit',
  'forum',
  'myself',
  'myself',
  'own website',
];

// ================================================================
// MAIN
// ================================================================
function main() {
  Logger.log('==============================================');
  Logger.log('  Auto Negative Keyword Script');
  Logger.log('  Campaign: ' + CONFIG.CAMPAIGN_NAME);
  Logger.log('  Mode: ' + (CONFIG.DRY_RUN ? 'DRY RUN (no changes made)' : 'LIVE'));
  Logger.log('==============================================');

  // Get the campaign
  var campaignIterator = AdsApp.campaigns()
    .withCondition("Name = '" + CONFIG.CAMPAIGN_NAME + "'")
    .get();

  if (!campaignIterator.hasNext()) {
    Logger.log('ERROR: Campaign "' + CONFIG.CAMPAIGN_NAME + '" not found.');
    return;
  }

  var campaign = campaignIterator.next();

  // Get existing negative keywords so we don't add duplicates
  var existingNegatives = getExistingNegatives(campaign);
  Logger.log('Existing negative keywords: ' + existingNegatives.length);

  // Pull search terms report
  var report = AdsApp.report(
    'SELECT Query, Impressions, Clicks, Cost, Conversions, Ctr ' +
    'FROM SEARCH_QUERY_PERFORMANCE_REPORT ' +
    'WHERE CampaignName = "' + CONFIG.CAMPAIGN_NAME + '" ' +
    'DURING ' + CONFIG.LOOKBACK_DAYS
  );

  var toNegate   = [];
  var rows       = report.rows();
  var totalTerms = 0;

  while (rows.hasNext()) {
    var row         = rows.next();
    var term        = row['Query'].toLowerCase().trim();
    var impressions = parseInt(row['Impressions'].replace(/,/g, ''), 10) || 0;
    var clicks      = parseInt(row['Clicks'].replace(/,/g, ''), 10)      || 0;
    var cost        = parseFloat(row['Cost'].replace(/,/g, ''))           || 0;
    var conversions = parseFloat(row['Conversions'])                      || 0;
    var reason      = '';

    totalTerms++;

    // Skip if already a negative
    if (existingNegatives.indexOf(term) !== -1) continue;

    // Rule 1: matches a bad pattern
    for (var p = 0; p < BAD_PATTERNS.length; p++) {
      if (term.indexOf(BAD_PATTERNS[p]) !== -1) {
        reason = 'matches bad pattern "' + BAD_PATTERNS[p] + '"';
        break;
      }
    }

    // Rule 2: impressions but zero clicks
    if (!reason && impressions >= CONFIG.MIN_IMPRESSIONS_NO_CLICK && clicks === 0) {
      reason = impressions + ' impressions, 0 clicks';
    }

    // Rule 3: clicks but no conversions and high cost
    if (!reason && clicks >= CONFIG.MIN_CLICKS_NO_CONVERSION && conversions === 0 && cost >= CONFIG.MAX_COST_NO_CONVERSION) {
      reason = clicks + ' clicks, $' + cost.toFixed(2) + ' spent, 0 conversions';
    }

    if (reason) {
      toNegate.push({ term: term, reason: reason });
    }
  }

  Logger.log('');
  Logger.log('Search terms reviewed: ' + totalTerms);
  Logger.log('Terms to negate: ' + toNegate.length);
  Logger.log('');

  if (toNegate.length === 0) {
    Logger.log('Nothing to negate — campaign is clean.');
    return;
  }

  // Add negatives
  var added   = 0;
  var skipped = 0;

  for (var i = 0; i < toNegate.length; i++) {
    var item = toNegate[i];
    Logger.log('NEGATE: "' + item.term + '" — ' + item.reason);

    if (!CONFIG.DRY_RUN) {
      try {
        campaign.createNegativeKeyword(item.term);
        added++;
      } catch (e) {
        Logger.log('  Could not add "' + item.term + '": ' + e);
        skipped++;
      }
    }
  }

  Logger.log('');
  Logger.log('==============================================');
  if (CONFIG.DRY_RUN) {
    Logger.log('DRY RUN — no changes made.');
    Logger.log('Set DRY_RUN: false to apply changes.');
  } else {
    Logger.log('Negative keywords added: ' + added);
    if (skipped > 0) Logger.log('Skipped (errors): ' + skipped);
  }
  Logger.log('==============================================');
}

// ================================================================
// HELPERS
// ================================================================
function getExistingNegatives(campaign) {
  var negatives = [];
  try {
    var iter = campaign.negativeKeywords().get();
    while (iter.hasNext()) {
      negatives.push(iter.next().getText().toLowerCase().replace(/[+"\[\]]/g, '').trim());
    }
  } catch (e) {
    // non-fatal
  }
  return negatives;
}
