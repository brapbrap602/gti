// The jobs panel's two toggles: the drawer on narrow screens (.open) and the Recent list
// (.show-recent). Their state lives on aside.jobs, which SSE never replaces; the Recent
// button is inside the replaced #jobs region, so its aria-expanded is restored whenever
// the panel's content changes, as is the Jobs button's running dot.
(function () {
    'use strict';

    function panel() {
        return document.querySelector('aside.jobs');
    }

    function sync() {
        const aside = panel();
        if (!aside) return;
        const running = !!aside.querySelector('.job--running, .job--queued');
        document.querySelectorAll('.jobs-toggle').forEach((b) => {
            b.setAttribute('aria-expanded', String(aside.classList.contains('open')));
            b.classList.toggle('jobs-toggle--running', running);
        });
        aside.querySelectorAll('.recent-toggle').forEach((b) => {
            b.setAttribute('aria-expanded', String(aside.classList.contains('show-recent')));
        });
    }

    document.addEventListener('click', (e) => {
        const aside = panel();
        if (!aside) return;
        if (e.target.closest('.jobs-toggle')) aside.classList.toggle('open');
        else if (e.target.closest('.jobs-close')) aside.classList.remove('open');
        else if (e.target.closest('.recent-toggle')) aside.classList.toggle('show-recent');
        else return;
        sync();
    });

    document.addEventListener('keydown', (e) => {
        const aside = panel();
        if (e.key === 'Escape' && aside && aside.classList.contains('open')) {
            aside.classList.remove('open');
            sync();
            document.querySelector('.jobs-toggle').focus();
        }
    });

    document.addEventListener('DOMContentLoaded', () => {
        const aside = panel();
        if (!aside) return;
        new MutationObserver(sync).observe(aside, { childList: true, subtree: true });
        sync();
    });
})();
