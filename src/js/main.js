// Mobile nav toggle
const toggle = document.getElementById('nav-toggle');
const menu = document.getElementById('nav-menu');

toggle?.addEventListener('click', () => {
  const isOpen = menu?.classList.toggle('active');
  toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
});

// Close menu on link click
menu?.querySelectorAll('.nav__link').forEach((link) => {
  link.addEventListener('click', () => {
    menu.classList.remove('active');
    toggle?.setAttribute('aria-expanded', 'false');
  });
});

// Header scroll effect
const header = document.getElementById('header');
window.addEventListener('scroll', () => {
  header?.classList.toggle('scrolled', window.scrollY > 50);
});

// Smooth reveal on scroll
const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      entry.target.style.opacity = '1';
      entry.target.style.transform = 'translateY(0)';
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.1 });

document
  .querySelectorAll('.service__card, .problem__card, .process__step, .result__card, .portfolio__card, .faq__item')
  .forEach((el) => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(20px)';
    el.style.transition = 'opacity 0.6s, transform 0.6s';
    observer.observe(el);
  });

// FAQ accordion
document.querySelectorAll('.faq__question').forEach((button) => {
  button.addEventListener('click', () => {
    const item = button.closest('.faq__item');
    const isOpen = item?.classList.contains('open');

    document.querySelectorAll('.faq__item').forEach((faqItem) => {
      faqItem.classList.remove('open');
      faqItem.querySelector('.faq__question')?.setAttribute('aria-expanded', 'false');
    });

    if (!isOpen && item) {
      item.classList.add('open');
      button.setAttribute('aria-expanded', 'true');
    }
  });
});

// Dynamic year
const yearEl = document.getElementById('year');
if (yearEl) yearEl.textContent = String(new Date().getFullYear());

// Campaign source tracking from URL params
const params = new URLSearchParams(window.location.search);
const leadSourceInput = document.getElementById('lead-source');
const heroBadge = document.querySelector('.hero__badge');

const utmSource = params.get('utm_source');
const utmMedium = params.get('utm_medium');
const utmCampaign = params.get('utm_campaign');

if (leadSourceInput && (utmSource || utmMedium || utmCampaign)) {
  leadSourceInput.value = `${utmSource || 'direct'}|${utmMedium || 'none'}|${utmCampaign || 'none'}`;
}

if (heroBadge && utmSource === 'offline_qr') {
  heroBadge.textContent = '📍 You scanned the Money-Leak Audit QR';
}

// Contact form submission
const form = document.getElementById('contact-form');
const statusEl = document.getElementById('form-status');

form?.addEventListener('submit', async (e) => {
  e.preventDefault();

  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());

  // Simple honeypot spam check
  if (String(payload.company || '').trim()) {
    return;
  }

  const lines = [
    `Name: ${payload.name || ''}`,
    `Email: ${payload.email || ''}`,
    `Phone: ${payload.phone || ''}`,
    `Website: ${payload.website || ''}`,
    `Goal: ${payload.goal || ''}`,
    `Source: ${payload.source || 'website-direct'}`,
    '',
    'Business details:',
    `${payload.message || ''}`,
  ];

  const endpoint = form.dataset.endpoint;

  try {
    if (endpoint) {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('Submission failed');
      statusEl.textContent = 'Thanks — your audit request has been sent. We will be in touch shortly.';
    } else {
      const subject = encodeURIComponent('New Website Audit Request');
      const body = encodeURIComponent(lines.join('\n'));
      window.location.href = `mailto:james@improveyoursite.com?subject=${subject}&body=${body}`;
      statusEl.textContent = 'Thanks! Your email app should open now so you can send your audit request.';
    }

    form.reset();
    if (leadSourceInput && (utmSource || utmMedium || utmCampaign)) {
      leadSourceInput.value = `${utmSource || 'direct'}|${utmMedium || 'none'}|${utmCampaign || 'none'}`;
    }
  } catch (error) {
    statusEl.textContent = 'Something went wrong submitting the form. Please email james@improveyoursite.com directly.';
  }
});

// Testimonials horizontal controls
const testimonialTrack = document.getElementById('testimonials-track');
document.getElementById('testimonials-prev')?.addEventListener('click', () => {
  testimonialTrack?.scrollBy({ left: -340, behavior: 'smooth' });
});
document.getElementById('testimonials-next')?.addEventListener('click', () => {
  testimonialTrack?.scrollBy({ left: 340, behavior: 'smooth' });
});

// ROI calculator
const roiCalcBtn = document.getElementById('roi-calc');
const roiResult = document.getElementById('roi-result');

roiCalcBtn?.addEventListener('click', () => {
  const visitors = Number(document.getElementById('roi-visitors')?.value || 0);
  const current = Number(document.getElementById('roi-current')?.value || 0) / 100;
  const target = Number(document.getElementById('roi-target')?.value || 0) / 100;
  const value = Number(document.getElementById('roi-value')?.value || 0);

  const currentRevenue = visitors * current * value;
  const targetRevenue = visitors * target * value;
  const uplift = Math.max(0, targetRevenue - currentRevenue);

  if (roiResult) {
    roiResult.innerHTML = `<p>Potential additional monthly revenue</p><h3>$${Math.round(uplift).toLocaleString()}</h3><small>Based on your estimates. Annual upside: $${Math.round(uplift * 12).toLocaleString()}</small>`;
  }
});

// Sticky CTA show/hide based on scroll depth
const stickyCta = document.getElementById('sticky-cta');
window.addEventListener('scroll', () => {
  if (!stickyCta) return;
  if (window.scrollY > 700) stickyCta.classList.add('show');
  else stickyCta.classList.remove('show');
});
