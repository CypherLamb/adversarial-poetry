"""Client launches the MCP server subprocess, connects, and cleans it up.

This exercises the real launch path (explicit executable + argument list, no
shell) and confirms the subprocess is torn down when the client session exits.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from conftest import requires_unix

pytest.importorskip("mcp", reason="MCP SDK not installed")
pytestmark = requires_unix

SRC = Path(__file__).resolve().parents[1] / "src"
EXPECTED_TOOLS = {
    "list_poetic_forms",
    "list_models",
    "generate_poems",
    "save_poems",
    "generate_and_save",
}


async def _list_tools(tmp_path: Path) -> set[str]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "cfg")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "adversarial_poetry.server"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            return {t.name for t in listed.tools}


def test_client_launches_and_cleans_up_server(tmp_path: Path):
    # asyncio.run tears down the event loop; stdio_client's context exit closes
    # and reaps the server subprocess. Completing without hang == clean teardown.
    names = asyncio.run(asyncio.wait_for(_list_tools(tmp_path), timeout=30))
    assert EXPECTED_TOOLS.issubset(names)
