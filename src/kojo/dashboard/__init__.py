"""Read-only web dashboard for run progress and results; stdlib only, no inference."""
from kojo.dashboard.server import main, make_handler

__all__ = ['main', 'make_handler']
