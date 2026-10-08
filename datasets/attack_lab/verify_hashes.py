"""Verify every acquisition file against its generated SHA-256 manifest."""
import hashlib
import json
from pathlib import Path
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--subjects", type=Path, default=Path(__file__).resolve().parent / "subjects")
root = parser.parse_args().subjects.resolve()
manifests = sorted(root.glob("*/manifest.json"))
assert len(manifests) == 6, "Expected six generated subjects"
total = files = rows = 0
for manifest in manifests:
    subject = manifest.parent
    data = json.loads(manifest.read_text(encoding="utf-8"))
    rows += sum(data["baseline_rows"].values())
    listed = set()
    for item in data["files"]:
        path = (subject / item["path"]).resolve()
        assert path.is_relative_to(subject.resolve()), f"Path outside subject: {path}"
        assert path.stat().st_size == item["bytes"], f"Size changed: {path}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], f"Hash changed: {path}"
        listed.add(path)
        total += path.stat().st_size
        files += 1
    actual = {p.resolve() for directory in (subject / "ibd", subject / "binlog") for p in directory.iterdir()}
    assert listed == actual, f"Evidence inventory changed: {subject}"
    assert (subject / "EXPECTED_FINDINGS.md").is_file()
print(f"Checked {len(manifests)} subjects, {files} evidence files, {rows:,} seeded rows, "
      f"{total/1048576:.2f} MiB; all acquisition hashes match.")
