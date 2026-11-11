// The reader site: the reading page's bar and chapter navigation, resume (the library's Continue row),
// "Go to chapter", and text settings. One file, no framework; sections are independent and each starts from
// its own markup. Everything here must keep working when localStorage throws: then
// nothing is saved.
(function () {
    'use strict';

    // -- storage --------------------------------------------------------------

    const POSITION = 'reader:pos:'; // + novel slug: {file, anchor, para, label, t}

    const storage = {
        get(key) {
            try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; }
        },
        set(key, value) {
            this.setRaw(key, JSON.stringify(value));
        },
        raw(key) { // the stored text, or null
            try { return localStorage.getItem(key); } catch (e) { return null; }
        },
        setRaw(key, text) {
            try { localStorage.setItem(key, text); } catch (e) { /* not saved */ }
        },
        remove(key) {
            try { localStorage.removeItem(key); } catch (e) { /* nothing to remove */ }
        },
    };

    // -- reading page: bar, current chapter, in-page jumps --------------------

    const REVEAL_TOP = 64;   // px from the top where the bar always shows
    const REVEAL_TRAVEL = 8; // px of scrolling in one direction that shows or hides it

    // Returns the current article and the bar's height, for resume; null off a reading page.
    function initReader() {
        const bar = document.querySelector('.reader-bar');
        const articles = Array.from(document.querySelectorAll('main > article'));
        if (!bar || !articles.length) return null;
        bar.hidden = false;
        const title = bar.querySelector('.bar-title');
        const prevLink = bar.querySelector('.bar-prev');
        const nextLink = bar.querySelector('.bar-next');
        const sheetLinks = Array.from(document.querySelectorAll('#chapters .sheet-toc a'));
        let current = -1;

        function currentIndex() {
            const doc = document.documentElement;
            if (scrollY + innerHeight >= doc.scrollHeight - 2) return articles.length - 1;
            const line = bar.offsetHeight + 1;
            let found = 0;
            articles.forEach((article, i) => {
                if (article.getBoundingClientRect().top <= line) found = i;
            });
            return found;
        }

        function setLink(link, href) {
            if (href) {
                link.setAttribute('href', href);
                link.removeAttribute('aria-disabled');
            } else {
                link.removeAttribute('href');
                link.setAttribute('aria-disabled', 'true');
            }
        }

        function updateCurrent() {
            const i = currentIndex();
            if (i === current) return;
            current = i;
            const heading = articles[i].querySelector('.chapter');
            title.textContent = heading ? heading.textContent.replace(/^Chapter /, 'Ch ') : '';
            setLink(prevLink, i > 0 ? '#' + articles[i - 1].id : bar.dataset.prevPage);
            setLink(nextLink, i < articles.length - 1 ? '#' + articles[i + 1].id : bar.dataset.nextPage);
            const hash = '#' + articles[i].id;
            sheetLinks.forEach((a) => {
                if (a.getAttribute('href') === hash) a.setAttribute('aria-current', 'location');
                else a.removeAttribute('aria-current');
            });
        }

        let lastY = scrollY;
        let travel = 0;

        function show(shown) {
            bar.classList.toggle('reader-bar--shown', shown);
        }

        function reveal() {
            const dy = scrollY - lastY;
            lastY = scrollY;
            if (dy && Math.sign(dy) !== Math.sign(travel)) travel = 0;
            travel += dy;
            if (scrollY < REVEAL_TOP || travel <= -REVEAL_TRAVEL) show(true);
            else if (travel >= REVEAL_TRAVEL && !document.querySelector('dialog[open]')) show(false);
        }

        // An in-page jump from the bar or the chapters sheet: the bar stays as it was.
        function jump(link) {
            const dialog = link.closest('dialog');
            if (dialog) dialog.close();
            const hash = link.getAttribute('href');
            if (location.hash === hash) document.getElementById(hash.slice(1)).scrollIntoView();
            else location.hash = hash;
            lastY = scrollY;
            travel = 0;
            link.blur();
        }

        document.addEventListener('click', (e) => {
            const link = e.target.closest('.reader-bar a[href^="#"], #chapters a[href^="#"]');
            if (!link) return;
            e.preventDefault();
            jump(link);
        });

        let pending = false;
        addEventListener('scroll', () => {
            if (pending) return;
            pending = true;
            requestAnimationFrame(() => {
                pending = false;
                updateCurrent();
                reveal();
            });
        }, { passive: true });
        bar.addEventListener('focusin', () => show(true));

        updateCurrent();
        show(scrollY < REVEAL_TOP);
        return {
            article: () => articles[currentIndex()],
            barHeight: () => bar.offsetHeight,
        };
    }

    // -- resume: save the last place actually read ----------------------------
    //
    // Saving arms once this visit has scrolled 1.5 viewports, counting only steps of at
    // most one viewport: anything bigger is a jump (a link, go-to, the arrows, the
    // browser restoring the scroll on reload, the ?p restore), not reading. Arriving
    // through Continue arms it at once. Until armed nothing is written, so a quick look
    // at an old range keeps the saved place.

    const ARM_VIEWPORTS = 1.5;
    const SAVE_DELAY = 1000; // ms

    function initResume(reader) {
        const main = document.querySelector('main[data-slug]');
        if (!reader || !main) return;
        const key = POSITION + main.dataset.slug;
        const file = location.pathname.split('/').pop();
        const restore = restoreTarget();
        let armed = restore !== null;
        let distance = 0;
        let lastY = scrollY;
        let timer = 0;

        function save() {
            clearTimeout(timer);
            if (!armed) return;
            const article = reader.article();
            const line = reader.barHeight();
            const paragraphs = Array.from(article.querySelectorAll('p'));
            let para = paragraphs.findIndex((p) => p.getBoundingClientRect().bottom > line);
            if (para < 0) para = Math.max(paragraphs.length - 1, 0);
            storage.set(key, { file, anchor: article.id, para, label: article.dataset.label, t: Date.now() });
        }

        addEventListener('scroll', () => {
            const dy = Math.abs(scrollY - lastY);
            lastY = scrollY;
            if (dy <= innerHeight) distance += dy;
            if (distance >= ARM_VIEWPORTS * innerHeight) armed = true;
            if (armed) {
                clearTimeout(timer);
                timer = setTimeout(save, SAVE_DELAY);
            }
        }, { passive: true });
        addEventListener('pagehide', save);
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'hidden') save();
        });

        if (restore) {
            history.replaceState(history.state, '', location.pathname + location.hash);
            // Again on load: the browser's own scroll to the #anchor can land after DOMContentLoaded.
            const go = () => {
                restore.scrollIntoView();
                lastY = scrollY;
            };
            go();
            addEventListener('load', go, { once: true });
        }
    }

    // The paragraph a Continue link (?p=<index>#<anchor>) points at, clamped; else null.
    function restoreTarget() {
        const p = new URLSearchParams(location.search).get('p');
        const article = location.hash && document.getElementById(location.hash.slice(1));
        if (p === null || !/^\d+$/.test(p) || !article) return null;
        const paragraphs = article.querySelectorAll('p');
        return paragraphs.length ? paragraphs[Math.min(Number(p), paragraphs.length - 1)] : article;
    }

    // -- library: the Continue row ---------------------------------------------
    //
    // One entry per listed novel with a saved place in this browser, most recent first,
    // built from the list rows (titles from data-title, so a renamed novel shows its new
    // title). × forgets the place at once; Undo puts it back unless something newer was
    // saved meanwhile. The Undo line sits outside the row, so it survives the row emptying.

    const SAVED_FILE = /^\d+-\d+\.html$/;
    const SAVED_ANCHOR = /^c\d+(-\d+)?$/;
    const UNDO_FOR = 6000; // ms
    const YEAR = 365 * 86400;
    const AGES = [['month', 30 * 86400], ['week', 7 * 86400], ['day', 86400], ['hour', 3600], ['minute', 60]];

    function validPlace(pos) {
        return !!pos && SAVED_FILE.test(pos.file) && SAVED_ANCHOR.test(pos.anchor)
            && Number.isInteger(pos.para) && pos.para >= 0;
    }

    // "just now", "5 minutes ago", ... "3 months ago"; '' when t is missing or over a year old.
    function ago(t, now) {
        if (!Number.isFinite(t)) return '';
        const seconds = (now - t) / 1000;
        if (seconds > YEAR) return '';
        const found = AGES.find(([, size]) => seconds >= size);
        if (!found) return 'just now';
        const [unit, size] = found;
        return new Intl.RelativeTimeFormat('en', { numeric: 'auto' }).format(-Math.floor(seconds / size), unit);
    }

    function initContinue() {
        const row = document.querySelector('.continue-row');
        if (!row) return;
        const list = row.querySelector('.continue-list');
        const undoLine = document.querySelector('.continue-undo');
        const allHeading = document.getElementById('all-h');
        const novels = Array.from(document.querySelectorAll('li.novel-row[data-slug]'));
        let undoTimer = 0;

        function places() {
            const found = [];
            novels.forEach((novel) => {
                const pos = storage.get(POSITION + novel.dataset.slug);
                if (!validPlace(pos)) return;
                const files = Array.from(novel.querySelectorAll('.book-parts a'), (a) => a.getAttribute('href').split('/').pop());
                if (!files.includes(pos.file)) return; // its page has left the site
                found.push({ slug: novel.dataset.slug, title: novel.dataset.title, pos });
            });
            const time = (p) => (Number.isFinite(p.pos.t) ? p.pos.t : 0);
            return found.sort((a, b) => time(b) - time(a));
        }

        function entry(place, now) {
            const li = document.createElement('li');
            li.dataset.slug = place.slug;
            const link = document.createElement('a');
            link.className = 'continue-link';
            link.href = `novels/${place.slug}/${place.pos.file}?p=${place.pos.para}#${place.pos.anchor}`;
            const title = document.createElement('span');
            title.className = 'continue-title';
            title.textContent = place.title;
            const meta = document.createElement('span');
            meta.className = 'continue-meta';
            const ch = document.createElement('span');
            ch.className = 'continue-ch';
            ch.textContent = `Ch ${place.pos.label}`;
            meta.append(ch);
            const when = ago(place.pos.t, now);
            if (when) {
                const time = document.createElement('span');
                time.className = 'continue-time';
                time.textContent = when;
                meta.append(' · ', time);
            }
            link.append(title, meta);
            const forget = document.createElement('button');
            forget.type = 'button';
            forget.className = 'forget';
            forget.setAttribute('aria-label', `Forget your place in ${place.title}`);
            forget.textContent = '×';
            li.append(link, forget);
            return li;
        }

        function render() {
            const now = Date.now();
            list.replaceChildren(...places().map((p) => entry(p, now)));
            row.hidden = !list.children.length;
        }

        function firstLinkOrHeading() {
            return list.querySelector('a') || allHeading;
        }

        function endUndo(moveFocus) {
            clearTimeout(undoTimer);
            const hadFocus = undoLine.contains(document.activeElement);
            undoLine.replaceChildren();
            if (moveFocus && hadFocus) firstLinkOrHeading().focus();
        }

        function offerUndo(place, json) {
            endUndo(false);
            const undo = document.createElement('button');
            undo.type = 'button';
            undo.id = 'continue-undo-button';
            undo.textContent = 'Undo';
            undo.addEventListener('click', () => {
                if (storage.raw(POSITION + place.slug) === null) storage.setRaw(POSITION + place.slug, json);
                endUndo(false);
                render();
                const back = list.querySelector(`li[data-slug="${CSS.escape(place.slug)}"] a`);
                (back || firstLinkOrHeading()).focus();
            });
            undoLine.append(`Forgot your place in ${place.title}. `, undo);
            undo.focus();
            undoTimer = setTimeout(() => endUndo(true), UNDO_FOR);
        }

        list.addEventListener('click', (e) => {
            const button = e.target.closest('button.forget');
            if (!button) return;
            const slug = button.closest('li').dataset.slug;
            const key = POSITION + slug;
            const json = storage.raw(key);
            storage.remove(key);
            render();
            if (json !== null) offerUndo(novels.find((n) => n.dataset.slug === slug).dataset, json);
        });
        // Leaving the page ends the offer: the place stays forgotten.
        addEventListener('pagehide', () => endUndo(false));
        // Back from the back/forward cache: places may have changed on the pages read meanwhile.
        addEventListener('pageshow', (e) => {
            if (e.persisted) render();
        });
        render();
    }

    // -- dialogs --------------------------------------------------------------

    function initDialogs() {
        document.addEventListener('click', (e) => {
            const opener = e.target.closest('[data-open]');
            if (!opener) return;
            const dialog = document.getElementById(opener.dataset.open);
            dialog.showModal();
            const here = dialog.querySelector('[aria-current]');
            if (here) here.scrollIntoView({ block: 'nearest' });
        });
    }

    // -- go to chapter (reading page and library) ------------------------------

    const tocs = new Map(); // toc.json URL -> promise of its contents, fetched on first use

    function loadToc(url) {
        if (!tocs.has(url)) {
            tocs.set(url, fetch(url).then((r) => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            }).catch((e) => {
                tocs.delete(url); // try again next time
                throw e;
            }));
        }
        return tocs.get(url);
    }

    // The first page entry holding chapter n, else the nearest numbers either side.
    function findChapter(toc, n) {
        let below = null;
        let above = null;
        for (const page of toc.pages) {
            for (const chapter of page.chapters) {
                if (chapter.n === n) return { file: page.file, anchor: chapter.a };
                if (chapter.n < n && (below === null || chapter.n > below)) below = chapter.n;
                if (chapter.n > n && (above === null || chapter.n < above)) above = chapter.n;
            }
        }
        return { nearest: [below, above].filter((x) => x !== null) };
    }

    function initGoto(form) {
        form.hidden = false;
        const input = form.querySelector('input');
        const status = form.querySelector('[role="status"]');
        const tocUrl = new URL(form.closest('[data-toc]').dataset.toc, location.href);

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const text = input.value.trim();
            if (!/^\d+$/.test(text)) {
                status.textContent = 'Enter a chapter number.';
                return;
            }
            const n = Number(text);
            let toc;
            try {
                toc = await loadToc(tocUrl.href);
            } catch (err) {
                status.textContent = "Couldn't load the chapter list.";
                return;
            }
            const found = findChapter(toc, n);
            if (!found.file) {
                const nearest = found.nearest.length ? ` Nearest: ${found.nearest.join(' or ')}.` : '';
                status.textContent = `Chapter ${n} isn't on the site.${nearest}`;
                return;
            }
            status.textContent = '';
            const dialog = form.closest('dialog');
            if (dialog) dialog.close();
            const target = new URL(found.file, tocUrl);
            target.hash = found.anchor;
            location.assign(target.href);
        });
    }

    // -- settings -------------------------------------------------------------

    function initSettings() {
        const dialog = document.getElementById('settings');
        if (!dialog) return;
        const output = dialog.querySelector('output');
        const smaller = dialog.querySelector('[data-size="-1"]');
        const larger = dialog.querySelector('[data-size="1"]');
        const { key, apply, scales, current } = window.readerSettings;

        const radios = Array.from(dialog.querySelectorAll('fieldset input[type="radio"]'));

        function show(s) {
            output.textContent = Math.round(scales[s.scale] * 100) + '%';
            smaller.disabled = s.scale === 0;
            larger.disabled = s.scale === scales.length - 1;
            // Every radio group is named after its settings field; a value with no radio checks none.
            radios.forEach((radio) => { radio.checked = s[radio.name] === radio.value; });
        }

        function change(patch) {
            const s = apply(Object.assign({}, current(), patch));
            storage.set(key, s);
            show(s);
        }

        dialog.addEventListener('click', (e) => {
            const button = e.target.closest('[data-size]');
            if (button) change({ scale: current().scale + Number(button.dataset.size) });
        });
        dialog.addEventListener('change', (e) => {
            if (radios.includes(e.target)) change({ [e.target.name]: e.target.value });
        });
        show(current());
    }

    document.addEventListener('DOMContentLoaded', () => {
        initContinue();
        initResume(initReader());
        initDialogs();
        document.querySelectorAll('form.goto').forEach(initGoto);
        initSettings();
    });
})();
