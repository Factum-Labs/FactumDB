"""Check an extracted/installed Linux bundle without a GUI or real accounts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def check(resources, evidence=None):
    resources = resources.resolve()
    bundle = resources / "runtime/linux"
    manifest = json.loads((bundle / "manifest.json").read_text())
    for relative, expected in manifest["files"].items():
        path = (bundle / relative).resolve()
        path.relative_to(bundle)
        with path.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == expected, relative
    for key in ("mysql_source", "ibd2sql"):
        artifact = manifest["artifacts"][key]
        with (resources / "sources" / artifact["filename"]).open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == artifact["sha256"], key
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("FACTUMDB_") and key not in ("PYTHONPATH", "LD_LIBRARY_PATH")}
    env.update(PATH="/usr/bin:/bin", FACTUMDB_BUNDLE_ROOT=str(bundle))
    python = Path("/usr/bin/python3")
    for key, relative in manifest["tools"].items():
        args = [str(bundle / relative), "--version"]
        if key == "ibd2sql_path":
            args = [str(python), "-B", *args]
        else:
            assert os.access(bundle / relative, os.X_OK), relative
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, (key, result.stderr)
        print(result.stdout.strip(), flush=True)
    with tempfile.TemporaryDirectory(prefix="factumdb linux bundle ") as directory:
        workspace = Path(directory)
        source = resources / "backend"
        # Seed a test-only account directly in the temporary database. Production
        # sign-up still requires polkit; no bypass is added to the application.
        seed = ("import sys; sys.path.insert(0,sys.argv[1]); "
                "from sidecar.desktop import DesktopRuntime; "
                "from core.application.authentication import AuthenticationService; "
                "r=DesktopRuntime(sys.argv[2]); salt=bytes(range(16)); "
                "r.auth.accounts.create('BundleTest','bundletest',salt,"
                "AuthenticationService.digest('Bundle test password 123',salt),r.auth.device.identity()); r.close()")
        subprocess.run([str(python), "-B", "-c", seed, str(source), directory], env=env, check=True)
        args = [str(python), "-B", "-u", "-X", "utf8", "-c",
                "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('sidecar.desktop',run_name='__main__')",
                str(source), "--workspace", directory]

        def request(process, command, payload=None, error=None):
            process.stdin.write(json.dumps({"request_id": "bundle", "command": command, "payload": payload or {}}) + "\n")
            process.stdin.flush()
            result = json.loads(process.stdout.readline())
            if error:
                assert result.get("error_code") == error, result
                return result
            assert result["ok"], result
            return result["result"]

        for attempt in range(2):
            # Put stderr in a file so large utility diagnostics cannot block a pipe.
            with (workspace / "stderr.log").open("w+") as stderr:
                process = subprocess.Popen(args, env=env, stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=stderr, text=True)
                try:
                    assert request(process, "health")["application_configured"]
                    request(process, "list_cases", error="AuthenticationRequiredError")
                    assert request(process, "auth_status")["user"] is None
                    request(process, "auth_login", {"username": "BundleTest", "password": "Bundle test password 123"})
                    settings = request(process, "get_settings")
                    assert len(settings["bundled_tools"]) == 4
                    assert Path(settings["tools"]["python_path"]).resolve() == python.resolve()
                    for key, relative in manifest["tools"].items():
                        assert Path(settings["tools"][key]) == bundle / relative
                    if attempt == 0:
                        case_id = request(process, "create_case", {"case_name": "Linux bundle smoke", "examiner": "Ignored"})["case_id"]
                        if evidence:
                            inputs = sorted((evidence / "ibd").glob("*.ibd")) + sorted((evidence / "binlog").glob("*"))
                            assert inputs, evidence
                            for path in inputs:
                                if path.is_file():
                                    request(process, "register_evidence", {"case_id": case_id, "source_path": str(path.resolve())})
                            run = request(process, "start_pipeline", {"case_id": case_id})
                            for _ in range(20):
                                if run["stopped"]:
                                    break
                                run = request(process, "run_next_stage", {"run_id": run["run_id"]})
                            assert run["complete"], run
                            exported = workspace / "report.json"
                            request(process, "export_case", {"case_id": case_id, "format": "JSON", "path": str(exported)})
                            assert json.loads(exported.read_text())
                            print("PASS: real bundled tools, all pipeline stages and JSON export", flush=True)
                    assert len(request(process, "list_cases")) == 1
                    assert request(process, "get_case_data", {"case_id": case_id})["case"]["examiner"] == "BundleTest"
                    request(process, "auth_logout")
                    request(process, "list_cases", error="AuthenticationRequiredError")
                finally:
                    process.stdin.close()
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise
                    stderr.seek(0)
                    assert process.returncode == 0, stderr.read()
    print("PASS: package hashes, automatic tool paths, authentication, case persistence and restart", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("resources", type=Path, help="Resource directory or a .deb installer")
    parser.add_argument("--evidence", type=Path, help="Optional fixture subject containing ibd/ and binlog/")
    options = parser.parse_args()
    if options.resources.suffix == ".deb":
        with tempfile.TemporaryDirectory(prefix="factumdb-deb-") as directory:
            target = Path(directory)
            subprocess.run(["dpkg-deb", "-x", str(options.resources), directory], check=True)
            assert (target / "usr/share/polkit-1/actions/org.factumdb.signup.policy").is_file()
            assert list((target / "usr/share/applications").glob("*.desktop"))
            manifests = list(target.glob("usr/lib/*/runtime/linux/manifest.json"))
            assert len(manifests) == 1, manifests
            check(manifests[0].parents[2], options.evidence)
    else:
        check(options.resources, options.evidence)
