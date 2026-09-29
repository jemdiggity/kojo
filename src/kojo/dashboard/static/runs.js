import { getJson, getText } from './api.js';
import { escapeHtml as h, duration, percent, plural, usd } from './format.js';
import { render } from './view.js';

const table = (headers, rows, empty) =>
  rows ? `<div class="scroll"><table><tr>${headers}</tr>${rows}</table></div>` : `<p class="muted">${empty}</p>`;

const batchRow = (batch) => {
  const pills = Object.entries(batch.counts).map(([s, n]) => `<span class="pill ${s}">${n} ${h(s)}</span>`).join(' ');
  return `<tr><td>${h(batch.id)}</td><td>${h(batch.action)}</td><td>${pills}</td><td>${batch.cancelled ? 'cancelled' : ''}</td></tr>`;
};

const runRow = (run) => `
  <tr class="click" data-href="run/${run.id}"><td>${h(run.id)}</td><td class="${run.status}">${h(run.status)}</td>
  <td>${h(run.models.join(', '))}</td><td class="num">${run.strict_passed}/${run.checkpoints_graded}</td>
  <td class="num">${percent(run.partial_pass)}</td><td class="num">${usd(run.cost_usd)}</td>
  <td class="num">${duration(run.elapsed_seconds)}</td></tr>`;

/** All runs, or only those in the `ids` query parameter (linked from the leaderboard). */
export async function runsView({ params }) {
  const data = await getJson('/api/overview');
  const ids = params.get('ids') ? new Set(params.get('ids').split(',')) : null;
  const runs = ids ? data.runs.filter((run) => ids.has(run.id)) : data.runs;
  const heading = ids
    ? `<p><a href="#leaderboard" data-back>← Leaderboard</a> · showing ${plural(runs.length, 'run')} · <a href="#runs">show all runs</a></p>`
    : `<h2>Batches</h2>${table('<th>Batch</th><th>Action</th><th>Runs</th><th></th>', data.batches.map(batchRow).join(''), 'No batches.')}`;
  const header = '<th>Run</th><th>Status</th><th>Model</th><th class="num">Strict</th><th class="num">Partial</th><th class="num">Cost</th><th class="num">Time</th>';
  render(`${heading}<h2>Runs</h2>${table(header, runs.map(runRow).join(''), 'No runs found under results/runs or intermediate/runs.')}`);
}

const checkpointRow = (c) => {
  const tally = (t) => (t && t.total ? `${t.passed}/${t.total}` : '–');
  const verdict = c.strict == null ? '–' : c.strict ? '✓ strict' : '✗';
  const failures = (c.failed || []).map((f) => `<div>${h(f.group)}::${h(f.name)} <span class="muted">${h(f.state)}</span></div>`).join('');
  const details = failures
    ? `<tr><td></td><td colspan="7"><details data-key="failed-${c.role}-${c.checkpoint}"><summary>${c.failed.length} not passing</summary>${failures}</details></td></tr>`
    : '';
  return `<tr><td>${c.role}</td><td>${c.checkpoint}</td><td class="${c.status === 'complete' ? 'ok' : ''}">${h(c.status)}</td>
    <td class="num">${tally(c.current)}</td><td class="num">${tally(c.prior)}</td>
    <td class="${c.strict ? 'ok' : c.strict === false ? 'bad' : ''}">${verdict}</td>
    <td class="num">${usd(c.cost_usd)}</td><td class="num">${duration(c.elapsed_seconds)}</td></tr>${details}`;
};

export async function runView({ parts: [id] }) {
  const [run, log] = await Promise.all([getJson(`/api/runs/${id}`), getText(`/api/runs/${id}/log`)]);
  const header = '<th>Role</th><th>#</th><th>Status</th><th class="num">Current</th><th class="num">Regression</th><th>Result</th><th class="num">Cost</th><th class="num">Time</th>';
  const rows = run.checkpoints.map(checkpointRow).join('') || '<tr><td colspan="8" class="muted">No checkpoints yet.</td></tr>';
  render(`<p><a href="#runs" data-back>← Back</a></p>
    <h2 class="first">${h(run.id)} <span class="pill ${run.status}">${h(run.status)}</span></h2>
    <p class="muted">${run.batch ? `Batch ${h(run.batch)} · ` : ''}${h(run.models.join(', '))} · ${run.strict_passed}/${run.checkpoints_graded} strict · ${usd(run.cost_usd)} · ${duration(run.elapsed_seconds)}</p>
    <h2>Checkpoints</h2><div class="scroll"><table><tr>${header}</tr>${rows}</table></div>
    <details data-key="log"><summary>Controller log (tail)</summary><pre>${h(log) || 'No log.'}</pre></details>`);
}
