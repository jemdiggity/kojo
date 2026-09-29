const main = () => document.querySelector('#main');

/** Replace the page body, keeping any <details data-key> the user had open. */
export function render(html) {
  const open = new Set([...document.querySelectorAll('details[data-key][open]')].map((d) => d.dataset.key));
  main().innerHTML = html;
  document.querySelectorAll('details[data-key]').forEach((d) => {
    d.open = open.has(d.dataset.key);
  });
}

export const navigate = (hash) => {
  location.hash = hash;
};

/** Run `handler(target)` on change/click for each element matching `selector`. */
export function on(event, selector, handler) {
  document.querySelectorAll(selector).forEach((el) => el.addEventListener(event, () => handler(el)));
}

export const options = (choices, current) =>
  Object.entries(choices)
    .map(([value, label]) => `<option value="${value}"${value === current ? ' selected' : ''}>${label}</option>`)
    .join('');
