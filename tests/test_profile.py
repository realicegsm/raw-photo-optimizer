import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from optimize_profile import determine_lens_profile, optimize_pp3
from process_raw import optimize_profile


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


def test_ttartisan_lcp_profiles_match_distinct_focal_lengths():
    templates_dir = ROOT / "templates"

    assert determine_lens_profile("TTARTISAN 35mm F1.8 ", templates_dir) == (
        templates_dir / "TTARTISAN AF 35mm F1.8.lcp"
    )
    assert determine_lens_profile("TTARTISAN 50mm F1.8 ", templates_dir) == (
        templates_dir / LCP_NAME
    )


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


def test_black_and_white_modes_write_expected_profile_settings(tmp_path):
    params = {
        "comp_val": "0",
        "drc_val": "0",
        "camera_model": "ILCE-6100",
        "lens_model": "",
        "over_pct": 0.0,
        "under_pct": 0.0,
        "iso": 100,
        "dr_ev": None,
        "mean_green": 0.15,
    }

    expected_modes = {
        "channel_mixer": {
            "Enabled": "true",
            "Method": "ChannelMixer",
            "Auto": "false",
            "ComplementaryColors": "true",
            "Setting": "Luminance",
            "Filter": "None",
            "MixerRed": "30",
            "MixerOrange": "33",
            "MixerYellow": "33",
            "MixerGreen": "59",
            "MixerCyan": "33",
            "MixerBlue": "11",
            "MixerMagenta": "33",
            "MixerPurple": "33",
            "GammaRed": "0",
            "GammaGreen": "0",
            "GammaBlue": "0",
            "Algorithm": "SP",
            "LuminanceCurve": "0;",
            "BeforeCurveMode": "Standard",
            "AfterCurveMode": "Standard",
            "BeforeCurve": "0;",
            "AfterCurve": "0;",
        },
        "desaturation": {
            "Enabled": "true",
            "Method": "Desaturation",
            "Auto": "false",
            "ComplementaryColors": "true",
            "Setting": "RGB-Rel",
            "Filter": "None",
            "MixerRed": "33",
            "MixerOrange": "33",
            "MixerYellow": "33",
            "MixerGreen": "33",
            "MixerCyan": "33",
            "MixerBlue": "33",
            "MixerMagenta": "33",
            "MixerPurple": "33",
            "GammaRed": "0",
            "GammaGreen": "0",
            "GammaBlue": "0",
            "Algorithm": "SP",
            "LuminanceCurve": "0;",
            "BeforeCurveMode": "Standard",
            "AfterCurveMode": "Standard",
            "BeforeCurve": "0;",
            "AfterCurve": "0;",
        },
    }

    for mode, expected_values in expected_modes.items():
        output_profile = tmp_path / f"profile_{mode}.pp3"
        applied = optimize_pp3(
            TEMPLATE_PROFILE,
            output_profile,
            {**params, "black_and_white_mode": mode},
        )

        actual_values = read_section_values(output_profile, "Black & White")
        for key, expected_value in expected_values.items():
            assert actual_values[key] == expected_value
        assert applied["black_and_white_mode"] == mode
        assert applied["black_and_white_parameters"]["Black & White"] == expected_values

    lab_profile = tmp_path / "profile_lab.pp3"
    lab_applied = optimize_pp3(
        TEMPLATE_PROFILE,
        lab_profile,
        {**params, "black_and_white_mode": "lab"},
    )
    assert read_section_values(lab_profile, "Black & White")["Enabled"] == "false"
    assert read_section_values(lab_profile, "Luminance Curve")["Enabled"] == "true"
    assert read_section_values(lab_profile, "Luminance Curve")["Chromaticity"] == "-100"
    assert read_section_values(lab_profile, "Lab Adjustments") == {}
    assert lab_applied["black_and_white_parameters"] == {
        "Black & White": {"Enabled": "false"},
        "Luminance Curve": {"Enabled": "true", "Chromaticity": "-100"},
    }

    channel_mixer_profile = tmp_path / "profile_channel_mixer.pp3"
    optimize_pp3(
        TEMPLATE_PROFILE,
        channel_mixer_profile,
        {**params, "black_and_white_mode": "channel_mixer"},
    )
    assert read_section_values(channel_mixer_profile, "Luminance Curve")["Enabled"] == "false"

    color_profile = tmp_path / "profile_color.pp3"
    optimize_pp3(TEMPLATE_PROFILE, color_profile, params)
    assert read_section_values(color_profile, "Black & White")["Enabled"] == "false"
    assert read_section_values(color_profile, "Luminance Curve")["Enabled"] == "false"


def test_color_mode_omits_black_and_white_parameters_from_report(tmp_path):
    _, _, decision_values = optimize_profile(
        tmp_path / "color.ARW",
        "color",
        {},
        "ILCE-6100",
        "",
        100,
        keep=True,
    )

    assert decision_values["black_and_white_mode"] == ""
    assert decision_values["black_and_white_parameters"] == ""
