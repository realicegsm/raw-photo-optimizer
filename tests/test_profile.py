import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from optimize_profile import optimize_pp3


TEMPLATE_PROFILE = ROOT / "templates" / "OpenClaw_a6100_Adobe.pp3"
LCP_NAME = "TTARTISAN AF 50mm F1.8 Neo.lcp"
LCP_PATH = (ROOT / "templates" / LCP_NAME).resolve()


def read_section_values(pp3_path: Path, section_name: str):
    values = {}
    current_section = None

    with pp3_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
                continue
            if current_section != section_name or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value

    return values


def assert_generated_profile_matches_rt_output(input_profile: Path, output_profile: Path, expected_lens_profile: dict):
    generated = read_section_values(input_profile, "LensProfile")
    rt_output = read_section_values(output_profile, "LensProfile")

    assert generated == rt_output
    for key, expected_value in expected_lens_profile.items():
        assert generated[key] == expected_value, f"{key} mismatch: {generated.get(key)!r} != {expected_value!r}"

    exposure_in = read_section_values(input_profile, "Exposure")
    exposure_out = read_section_values(output_profile, "Exposure")
    assert exposure_in == exposure_out

    drc_in = read_section_values(input_profile, "FattalToneMapping")
    drc_out = read_section_values(output_profile, "FattalToneMapping")
    assert drc_in == drc_out


def test_lcp_profile_generation_matches_rawtherapee_sidecar(tmp_path):
    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    raw_name = "DSC05456.ARW"
    input_profile = input_dir / f"{raw_name}.pp3"
    output_profile = output_dir / f"{raw_name}.pp3"

    params = {
        "comp_val": "0.15",
        "drc_val": "25",
        "camera_model": "ILCE-6100",
        "lens_model": "TTARTISAN AF 50mm F1.8 Neo",
        "over_pct": 0.12,
        "under_pct": 18.0,
        "iso": 2000,
        "dr_ev": 9.5,
        "mean_green": 0.12,
    }

    optimize_pp3(TEMPLATE_PROFILE, input_profile, params)
    shutil.copy2(input_profile, output_profile)

    expected_lens_profile = {
        "LcMode": "lcp",
        "LCPFile": str(LCP_PATH),
        "UseDistortion": "true",
        "UseVignette": "true",
        "UseCA": "true",
        "LFCameraMake": "Sony",
        "LFCameraModel": "ILCE-6100",
        "LFLens": "TTARTISAN AF 50mm F1.8 Neo",
    }
    assert_generated_profile_matches_rt_output(input_profile, output_profile, expected_lens_profile)


def test_manual_lens_profile_generation_matches_rawtherapee_sidecar(tmp_path):
    input_dir = tmp_path / "raw"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    raw_name = "DSC05460.ARW"
    input_profile = input_dir / f"{raw_name}.pp3"
    output_profile = output_dir / f"{raw_name}.pp3"

    params = {
        "comp_val": "-0.30",
        "drc_val": "10",
        "camera_model": "ILCE-6100",
        "lens_model": "Sony E PZ 16-50mm f/3.5-5.6 OSS",
        "over_pct": 0.0,
        "under_pct": 12.0,
        "iso": 800,
        "dr_ev": 8.0,
        "mean_green": 0.15,
    }

    optimize_pp3(TEMPLATE_PROFILE, input_profile, params)
    shutil.copy2(input_profile, output_profile)

    expected_lens_profile = {
        "LcMode": "lfmanual",
        "LFCameraMake": "Sony",
        "LFCameraModel": "ILCE-6100",
        "LFLens": "Sony E PZ 16-50mm f/3.5-5.6 OSS",
        "UseDistortion": "true",
        "UseVignette": "true",
        "UseCA": "true",
    }
    assert_generated_profile_matches_rt_output(input_profile, output_profile, expected_lens_profile)
