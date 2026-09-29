const main = () => document.querySelector('#main');

/** Replace the page body, keeping any <details data-key> the user had open. */
export function render(html) {
  const open = new Set([...document.querySelectorAll('details[data-key][open]')].map((d) => d.dataset.key));
  main().innerHTML = html;
  document.querySelectorAll('details[data-key]').forEach((d) => {
    d.open = open.has(d.dataset.key);
  });
}

/**
 * Pages describe navigation in markup instead of wiring handlers:
 *   [data-href="<hash>"]           click goes to that hash
 *   [data-back]                    click goes back in history (falling back to its href)
 *   select[data-nav] / input[data-nav="<hash>"]   change goes to the select's value / the input's hash
 * (multi-select lists are wired by the page that owns them, since their hash depends on the whole selection)
 */
export function installNavigation() {
  const go = (hash) => {
    location.hash = hash;
  };
  document.addEventListener('click', (event) => {
    const back = event.target.closest('[data-back]');
    if (back) {
      event.preventDefault();
      if (history.length > 1) history.back();
      else go(back.getAttribute('href').slice(1));
      return;
    }
    const link = event.target.closest('[data-href]');
    if (link) go(link.dataset.href);
  });
  document.addEventListener('change', (event) => {
    const { target } = event;
    if (!target.matches('[data-nav]')) return;
    const hash = target.tagName === 'SELECT' ? target.value : target.dataset.nav;
    if (hash) go(hash);
  });
}

/** <option>s whose values are hashes; `current` marks the selected one. */
export const hashOptions = (items) =>
  items.map(({ hash, label, selected }) => `<option value="${hash}"${selected ? ' selected' : ''}>${label}</option>`).join('');

const COPY_ICON = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.5" d="M5.5 5.5h7v8h-7zM3.5 10.5v-8h7"/></svg>';
const CHECK_ICON = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" d="M3 8.5l3.5 3.5L13 4.5"/></svg>';
const FEEDBACK_MS = 1500;

/** A button that copies `text` to the clipboard when clicked (see installCopyButtons). */
export const copyButton = (text, label) =>
  `<button class="copy" type="button" data-copy="${text}" title="${label}" aria-label="${label}">${COPY_ICON}</button>`;

/** Handle clicks on every copyButton, briefly swapping its icon to confirm. */
export function installCopyButtons() {
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-copy]');
    if (!button) return;
    const original = button.title;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.innerHTML = CHECK_ICON;
      button.title = 'Copied';
    } catch {
      button.title = 'Copy failed';
    }
    setTimeout(() => {
      button.innerHTML = COPY_ICON;
      button.title = original;
    }, FEEDBACK_MS);
  });
}
