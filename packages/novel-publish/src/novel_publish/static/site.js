// Scroll-to-top button: shown while scrolling up, away from the top of the page.
document.addEventListener('DOMContentLoaded', function () {
    const button = document.getElementById('scrollToTopBtn');
    if (!button) return;

    let lastScrollY = window.pageYOffset;
    window.addEventListener('scroll', function () {
        const currentScrollY = window.pageYOffset;
        button.classList.toggle('visible', currentScrollY < lastScrollY && currentScrollY > 300);
        lastScrollY = currentScrollY;
    });

    button.addEventListener('click', function () {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
});
