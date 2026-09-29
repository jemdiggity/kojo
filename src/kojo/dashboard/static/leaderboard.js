import { getJson } from './api.js';
import { LINE_COLORS, PROGRESS_LABELS, lineChart } from './chart.js';
import { escapeHtml as h, fixed, meanSd, plural } from './format.js';
import { hashOptions, render } from './view.js';

const METRICS = { strict: 'Strict', iso: 'Iso.', core: 'Core', partial: 'Partial' }; // % of checkpoints; the chart metric
const QUALITY = { erosion: 'Erosion', verbosity: 'Verbosity' }; // static analysis, lower is better; columns and charts only
const FILTERS = { batch: 'Batch', run: 'Run', problem: 'Problem', model: 'Model', skill: 'Skill set', factory: 'Factory', effort: 'Effort' };
const GROUPS = { model: 'Model', skill: 'Skill set', factory: 'Factory', effort: 'Effort', problem: 'Problem', batch: 'Batch', run: 'Run' };
const MAX_LIST_ROWS = 6; // filter lists share one height so they line up
const PALETTE = ['#b3d4ff', '#fdf7b5', '#86e0c4', '#c76ea0', '#f4b183', '#a9a3f0', '#9adf8f', '#e58f8f'];
const DEFINITIONS = `<b>Strict</b>: every test passes, including regressions. <b>Iso.</b>: every test introduced by
  that checkpoint passes (regressions ignored). <b>Core</b>: every Core-category test passes. <b>Partial</b>: mean
  passed/collected tests. <b>Erosion</b>: share of complexity mass in high-complexity functions; <b>Verbosity</b>: share of
  flagged source lines (lower is better for both; only analyzed checkpoints count). Costs are API-equivalent USD; ± is
  standard deviation across checkpoints.`;

// ---- state <-> URL -------------------------------------------------------
// #leaderboard/<metric>/<by>/<then>?<filter>=a,b   (runs are chosen only by filters)

export function parseState({ parts, params }) {
  const [metric, by, then] = parts;
  const state = {
    metric: metric in METRICS ? metric : 'strict',
    by: by in GROUPS ? by : 'model',
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
  const query = params.toString();
  return `leaderboard/${state.metric}/${state.by}/${state.then}${query ? `?${query}` : ''}`;
}

function apiQuery(state) {
  const query = new URLSearchParams({ by: state.by, then: state.then });
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
  const score = (row) => row[state.metric] ?? -1;
  const best = {};
  rows.forEach((row) => {
    best[row.key] = Math.max(best[row.key] ?? -1, score(row));
  });
  const subs = subValues(rows);
  return [...rows].sort(
    (a, b) =>
      best[b.key] - best[a.key] ||
      a.key.localeCompare(b.key) ||
      (state.then ? subs.indexOf(a.sub) - subs.indexOf(b.sub) : score(b) - score(a)),
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
  const experiments = hashOptions(comparisonOptions(state, data));
  const rows = Math.min(Math.max(2, ...Object.values(data.facets).map((f) => f.length)), MAX_LIST_ROWS);
  const filterLists = Object.entries(FILTERS).map(([name, label]) => filterList(state, data, name, label, rows)).join('');
  const clear = hasFilters(state) ? `<a href="#${h(next(state, { filters: {} }))}">clear filters</a>` : '';
  return `
    <div class="ctl">
      <label>Metric <select data-nav>${metrics}</select></label>
      <label>Group by <select data-nav>${groups}</select></label>
      <label>Then by <select data-nav>${thens}</select></label>
      <span class="muted">% of checkpoints, final stage output graded per checkpoint</span>
    </div>
    <div class="ctl">
      <label>Suggested comparison <select class="wide" data-nav>${experiments}</select></label>
      ${clear}
    </div>
    <div class="filters">${filterLists}</div>
    <p class="muted">${poolingNote(state, data)}</p>`;
}

/**
 * One filter: an always-visible multi-select list. Click picks a value, shift-click a range,
 * ctrl/cmd-click toggles. The page wires its change event (see wireFilters) because the hash
 * depends on the whole selection.
 */
function filterList(state, data, name, label, rows) {
  const chosen = state.filters[name] || [];
  const options = data.facets[name]
    .map(([value, count]) => `<option value="${h(value)}" title="${h(value)}"${chosen.includes(value) ? ' selected' : ''}>${h(value)} (${count})</option>`)
    .join('');
  return `<label class="filter">${label}${chosen.length ? ` (${chosen.length} selected)` : ''}
    <select multiple size="${rows}" data-filter="${name}">${options}</select></label>`;
}

/** Navigate to the state whose `name` filter is the list's current selection. */
function wireFilters(state) {
  document.querySelectorAll('select[data-filter]').forEach((list) => {
    list.addEventListener('change', () => {
      const values = [...list.selectedOptions].map((option) => option.value);
      location.hash = next(state, { filters: { ...state.filters, [list.dataset.filter]: values } });
    });
  });
}

const hasFilters = (state) => Object.values(state.filters).some((values) => values.length);
const sameValues = (a, b) => a.length === b.length && a.every((value) => b.includes(value));

/**
 * Suggested comparisons are only presets: picking one ticks the batch boxes (and groups by what
 * varies), after which the filters can be edited like any others.
 */
function comparisonOptions(state, data) {
  const active = Object.entries(state.filters).filter(([, values]) => values.length);
  const matches = (e) => active.length === 1 && active[0][0] === 'batch' && sameValues(active[0][1], e.batches);
  const presets = data.experiments.map((e) => ({
    hash: h(next(state, { filters: { batch: e.batches }, by: e.vary, then: experimentThen(e) })),
    label: h(experimentLabel(e)),
    selected: matches(e),
  }));
  const custom = active.length && !data.experiments.some(matches);
  return [
    { hash: h(next(state, { filters: {} })), label: '— all runs —', selected: !active.length },
    ...(custom ? [{ hash: h(next(state, {})), label: '— custom filters —', selected: true }] : []),
    ...presets,
  ];
}

const experimentLabel = (e) => {
  const fixedText = Object.entries(e.fixed).map(([name, values]) => `${name}=${values.join('/')}`).join(', ');
  return `${FILTERS[e.vary]} varies (${e.values.length}) across ${plural(e.batches.length, 'batch', 'batches')} · ${fixedText} · ${plural(e.runs.length, 'run')}`;
};

/** The experiment's second axis: the first held setting that still varies inside each batch. */
const experimentThen = (e) => Object.entries(e.fixed).find(([, values]) => values.length > 1)?.[0] ?? '';

/** Which settings the included runs share, and which differ (batch and run are identifiers, not settings). */
function poolingNote(state, data) {
  const settings = Object.entries(data.pooled).filter(([name]) => name !== 'batch' && name !== 'run');
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

/** Upper end of the bar scale: whole tens of percent. */
const barScale = (rows, metric) => Math.max(10, Math.ceil(Math.max(0, ...rows.map((r) => r[metric] || 0)) / 10) * 10);

function bars(rows, state) {
  const subs = subValues(rows);
  const top = barScale(rows, state.metric);
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
  const header = (name) =>
    `<th class="num metric${name === state.metric ? ' sel' : ''}" data-href="${h(next(state, { metric: name }))}">${METRICS[name]}</th>`;
  const cell = (name, content) => `<td class="num${name === state.metric ? ' sel' : ''}">${content}</td>`;
  const body = rows.map((row) => `
    <tr class="click" data-href="${h(runsHash(row.run_ids))}">
      <td>${h(row.key)}</td>${state.then ? `<td>${h(row.sub)}</td>` : ''}
      <td class="num">${row.runs}</td><td class="num">${row.checkpoints}</td>
      ${Object.keys(METRICS).map((name) => cell(name, fixed(row[name]))).join('')}
      <td class="num">${meanSd(row.cost_mean, row.cost_sd, 2)}</td><td class="num">${row.cost_total.toFixed(2)}</td>
      <td class="num">${meanSd(row.minutes_mean, row.minutes_sd, 1)}</td>
      ${Object.keys(QUALITY).map((name) => `<td class="num">${meanSd(row[name], row[`${name}_sd`], 2)}</td>`).join('')}</tr>`).join('');
  const title = `Per-${GROUPS[state.by].toLowerCase()}${state.then ? ` × ${GROUPS[state.then].toLowerCase()}` : ''} performance`;
  return `<h2>${h(title)}</h2><div class="scroll"><table>
    <tr><th>${GROUPS[state.by]}</th>${state.then ? `<th>${GROUPS[state.then]}</th>` : ''}<th class="num">Runs</th><th class="num">Ckpts</th>
    ${Object.keys(METRICS).map(header).join('')}<th class="num">$/CKPT</th><th class="num">Net $</th><th class="num">Min/CKPT</th>
    ${Object.values(QUALITY).map((label) => `<th class="num">${label}</th>`).join('')}</tr>
    ${body}</table></div><p class="muted">${DEFINITIONS}</p>`;
}

/** Erosion and verbosity across normalized progress, one line per group; nothing if none were analyzed. */
function qualityCharts(data, state) {
  const label = (t) => (state.then ? `${t.key} · ${t.sub}` : t.key);
  const charts = Object.entries(QUALITY)
    .map(([metric, title]) =>
      lineChart({
        title: `${title} across progress (lower is better)`,
        xLabels: PROGRESS_LABELS,
        series: data.trajectories.flatMap((t, i) => {
          const color = LINE_COLORS[i % LINE_COLORS.length];
          const final = { label: label(t), color, values: t[metric] || [] };
          const earlier = t.intermediate[metric];
          return earlier ? [final, { label: `${label(t)} (intermediate)`, color, values: earlier, dashed: true }] : [final];
        }),
      }),
    )
    .join('');
  if (!charts) return NO_QUALITY;
  const hasIntermediate = data.trajectories.some((t) => Object.values(t.intermediate).some(Boolean));
  const dotted = hasIntermediate
    ? ' Dotted lines show the output of an intermediate stage (e.g. build) before a later stage (review/fix) changed the code; the solid line and the table use the final output.'
    : '';
  return `<h2>Code quality over a run</h2><div class="charts">${charts}</div>
    <p class="muted">Each run is placed on 0–100% by checkpoint order and interpolated, then averaged per group. Only runs with a static analysis contribute.${dotted}</p>`;
}

const NO_QUALITY = `<h2>Code quality over a run</h2><p class="muted">No erosion/verbosity analysis found for these runs. Generate it with
  <code>scripts/scb_quality.py &lt;run ids&gt; --output results/comparisons/&lt;name&gt;</code>; the dashboard picks up any
  <code>quality.json</code> under <code>results/comparisons</code>.</p>`;

export async function leaderboardView(route) {
  const state = parseState(route);
  const data = await getJson(`/api/leaderboard?${apiQuery(state)}`);
  const rows = sortRows(data.rows, state);
  const content = rows.length
    ? bars(rows, state) + table(rows, state) + qualityCharts(data, state)
    : '<p class="muted">No graded runs found.</p>';
  render(`${controls(state, data)}${content}`);
  wireFilters(state);
}
