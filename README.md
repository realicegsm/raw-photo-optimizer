# raw-photo-optimizer

Automated RAW development pipeline for Sony A6100 (`.ARW`) files rendered to JPEG through RawTherapee CLI, using real sensor behavior and measured PDR thresholds instead of fixed hardcoded assumptions.

This project combines:

- sensor-level RAW analysis through `rawpy`
- scene exposure and dynamic-range estimation
- ISO-aware PDR ceiling evaluation
- per-file `.pp3` profile generation
- batch RAW processing with CSV logging and optional profile retention

## What the project does

- reads EXIF data: ISO, camera model, lens model
- analyzes raw sensor data before tone curves and WB are applied
- calculates `mean_green`, `dynamic_range_ev`, `under_pct`, `over_pct`, and `estimated_shift_ev`
- chooses development parameters based on `headroom_ratio` and `pdr_delta_ev`
- generates a `.pp3` profile for each file
- runs batch processing via RawTherapee
- writes CSV reports with applied decisions and output paths

## Project structure

```text
raw-photo-optimizer/
├── README.md
├── README.ru.md
├── SKILL.md
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
├── docs/
│   ├── architecture.md
│   ├── architecture.ru.md
│   ├── calibration.md
│   ├── calibration.ru.md
│   ├── troubleshooting.md
│   └── troubleshooting.ru.md
├── scripts/
│   ├── analyze_raw.py
│   ├── optimize_profile.py
│   ├── pdr_curve.py
│   └── process_raw.py
├── templates/
│   ├── OpenClaw_a6100_Adobe.pp3
│   ├── OpenClaw_Base.pp3
│   ├── OpenClaw_Base_WB.pp3
│   ├── OpenClaw_a6100_ViVid.pp3
│   ├── Sony ILCE-6100A/
│   ├── Sony ILCE-6100A Adobe Standard.dcp
│   ├── TTARTISAN AF 50mm F1.8 Neo.lcp
│   ├── DSC01770.result.pp3
│   ├── DSC02142.result.pp3
│   └── *.backup.pp3
├── tests/
│   ├── fixtures/
│   └── test_profile.py
├── examples/
│   ├── sample_raw/
│   └── sample_output/
├── test-output/
│   └── ...
├── release/
│   └── raw-photo-optimizer/
│       ├── SKILL.md
│       ├── scripts/
│       │   ├── analyze_raw.py
│       │   ├── optimize_profile.py
│       │   ├── pdr_curve.py
│       │   └── process_raw.py
│       └── templates/
│           ├── OpenClaw_a6100_Adobe.pp3
│           ├── Sony ILCE-6100A Adobe Standard.dcp
│           └── TTARTISAN AF 50mm F1.8 Neo.lcp
└── .
```

## Development model

The project keeps a consistent layout for both development and release:

- `scripts/` — active development logic
- `release/raw-photo-optimizer/` — clean exportable skill bundle
- `templates/` — base `.pp3` templates and camera profile assets
- `docs/` — architecture, calibration, and troubleshooting guides

This keeps the development workflow intact while also preserving a minimal exportable package for publication and agent use.

## Requirements

Before running the pipeline, ensure the following are available:

- Python 3.8+
- `numpy`
- `rawpy`
- `exiftool` in `PATH`
- `rawtherapee-cli`

Install dependencies:

```bash
pip install numpy rawpy
```

## Usage

Process a full RAW directory:

```bash
python3 scripts/process_raw.py /path/to/raw /path/to/output
```

Process a single RAW file:

```bash
python3 scripts/process_raw.py /path/to/raw/DSC01900.ARW /path/to/output
```

Save the generated `.pp3` file and write a CSV report:

```bash
python3 scripts/process_raw.py /path/to/raw /path/to/output --keep --log
```

Choose one black-and-white conversion mode:

```bash
python3 scripts/process_raw.py /path/to/raw /path/to/output -BW       # channel mixer
python3 scripts/process_raw.py /path/to/raw /path/to/output --BW_AVG  # RGB-relative desaturation
python3 scripts/process_raw.py /path/to/raw /path/to/output --BW_LAB  # Luminance Curve chromaticity adjustment
```

Analyze a single RAW file:

```bash
python3 scripts/analyze_raw.py DSC01900.ARW
```

## Core modules

- `scripts/analyze_raw.py` — EXIF extraction and raw sensor analysis
- `scripts/pdr_curve.py` — PDR curve and ISO interpolation logic
- `scripts/optimize_profile.py` — profile generation and `.pp3` writing logic
- `scripts/process_raw.py` — orchestration, batch rendering, CSV logging

## Decision logic

The pipeline does not rely on magic fixed thresholds alone. It uses measured sensor characteristics:

- `mean_green` — global scene exposure estimate
- `dynamic_range_ev` — scene dynamic range
- `headroom_ratio` — scene DR relative to the sensor ceiling at the current ISO
- `pdr_delta_ev` — loss of PDR relative to base ISO

These values drive:

- exposure compensation
- DRC amount, anchor, and contrast
- highlight recovery
- shadow lift
- denoising
- lens correction and CA handling

## Release bundle

The release bundle is stored in:

```text
release/raw-photo-optimizer/
├── SKILL.md
├── scripts/
│   ├── analyze_raw.py
│   ├── optimize_profile.py
│   ├── pdr_curve.py
│   └── process_raw.py
└── templates/
    ├── OpenClaw_a6100_Adobe.pp3
    ├── Sony ILCE-6100A Adobe Standard.dcp
    └── TTARTISAN AF 50mm F1.8 Neo.lcp
```

This structure is intended for publishing the skill bundle without local debris, temporary outputs, or development artifacts.

## Documentation

- [docs/architecture.md](docs/architecture.md)
- [docs/calibration.md](docs/calibration.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
- [README.ru.md](README.ru.md)
- [docs/architecture.ru.md](docs/architecture.ru.md)
- [docs/calibration.ru.md](docs/calibration.ru.md)
- [docs/troubleshooting.ru.md](docs/troubleshooting.ru.md)

## Important note

The project is tuned for Sony A6100 and RawTherapee-based workflows. It is designed as a controlled but automated RAW processing pipeline, preserving the development workflow while also supporting an exportable skill package for publication.
