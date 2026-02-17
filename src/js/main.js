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
      window.location.href = `mailto:hello@improveyoursite.com?subject=${subject}&body=${body}`;
      statusEl.textContent = 'Thanks! Your email app should open now so you can send your audit request.';
    }

    form.reset();
  } catch (error) {
    statusEl.textContent = 'Something went wrong submitting the form. Please email hello@improveyoursite.com directly.';
  }
});
