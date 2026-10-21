"""Real stdio subprocess tests (fake backend, no model)."""
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters

pytestmark = pytest.mark.anyio

TESTS = Path(__file__).parent

# A backend whose preload swaps sys.stdout the way sa3-tflite does around every
# model call (upstream prints its progress to stdout). Started before the
# transport claims stdout, it used to make every JSON-RPC reply go to stderr
# and the client hang on initialize.
SERVER = """
import contextlib, sys, time
from conftest import FakeBackend
from otomaker import server

class SlowPreload(FakeBackend):
    def _preload(self):
        with contextlib.redirect_stdout(sys.stderr):
            print("loading weights...")
            time.sleep(2)
        self._loaded = True

server.set_backend(SlowPreload())
server.main(sys.argv[1:])
"""


async def test_preload_does_not_break_stdio(tmp_path):
    params = StdioServerParameters(
        command=sys.executable, args=["-c", SERVER, "--preload"],
        env={**os.environ, "PYTHONPATH": str(TESTS), "OTOMAKER_OUTPUT_DIR": str(tmp_path)})
    with anyio.fail_after(30):
        async with Client(params, read_timeout_seconds=20) as c:
            await anyio.sleep(3)  # preload finished
            r = await c.call_tool("generate_audio", {"prompt": "x", "duration_seconds": 1, "seed": 1})
            assert not r.is_error, r.content
            assert '"included_model_load": false' in r.content[0].text


async def test_server_without_runtime_starts_and_says_what_to_run(tmp_path):
    # A fresh `uvx … otomaker-mcp` before otomaker-download: the server must not
    # exit, the tools are listed, and a call explains the next step.
    env = {k: v for k, v in os.environ.items() if not k.startswith("OTOMAKER_")}
    env.update(OTOMAKER_OUTPUT_DIR=str(tmp_path / "out"), OTOMAKER_HOME=str(tmp_path / "home"))
    params = StdioServerParameters(command=sys.executable, args=["-m", "otomaker"], env=env)
    with anyio.fail_after(60):
        async with Client(params, read_timeout_seconds=50) as c:
            tools = sorted(t.name for t in (await c.list_tools()).tools)
            assert tools == ["edit_audio", "generate_audio", "process_audio", "unload_models"]
            r = await c.call_tool("generate_audio", {"prompt": "x", "duration_seconds": 1, "seed": 1})
            text = r.content[0].text
            assert r.is_error and "otomaker-download" in text, text
            assert str(tmp_path / "home") in text   # the runtime place follows OTOMAKER_HOME
