import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "process_raw.py"
RAW_DIR = ROOT / "examples" / "sample_raw"
OUTPUT_DIR = ROOT / "examples" / "sample_output"


def test_process_raw_keep_log_generates_jpg_and_profile(tmp_path):
    input_dir = tmp_path / "sample_raw"
    output_dir = tmp_path / "sample_output"
    shutil.copytree(RAW_DIR, input_dir)

    env = os.environ.copy()
    env["RAWTHERAPEE_BIN"] = str(ROOT / "bin" / "fake_rawtherapee")

    fake_bin = ROOT / "bin" / "fake_rawtherapee"
    fake_bin.parent.mkdir(parents=True, exist_ok=True)
    fake_bin.write_text(
        """#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
if not args:
    raise SystemExit(1)

out_dir = None
profile = None
raw = None
for i, arg in enumerate(args):
    if arg == '-p':
        profile = args[i + 1]
    if arg == '-c':
        raw = args[i + 1]
    if arg.startswith('-O') or arg.startswith('-o'):
        out_dir = args[i + 1]

if out_dir is None or raw is None or profile is None:
    raise SystemExit(2)

raw_path = Path(raw)
out_path = Path(out_dir)
out_path.mkdir(parents=True, exist_ok=True)

jpg = out_path / (raw_path.stem + '.jpg')
jpg.write_bytes(b'fake-jpg')

pp3 = out_path / (raw_path.stem + '.pp3')
src_pp3 = Path(profile)
if src_pp3.exists():
    shutil.copy2(src_pp3, pp3)
else:
    pp3.write_text(\"[LensProfile]\\nLcMode=lfmanual\\n\")

print(f\"fake rawtherapee processed {raw}\")
""",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)

    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        str(input_dir),
        str(output_dir),
        "--keep",
        "--log",
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 0, result.stderr or result.stdout

    generated_jpgs = sorted(output_dir.glob("*.jpg"))
    assert generated_jpgs, "No JPG output produced in output_dir"

    generated_pp3s = sorted(output_dir.glob("*.pp3"))
    assert generated_pp3s, "No final .pp3 output produced in output_dir"

    csv_files = sorted(output_dir.glob("*_report *.csv"))
    assert csv_files, "No CSV report was created for the processing run"

    with csv_files[0].open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, "CSV report is empty"

    for raw_file in input_dir.glob("*.ARW"):
        sidecar = raw_file.with_suffix(raw_file.suffix + ".pp3")
        assert sidecar.exists(), f"Expected input-sidecar PP3 for {raw_file.name}"

    # Clean up the fake RawTherapee binary after the test run.
    fake_bin.unlink(missing_ok=True)
