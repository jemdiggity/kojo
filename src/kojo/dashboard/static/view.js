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
    const hash = target.tagName === 'SELECT' ? target.value : target.dataset.nav;
    if (hash) go(hash);
  });
}

/** <option>s whose values are hashes; `current` marks the selected one. */
export const hashOptions = (items) =>
  items.map(({ hash, label, selected }) => `<option value="${hash}"${selected ? ' selected' : ''}>${label}</option>`).join('');
