// The reader site: text settings (more sections join as the reader grows).
// Everything here must keep working when localStorage throws; then nothing is saved.
(function () {
    'use strict';

    // -- storage --------------------------------------------------------------

    const SETTINGS = 'reader:settings';

    const storage = {
        get(key) {
            try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; }
        },
        set(key, value) {
            try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* not saved */ }
        },
    };

    // -- settings -------------------------------------------------------------

    function initSettings() {
        const dialog = document.getElementById('settings');
        if (!dialog) return;
        const output = dialog.querySelector('output');
        const smaller = dialog.querySelector('[data-size="-1"]');
        const larger = dialog.querySelector('[data-size="1"]');
        const { apply, scales, current } = window.readerSettings;

        function show(s) {
            output.textContent = Math.round(scales[s.scale] * 100) + '%';
            smaller.disabled = s.scale === 0;
            larger.disabled = s.scale === scales.length - 1;
            dialog.querySelector(`input[name="theme"][value="${s.theme}"]`).checked = true;
        }

        function change(patch) {
            const s = apply(Object.assign({}, current(), patch));
            storage.set(SETTINGS, s);
            show(s);
        }

        dialog.addEventListener('click', (e) => {
            const button = e.target.closest('[data-size]');
            if (button) change({ scale: current().scale + Number(button.dataset.size) });
        });
        dialog.addEventListener('change', (e) => {
            if (e.target.name === 'theme') change({ theme: e.target.value });
        });
        show(current());
    }

    document.addEventListener('DOMContentLoaded', () => {
        initSettings();
    });
})();
