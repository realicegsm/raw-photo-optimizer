import csv
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "process_raw.py"
RAW_DIR = ROOT / "examples" / "sample_raw"
OUTPUT_DIR = ROOT / "examples" / "sample_output"
sys.path.insert(0, str(ROOT / "scripts"))

import process_raw as process_raw_module


def resolve_rawtherapee_cli() -> Path:
    configured_binary = os.environ.get("RAWTHERAPEE_BIN")
    if configured_binary:
        binary = Path(configured_binary).expanduser()
    else:
        discovered_binary = shutil.which("rawtherapee-cli")
        binary = Path(discovered_binary) if discovered_binary else Path("/usr/local/bin/rawtherapee-cli")

    if not binary.is_file() or not os.access(binary, os.X_OK):
        pytest.skip(f"Executable RawTherapee CLI was not found: {binary}")

    version = subprocess.run(
        [str(binary), "-v"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert "RawTherapee, version" in version.stdout, (
        f"Configured executable is not RawTherapee CLI: {binary}\n"
        f"{version.stdout}\n{version.stderr}"
    )
    return binary


def clear_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT_DIR.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def read_section_values(pp3_path: Path, section_name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    current_section = None

    with pp3_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
            elif current_section == section_name and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value

    return values


def assert_profile_values_preserved(input_profile: Path, output_profile: Path) -> None:
    controlled_parameters = {
        "Exposure": ("Compensation", "Contrast"),
        "HLRecovery": ("Enabled", "Method", "Hlth"),
        "Directional Pyramid Denoising": (
            "Enabled",
            "SMethod",
            "Median",
            "Ldetail",
            "Luma",
            "Chroma",
        ),
        "FattalToneMapping": ("Enabled", "Amount", "Anchor"),
        "Shadows & Highlights": (
            "Enabled",
            "Highlights",
            "HighlightTonalWidth",
            "Shadows",
            "ShadowTonalWidth",
            "Radius",
            "Lab",
        ),
        "LensProfile": (
            "LcMode",
            "LCPFile",
            "UseDistortion",
            "UseVignette",
            "UseCA",
            "LFCameraMake",
            "LFCameraModel",
            "LFLens",
        ),
        "RAW": ("CA",),
    }
    expected_values = {
        section_name: read_section_values(input_profile, section_name)
        for section_name in controlled_parameters
    }
    actual_values = {
        section_name: read_section_values(output_profile, section_name)
        for section_name in controlled_parameters
    }

    required_parameters = {
        "Exposure": ("Compensation",),
        "FattalToneMapping": ("Enabled", "Amount"),
        "Shadows & Highlights": (
            "Enabled",
            "Highlights",
            "HighlightTonalWidth",
            "Shadows",
            "ShadowTonalWidth",
            "Radius",
            "Lab",
        ),
        "LensProfile": ("LcMode",),
        "RAW": ("CA",),
    }
    if expected_values["Directional Pyramid Denoising"].get("Enabled") == "true":
        required_parameters["Directional Pyramid Denoising"] = controlled_parameters[
            "Directional Pyramid Denoising"
        ]
    if expected_values["HLRecovery"].get("Enabled") == "true":
        required_parameters["HLRecovery"] = controlled_parameters["HLRecovery"]
    if expected_values["LensProfile"].get("LcMode") in {"lcp", "lfmanual"}:
        required_parameters["LensProfile"] = (
            "LcMode",
            "UseDistortion",
            "UseVignette",
            "UseCA",
            "LFCameraMake",
            "LFCameraModel",
            "LFLens",
        )
        if expected_values["LensProfile"].get("LcMode") == "lcp":
            required_parameters["LensProfile"] += ("LCPFile",)

    compared_parameters = 0
    for section_name, keys in controlled_parameters.items():
        input_values = expected_values[section_name]
        output_values = actual_values[section_name]
        for key in required_parameters.get(section_name, ()):
            assert key in input_values, (
                f"{input_profile.name}: generated profile is missing "
                f"[{section_name}] {key}"
            )

        for key in keys:
            if key not in input_values:
                continue

            expected_value = input_values[key]
            actual_value = output_values.get(key)
            assert actual_value is not None, (
                f"{output_profile.name}: missing [{section_name}] {key}"
            )
            try:
                numeric_match = math.isclose(
                    float(actual_value),
                    float(expected_value),
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            except ValueError:
                numeric_match = False
            assert numeric_match or actual_value == expected_value, (
                f"{output_profile.name}: [{section_name}] {key} changed from "
                f"{expected_value!r} to {actual_value!r}"
            )
            compared_parameters += 1

    assert compared_parameters >= sum(map(len, required_parameters.values())), (
        f"Only {compared_parameters} controlled parameters were compared between "
        f"{input_profile.name} and {output_profile.name}"
    )


@pytest.mark.parametrize(
    ("bw_mode", "expected_filename"),
    [
        (None, "DSC05456.jpg"),
        ("channel_mixer", "DSC05456_BW.jpg"),
        ("desaturation", "DSC05456_BW_AVG.jpg"),
        ("lab", "DSC05456_BW_LAB.jpg"),
    ],
)
def test_process_raw_adds_bw_suffix_for_bw_modes(
    tmp_path, monkeypatch, bw_mode, expected_filename
) -> None:
    input_raw = tmp_path / "DSC05456.ARW"
    input_raw.touch()
    stats = {"overexposed_pct": 0.0, "underexposed_pct": 0.0}
    exif = {"ISO": 100, "Model": "ILCE-6100", "LensModel": "Test Lens"}
    monkeypatch.setattr(
        process_raw_module,
        "analyze_file",
        lambda _file_path: {"stats": stats, "exif": exif},
    )
    monkeypatch.setattr(
        process_raw_module,
        "optimize_profile",
        lambda *_args, **_kwargs: ("", [], {}),
    )

    def fake_subprocess_run(command, **_kwargs):
        if command[0] == "rm":
            shutil.rmtree(command[-1], ignore_errors=True)
        else:
            temp_output_dir = Path(command[2])
            (temp_output_dir / "DSC05456.jpg").write_bytes(b"jpeg")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(process_raw_module.subprocess, "run", fake_subprocess_run)

    result = process_raw_module.process_raw(
        input_raw, tmp_path / "output", bw_mode=bw_mode
    )

    assert Path(result["output_file"]).name == expected_filename


def test_process_raw_lab_mode_is_preserved_by_rawtherapee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rawtherapee_cli = resolve_rawtherapee_cli()
    monkeypatch.setattr(process_raw_module, "RAWTHERAPEE_BIN", str(rawtherapee_cli))

    input_dir = tmp_path / "raw"
    input_dir.mkdir()
    input_raw = input_dir / "BWLabIntegration.ARW"
    shutil.copy2(RAW_DIR / "DSC05456.ARW", input_raw)

    report = process_raw_module.process_raw(
        input_raw,
        tmp_path / "output",
        keep=True,
        bw_mode="lab",
    )

    assert report["status"] == "OK", report["reason"]
    output_file = Path(report["output_file"])
    output_profile = Path(report["output_profile"])
    assert output_file.name == "BWLabIntegration_BW_LAB.jpg"
    assert output_file.is_file() and output_file.stat().st_size > 0
    assert output_profile.is_file() and output_profile.stat().st_size > 0

    assert read_section_values(output_profile, "Black & White")["Enabled"] == "false"
    luminance_curve = read_section_values(output_profile, "Luminance Curve")
    assert luminance_curve["Enabled"] == "true"
    assert math.isclose(float(luminance_curve["Chromaticity"]), -100.0)
    assert report["black_and_white_mode"] == "--BW_LAB"
    assert json.loads(report["black_and_white_parameters"]) == {
        "Black & White": {"Enabled": "false"},
        "Luminance Curve": {"Chromaticity": "-100", "Enabled": "true"},
    }

    report_path = tmp_path / "report.csv"
    process_raw_module.write_report(report_path, [report])
    with report_path.open("r", encoding="utf-8", newline="") as report_file:
        logged_report = next(csv.DictReader(report_file))
    assert logged_report["black_and_white_mode"] == "--BW_LAB"
    assert json.loads(logged_report["black_and_white_parameters"]) == json.loads(
        report["black_and_white_parameters"]
    )


def test_process_raw_with_real_rawtherapee(tmp_path: Path) -> None:
    raw_files = sorted(RAW_DIR.glob("*.ARW"))
    assert raw_files, f"No RAW fixtures found in {RAW_DIR}"

    rawtherapee_cli = resolve_rawtherapee_cli()
    input_dir = tmp_path / "sample_raw"
    shutil.copytree(RAW_DIR, input_dir, ignore=shutil.ignore_patterns(".DS_Store"))
    clear_output_dir()

    env = os.environ.copy()
    env["RAWTHERAPEE_BIN"] = str(rawtherapee_cli)
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        str(input_dir),
        str(OUTPUT_DIR),
        "--keep",
        "--log",
    ]
    result = subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=900,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    report_files = sorted(OUTPUT_DIR.glob("_report *.csv"))
    assert len(report_files) == 1, (
        f"Expected one new CSV report in {OUTPUT_DIR}, found {len(report_files)}"
    )
    with report_files[0].open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == len(raw_files), f"Expected {len(raw_files)} report rows, got {len(rows)}"
    failed_rows = [row for row in rows if row["status"] != "OK"]
    assert not failed_rows, (
        "Real RawTherapee failed to process sample RAW files: "
        + "; ".join(f"{row['file_id']}: {row['reason']}" for row in failed_rows)
    )

    for row in rows:
        input_raw = input_dir / f"{row['file_id']}.ARW"
        input_profile = input_raw.with_suffix(input_raw.suffix + ".pp3")
        output_file = Path(row["output_file"])
        output_profile = Path(row["output_profile"])

        assert input_profile.is_file(), f"Missing generated input profile for {input_raw.name}"
        assert output_file.parent == OUTPUT_DIR, (
            f"Expected output under {OUTPUT_DIR}, got {output_file}"
        )
        assert output_file.is_file() and output_file.stat().st_size > 0, (
            f"Missing or empty RawTherapee JPG for {input_raw.name}"
        )
        assert output_profile.is_file() and output_profile.stat().st_size > 0, (
            f"Missing or empty RawTherapee output profile for {input_raw.name}"
        )
        assert_profile_values_preserved(input_profile, output_profile)
