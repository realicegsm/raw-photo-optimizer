import sys
from pathlib import Path

from pdr_curve import pdr_delta_ev, interp_control_points, dr_headroom_ratio

# --- GLOBAL CONFIGURATION ---
# These parameters can be tuned to calibrate the pipeline's aesthetic result.

CONFIG = {
    "general": {
        "camera_model": "ILCE-6100"  # Set to e.g. "ILCE-6100" to force a specific model, or None to use EXIF
    },
    "analysis": {
        "base_target_green": 0.15,      # Ideal mean green for well-exposed scenes
        "dark_target_green": 0.04,      # Target for very dark scenes
        "dark_threshold": 0.10,         # Threshold to start interpolating target_green
    },

    "exposure": {
        "ev_clamp_min": -1.2,           # Minimum exposure shift (protects from over-darkening)
        "ev_clamp_max": 0.9,            # Maximum exposure shift (protects from blowing highlights)
    },
    "drc": {
        # Thresholds are ratios of measured scene DR to the sensor's *actual* PDR
        # ceiling at the shot's ISO (see pdr_curve.py — measured PhotonsToPhotos
        # data for the ILCE-6100).
        #
        # IMPORTANT CONTEXT: these Amount tiers were originally calibrated while
        # the tool was silently a no-op — earlier code wrote the pp3 section
        # under the name "[Dynamic Range Compression]", which this RT version
        # does not read (it expects "[FattalToneMapping]"). So none of this had
        # ever actually been visually validated until the section name was
        # fixed. The first real run showed the tiers were too strong (flat,
        # over-darkened, especially DSC02348) — values below are roughly halved
        # from the original blind guess as a more conservative starting point.
        "high_headroom_ratio": 0.92,
        "high_dr_amount": "25",
        "mid_headroom_ratio": 0.80,
        "mid_dr_amount": "15",
        "low_headroom_ratio": 0.65,
        "low_dr_amount": "6",
        "fallback_amount": "5",   # used when dr_ev is unavailable but over_pct still triggers it
        # Threshold (RT's "Detail" slider: local-contrast preservation) is
        # deliberately NOT written by this code — no clear signal on it yet,
        # only one manually-tuned file touched it (DSC02511: 30→20), the rest
        # left it at RT's own default of 30.
        #
        # Anchor (biases the compression toward shadows/highlights — per
        # RawPedia it "effectively functions as an exposure compensation")
        # DOES have a real signal from manual calibration, confirmed across
        # two independent rounds: never lowered from RT's default (50) when
        # DRC stays enabled. Round 2 values (Amount>0 files): 100, 70, 85,
        # 85, 85, 75, 75 — mode is 85, not the median/mean (both ~75), so 85
        # is used as the new baseline. The two 50s in that round (DSC02511/
        # 512) are the residual-DRC dampened cases with tiny Amount (8-10),
        # where Anchor barely matters — excluded from driving the baseline.
        # DSC02160 (headroom_ratio=2.44, the most extreme case) tested best
        # at 100 specifically, suggesting Anchor may scale up further at the
        # high end, but that's a single data point — not enough to derive a
        # formula yet, so still a flat baseline for now.
        "anchor": "85",
    },
    "denoise": {
        "enable_delta_ev": 0.5,   # min PDR loss vs base ISO before denoise kicks in
        "max_luma": 35,           # Hard limit for Luma denoise (lowered from 50 — was over-smoothing)
        "max_chroma": 50,         # Hard limit for Chroma denoise (lowered from 70)
        # Base (Luma, Chroma) strength as a function of delta_ev = how many EV
        # of PDR have been lost vs base ISO 100 (from the real PDR curve).
        # Interpolated linearly between points — replaces the old flat
        # iso >= 1200 on/off switch with a continuous ramp.
        # Values scaled down ~35-40% from the first pass: at max_luma=50 the
        # output was visibly "watercolor" — losing fine texture even before
        # accounting for the Median/Ldetail issue below.
        "control_points": [
            (0.0, 0,  0),
            (1.5, 5,  7),    # ~ISO 350-400
            (2.4, 10, 14),   # ~ISO 800
            (3.4, 15, 20),   # ~ISO 1600
            (4.3, 20, 28),   # ~ISO 3200
            (5.3, 25, 35),   # ~ISO 6400
            (6.4, 30, 42),   # ~ISO 12800
            (7.3, 35, 46),   # ~ISO 25600+
        ],
        # Ldetail: RawTherapee's detail-recovery pass after denoising (0-100,
        # higher = more texture preserved). Was hardcoded to 15 regardless of
        # denoise strength — far too aggressive, this alone was the main cause
        # of the "watercolor" look. Now scales up with delta_ev so heavier
        # denoising gets proportionally more detail recovery to compensate.
        "ldetail_base": 45,
        "ldetail_max": 65,
        # Median adds an extra smoothing pass on top of the wavelet denoiser
        # itself — it's the single biggest contributor to plastic/smeared
        # texture. Only worth it at very high ISO where chroma noise is
        # otherwise unmanageable; off by default.
        "median_delta_ev_threshold": 6.0,   # ~ISO 12800+
        # Multiplies the base strength above for dark/underexposed scenes,
        # where shadow push amplifies noise beyond what ISO alone predicts.
        "levels": [
            {"threshold_green": 0.05, "threshold_under": 66.0, "factor": 1.5},
            {"threshold_green": 0.08, "threshold_under": 45.0, "factor": 1.2},
        ]
    },
    "recovery": {
        "hl_threshold_high": "0.90",    # Threshold for strong overexposure
        "hl_threshold_low": "0.85",     # Threshold for mild overexposure,
        "over_pct_high": 0.5,           # Percentage to trigger hl_threshold_high
        "over_pct_min": 0.005,          # Percentage to enable HL Recovery
    },
    "drc_dampening": {
        # Stacking strong DRC on top of a large positive exposure push
        # (already-lifted shadows) compounds into a flat, muddy image.
        "under_pct_trigger": 30.0,
        "positive_shift_trigger": 0.4,
        # Two independent manual calibration rounds showed the dampened set
        # splits by ISO: at >= full_disable_iso, DRC was left fully off both
        # times (DSC02478 @6400, DSC02479 @2000); below it, a small residual
        # amount was re-enabled both times instead (DSC02511 @500: 5 then 8;
        # DSC02512 @400: off then 10) — full zero was overshooting there.
        "full_disable_iso": 2000,
        "residual_amount": "8",
    },
    "shadows": {
        # Backlit / high local-contrast scenes: bright background + dark
        # subject. The signature we can actually measure is headroom_ratio
        # (measured scene DR ÷ sensor's physical PDR ceiling at this ISO) —
        # when the scene's real contrast exceeds what the sensor can capture
        # cleanly, that's a strong, specific indicator of exactly this
        # situation. This replaces an earlier attempt gated on raw shadow
        # percentile (p_low), which fired on nearly every frame (almost any
        # photo has *some* near-black pixels) and a static always-on default
        # in the .pp3 template, which affected every frame including scenes
        # that didn't need it.
        #
        # Values below are what the user manually tuned to match the in-camera
        # JPEG's D-Range Optimizer look on a known-backlit reference shot
        # (DSC02160, headroom_ratio ~2.44). Scaled smoothly rather than
        # on/off between min_headroom_ratio and full_strength_ratio.
        "min_headroom_ratio": 1.15,   # below this, treat as a normal scene — no lift
        "full_strength_ratio": 1.6,   # at/above this, apply the full tuned amount
        "max_shadow_amount": 33,
        "shadow_tonal_width": 30,     # narrow — only touches near-black tones, not midtones/background
        "radius": 40,
        "max_highlights_amount": 24,  # counterweight so the bright background doesn't lift with the shadows
        "highlights_tonal_width": 70,
        # High-ISO dampening: two independent manual rounds both fully
        # disabled Shadow Lift on DSC02478 (headroom_ratio=3.68, ISO 6400,
        # delta_ev=5.29) despite it being the strongest headroom signal in
        # the dataset — aggressive local shadow lift amplifies noise at high
        # ISO faster than it helps. DSC02479 (delta_ev=3.66) also got its
        # already-small lift zeroed. DSC02160 (delta_ev=2.38, full lift KEPT
        # both rounds) and DSC02274 (delta_ev=1.40, partial lift KEPT) sit
        # well below the threshold below — consistent with only dampening at
        # the high end.
        "high_iso_dampen_delta_ev": 3.0,
    }
}

def modify_pp3_value(content, section, key, value):
    lines = content.splitlines()
    new_lines = []
    current_section = None
    found = False
    
    target_section = section.strip().casefold()
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            current_section = stripped
        
        if current_section and current_section.strip().casefold() == target_section and stripped.startswith(key + "="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
            
    if not found:
        final_lines = []
        section_found = False
        for line in lines:
            final_lines.append(line)
            if line.strip().casefold() == target_section:
                section_found = True
                final_lines.append(f"{key}={value}")
        
        if not section_found:
            final_lines.append("")
            final_lines.append(section)
            final_lines.append(f"{key}={value}")
        return "\n".join(final_lines)
        
    return "\n".join(new_lines)


def normalize_lcp_path(value):
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    # RawTherapee and profile-generation code sometimes leaves a stale prefix
    # before the actual file path, like:
    #   "/Users/.../Raw/file:/Users/.../TTARTISAN.lcp"
    # We must keep only the final absolute path and strip any file: URL prefix.
    for marker in ("file://", "file:"):
        if marker in text:
            text = text.rsplit(marker, 1)[-1]

    text = text.strip().replace("\\", "/")
    if not text:
        return ""

    return str(Path(text).expanduser().resolve(strict=False))


def determine_lens_profile(
    lens_info: str | None,
    templates_dir: Path | None = None,
) -> Path | str | None:
    if not lens_info:
        return None

    li = lens_info.lower().strip()

    def normalize_text(value):
        import re
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def has_lcp_match(value, profile_name):
        if not value or not profile_name:
            return False

        lens_norm = normalize_text(value)
        profile_norm = normalize_text(profile_name)

        if not lens_norm or not profile_norm:
            return False

        lens_tokens = set(lens_norm.split())
        profile_tokens = set(profile_norm.split())

        # Exact strong match: one normalized string contains the other.
        if lens_norm in profile_norm or profile_norm in lens_norm:
            return True

        # Partial token match: most important tokens from the LCP profile appear in
        # the EXIF lens name. This handles variants like:
        #   "TTARTISAN 50mm F1.8" vs "TTARTISAN AF 50mm F1.8 Neo"
        #   "E PZ 16-50mm F3.5-5.6 OSS II" vs "Sony E PZ 16-50mm f/3.5-5.6 OSS"
        shared = lens_tokens & profile_tokens
        if len(shared) >= max(2, len(profile_tokens) // 3):
            return True

        # Also allow a looser match when the profile's main brand/model tokens are
        # present even if some optional suffix words differ.
        for token in ("ttartisan", "sony", "e", "pz", "55", "210", "50", "16", "f18", "f1", "f35", "f36"):
            if token in lens_tokens and token in profile_tokens:
                return True

        return False

    if templates_dir is not None:
        templates_dir = Path(templates_dir)
        if templates_dir.exists():
            for profile_path in sorted(templates_dir.glob("*.lcp")):
                if has_lcp_match(li, profile_path.name):
                    return profile_path

    # More flexible matching for Sony PZ 16-50 and 55-210
    if "16-50" in li or "16 50" in li or "16-50mm" in li:
        return "Sony E PZ 16-50mm f/3.5-5.6 OSS"
    if "55-210" in li or "55 210" in li or "55-210mm" in li:
        return "Sony E 55-210mm f/4.5-6.3 OSS"
    return None

def optimize_pp3(base_pp3_path, output_pp3_path, params):
    """
    Optimizes a RawTherapee .pp3 profile based on exposure analysis.
    """
    base_pp3_path = Path(base_pp3_path)
    output_pp3_path = Path(output_pp3_path)
    
    comp_val = params.get('comp_val', '0')
    drc_val = params.get('drc_val', '0')
    
    # Simple Camera Model Logic: Override in CONFIG -> EXIF -> Default fallback
    config_model = CONFIG["general"].get("camera_model")
    
    if config_model is not None:
        # Priority 1: Explicit override in CONFIG
        camera_model = config_model
    else:
        # Priority 2: Try to get from EXIF
        exif_model = params.get('camera_model')
        if exif_model and str(exif_model).lower() != 'none':
            camera_model = exif_model
        else:
            # Priority 3: Absolute fallback
            camera_model = "ILCE-6100"
        
    lens_model = params.get('lens_model', '')
    over_pct = float(params.get('over_pct', 0.0))
    under_pct = float(params.get('under_pct', 0.0))
    iso = int(params.get('iso', 0))
    dr_ev = params.get('dr_ev')
    mean_green = params.get('mean_green')

    applied = {
        "denoise_enabled": False,
        "denoise_luma": 0,
        "denoise_chroma": 0,
        "denoise_ldetail": 0,
        "denoise_median": False,
        "delta_ev": pdr_delta_ev(iso),
        "shadow_lift_amount": 0,
        "shadow_highlights_amount": 0,
        "headroom_ratio": dr_headroom_ratio(dr_ev, iso) if dr_ev is not None else 0.0,
        "contrast": 0,
        "drc_anchor": 0,
        "lens_profile_applied": "none",
        "lens_camera_model": "",
        "black_and_white_mode": None,
        "black_and_white_parameters": {},
    }

    with open(base_pp3_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # --- DCP Profile Path Resolution ---
    # If InputProfile is just a filename (doesn't contain ':'), make it an absolute path.
    # This keeps the template human-readable but ensures RawTherapee finds the file.
    import re
    dcp_match = re.search(r'^InputProfile=(.*)$', content, re.MULTILINE)
    if dcp_match:
        current_val = dcp_match.group(1).strip()
        if current_val and ':' not in current_val:
            templates_dir = base_pp3_path.parent
            dcp_path = templates_dir / current_val
            if dcp_path.exists():
                content = content.replace(f"InputProfile={current_val}", f"InputProfile=file:{dcp_path}")
            else:
                print(f"⚠️ Warning: DCP profile not found at {dcp_path}")
    
    content = modify_pp3_value(content, "[Exposure]", "Compensation", str(comp_val))
    bw_mode = params.get("black_and_white_mode")
    if bw_mode not in (None, "channel_mixer", "desaturation", "lab"):
        raise ValueError(f"Unsupported black-and-white mode: {bw_mode}")

    bw_parameters = {
        "Black & White": {"Enabled": "false"},
        "Luminance Curve": {"Enabled": "false"},
    }
    if bw_mode in ("channel_mixer", "desaturation"):
        bw_values = {
            "Enabled": "true",
            "Method": "ChannelMixer" if bw_mode == "channel_mixer" else "Desaturation",
            "Auto": "false",
            "ComplementaryColors": "true",
            "Setting": "Luminance" if bw_mode == "channel_mixer" else "RGB-Rel",
            "Filter": "None",
            "MixerRed": "30" if bw_mode == "channel_mixer" else "33",
            "MixerOrange": "33",
            "MixerYellow": "33",
            "MixerGreen": "59" if bw_mode == "channel_mixer" else "33",
            "MixerCyan": "33",
            "MixerBlue": "11" if bw_mode == "channel_mixer" else "33",
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
        }
        for key, value in bw_values.items():
            content = modify_pp3_value(content, "[Black & White]", key, value)
        bw_parameters["Black & White"] = bw_values
    else:
        content = modify_pp3_value(content, "[Black & White]", "Enabled", "false")

    if bw_mode == "lab":
        content = modify_pp3_value(content, "[Luminance Curve]", "Enabled", "true")
        content = modify_pp3_value(content, "[Luminance Curve]", "Chromaticity", "-100")
        bw_parameters["Luminance Curve"] = {
            "Enabled": "true",
            "Chromaticity": "-100",
        }
    else:
        content = modify_pp3_value(content, "[Luminance Curve]", "Enabled", "false")

    applied["black_and_white_mode"] = bw_mode
    applied["black_and_white_parameters"] = bw_parameters

    content = modify_pp3_value(content, "[FattalToneMapping]", "Enabled", "true" if float(drc_val) > 0 else "false")
    content = modify_pp3_value(content, "[FattalToneMapping]", "Amount", str(drc_val))
    # Contrast: two independent manual calibration rounds showed a boost
    # (10-15) improves the result on most files where DRC is engaged — DRC's
    # tone compression tends to flatten local contrast, and this counteracts
    # it. Tied directly to drc_val (not headroom_ratio or any other proxy)
    # since that's the actual condition the user identified. The dr_ev<6.0
    # branch below stays as a fallback for flat scenes where DRC didn't
    # trigger at all.
    contrast_val = 0
    if float(drc_val) > 0:
        contrast_val = 10
        content = modify_pp3_value(content, "[FattalToneMapping]", "Anchor", CONFIG["drc"]["anchor"])
        applied["drc_anchor"] = int(CONFIG["drc"]["anchor"])
    # Threshold intentionally not written — see CONFIG["drc"] comment.


    if contrast_val == 0 and dr_ev is not None and float(dr_ev) < 6.0:
        contrast_val = 10
    if contrast_val > 0:
        content = modify_pp3_value(content, "[Exposure]", "Contrast", str(contrast_val))
    applied["contrast"] = contrast_val

    if over_pct > CONFIG["recovery"]["over_pct_min"]:
        hl_threshold = CONFIG["recovery"]["hl_threshold_high"] if over_pct > CONFIG["recovery"]["over_pct_high"] else CONFIG["recovery"]["hl_threshold_low"]
        content = modify_pp3_value(content, "[HLRecovery]", "Enabled", "true")
        content = modify_pp3_value(content, "[HLRecovery]", "Method", "Coloropp")
        content = modify_pp3_value(content, "[HLRecovery]", "Hlth", hl_threshold)
    
    delta_ev = applied["delta_ev"]
    if delta_ev > CONFIG["denoise"]["enable_delta_ev"]:
        dn_cfg = CONFIG["denoise"]
        base_luma, base_chroma = interp_control_points(dn_cfg["control_points"], delta_ev)

        # Dark/underexposed scenes push shadows further, amplifying noise
        # beyond what ISO-derived delta_ev alone predicts — apply as a multiplier.
        dark_factor = 1.0
        for level in dn_cfg["levels"]:
            if (mean_green is not None and float(mean_green) < level["threshold_green"]) or under_pct > level["threshold_under"]:
                dark_factor = level["factor"]
                break

        final_luma = min(dn_cfg["max_luma"], round(base_luma * dark_factor))
        final_chroma = min(dn_cfg["max_chroma"], round(base_chroma * dark_factor))

        # Ldetail scales up with delta_ev: heavier denoising gets
        # proportionally more detail-recovery to counteract it, instead of a
        # flat low value that smeared texture at every ISO equally.
        ldetail_ratio = min(1.0, delta_ev / dn_cfg["control_points"][-1][0])
        final_ldetail = round(dn_cfg["ldetail_base"] + ldetail_ratio * (dn_cfg["ldetail_max"] - dn_cfg["ldetail_base"]))

        use_median = delta_ev > dn_cfg["median_delta_ev_threshold"]

        content = modify_pp3_value(content, "[Directional Pyramid Denoising]", "Enabled", "true")
        content = modify_pp3_value(content, "[Directional Pyramid Denoising]", "SMethod", "shalbi")
        content = modify_pp3_value(content, "[Directional Pyramid Denoising]", "Median", "true" if use_median else "false")
        content = modify_pp3_value(content, "[Directional Pyramid Denoising]", "Ldetail", str(final_ldetail))
        content = modify_pp3_value(content, "[Directional Pyramid Denoising]", "Luma", str(final_luma))
        content = modify_pp3_value(content, "[Directional Pyramid Denoising]", "Chroma", str(final_chroma))

        applied["denoise_enabled"] = True
        applied["denoise_luma"] = final_luma
        applied["denoise_chroma"] = final_chroma
        applied["denoise_ldetail"] = final_ldetail
        applied["denoise_median"] = use_median

    # Shadow lift for genuinely backlit/high-contrast scenes only (see
    # CONFIG["shadows"] docstring). The section is written explicitly on
    # every frame — enabled with computed values, or disabled at 0 — so
    # nothing left over in the base template can leak into frames that
    # don't qualify.
    sh_cfg = CONFIG["shadows"]
    headroom_ratio = applied["headroom_ratio"]
    if headroom_ratio > sh_cfg["min_headroom_ratio"] and delta_ev <= sh_cfg["high_iso_dampen_delta_ev"]:
        lift_ratio = min(1.0, (headroom_ratio - sh_cfg["min_headroom_ratio"]) /
                          (sh_cfg["full_strength_ratio"] - sh_cfg["min_headroom_ratio"]))
        shadow_amount = round(sh_cfg["max_shadow_amount"] * lift_ratio)
        highlights_amount = round(sh_cfg["max_highlights_amount"] * lift_ratio)
    else:
        shadow_amount = 0
        highlights_amount = 0

    content = modify_pp3_value(content, "[Shadows & Highlights]", "Enabled", "true" if shadow_amount > 0 else "false")
    content = modify_pp3_value(content, "[Shadows & Highlights]", "Highlights", str(highlights_amount))
    content = modify_pp3_value(content, "[Shadows & Highlights]", "HighlightTonalWidth", str(sh_cfg["highlights_tonal_width"]))
    content = modify_pp3_value(content, "[Shadows & Highlights]", "Shadows", str(shadow_amount))
    content = modify_pp3_value(content, "[Shadows & Highlights]", "ShadowTonalWidth", str(sh_cfg["shadow_tonal_width"]))
    content = modify_pp3_value(content, "[Shadows & Highlights]", "Radius", str(sh_cfg["radius"]))
    content = modify_pp3_value(content, "[Shadows & Highlights]", "Lab", "false")

    if shadow_amount > 0:
        applied["shadow_lift_amount"] = shadow_amount
        applied["shadow_highlights_amount"] = highlights_amount

    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    selected_lens = determine_lens_profile(lens_model, templates_dir)
    if selected_lens:
        selected_lens_str = str(selected_lens)
        selected_lens_path = Path(selected_lens)
        if selected_lens_path.suffix.lower() == ".lcp":
            lcp_path = normalize_lcp_path(selected_lens_path.resolve())
            lcp_lens_name = lens_model or selected_lens_path.name
            content = modify_pp3_value(content, "[LensProfile]", "LcMode", "lcp")
            content = modify_pp3_value(content, "[LensProfile]", "LCPFile", lcp_path)
            content = modify_pp3_value(content, "[LensProfile]", "UseDistortion", "true")
            content = modify_pp3_value(content, "[LensProfile]", "UseVignette", "true")
            content = modify_pp3_value(content, "[LensProfile]", "UseCA", "true")
            content = modify_pp3_value(content, "[LensProfile]", "LFCameraMake", "Sony")
            content = modify_pp3_value(content, "[LensProfile]", "LFCameraModel", camera_model)
            content = modify_pp3_value(content, "[LensProfile]", "LFLens", lcp_lens_name)
            applied["lens_profile_applied"] = selected_lens_path.name
            applied["lens_camera_model"] = camera_model
        else:
            content = modify_pp3_value(content, "[LensProfile]", "LcMode", "lfmanual")
            content = modify_pp3_value(content, "[LensProfile]", "UseDistortion", "true")
            content = modify_pp3_value(content, "[LensProfile]", "UseVignette", "true")
            content = modify_pp3_value(content, "[LensProfile]", "UseCA", "true")
            content = modify_pp3_value(content, "[LensProfile]", "LFCameraMake", "Sony")
            content = modify_pp3_value(content, "[LensProfile]", "LFCameraModel", camera_model)
            content = modify_pp3_value(content, "[LensProfile]", "LFLens", selected_lens_str)
            applied["lens_profile_applied"] = selected_lens_str
            applied["lens_camera_model"] = camera_model
    else:
        content = modify_pp3_value(content, "[LensProfile]", "LcMode", "lfauto")
        applied["lens_profile_applied"] = "lfauto"

    # Chromatic aberration correction — was OFF everywhere in the base
    # template (RAW CA=false, CACorrection Red/Blue=0, LensProfile
    # UseCA=false, Defringing Enabled=false). Found via DSC01900: a hard
    # dark-structure/bright-sky edge showed a visible purple/blue fringe
    # after processing. The camera JPEG hides this by leaving that exact
    # edge crushed to black; our Shadow Lift + DRC + HL Recovery lift
    # detail there, which reveals lateral CA that was always physically
    # present in the raw data but never visible before. [RAW] CA=true runs
    # RT's automatic per-shot lateral CA detection directly on the raw
    # Bayer data — independent of lens profile matching, so it helps even
    # on frames with an unrecognized lens.
    content = modify_pp3_value(content, "[RAW]", "CA", "true")
        
    with open(output_pp3_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return applied

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 8: sys.exit(1)
    base_pp3_path = sys.argv[1]
    output_pp3_path = sys.argv[2]
    params = {
        "comp_val": sys.argv[3],
        "drc_val": sys.argv[4],
        "camera_model": sys.argv[5],
        "lens_model": sys.argv[6],
        "over_pct": sys.argv[7],
        "under_pct": sys.argv[8] if len(sys.argv) > 8 else 0.0,
        "iso": sys.argv[9] if len(sys.argv) > 9 else 0,
        "dr_ev": sys.argv[10] if len(sys.argv) > 10 else None,
        "mean_green": sys.argv[11] if len(sys.argv) > 11 else None,
    }
    optimize_pp3(base_pp3_path, output_pp3_path, params)
