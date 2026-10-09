---
name: "raw-photo-optimizer"
description: "Automated Sony A6100 RAW (.ARW) development pipeline: sensor-level analysis, PDR-relative decisions (exposure, Fattal DRC, shadow lift, denoise), per-file RawTherapee .pp3 generation and parallel rendering with a full CSV audit log."
status: proposal
version: "v6"
date: "2026-10-09"
---

# Raw Photo Optimizer 📸

Automated pipeline for developing Sony RAW images (.ARW) with RawTherapee CLI. Each file goes through: **Analysis → Decision → Profile (.pp3) generation → Render → Audit log**. All decisions are derived from linear sensor data and the *measured* Photographic Dynamic Range (PDR) curve of the Sony A6100 sensor, not from fixed absolute thresholds.

## 🛠 Technical Stack
- **RawTherapee CLI** (`rawtherapee-cli`): rendering engine.
- **rawpy + NumPy**: linear sensor analysis (black-level subtraction per Bayer channel, percentiles, green-channel mean).
- **ExifTool**: ISO, camera model, lens model.
- **PDR curve** (`scripts/pdr_curve.py`): measured PhotonsToPhotos data for the Sony A6100, interpolated in log2(ISO).

ImageMagick is **not** required (the old preview-based fallback no longer exists; if sensor analysis fails the file is processed with neutral stats).

## ⚙️ How decisions are made
Core quantities (all computed in `pdr_curve.py` / `analyze_raw.py`):
- `mean_green`, `under_pct`, `estimated_shift_ev` — exposure analysis against a smooth target (0.04 → 0.15).
- `dynamic_range_ev` — `log2(p99.9 / p0.1)` of normalized sensor values.
- `delta_ev` — PDR lost versus base ISO (drives denoise and high-ISO dampening).
- `headroom_ratio` — measured scene DR ÷ sensor PDR ceiling at the shot's ISO (drives DRC and shadow lift).

Resulting settings (all tunable in `CONFIG` inside `optimize_profile.py`):
- **Exposure Compensation**: `estimated_shift_ev`, clamped to [-1.2, +0.9] EV.
- **Dynamic Range Compression** (RawTherapee section `[FattalToneMapping]`): `Amount` tiers 25 / 15 / 6 by `headroom_ratio` (0.92 / 0.80 / 0.65), `Anchor=85`. `Threshold` is deliberately left at RawTherapee's default.
- **Contrast**: +10 whenever DRC is active (also for flat scenes with `dr_ev < 6`).
- **DRC dampening**: set to 0 when `delta_ev > 3.0` (high ISO); when `under_pct > 30%` and exposure shift `> +0.4 EV` → 0 at ISO ≥ 2000, residual `Amount=8` below.
- **Shadow Lift** (`[Shadows & Highlights]`): ramps from `headroom_ratio` 1.15 to 1.6 up to Shadows=33 / Highlights=24 (narrow tonal widths 30/70); disabled when `delta_ev > 3.0`. The section is written explicitly for every file.
- **Highlight Recovery**: enabled when clipping > 0.005% (Hlth 0.85, or 0.90 above 0.5%).
- **Noise reduction**: continuous ramp by `delta_ev` (Luma ≤ 35, Chroma ≤ 50), ×1.2–1.5 for dark scenes, `Ldetail` 45→65, `Median` only above `delta_ev` 6.0.
- **Lens correction**: Sony 16-50mm PZ and 55-210mm recognised → lensfun manual profile with distortion, vignetting and CA; otherwise `lfauto`. `[RAW] CA=true` always.
- **Colour**: Adobe Standard DCP for the A6100, path resolved dynamically relative to `templates/`.

## 📋 User Request Template
To trigger this skill, the user should provide:
- **Skill to use**: `raw-photo-optimizer`
- **Input Directory**: `[Path to folder with .ARW files]`
- **Output Directory**: `[Path to save processed JPGs]`
- **Task**: "Run RAW optimization pipeline using the raw-photo-optimizer skill" (optionally add `--keep` to preserve profiles or `--log` for a detailed CSV report).

## 🚀 Execution Guide for Agents
**CRITICAL: EXECUTION METHOD**
The scripts are NOT standalone executables. They MUST be executed via the Python 3 interpreter. Do not attempt to use `chmod +x`.

1. **Dependency Check**: verify that `rawtherapee-cli` and `exiftool` are installed, and that Python has `rawpy` and `numpy`. The RawTherapee binary path is set in `scripts/process_raw.py` (`RAWTHERAPEE_BIN`, default `/usr/local/bin/rawtherapee-cli`).
2. **Command Execution**:
   `python3 scripts/process_raw.py [input_dir] [output_dir]`

   Preserve generated profiles for analysis:
   `python3 scripts/process_raw.py [input_dir] [output_dir] --keep`

   Write a detailed CSV report into the output directory:
   `python3 scripts/process_raw.py [input_dir] [output_dir] --log`

3. **Defaults**: if directories are not specified, the script falls back to `DEFAULT_RAW_DIR` / `DEFAULT_OUTPUT_DIR` defined at the top of `process_raw.py`.

## 📂 Tooling Architecture
- `scripts/pdr_curve.py`: PDR reference data, `sensor_pdr_ceiling`, `pdr_delta_ev`, `dr_headroom_ratio`, interpolation helper.
- `scripts/analyze_raw.py`: EXIF extraction and sensor-level exposure statistics.
- `scripts/optimize_profile.py`: `CONFIG` with all calibration constants; generates the per-file `.pp3` and returns the exact values it applied.
- `scripts/process_raw.py`: orchestrator — parallel rendering (`ProcessPoolExecutor`), decision logic for exposure/DRC, CSV audit log.
- `templates/`: base `.pp3` profile and the Adobe Standard `.dcp` colour file.

## ⚠️ Profile Management
- **Default mode**: profiles are ephemeral — created in `/tmp`, used for the render, deleted afterwards.
- **Keep mode (`--keep`)**: two copies are preserved:
  - the *input* profile as `<filename>.ARW.pp3` next to the RAW (what the pipeline generated; overwritten on every `--keep` run);
  - the *applied* profile as `<output>.pp3` next to the output JPG, copied by RawTherapee itself (`-O`) — includes RawTherapee's own defaults for unset keys. Diffing the two reveals parameters silently ignored after RawTherapee renames sections or keys.

## 🧾 CSV Report (`--log`)
One row per file: raw statistics (`dynamic_range_ev`, `mean_green`, `headroom_ratio`, `percentile_low_0_1`…), every applied value (`exposure_compensation_ev`, `drc_amount`, `drc_anchor`, `drc_dampened`, `exposure_contrast`, `denoise_*`, `shadow_lift_*`, `lens_profile_applied`…), a human-readable `decisions_summary` and output paths. Values are read back from what was actually written to the profile, so the log matches the render.

## ⚠️ Known Limitations
- Calibrated for one sensor (A6100) and two lenses; thresholds come from a small manually-graded sample.
- Global statistics cannot distinguish intentionally dark scenes (twilight/night) from underexposed ones, or front-lit from back-lit scenes; such frames may need manual correction.
- White balance and `Brightness` are never adjusted automatically.
