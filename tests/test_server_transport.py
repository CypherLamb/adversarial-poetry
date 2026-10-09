"""MCP stdio transport: stdout carries JSON-RPC, stderr carries diagnostics;
the server subprocess tears down on SIGTERM."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import requires_unix

pytest.importorskip("mcp", reason="MCP SDK not installed")

SRC = Path(__file__).resolve().parents[1] / "src"

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "transport-test", "version": "0"},
    },
}


def _env(tmp_path: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "cfg")  # isolate: no real config
    return env


def test_stdout_is_jsonrpc_stderr_is_diagnostics(tmp_path: Path):
    proc = subprocess.Popen(
        [sys.executable, "-m", "adversarial_poetry.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp_path),
    )
    out, err = proc.communicate(input=json.dumps(INITIALIZE) + "\n", timeout=30)

    # stdout must contain only JSON-RPC: every non-empty line parses as JSON
    # and the initialize response carries our id with a result.
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines, f"no stdout from server; stderr={err!r}"
    saw_response = False
    for ln in lines:
        obj = json.loads(ln)  # raises if stdout had non-JSON noise
        assert obj.get("jsonrpc") == "2.0"
        if obj.get("id") == 1 and "result" in obj:
            saw_response = True
    assert saw_response, f"no initialize result on stdout; got {lines!r}"

    # Diagnostics went to stderr, not stdout.
    assert "endpoint=" in err


@requires_unix
def test_server_terminates_on_sigterm(tmp_path: Path):
    proc = subprocess.Popen(
        [sys.executable, "-m", "adversarial_poetry.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp_path),
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(INITIALIZE) + "\n")
    proc.stdin.flush()
    proc.terminate()  # SIGTERM
    returncode = proc.wait(timeout=15)
    assert returncode is not None
