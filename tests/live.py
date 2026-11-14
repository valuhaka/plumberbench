"""Helpers for tests that start a real PlumberBench MCP server."""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(tmp_path, **env):
    port = free_port()
    full = {**os.environ, "PYTHONPATH": str(SRC), "PB_PORT": str(port),
            "PB_LOG_DIR": str(tmp_path / "log"), **env}
    proc = subprocess.Popen([sys.executable, "-m", "plumberbench.server"], env=full,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return proc, port
        except OSError:
            time.sleep(0.25)
    proc.kill()
    pytest.fail("server did not start")
