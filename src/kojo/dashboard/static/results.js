import { getJson } from './api.js';
import { escapeHtml as h, duration, percent, usd } from './format.js';
import { render } from './view.js';

const gridCell = (c) =>
  `<span class="cell${c.strict ? ' strict' : ''}" title="${h(c.problem)} #${c.checkpoint}: ${c.passed} passed, ${c.failed} failed, ${c.skipped} skipped"></span>`;

const modelRow = (m) => `<tr><td>${h(m.model)}</td><td class="num">${m.strict}/${m.checkpoints}</td>
  <td class="num">${percent(m.partial_pass)}</td><td class="num">${usd(m.cost_usd)}</td>
  <td class="num">${duration((m.minutes || 0) * 60)}</td><td><div class="grid">${m.grid.map(gridCell).join('')}</div></td></tr>`;

/** The most recent published comparison unless one is named. */
export async function resultsView({ parts: [name] }) {
  const { comparisons } = await getJson('/api/overview');
  name = name || comparisons[comparisons.length - 1];
  if (!name) return render('<p class="muted">No published comparisons.</p>');
  const data = await getJson(`/api/comparisons/${name}`);
  const figures = data.charts.map((c) => `<img loading="lazy" src="/api/comparisons/${data.name}/charts/${c}" alt="${h(c)}">`).join('');
  render(`<h2 class="first">${h(data.name)}</h2><div class="scroll"><table>
    <tr><th>Model</th><th class="num">Strict</th><th class="num">Partial</th><th class="num">Cost</th><th class="num">Time</th><th>Checkpoints (green = strict pass)</th></tr>
    ${data.models.map(modelRow).join('')}</table></div><h2>Figures</h2>${figures}`);
}
