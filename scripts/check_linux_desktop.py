"""Verify installed desktop startup and renderer-to-backend IPC under Xvfb."""
import argparse
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import tempfile
import time


def check(binary):
    with tempfile.TemporaryDirectory(prefix="factumdb-desktop-") as directory:
        root = Path(directory)
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        env = {key: value for key, value in os.environ.items() if not key.startswith("FACTUMDB_")}
        env.update(XDG_DATA_HOME=str(root / "data"), XDG_CONFIG_HOME=str(root / "config"),
                   XDG_CACHE_HOME=str(root / "cache"), XDG_RUNTIME_DIR=str(runtime),
                   WEBKIT_DISABLE_DMABUF_RENDERER="1")
        catalog = root / "data/lk.ac.uom.factumdb/catalog.db"
        with (root / "desktop.log").open("w+") as log:
            process = subprocess.Popen(["xvfb-run", "-a", "dbus-run-session", "--", str(binary)],
                                       env=env, stdout=log, stderr=log, start_new_session=True)
            try:
                deadline = time.monotonic() + 30
                while not catalog.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.25)
                time.sleep(3)
                log.seek(0)
                diagnostics = log.read()
                assert process.poll() is None, diagnostics
                assert catalog.exists(), "The renderer did not start its packaged backend.\n" + diagnostics
                with sqlite3.connect(catalog) as database:
                    tables = database.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    assert tables, "Backend catalog schema was not initialized"
                print("PASS: installed desktop stays running under Xvfb and renderer IPC starts the packaged backend")
            finally:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", nargs="?", type=Path, default=Path("/usr/bin/factumdb"))
    check(parser.parse_args().binary)
