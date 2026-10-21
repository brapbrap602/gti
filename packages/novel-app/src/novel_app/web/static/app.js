// nov serve's behaviour on top of htmx: two sheets (the jobs panel and, on narrow or wide
// pages, the sidebar), the Jobs pill and job progress mirrored from #jobs, dropdown menus,
// toasts in #notice, and the novel page's hash tabs.
//
// Sheet and Recent state live on elements SSE never replaces (aside.jobs, nav#sidebar); the
// tab lives on <html data-tab>, outside #main, so a live reload of main keeps it. Whatever
// sits inside a replaced region (the Recent button, the pill's mirror targets, tab links) is
// brought back in step after each swap.
(function () {
    'use strict';

    const root = document.documentElement;
    const PANELS = ['sources', 'chapters', 'translate', 'check'];
    const TOAST_MS = 6000;
    const SHEETS = [
        { sheet: 'aside.jobs', toggle: '.jobs-toggle', close: '.jobs-close' },
        { sheet: '#sidebar', toggle: '.nav-toggle', close: '.sidebar-close' },
    ];

    // -- sheets ---------------------------------------------------------------------

    function setSheet(s, open) {
        const sheet = document.querySelector(s.sheet);
        if (!sheet) return;
        sheet.classList.toggle('open', open);
        document.querySelectorAll(s.toggle).forEach((b) => b.setAttribute('aria-expanded', String(open)));
    }

    function openSheet() {
        return SHEETS.find((s) => document.querySelector(s.sheet + '.open'));
    }

    function toggleSheet(s) {
        const opening = !document.querySelector(s.sheet + '.open');
        SHEETS.forEach((other) => setSheet(other, false));  // one sheet at a time
        setSheet(s, opening);
        root.classList.toggle('sheet-open', opening);
        if (opening) document.querySelector(s.sheet).querySelector(s.close)?.focus();
    }

    function closeSheets(returnFocus) {
        const s = openSheet();
        SHEETS.forEach((other) => setSheet(other, false));
        root.classList.remove('sheet-open');
        if (s && returnFocus) document.querySelector(s.toggle)?.focus();
    }

    // -- the Jobs pill and progress mirrors -----------------------------------------

    function sync() {
        const aside = document.querySelector('aside.jobs');
        if (!aside) return;
        const active = [...aside.querySelectorAll('#jobs li.job--running, #jobs li.job--queued')];
        // Unresolved problems: what needs attention and is not active (the server counts the same).
        const problems = aside.querySelectorAll('#jobs li.job:not(.job--recent):not(.job--running):not(.job--queued)').length;
        const first = active.find((li) => li.querySelector('progress'));

        document.querySelectorAll('.jobs-toggle').forEach((b) => {
            b.setAttribute('aria-expanded', String(aside.classList.contains('open')));
            b.classList.toggle('jobs-toggle--running', active.length > 0);
            b.classList.toggle('jobs-toggle--problem', !active.length && problems > 0);
            const label = b.querySelector('.pill-label');
            if (label) {
                label.textContent = active.length ? `${active.length} running`
                    : problems ? `${problems} problem${problems === 1 ? '' : 's'}` : 'Jobs';
            }
            const bar = b.querySelector('.pill-progress');
            if (bar) mirrorProgress(bar, first && first.querySelector('progress'));
        });
        aside.querySelectorAll('.recent-toggle').forEach((b) => {
            b.setAttribute('aria-expanded', String(aside.classList.contains('show-recent')));
        });

        // A novel's card or header shows its job's progress; #main only reloads when a job starts or ends.
        document.querySelectorAll('[data-job-progress]').forEach((el) => {
            const li = active.find((j) => j.dataset.target === el.dataset.jobProgress);
            el.hidden = !li;
            if (!li) return;
            const source = li.querySelector('progress');
            const text = el.querySelector('.job-progress-text');
            if (text) {
                text.textContent = source ? `${li.dataset.label} ${source.value}/${source.max}`
                    : `${li.dataset.label} ${li.querySelector('.job-state')?.textContent || ''}`.trim();
            }
            const bar = el.querySelector('progress');
            if (bar) mirrorProgress(bar, source);
        });
    }

    function mirrorProgress(bar, source) {
        bar.hidden = !source;
        if (!source) return;
        bar.max = source.max;
        bar.value = source.value;
    }

    // -- toasts ---------------------------------------------------------------------

    let toastTimer = 0;

    // A success clears itself; an error stays until closed or replaced. Every swap into
    // #notice cancels the pending timer first, so an old timer never wipes a newer error.
    function armToast() {
        clearTimeout(toastTimer);
        const toast = document.querySelector('#notice .toast');
        if (!toast || toast.classList.contains('toast--destructive')) return;
        toastTimer = setTimeout(() => {
            if (toast.isConnected) toast.remove();
        }, TOAST_MS);
    }

    // -- tabs on the novel page ---------------------------------------------------------

    function showTab(name) {
        if (!document.querySelector('[data-tabs]')) return;
        if (!document.querySelector(`[data-panel="${name}"]`)) name = 'chapters';
        root.dataset.tab = name;
        document.querySelectorAll('[data-tab-link]').forEach((a) => {
            if (a.dataset.tabLink === name) a.setAttribute('aria-current', 'true');
            else a.removeAttribute('aria-current');
        });
    }

    // -- events ---------------------------------------------------------------------

    document.addEventListener('click', (e) => {
        const t = e.target;
        document.querySelectorAll('details.menu[open]').forEach((m) => {
            if (!m.contains(t)) m.open = false;
        });

        const toggled = SHEETS.find((s) => t.closest(s.toggle));
        if (toggled) {
            toggleSheet(toggled);
            sync();
            return;
        }
        if (SHEETS.some((s) => t.closest(s.close))) {
            closeSheets(true);
            sync();
            return;
        }
        if (t.closest('.recent-toggle')) {
            document.querySelector('aside.jobs').classList.toggle('show-recent');
            sync();
            return;
        }
        if (t.closest('.toast-close')) {
            clearTimeout(toastTimer);
            t.closest('.toast').remove();
            return;
        }
        // A click outside the open sheet (on the scrim) closes it.
        const s = openSheet();
        if (s && !t.closest(s.sheet)) closeSheets(false);

        // Links to a panel switch tabs: tab links, and #check from the estimate or a failed count.
        const link = t.closest('a[href^="#"]');
        const name = link && link.getAttribute('href').slice(1);
        if (name && PANELS.includes(name) && document.querySelector(`[data-panel="${name}"]`)) {
            e.preventDefault();
            showTab(name);
            history.replaceState(null, '', '#' + name);
            document.querySelector('[data-tabs]')?.scrollIntoView({ block: 'start' });
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        const menu = document.querySelector('details.menu[open]');
        if (menu) {
            menu.open = false;
            menu.querySelector('summary').focus();
            return;
        }
        if (openSheet()) {
            closeSheets(true);
            sync();
        }
    });

    addEventListener('hashchange', () => {
        const name = location.hash.slice(1);
        if (PANELS.includes(name)) showTab(name);
    });

    document.addEventListener('htmx:beforeSwap', (e) => {
        if (e.detail.target && e.detail.target.id === 'notice') clearTimeout(toastTimer);
    });

    document.addEventListener('htmx:afterSwap', (e) => {
        if (e.detail.target && e.detail.target.id === 'notice') armToast();
        showTab(root.dataset.tab);
        sync();
    });

    document.addEventListener('DOMContentLoaded', () => {
        const aside = document.querySelector('aside.jobs');
        if (aside) new MutationObserver(sync).observe(aside, { childList: true, subtree: true });
        showTab(root.dataset.tab);
        sync();
        armToast();  // the ?notice= of a plain form's redirect
    });
})();
