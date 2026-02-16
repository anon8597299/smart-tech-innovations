// Mobile nav toggle
const toggle = document.getElementById('nav-toggle');
const menu = document.getElementById('nav-menu');
toggle?.addEventListener('click', () => menu.classList.toggle('active'));

// Close menu on link click
document.querySelectorAll('.nav__link').forEach(link => {
  link.addEventListener('click', () => menu.classList.remove('active'));
});

// Header scroll effect
const header = document.getElementById('header');
window.addEventListener('scroll', () => {
  header.classList.toggle('scrolled', window.scrollY > 50);
});

// Smooth reveal on scroll
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.style.opacity = '1';
      entry.target.style.transform = 'translateY(0)';
    }
  });
}, { threshold: 0.1 });

document.querySelectorAll('.service__card, .problem__card, .process__step, .result__card').forEach(el => {
  el.style.opacity = '0';
  el.style.transform = 'translateY(20px)';
  el.style.transition = 'opacity 0.6s, transform 0.6s';
  observer.observe(el);
});

// Form submission
document.getElementById('contact-form')?.addEventListener('submit', (e) => {
  e.preventDefault();
  const data = new FormData(e.target);
  // TODO: Connect to backend/email service
  alert('Thanks! We\'ll be in touch within 24 hours with your free audit.');
  e.target.reset();
});
