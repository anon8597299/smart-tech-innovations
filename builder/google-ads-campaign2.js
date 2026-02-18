// ================================================================
// ImproveYourSite — Campaign 2
// Google Ads Script — Search Campaign for Australian Small Businesses
//
// HOW TO USE:
// 1. Go to Google Ads → Tools → Scripts → + New Script
// 2. Delete all existing code in the editor
// 3. Paste this entire script
// 4. Click "Authorize" then "Run" to preview
// 5. Check the Logs tab — campaign will be PAUSED for review
// 6. Once happy, go to Campaigns and set it to ENABLED
// ================================================================

var CONFIG = {
  CAMPAIGN_NAME:    'Campaign 2',
  DAILY_BUDGET_AUD: 30,           // ← Change to your preferred daily spend (AUD)
  DEFAULT_CPC_AUD:  2.00,         // ← Max cost-per-click (AUD)
  FINAL_URL:        'https://improveyoursite.com/packages.html',
  PATH1:            'packages',
  PATH2:            'pricing',
  START_PAUSED:     true,         // Keep PAUSED until you review and approve — duplicate removed below
};

// ================================================================
// AD GROUPS & KEYWORDS
// 3 groups targeting different buyer intent levels
// ================================================================
var AD_GROUPS = [
  {
    name: 'Website Design - Small Business',
    cpc:  2.00,
    keywords: [
      { text: 'small business website design',       match: 'BROAD' },
      { text: 'website design for small business',   match: 'BROAD' },
      { text: 'professional website design',         match: 'PHRASE' },
      { text: 'website design australia',            match: 'PHRASE' },
      { text: 'small business website',              match: 'BROAD' },
      { text: 'get a website for my business',       match: 'BROAD' },
      { text: 'business website design',             match: 'PHRASE' },
    ],
  },
  {
    name: 'Website Rebuild & Redesign',
    cpc:  2.50,
    keywords: [
      { text: 'website redesign',                    match: 'PHRASE' },
      { text: 'website rebuild',                     match: 'PHRASE' },
      { text: 'redesign my website',                 match: 'BROAD' },
      { text: 'update my business website',          match: 'BROAD' },
      { text: 'new website for my business',         match: 'BROAD' },
      { text: 'old website redesign',                match: 'BROAD' },
      { text: 'website refresh',                     match: 'PHRASE' },
    ],
  },
  {
    name: 'Improve & Fix My Website',
    cpc:  1.80,
    keywords: [
      { text: 'improve my website',                  match: 'PHRASE' },
      { text: 'fix my website',                      match: 'PHRASE' },
      { text: 'website not getting enquiries',       match: 'BROAD' },
      { text: 'website audit',                       match: 'PHRASE' },
      { text: 'website scan and fix',                match: 'BROAD' },
      { text: 'why is my website not converting',    match: 'BROAD' },
      { text: 'website conversion optimisation',     match: 'PHRASE' },
    ],
  },
];

// ================================================================
// RESPONSIVE SEARCH AD CONTENT
// Up to 15 headlines and 4 descriptions — Google mixes and matches
// ================================================================
var HEADLINES = [
  'Professional Websites From $3,000',
  'Australian Small Business Websites',
  'Get Your Business Website Built',
  'High-Converting Website Design',
  'Website That Wins More Customers',
  'Scan, Fix or Full Website Build',
  'Local Australian Web Design Team',
  'Pay Online — We Build Your Site',
  'Websites That Rank and Convert',
  'Improve Your Site — See Results',
  'View Live Demo Sites Before Buying',
  'No Lock-In — Pay Once, Own It',
  'Trusted by Australian Businesses',
  'Fast Turnaround Website Packages',
  'From Scan and Fix to Full Build',
];

var DESCRIPTIONS = [
  'Professional websites for Australian small businesses. Choose Scan & Fix, Full Build or Premium Growth.',
  'High-converting websites built for Australian businesses. Pay online and we start immediately.',
  'Trusted by Australian small businesses. View live demo sites and choose your package today.',
  'From $3,000 — website packages that drive real enquiries. See our work and get started.',
];

// ================================================================
// NEGATIVE KEYWORDS — stop wasting spend on irrelevant clicks
// ================================================================
var NEGATIVE_KEYWORDS = [
  'free',
  'diy',
  'wix',
  'squarespace',
  'wordpress',
  'template',
  'course',
  'learn',
  'tutorial',
  'how to build',
  'jobs',
  'careers',
  'cheap',
];

// ================================================================
// MAIN
// ================================================================
function main() {
  Logger.log('==============================================');
  Logger.log('  ImproveYourSite — Campaign 2 Builder');
  Logger.log('==============================================');

  // Check campaign doesn't already exist
  var existing = AdsApp.campaigns()
    .withCondition("Name = '" + CONFIG.CAMPAIGN_NAME + "'")
    .get();

  if (existing.hasNext()) {
    Logger.log('WARNING: "' + CONFIG.CAMPAIGN_NAME + '" already exists. Exiting to avoid duplicates.');
    return;
  }

  // Build campaign
  Logger.log('Creating campaign: ' + CONFIG.CAMPAIGN_NAME);

  var campaignOp = AdsApp.newCampaignBuilder()
    .withName(CONFIG.CAMPAIGN_NAME)
    .withStatus(CONFIG.START_PAUSED ? 'PAUSED' : 'ENABLED')
    .withDailyBudget(CONFIG.DAILY_BUDGET_AUD)
    .withBiddingStrategy('MANUAL_CPC')
    .build();

  if (!campaignOp.isSuccessful()) {
    Logger.log('ERROR creating campaign: ' + campaignOp.getErrors());
    return;
  }

  var campaign = campaignOp.getResult();
  Logger.log('Campaign created.');

  // Geo target: Orange and Dubbo (50km radius)
  var LOCATIONS = [
    { city: 'Orange', province: 'New South Wales', radius: 50 },
    { city: 'Dubbo',  province: 'New South Wales', radius: 50 },
  ];

  for (var g = 0; g < LOCATIONS.length; g++) {
    var loc = LOCATIONS[g];
    try {
      campaign.targeting().targetedProximities().newProximityBuilder()
        .withAddress({
          cityName:     loc.city,
          provinceName: loc.province,
          countryCode:  'AU'
        })
        .withRadius(loc.radius, 'KILOMETERS')
        .build();
      Logger.log('Geo targeting set: ' + loc.city + ' (' + loc.radius + 'km radius)');
    } catch (e) {
      Logger.log('Could not set geo for ' + loc.city + '. Set manually. (' + e + ')');
    }
  }

  // Add campaign-level negative keywords
  for (var n = 0; n < NEGATIVE_KEYWORDS.length; n++) {
    try {
      campaign.createNegativeKeyword(NEGATIVE_KEYWORDS[n]);
    } catch (e) {
      // non-fatal
    }
  }
  Logger.log('Negative keywords added: ' + NEGATIVE_KEYWORDS.length);

  // Create ad groups
  for (var i = 0; i < AD_GROUPS.length; i++) {
    createAdGroup(campaign, AD_GROUPS[i]);
  }

  Logger.log('');
  Logger.log('==============================================');
  Logger.log('DONE — Campaign 2 created in PAUSED state.');
  Logger.log('Review in Google Ads, then ENABLE when ready.');
  Logger.log('Daily budget: $' + CONFIG.DAILY_BUDGET_AUD + ' AUD');
  Logger.log('Ad groups: ' + AD_GROUPS.length);
  Logger.log('==============================================');
}

// ================================================================
// CREATE AD GROUP WITH KEYWORDS + RSA
// ================================================================
function createAdGroup(campaign, groupConfig) {
  Logger.log('');
  Logger.log('Ad group: ' + groupConfig.name);

  var adGroupOp = campaign.newAdGroupBuilder()
    .withName(groupConfig.name)
    .withStatus('ENABLED')
    .withCpc(groupConfig.cpc)
    .build();

  if (!adGroupOp.isSuccessful()) {
    Logger.log('  ERROR creating ad group: ' + adGroupOp.getErrors());
    return;
  }

  var adGroup = adGroupOp.getResult();

  // Keywords
  for (var k = 0; k < groupConfig.keywords.length; k++) {
    var kw = groupConfig.keywords[k];
    var kwOp = adGroup.newKeywordBuilder()
      .withText(kw.text)
      .withMatchType(kw.match)
      .withCpc(groupConfig.cpc)
      .build();

    if (kwOp.isSuccessful()) {
      Logger.log('  + [' + kw.match + '] ' + kw.text);
    } else {
      Logger.log('  ERROR keyword "' + kw.text + '": ' + kwOp.getErrors());
    }
  }

  // Responsive Search Ad
  var adBuilder = adGroup.newAd().responsiveSearchAdBuilder()
    .withFinalUrl(CONFIG.FINAL_URL)
    .withPath1(CONFIG.PATH1)
    .withPath2(CONFIG.PATH2);

  for (var h = 0; h < HEADLINES.length; h++) {
    adBuilder = adBuilder.addHeadline(HEADLINES[h]);
  }
  for (var d = 0; d < DESCRIPTIONS.length; d++) {
    adBuilder = adBuilder.addDescription(DESCRIPTIONS[d]);
  }

  var adOp = adBuilder.build();
  if (adOp.isSuccessful()) {
    Logger.log('  RSA ad created.');
  } else {
    Logger.log('  ERROR creating RSA ad: ' + adOp.getErrors());
  }
}
