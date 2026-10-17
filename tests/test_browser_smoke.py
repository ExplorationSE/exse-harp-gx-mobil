"""Browser-Rauchtest (tools/browser_smoke.py) gegen einen echten Server: alle Ansichten, alle Wechsel, Desktop und
390 px, nach Datei-Umlauf, zwei Clients/Zuschauer-Modus, Auswahlfelder. Übersprungen ohne Playwright/Chromium."""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    pytest.importorskip("playwright.sync_api")
    from tools.generate_gx import generate
    d = tmp_path_factory.mktemp("smoke")
    (d / "data").mkdir()
    generate("thermal_cw", d / "data" / "Thermisch_cw.ptu", 1.5, seed=21)
    port = _free_port()
    (d / "config.toml").write_text(
        f'[server]\nhost = "127.0.0.1"\nport = {port}\ntoken = ""\n'
        f'[source]\nkind = "pure"\ndata_dir = "{(d / "data").as_posix()}"\ndefault_file = "Thermisch_cw.ptu"\nautostart = true\n'
        f'[defaults]\nrefresh_ms = 150\nspeed = 1.0\nloop = true\n[logging]\nlog_dir = "{(d / "logs").as_posix()}"\n'
        '[gx]\nenabled = true\n', encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "HARP_GX_DISABLE"}
    p = subprocess.Popen([sys.executable, str(ROOT / "run_server.py"), "--config", str(d / "config.toml")],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        yield url
    finally:
        p.terminate()
        p.wait(timeout=10)


def test_all_views_in_browser(server):
    from playwright.sync_api import Error
    from tools import browser_smoke
    try:
        fails = browser_smoke.run(server, Path(os.environ["HARP_SHOTS"]) if os.environ.get("HARP_SHOTS") else None,
                                  log=lambda *a: None)
    except Error as e:   # Chromium fehlt
        if "Executable doesn't exist" in str(e):
            pytest.skip("Chromium für Playwright nicht installiert")
        raise
    assert not fails, "\n".join(fails)
