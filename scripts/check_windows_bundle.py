"""Exercise the packaged backend with the isolated interpreter and no tool PATH."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def check(resources):
    resources = resources.resolve()
    bundle = resources / "runtime/windows"
    python = bundle / "python/python.exe"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["files"].items():
        path = (bundle / relative).resolve()
        path.relative_to(bundle)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
    for name in ("mysql_source", "ibd2sql"):
        artifact = manifest["artifacts"][name]
        with (resources / "sources" / artifact["filename"]).open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == artifact["sha256"], name
    env = {**os.environ, "PATH": str(Path(os.environ["SystemRoot"]) / "System32"),
           "FACTUMDB_BUNDLE_ROOT": str(bundle)}
    env.pop("PYTHONPATH", None)
    for name, relative in manifest["tools"].items():
        args = [str(bundle / relative), "--version"]
        if name == "ibd2sql_path":
            args = [str(python), "-B", "-X", "utf8", *args]
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, (name, result.returncode, result.stderr)
    with tempfile.TemporaryDirectory(prefix="factumdb bundle ", dir=ROOT / ".bundle-cache") as workspace:
        args = [str(python), "-B", "-u", "-X", "utf8", "-c",
                "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('sidecar.desktop',run_name='__main__')",
                str(resources / "backend"), "--workspace", workspace]
        def request(process, command, payload=None):
            process.stdin.write(json.dumps({"request_id": "smoke", "command": command, "payload": payload or {}}) + "\n")
            process.stdin.flush()
            result = json.loads(process.stdout.readline())
            assert result["ok"], result
            return result["result"]
        for attempt in range(2):
            process = subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding="utf-8")
            try:
                assert request(process, "health")["application_configured"]
                settings = request(process, "get_settings")
                assert Path(settings["tools"]["python_path"]) == python
                assert len(settings["bundled_tools"]) == 5
                if attempt == 0:
                    request(process, "create_case", {"case_name": "Bundled Windows case", "examiner": "Smoke test"})
                assert len(request(process, "list_cases")) == 1
            finally:
                process.stdin.close()
                process.wait(timeout=30)
                assert process.returncode == 0, process.stderr.read()
    print("Isolated bundled backend: startup, automatic tool paths, case creation and restart passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("resources", type=Path)
    check(parser.parse_args().resources)
