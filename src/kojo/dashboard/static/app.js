import { leaderboardView } from './leaderboard.js';
import { resultsView } from './results.js';
import { runView, runsView } from './runs.js';
import { escapeHtml as h } from './format.js';
import { installCopyButtons, installNavigation, render } from './view.js';

const REFRESH_MS = 5000;
const TABS = { leaderboard: 'Leaderboard', runs: 'Runs', results: 'Results' };
// `live` views poll while open; the others render once per navigation.
const VIEWS = {
  leaderboard: { render: leaderboardView, tab: 'leaderboard' },
  runs: { render: runsView, tab: 'runs', live: true },
  run: { render: runView, tab: 'runs', live: true },
  results: { render: resultsView, tab: 'results' },
};

/** '#run/abc?x=1' -> { name: 'run', parts: ['abc'], params }. */
export function parseRoute(hash) {
  const [path, query] = (hash.replace(/^#/, '') || 'leaderboard').split('?');
  const [name, ...parts] = path.split('/');
  return { name: name in VIEWS ? name : 'leaderboard', parts, params: new URLSearchParams(query || '') };
}

let timer;

async function show() {
  clearInterval(timer);
  const route = parseRoute(location.hash);
  const view = VIEWS[route.name];
  document.querySelector('#nav').innerHTML = Object.entries(TABS)
    .map(([tab, label]) => `<a href="#${tab}"${tab === view.tab ? ' class="on"' : ''}>${label}</a>`)
    .join('');
  const draw = async () => {
    try {
      await view.render(route);
      document.querySelector('#stamp').textContent = `updated ${new Date().toLocaleTimeString()}`;
    } catch (error) {
      render(`<p class="bad">${h(error.message)}</p>`);
    }
  };
  await draw();
  if (view.live) timer = setInterval(draw, REFRESH_MS);
}

installNavigation();
installCopyButtons();
addEventListener('hashchange', show);
show();
