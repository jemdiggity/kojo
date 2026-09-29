import { escapeHtml as h } from './format.js';

const WIDTH = 420;
const HEIGHT = 240;
const PAD = { left: 44, right: 12, top: 12, bottom: 28 };
const GRID_LINES = 4;
// Deeper hues than the bar palette so thin lines stay visible; same order, same colour families.
export const LINE_COLORS = ['#2f6fdb', '#c99a00', '#1f9d7a', '#b0407f', '#e07b39', '#6f62d6', '#4aa84a', '#d35555'];

/** Round the data range outward to 0.05 steps (scores are non-negative). */
function yRange(values) {
  const low = Math.max(0, Math.floor((Math.min(...values) - 0.02) * 20) / 20);
  const high = Math.ceil((Math.max(...values) + 0.02) * 20) / 20;
  return [low, Math.max(high, low + 0.05)];
}

/** One SVG path per run of consecutive non-null points, so gaps stay gaps. */
function pathFor(values, x, y) {
  let path = '';
  let pen = false;
  values.forEach((value, i) => {
    if (value == null) {
      pen = false;
      return;
    }
    path += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(value).toFixed(1)}`;
    pen = true;
  });
  return path;
}

/**
 * A small multi-series line chart.
 * series: [{ label, color, values }] with one value (or null) per entry of xLabels.
 */
export function lineChart({ title, series, xLabels }) {
  const values = series.flatMap((s) => s.values).filter((v) => v != null);
  if (!values.length) return '';
  const [low, high] = yRange(values);
  const x = (i) => PAD.left + (i / (xLabels.length - 1)) * (WIDTH - PAD.left - PAD.right);
  const y = (v) => PAD.top + (1 - (v - low) / (high - low)) * (HEIGHT - PAD.top - PAD.bottom);

  const grid = Array.from({ length: GRID_LINES + 1 }, (_, i) => {
    const value = low + ((high - low) * i) / GRID_LINES;
    return `<line class="grid-line" x1="${PAD.left}" x2="${WIDTH - PAD.right}" y1="${y(value)}" y2="${y(value)}"/>
      <text class="axis-text" x="${PAD.left - 6}" y="${y(value) + 4}" text-anchor="end">${value.toFixed(2)}</text>`;
  });
  const ticks = xLabels.map((label, i) => `<text class="axis-text" x="${x(i)}" y="${HEIGHT - 8}" text-anchor="middle">${h(label)}</text>`);
  const lines = series.map((s) => {
    const dots = s.values
      .map((v, i) => (v == null ? '' : `<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="${s.color}"><title>${h(s.label)} · ${h(xLabels[i])}: ${v.toFixed(3)}</title></circle>`))
      .join('');
    return `<path d="${pathFor(s.values, x, y)}" fill="none" stroke="${s.color}" stroke-width="2"/>${dots}`;
  });
  const legend = series.map((s) => `<span class="key"><i style="background:${s.color}"></i>${h(s.label)}</span>`).join('');
  return `<figure class="line-chart"><figcaption>${h(title)}</figcaption>
    <svg viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img" aria-label="${h(title)}">${grid.join('')}${ticks.join('')}${lines.join('')}</svg>
    <div class="legend">${legend}</div></figure>`;
}

export const PROGRESS_LABELS = ['start', '25%', '50%', '75%', 'end'];
