"""HTTP layer: a route table over `Store` and `leaderboard`, plus the static frontend."""
import argparse
import json
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from kojo.catalog import BASE
from kojo.dashboard.leaderboard import FILTERABLE, leaderboard
from kojo.dashboard.store import Store

STATIC = Path(__file__).parent / 'static'
STATIC_TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css'}
ID = r'([a-z0-9-]+)'


class NotFound(Exception):
    pass


@dataclass
class Response:
    body: bytes
    content_type: str = 'application/json'
    status: int = 200


def json_response(value, status=200):
    return Response(json.dumps(value).encode(), status=status)


def found(value):
    if value is None:
        raise NotFound
    return json_response(value)


def static_file(name):
    path = STATIC / name
    if not path.is_file():
        raise NotFound
    return Response(path.read_bytes(), STATIC_TYPES[path.suffix])


def leaderboard_response(store, query):
    def one(name):
        return query.get(name, [None])[0] or None

    try:
        return json_response(leaderboard(
            store.graded_runs(), one('by') or 'model', then=one('then'),
            filters={name: query.get(name, []) for name in FILTERABLE}, experiment=one('experiment')))
    except ValueError as error:
        return json_response({'error': str(error)}, status=400)


def chart_response(store, name, filename):
    path = store.chart_path(name, filename)
    if path is None:
        raise NotFound
    return Response(path.read_bytes(), 'image/png')


# (path pattern, handler(store, query, *captures)); patterns must match the whole path.
ROUTES = [
    (r'/', lambda store, query: static_file('index.html')),
    (r'/static/([a-z-]+\.(?:js|css))', lambda store, query, name: static_file(name)),
    (r'/api/overview', lambda store, query: json_response(store.overview())),
    (r'/api/leaderboard', lambda store, query: leaderboard_response(store, query)),
    (rf'/api/runs/{ID}', lambda store, query, run: found(store.run_detail(run))),
    (rf'/api/runs/{ID}/log', lambda store, query, run: Response(store.log_tail(run).encode(), 'text/plain; charset=utf-8')),
    (rf'/api/comparisons/{ID}', lambda store, query, name: found(store.comparison(name))),
    (rf'/api/comparisons/{ID}/charts/(figure-[a-z0-9-]+\.png)', lambda store, query, name, chart: chart_response(store, name, chart)),
]


def dispatch(store, raw_path):
    url = urlparse(raw_path)
    for pattern, handler in ROUTES:
        match = re.fullmatch(pattern, url.path)
        if match:
            try:
                return handler(store, parse_qs(url.query), *match.groups())
            except NotFound:
                break
    return json_response({'error': 'not found'}, status=404)


def make_handler(base):
    store = Store(base)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            response = dispatch(store, self.path)
            self.send_response(response.status)
            self.send_header('Content-Type', response.content_type)
            self.send_header('Content-Length', str(len(response.body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(response.body)

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description='Serve the read-only Kojo run dashboard.')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--base', type=Path, default=BASE, help='checkout holding results/ and intermediate/')
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.base.resolve()))
    print(f'Kojo dashboard: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
