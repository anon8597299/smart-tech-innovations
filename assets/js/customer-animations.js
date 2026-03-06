/**
 * customer-animations.js — IYS Premium UI animation engine
 *
 * Loaded by all customer sites. Requires (via CDN, loaded before this file):
 *   - GSAP + ScrollTrigger
 *   - Lenis smooth scroll
 *   - Swiper
 *
 * Works across all IYS templates without template-specific markup changes.
 * Gracefully no-ops if any library fails to load.
 */

(function () {
  'use strict';

  // ── Lenis smooth scroll ──────────────────────────────────────────────────
  if (window.Lenis) {
    const lenis = new Lenis({ lerp: 0.1, wheelMultiplier: 0.9 });
    function rafLoop(time) { lenis.raf(time); requestAnimationFrame(rafLoop); }
    requestAnimationFrame(rafLoop);
    // Connect to GSAP ScrollTrigger tick if available
    if (window.gsap && window.ScrollTrigger) {
      lenis.on('scroll', ScrollTrigger.update);
      gsap.ticker.add(time => lenis.raf(time * 1000));
      gsap.ticker.lagSmoothing(0);
    }
  }

  // ── Guard: GSAP required for everything below ────────────────────────────
  if (!window.gsap) return;

  if (window.ScrollTrigger) {
    gsap.registerPlugin(ScrollTrigger);
  }

  // ── Hero animations (run immediately on load) ────────────────────────────
  const heroSection = document.querySelector('.hero');
  if (heroSection) {
    // Stagger the main hero text elements in
    const heroEls = heroSection.querySelectorAll(
      'h1, .lead, .badge, .cta, .trust-strip, .hero-grid, .hero-contact, .hero-badges'
    );
    if (heroEls.length) {
      gsap.from(heroEls, {
        y: 28,
        opacity: 0,
        duration: 0.7,
        stagger: 0.1,
        ease: 'power3.out',
        delay: 0.1,
      });
    }

    // Hero visual card floats in from right
    const heroVisual = heroSection.querySelector('.hero-visual, .hero-card');
    if (heroVisual) {
      gsap.from(heroVisual, {
        x: 30,
        opacity: 0,
        duration: 0.8,
        ease: 'power3.out',
        delay: 0.3,
      });
    }
  }

  // ── Scroll-triggered animations ──────────────────────────────────────────
  if (!window.ScrollTrigger) return;

  // Generic "fade up" for any element with [data-reveal]
  document.querySelectorAll('[data-reveal]').forEach(el => {
    gsap.from(el, {
      scrollTrigger: { trigger: el, start: 'top 88%' },
      y: 24, opacity: 0, duration: 0.6, ease: 'power2.out',
    });
  });

  // Service cards — staggered fade up
  const serviceGrids = document.querySelectorAll(
    '.services-grid, .grid-3, .collections-grid, .offers-grid'
  );
  serviceGrids.forEach(grid => {
    const cards = grid.querySelectorAll(
      '.service-card, .collection-card, .offer-card, .feature-card, [class*="-card"]'
    );
    if (cards.length) {
      gsap.from(cards, {
        scrollTrigger: { trigger: grid, start: 'top 85%' },
        y: 32, opacity: 0, duration: 0.55, stagger: 0.1, ease: 'power2.out',
      });
    }
  });

  // KPI / stat numbers — count up + fade in
  const kpiEls = document.querySelectorAll('.kpi, .stat-item, .stat-card, [class*="kpi-"]');
  kpiEls.forEach((el, i) => {
    gsap.from(el, {
      scrollTrigger: { trigger: el, start: 'top 88%' },
      y: 20, opacity: 0, duration: 0.5, delay: i * 0.08, ease: 'power2.out',
    });
    // Animate numbers inside
    const num = el.querySelector('strong, .stat-value, .kpi-value');
    if (num) {
      const raw = num.textContent.replace(/[^0-9.]/g, '');
      const target = parseFloat(raw);
      const prefix = num.textContent.split(raw)[0] || '';
      const suffix = num.textContent.split(raw)[1] || '';
      if (!isNaN(target) && target > 0) {
        ScrollTrigger.create({
          trigger: el,
          start: 'top 88%',
          once: true,
          onEnter: () => {
            gsap.from({ val: 0 }, {
              val: target,
              duration: 1.4,
              ease: 'power2.out',
              onUpdate: function () {
                num.textContent = prefix + Math.round(this.targets()[0].val) + suffix;
              },
            });
          },
        });
      }
    }
  });

  // Trust bar — slide in from left
  const trustBar = document.querySelector('.trust-bar');
  if (trustBar) {
    const items = trustBar.querySelectorAll('.trust-item');
    gsap.from(items, {
      scrollTrigger: { trigger: trustBar, start: 'top 90%' },
      x: -20, opacity: 0, duration: 0.5, stagger: 0.12, ease: 'power2.out',
    });
  }

  // Section headings — fade up
  document.querySelectorAll('.section h2, .section-label').forEach(heading => {
    gsap.from(heading, {
      scrollTrigger: { trigger: heading, start: 'top 88%' },
      y: 20, opacity: 0, duration: 0.55, ease: 'power2.out',
    });
  });

  // ── Swiper: auto-convert testimonials grid to carousel ───────────────────
  if (window.Swiper) {
    const tGrid = document.querySelector('.testimonials-grid');
    if (tGrid) {
      // Wrap cards in Swiper structure
      const cards = Array.from(tGrid.querySelectorAll('.testimonial-card'));
      if (cards.length > 1) {
        const wrapper = document.createElement('div');
        wrapper.className = 'swiper-wrapper';
        cards.forEach(card => {
          const slide = document.createElement('div');
          slide.className = 'swiper-slide';
          slide.appendChild(card);
          wrapper.appendChild(slide);
        });
        const pagination = document.createElement('div');
        pagination.className = 'swiper-pagination';

        tGrid.innerHTML = '';
        tGrid.classList.add('swiper', 'swiper-testimonials');
        tGrid.style.cssText = 'display:block;overflow:hidden;position:relative;';
        tGrid.appendChild(wrapper);
        tGrid.appendChild(pagination);

        new Swiper(tGrid, {
          slidesPerView: 1,
          spaceBetween: 16,
          loop: true,
          autoplay: { delay: 5000, disableOnInteraction: false },
          pagination: { el: pagination, clickable: true },
          breakpoints: {
            640:  { slidesPerView: 1.2 },
            900:  { slidesPerView: 2.2 },
            1100: { slidesPerView: 3 },
          },
        });
      }
    }
  }

  // ── Floating glow background parallax ───────────────────────────────────
  const glow = document.querySelector('.hero-glow');
  if (glow) {
    gsap.to(glow, {
      y: 60, ease: 'none',
      scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 1.5 },
    });
  }

})();
