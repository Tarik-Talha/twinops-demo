"""Resolve an independent runtime without changing legacy Python environments."""
from pathlib import Path
import argparse
import importlib.util
import json
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]

# =========================================================
# INDEPENDENT PILOT RUNTIME AND LOCAL STREAMLIT LAUNCH
# =========================================================
def python_path():
    local = PROJECT / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if local.exists():
        return str(local)
    if all(importlib.util.find_spec(k) for k in ('simpy','ortools','streamlit','plotly')):
        return sys.executable
    raise RuntimeError('Bağımsız ortam bulunamadı. README dosyasındaki kurulumu tamamlayın.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8515)
    args = parser.parse_args()
    return subprocess.call([python_path(), '-m', 'streamlit', 'run', str(PROJECT/'embroidery_pilot'/'app.py'),
                            '--server.address','127.0.0.1','--server.port',str(args.port),'--server.headless','true',
                            '--browser.gatherUsageStats','false'], cwd=PROJECT)


if __name__ == '__main__':
    raise SystemExit(main())
