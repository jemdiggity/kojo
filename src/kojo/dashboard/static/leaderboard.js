import { getJson } from './api.js';
import { escapeHtml as h, fixed, meanSd, plural } from './format.js';
import { hashOptions, render } from './view.js';

const METRICS = { strict: 'Strict', iso: 'Iso.', core: 'Core', partial: 'Partial' };
const FILTERS = { batch: 'Batch', problem: 'Problem', model: 'Model', skill: 'Skill set', factory: 'Factory', effort: 'Effort' };
const GROUPS = { model: 'Model', skill: 'Skill set', factory: 'Factory', effort: 'Effort', problem: 'Problem', batch: 'Batch', run: 'Run' };
const PALETTE = ['#b3d4ff', '#fdf7b5', '#86e0c4', '#c76ea0', '#f4b183', '#a9a3f0', '#9adf8f', '#e58f8f'];
const DEFINITIONS = `<b>Strict</b>: every test passes, including regressions. <b>Iso.</b>: every test introduced by
  that checkpoint passes (regressions ignored). <b>Core</b>: every Core-category test passes. <b>Partial</b>: mean
  passed/collected tests. Costs are API-equivalent USD; ± is standard deviation across checkpoints.`;

// ---- state <-> URL -------------------------------------------------------
// #leaderboard/<metric>/<by>/<then>?<filter>=a,b&experiment=<id>

export function parseState({ parts, params }) {
  const [metric, by, then] = parts;
  const state = {
    metric: metric in METRICS ? metric : 'strict',
    by: by in GROUPS ? by : 'model',
    experiment: params.get('experiment') || '',
    filters: {},
  };
  state.then = then in GROUPS && then !== state.by ? then : '';
  for (const name of Object.keys(FILTERS)) {
    if (params.get(name)) state.filters[name] = params.get(name).split(',');
  }
  return state;
}

export function stateHash(state) {
  const params = new URLSearchParams();
  for (const [name, values] of Object.entries(state.filters)) if (values.length) params.set(name, values.join(','));
  if (state.experiment) params.set('experiment', state.experiment);
  const query = params.toString();
  return `leaderboard/${state.metric}/${state.by}/${state.then}${query ? `?${query}` : ''}`;
}

function apiQuery(state) {
  const query = new URLSearchParams({ by: state.by, then: state.then, experiment: state.experiment });
  for (const [name, values] of Object.entries(state.filters)) values.forEach((v) => query.append(name, v));
  return query;
}

/** The hash for `state` with `change` applied; every control links to one of these. */
const next = (state, change) => stateHash({ ...state, ...change });

/** One run opens its page; several open the run list filtered to them. */
const runsHash = (ids) => (ids.length === 1 ? `run/${ids[0]}` : `runs?ids=${ids.join(',')}`);

// ---- ordering ---------------------------------------------------------------

/** Clusters by their best bar; within a cluster, second-dimension values alphabetically. */
function sortRows(rows, state) {
  const value = (row) => row[state.metric] ?? -1;
  const best = {};
  rows.forEach((row) => {
    best[row.key] = Math.max(best[row.key] ?? -1, value(row));
  });
  const subs = subValues(rows);
  return [...rows].sort(
    (a, b) =>
      best[b.key] - best[a.key] ||
      a.key.localeCompare(b.key) ||
      (state.then ? subs.indexOf(a.sub) - subs.indexOf(b.sub) : value(b) - value(a)),
  );
}

const subValues = (rows) => [...new Set(rows.map((r) => r.sub))].filter((s) => s != null).sort();

// ---- pieces -----------------------------------------------------------------

function controls(state, data) {
  const choose = (choices, isSelected, hashFor) =>
    hashOptions(Object.entries(choices).map(([key, label]) => ({ hash: h(hashFor(key)), label, selected: isSelected(key) })));
  const metrics = choose(METRICS, (k) => k === state.metric, (k) => next(state, { metric: k }));
  const groups = choose(GROUPS, (k) => k === state.by, (k) => next(state, { by: k, then: state.then === k ? '' : state.then }));
  const thenChoices = { '': '— none —', ...Object.fromEntries(Object.entries(GROUPS).filter(([k]) => k !== state.by)) };
  const thens = choose(thenChoices, (k) => k === state.then, (k) => next(state, { then: k }));
  const experiments = hashOptions([
    { hash: h(next(state, { experiment: '' })), label: '— all runs —', selected: !state.experiment },
    ...data.experiments.map((e) => ({
      hash: h(next(state, { experiment: e.id, filters: {}, by: e.vary, then: experimentThen(e) })),
      label: h(experimentLabel(e)),
      selected: e.id === state.experiment,
    })),
  ]);
  const filterMenus = Object.entries(FILTERS).map(([name, label]) => filterMenu(state, data, name, label)).join('');
  const active = state.experiment || Object.values(state.filters).some((v) => v.length);
  const clear = active ? `<a href="#${h(next(state, { filters: {}, experiment: '' }))}">clear filters</a>` : '';
  return `
    <div class="ctl">
      <label>Metric <select data-nav>${metrics}</select></label>
      <label>Group by <select data-nav>${groups}</select></label>
      <label>Then by <select data-nav>${thens}</select></label>
      <span class="muted">% of checkpoints, build output graded per checkpoint</span>
    </div>
    <div class="ctl">
      <label>Experiment <select class="wide" data-nav>${experiments}</select></label>
      ${filterMenus}
      ${clear}
    </div>
    <p class="muted">${poolingNote(state, data)}</p>`;
}

/** A dropdown of checkboxes; each box links to the state with that value toggled. */
function filterMenu(state, data, name, label) {
  const chosen = state.filters[name] || [];
  const boxes = data.facets[name].map(([value, count]) => {
    const toggled = chosen.includes(value) ? chosen.filter((v) => v !== value) : [...chosen, value];
    const hash = h(next(state, { filters: { ...state.filters, [name]: toggled } }));
    return `<label><input type="checkbox" data-nav="${hash}"${chosen.includes(value) ? ' checked' : ''}> ${h(value)} <span class="muted">${count}</span></label>`;
  });
  return `<details class="menu" data-key="filter-${name}"><summary>${label}${chosen.length ? ` (${chosen.length})` : ''}</summary><div class="menu-box">${boxes.join('')}</div></details>`;
}

const experimentLabel = (e) => {
  const fixedText = Object.entries(e.fixed).map(([name, values]) => `${name}=${values.join('/')}`).join(', ');
  return `${FILTERS[e.vary]} varies (${e.values.length}) across ${e.batches.length} batches · ${fixedText} · ${e.runs.length} runs`;
};

/** The experiment's second axis: the first held setting that still varies inside each batch. */
const experimentThen = (e) => Object.entries(e.fixed).find(([, values]) => values.length > 1)?.[0] ?? '';

/** Which settings the included runs share, and which differ (batch is bookkeeping, not a setting). */
function poolingNote(state, data) {
  const settings = Object.entries(data.pooled).filter(([name]) => name !== 'batch');
  const same = settings.filter(([, values]) => values.length === 1);
  const mixed = settings.filter(([name, values]) => values.length > 1 && name !== state.by && name !== state.then);
  let note = `Pooling ${plural(data.runs, 'run')}`;
  if (same.length) note += ` · same: ${same.map(([n, v]) => `${h(n)}=${h(v[0])}`).join(', ')}`;
  if (mixed.length) {
    const names = mixed.map(([n, v]) => `${h(n)} (${v.length})`).join(', ');
    note += ` · <span class="warn">mixed: ${names} — filter to compare like with like</span>`;
  }
  return note;
}

function bars(rows, state) {
  const subs = subValues(rows);
  const top = Math.max(10, Math.ceil(Math.max(...rows.map((r) => r[state.metric] || 0)) / 10) * 10);
  const bar = (row, index, label) => {
    const value = row[state.metric];
    const color = PALETTE[(state.then ? subs.indexOf(row.sub) : index) % PALETTE.length];
    return `<div class="hit" data-href="${h(runsHash(row.run_ids))}" title="${plural(row.runs, 'run')} — click to view">
      <div class="name" title="${h(label)}">${h(label)}</div>
      <div class="track"><div class="fill" style="width:${((value || 0) / top) * 100}%;background:${color}"></div></div>
      <div class="val">${value == null ? '–' : `${value.toFixed(1)}%`}</div></div>`;
  };
  const body = rows.map((row, i) => {
    if (!state.then) return bar(row, i, row.key);
    const heading = i === 0 || rows[i - 1].key !== row.key ? `<div class="cluster">${h(row.key)}</div>` : '';
    return heading + bar(row, i, row.sub);
  });
  const axis = `<div></div><div class="axis"><span>0%</span><span>${top / 2}%</span><span>${top}%</span></div><div></div>`;
  return `<div class="bars">${body.join('')}${axis}</div>`;
}

function table(rows, state) {
  const metricHeader = (name) =>
    `<th class="num metric${name === state.metric ? ' sel' : ''}" data-href="${h(next(state, { metric: name }))}">${METRICS[name]}</th>`;
  const metricCell = (row, name) => `<td class="num${name === state.metric ? ' sel' : ''}">${fixed(row[name])}</td>`;
  const body = rows.map((row) => `
    <tr class="click" data-href="${h(runsHash(row.run_ids))}">
      <td>${h(row.key)}</td>${state.then ? `<td>${h(row.sub)}</td>` : ''}
      <td class="num">${row.runs}</td><td class="num">${row.checkpoints}</td>
      ${Object.keys(METRICS).map((name) => metricCell(row, name)).join('')}
      <td class="num">${meanSd(row.cost_mean, row.cost_sd, 2)}</td><td class="num">${row.cost_total.toFixed(2)}</td>
      <td class="num">${meanSd(row.minutes_mean, row.minutes_sd, 1)}</td></tr>`).join('');
  const title = `Per-${GROUPS[state.by].toLowerCase()}${state.then ? ` × ${GROUPS[state.then].toLowerCase()}` : ''} performance`;
  return `<h2>${h(title)}</h2><div class="scroll"><table>
    <tr><th>${GROUPS[state.by]}</th>${state.then ? `<th>${GROUPS[state.then]}</th>` : ''}<th class="num">Runs</th><th class="num">Ckpts</th>
    ${Object.keys(METRICS).map(metricHeader).join('')}<th class="num">$/CKPT</th><th class="num">Net $</th><th class="num">Min/CKPT</th></tr>
    ${body}</table></div><p class="muted">${DEFINITIONS}</p>`;
}

export async function leaderboardView(route) {
  const state = parseState(route);
  const data = await getJson(`/api/leaderboard?${apiQuery(state)}`);
  const rows = sortRows(data.rows, state);
  render(`${controls(state, data)}${rows.length ? bars(rows, state) + table(rows, state) : '<p class="muted">No graded runs found.</p>'}`);
}
