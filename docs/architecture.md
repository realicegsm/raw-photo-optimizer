# Project architecture

## 1. System goal

The `raw-photo-optimizer` project is designed for batch processing of Sony RAW (`.ARW`) files into JPEG using RawTherapee CLI, with development parameters chosen from real sensor data rather than fixed hardcoded thresholds.

Each frame follows this flow:

1. EXIF extraction
2. raw sensor analysis
3. dynamic range and exposure estimation
4. development parameter selection
5. `.pp3` profile generation
6. render through RawTherapee
7. CSV audit log generation

---

## 2. System components

### 2.1 `scripts/analyze_raw.py`

Handles analysis of one RAW file before tone curves and white balance are applied. Its core purpose is to compute scene and sensor characteristics:

- ISO
- camera model
- lens model
- `mean_green`
- `under_pct` and `over_pct`
- `dynamic_range_ev`
- `estimated_shift_ev`
- clipping ratio and sensor overflow estimate

This module uses:

- `exiftool` for EXIF extraction
- `rawpy` for reading linear sensor data
- `numpy` for pixel statistics and calculations

### 2.2 `scripts/pdr_curve.py`

Contains the measured PDR curve for the Sony α6100 and helper functions for:

- `sensor_pdr_ceiling(iso)`
- `pdr_delta_ev(iso)`
- `dr_headroom_ratio(dr_ev, iso)`
- `interp_control_points(points, x)`

This module is central to why the project works with real sensor ceilings instead of arbitrary fixed thresholds.

### 2.3 `scripts/optimize_profile.py`

Contains the `CONFIG` settings and the logic for writing parameters into a RawTherapee `.pp3` profile.

Its main responsibilities are:

- deriving per-frame profile parameters
- adjusting INI sections in `.pp3`
- selecting the correct lens profile
- writing `InputProfile` with the correct path to the `.dcp` file
- returning an `applied` dictionary containing the values actually written

This is the engine that turns computed decisions into a final profile file.

### 2.4 `scripts/process_raw.py`

This is the entry point and orchestrator for the pipeline.

It performs:

- enumerating RAW files in a directory
- calling analysis for each frame
- making decisions for exposure, DRC, denoise, and lens handling
- generating a temporary or retained `.pp3`
- launching `rawtherapee-cli`
- exporting JPEG outputs
- writing CSV reports

It also contains parallel processing logic based on `ProcessPoolExecutor`.

---

## 3. Main runtime flow

```text
RAW file (.ARW)
    │
    ├── EXIF: ISO / Camera / Lens
    ├── sensor analysis: rawpy + numpy
    │      ├── mean_green
    │      ├── under_pct
    │      ├── over_pct
    │      ├── dynamic_range_ev
    │      └── estimated_shift_ev
    │
    ├── PDR model: pdr_curve.py
    │      ├── sensor_pdr_ceiling(iso)
    │      ├── pdr_delta_ev(iso)
    │      └── dr_headroom_ratio(...)
    │
    ├── decision layer
    │      ├── exposure compensation
    │      ├── DRC Amount
    │      ├── Highlight Recovery
    │      ├── noise reduction
    │      ├── shadow / highlight lift
    │      └── lens correction
    │
    ├── .pp3 generation
    │
    └── RawTherapee render -> JPEG + CSV
```

---

## 4. Architectural principles

### 4.1 Relative measurements instead of absolute thresholds

Instead of relying on rigid rules such as `dynamic_range_ev > 12`, the project uses the sensor's real measured ceiling at the current ISO. This matters because:

- ISO directly affects the real dynamic range of the sensor
- scene contrast must be compared with the sensor's true capacity, not a generic average
- on higher ISO values, noise and PDR loss matter much more than on lower ISO values

### 4.2 Physics and heuristics in one pipeline

The project keeps two categories of logic:

- mathematical logic: `pdr_curve.py`, `analyze_raw.py`
- heuristic decision logic: `process_raw.py`, `optimize_profile.py`

This allows adaptation to real-world scene variations without rewriting the full model.

### 4.3 The profile is a result, not a guess

Each `.pp3` is generated from:

- a base template
- computed values for this frame
- real values written back into the profile

That makes it possible to log exactly what was written and used in the final render.

---

## 5. Data and logging

Each processed file creates:

- a JPEG output
- a `.pp3` file, when `--keep` is enabled
- a CSV report containing applied parameters, decisions made, and output paths

This makes it possible to compare multiple runs and inspect which settings worked best for which scene.

---

## 6. Architectural limitations

The current project is tailored to:

- Sony α6100 / ILCE-6100
- RawTherapee builds that support the `FattalToneMapping` section
- lensfun profiles available in RawTherapee

As a result, it is a specialized RAW processing tool for one sensor family and a small set of known lenses, not a universal camera-agnostic RAW processor.

---

## 7. What has been implemented

The current version includes:

- batch RAW processing from a folder
- EXIF and raw sensor analysis
- PDR and headroom metric calculations
- automatic exposure and DRC decisions
- `.pp3` profile generation
- CSV report generation
- a clean release bundle at `release/raw-photo-optimizer/`

For methodology and tuning details, see [calibration.md](calibration.md).
