import subprocess
import json
import math
from pathlib import Path
import numpy as np
import rawpy

def get_exif_data(file_path):
    """Extracts basic EXIF metadata using exiftool."""
    try:
        result = subprocess.run(
            [
                'exiftool', '-j',
                '-Model', '-ISO', '-Aperture', '-ExposureTime', '-LensID', '-LensModel',
                str(file_path)
            ],
            capture_output=True, text=True, check=True
        )
        data = json.loads(result.stdout)[0]
        return data
    except Exception as e:
        print(f"Error extracting EXIF: {e}")
        return {}

def get_sensor_exposure_stats(file_path):
    """Analyze linear sensor data before RawTherapee tone curves/WB."""
    with rawpy.imread(str(file_path)) as raw:
        # 1. Extract white and black levels
        black_levels = np.array(raw.black_level_per_channel, dtype=np.float32)
        white = float(raw.white_level)

        # 2. Use visible image area to exclude sensor borders
        raw_image = raw.raw_image_visible.astype(np.float32)

        # 3. Per-channel black level subtraction (Bayer pattern 2x2)
        for y_offset in range(2):
            for x_offset in range(2):
                b_level = black_levels[raw.raw_color(y_offset, x_offset)]
                raw_image[y_offset::2, x_offset::2] -= b_level

        # Use average black level for consistency across channels
        avg_black = np.mean(black_levels)
        usable_range = max(white - avg_black, 1.0)

        # Normalize to [0.0, 1.0]
        raw_norm = raw_image / usable_range
        raw_norm = np.clip(raw_norm, 0.0, 1.0)

        # 4. Clipping calculation
        clip_threshold = 0.98
        clipped_pixels = np.count_nonzero(raw_norm >= clip_threshold)
        clip_percent = float(clipped_pixels / raw_norm.size * 100.0)

        # 5. Dynamic Range via percentiles
        p_low = float(np.percentile(raw_norm, 0.1))
        p_high = float(np.percentile(raw_norm, 99.9))
        eps = 1e-6
        dynamic_range_ev = float(math.log2((p_high + eps) / (p_low + eps)))

        # 6. Green channel analysis (G1 and G2)
        green_mask = np.zeros(raw_norm.shape, dtype=bool)
        for y in range(2):
            for x in range(2):
                color_char = chr(raw.color_desc[raw.raw_color(y, x)])
                if color_char == 'G':
                    green_mask[y::2, x::2] = True

        green_values = raw_norm[green_mask]
        mean_green = float(np.mean(green_values))

        # 7. Smooth target progression
        if mean_green < 0.10:
            target_green = 0.04 + (mean_green / 0.10) * (0.15 - 0.04)
        else:
            target_green = 0.15

        under_pct = max(0.0, min(100.0, (target_green - mean_green) / target_green * 100.0))
        exposure_shift_ev = float(math.log2(target_green / max(mean_green, 0.001)))

        return {
            "analysis_method": "raw_sensor",
            "overexposed_pct": clip_percent,
            "underexposed_pct": under_pct,
            "sensor_clip_percent": clip_percent,
            "dynamic_range_ev": dynamic_range_ev,
            "mean_green": mean_green,
            "target_green": target_green,
            "estimated_shift_ev": exposure_shift_ev,
            "percentile_low_0_1": p_low,
            "percentile_high_99_9": p_high,
        }

def get_exposure_stats_auto(file_path):
    """High-level entry point with fallback to preview analysis."""
    try:
        return get_sensor_exposure_stats(file_path)
    except Exception as e:
        print(f"Sensor RAW analysis failed, falling back: {e}")
        return {"overexposed_pct": 0.0, "underexposed_pct": 0.0, "analysis_method": "fallback"}

if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path
    if len(sys.argv) < 2: sys.exit(1)
    file_path = Path(sys.argv[1])
    exif = get_exif_data(file_path)
    stats = get_exposure_stats_auto(file_path)
    lens = exif.get('LensID') or exif.get('LensModel', 'Unknown Lens')
    result = {
        "file": str(file_path),
        "exif": {"ISO": exif.get("ISO"), "Aperture": exif.get("Aperture"), "ExposureTime": exif.get("ExposureTime"), "Model": exif.get("Model"), "LensModel": lens},
        "stats": stats
    }
    print(json.dumps(result, indent=2))
