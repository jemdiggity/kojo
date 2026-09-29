export const escapeHtml = (value) =>
  String(value ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

const DASH = '–';

export const percent = (fraction) => (fraction == null ? DASH : `${(fraction * 100).toFixed(1)}%`);
export const usd = (amount) => (amount ? `$${amount.toFixed(2)}` : DASH);
export const plural = (count, noun) => `${count} ${noun}${count === 1 ? '' : 's'}`;

export function duration(seconds) {
  if (seconds == null) return DASH;
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`;
  if (seconds >= 60) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds)}s`;
}

export const fixed = (value, digits = 1) => (value == null ? DASH : value.toFixed(digits));

/** "mean±sd", the sd muted. */
export const meanSd = (mean, sd, digits) =>
  mean == null ? DASH : `${mean.toFixed(digits)}<span class="muted">±${(sd || 0).toFixed(digits)}</span>`;
