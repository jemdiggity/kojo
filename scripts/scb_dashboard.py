"""Serve the read-only run dashboard: python3.12 scripts/scb_dashboard.py [--port N]."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kojo.dashboard import main

if __name__ == '__main__':
    main()
