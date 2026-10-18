import subprocess
import sys
import os
import shutil
import argparse
import csv
from pathlib import Path
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

# Import modular functions instead of using subprocess
from analyze_raw import get_exif_data, get_exposure_stats_auto
from optimize_profile import optimize_pp3, CONFIG
from pdr_curve import dr_headroom_ratio, pdr_delta_ev

# --- Default Configuration ---
RAWTHERAPEE_BIN = os.environ.get("RAWTHERAPEE_BIN", "/usr/local/bin/rawtherapee-cli")
DEFAULT_RAW_DIR = "/Users/realice/Documents/Raw"
DEFAULT_OUTPUT_DIR = "/Users/realice/Documents/Raw/Processed"
#BASE_PROFILE_NAME = "OpenClaw_Base.pp3"
#BASE_PROFILE_NAME = "OpenClaw_Base_WB.pp3"
BASE_PROFILE_NAME = "OpenClaw_a6100_Adobe.pp3"
#BASE_PROFILE_NAME = "OpenClaw_a6100_ViVid.pp3"
MAX_WORKERS = os.cpu_count() # Use all available cores

def analyze_file(file_path):
    """Directly calls the analysis function from the module."""
    try:
        stats = get_exposure_stats_auto(file_path)
        exif = get_exif_data(file_path)
        return {"exif": exif, "stats": stats}
    except Exception as e:
        print(f"❌ Analysis failed for {file_path}: {e}")
        return None

def optimize_profile(file_path, file_id, analysis_stats, camera_model, lens_model, iso, keep=False, bw=False):
    """Determines the best settings and creates a .pp3 profile via module call."""
    current_dir = Path(__file__).parent
    base_profile = current_dir.parent / "templates" / BASE_PROFILE_NAME
    
    if keep:
        out_profile = f"{file_path}.pp3"
    else:
        out_profile = f"/tmp/opt_{file_id}.pp3"
    
    over_pct = float(analysis_stats.get("overexposed_pct", 0.0))
    under_pct = float(analysis_stats.get("underexposed_pct", 0.0))
    dr_ev = analysis_stats.get("dynamic_range_ev")
    mean_green = analysis_stats.get("mean_green")
    estimated_shift_ev = analysis_stats.get("estimated_shift_ev")
    comp = "0.0"
    drc = "0"
    decision_values = {
        "exposure_compensation_ev": 0.0,
        "drc_enabled": False,
        "drc_amount": 0,
        "drc_dampened": False,
        "low_dr_contrast_enabled": False,
        "exposure_contrast": 0,
        "hl_recovery_enabled": False,
        "hl_recovery_method": "",
        "hl_recovery_hlth": "",
        "denoise_enabled": False,
        "denoise_luma": 0,
        "denoise_chroma": 0,
        "denoise_ldetail": 0,
        "denoise_median": False,
        "denoise_reason": "",
        "shadow_lift_amount": 0,
        "shadow_highlights_amount": 0,
        "headroom_ratio": 0.0,
        "drc_anchor": 0,
        "lens_profile_applied": "",
        "lens_camera_model": "",
    }

    if estimated_shift_ev is not None:
        shift = max(-1.2, min(0.9, float(estimated_shift_ev)))
        comp = f"{shift:.2f}"
    elif over_pct > 5.0:
        comp = "-1.5"
    elif over_pct > 1.0:
        comp = "-0.7"
    elif over_pct > 0.01:
        comp = "-0.5"
    elif under_pct > 70.0:
        comp = "0.70"
    elif under_pct > 50.0:
        comp = "0.50"
    elif under_pct > 30.0:
        comp = "0.30"
    elif under_pct > 15.0:
        comp = "0.15"
    decision_values["exposure_compensation_ev"] = float(comp)

    if dr_ev is not None:
        headroom_ratio = dr_headroom_ratio(dr_ev, iso)
        drc_cfg = CONFIG["drc"]
        if headroom_ratio > drc_cfg["high_headroom_ratio"]:
            drc = drc_cfg["high_dr_amount"]
        elif headroom_ratio > drc_cfg["mid_headroom_ratio"]:
            drc = drc_cfg["mid_dr_amount"]
        elif headroom_ratio > drc_cfg["low_headroom_ratio"]:
            drc = drc_cfg["low_dr_amount"]
        elif over_pct > 0.005:
            drc = drc_cfg["fallback_amount"]

        # High-ISO dampening, independent of the under_pct/shift dampening
        # below. headroom_ratio (and the dr_ev it's built from) is a
        # percentile-ratio measurement that cannot tell apart "genuinely
        # high scene contrast" (daytime backlit, e.g. DSC02160) from "an
        # isolated bright point against a near-black frame" (twilight/night
        # scenes, e.g. DSC01966/1972/1975) — confirmed empirically across
        # four different percentile-pair choices for computing dr_ev
        # (0.1/99.9, 1/99, 5/95, 10/90): the twilight files scored AS HIGH OR
        # HIGHER than the validated backlit reference on every single one, so
        # no threshold on this metric alone can separate them. Rather than
        # chase a fix for a structurally broken metric, this reuses the same
        # ISO/delta_ev threshold already validated for Shadow Lift's own
        # high-ISO dampening (CONFIG["shadows"]) — twilight/night shots are
        # reliably at meaningfully higher ISO than the daytime backlit case.
        delta_ev_for_drc = pdr_delta_ev(iso)
        if delta_ev_for_drc > CONFIG["shadows"]["high_iso_dampen_delta_ev"] and float(drc) > 0:
            drc = "0"
            decision_values["drc_dampened"] = True

        # Dampen DRC when the shot is already getting a large positive exposure
        # push over a lot of underexposed area — stacking strong DRC on top of
        # an already-lifted shadow compounds into a flat, muddy image.
        #
        # First pass stepped down by one tier — not enough (4/5 dampened
        # cases went to fully disabled or near-zero). Second pass went
        # straight to 0 for all dampened cases — but two independent manual
        # calibration rounds then showed an ISO split within the dampened
        # set: at ISO >= full_disable_iso (DSC02478 @6400, DSC02479 @2000)
        # the user left DRC fully off both times; at lower ISO (DSC02511
        # @500, DSC02512 @400) they both times re-enabled a small residual
        # amount (5-10) rather than leaving it at 0. Full zero was
        # overshooting specifically at the lower end of the dampened range.
        damp_cfg = CONFIG["drc_dampening"]
        if (under_pct > damp_cfg["under_pct_trigger"]
                and estimated_shift_ev is not None
                and float(estimated_shift_ev) > damp_cfg["positive_shift_trigger"]
                and float(drc) > 0):
            if iso >= damp_cfg["full_disable_iso"]:
                drc = "0"
            else:
                drc = damp_cfg["residual_amount"]
            decision_values["drc_dampened"] = True
    elif over_pct > 5.0:
        drc = "80"
    elif over_pct > 1.0:
        drc = "30"
    elif over_pct > 0.01:
        drc = "15"
    elif under_pct > 70.0:
        drc = "30"
    elif under_pct > 50.0:
        drc = "10"
    decision_values["drc_enabled"] = float(drc) > 0
    decision_values["drc_amount"] = int(float(drc))

    decisions = [f"Exposure Compensation={comp} EV"]
    drc_label = 'on, Amount=' + drc if float(drc) > 0 else 'off'
    if decision_values["drc_dampened"]:
        drc_label += " (dampened: high-ISO or high under_pct+shift)"
    decisions.append(f"Dynamic Range Compression={drc_label}")

    if over_pct > 0.005:
        hl_threshold = "0.90" if over_pct > 0.5 else "0.85"
        decision_values["hl_recovery_enabled"] = True
        decision_values["hl_recovery_method"] = "Coloropp"
        decision_values["hl_recovery_hlth"] = float(hl_threshold)
        decisions.append(f"Highlight Recovery=on, Method=Coloropp, Hlth={hl_threshold}")
    else:
        decisions.append("Highlight Recovery=base profile")

    params = {
        "comp_val": comp,
        "drc_val": drc,
        "camera_model": camera_model,
        "lens_model": lens_model,
        "over_pct": over_pct,
        "under_pct": under_pct,
        "iso": iso,
        "dr_ev": dr_ev,
        "mean_green": mean_green,
        "black_and_white": bw,
    }
    # optimize_pp3() is the single source of truth for denoise Luma/Chroma,
    # Shadow Lift, and Contrast — it returns exactly what it wrote to the
    # .pp3, so the CSV report reflects reality instead of a separately-
    # derived guess that can drift out of sync (previous version always
    # logged 0/0 here).
    applied = optimize_pp3(base_profile, out_profile, params)

    if applied["contrast"] > 0:
        decision_values["exposure_contrast"] = applied["contrast"]
        decision_values["low_dr_contrast_enabled"] = float(drc) == 0
        reason = "DRC engaged" if float(drc) > 0 else "Low-DR scene"
        decisions.append(f"Exposure Contrast={applied['contrast']} ({reason})")

    if applied["denoise_enabled"]:
        decision_values["denoise_enabled"] = True
        decision_values["denoise_luma"] = applied["denoise_luma"]
        decision_values["denoise_chroma"] = applied["denoise_chroma"]
        decision_values["denoise_ldetail"] = applied["denoise_ldetail"]
        decision_values["denoise_median"] = applied["denoise_median"]
        median_note = ", Median=on" if applied["denoise_median"] else ""
        decisions.append(f"Denoising=on, Luma={applied['denoise_luma']}, Chroma={applied['denoise_chroma']}, Ldetail={applied['denoise_ldetail']}{median_note} (\u0394PDR={applied['delta_ev']:.2f}EV vs base ISO)")
    else:
        decision_values["denoise_reason"] = f"ISO close to base (\u0394PDR={applied['delta_ev']:.2f}EV)"
        decisions.append("Denoising=base profile")

    decision_values["headroom_ratio"] = round(applied["headroom_ratio"], 2)
    if applied["shadow_lift_amount"] > 0:
        decision_values["shadow_lift_amount"] = applied["shadow_lift_amount"]
        decision_values["shadow_highlights_amount"] = applied["shadow_highlights_amount"]
        decisions.append(f"Shadow Lift=on, Shadows={applied['shadow_lift_amount']}, Highlights={applied['shadow_highlights_amount']} (headroom_ratio={applied['headroom_ratio']:.2f})")
    else:
        decisions.append(f"Shadow Lift=off (headroom_ratio={applied['headroom_ratio']:.2f})")

    decision_values["drc_anchor"] = applied["drc_anchor"]
    decision_values["lens_profile_applied"] = applied["lens_profile_applied"]
    decision_values["lens_camera_model"] = applied["lens_camera_model"]
    if applied["drc_anchor"] > 0:
        decisions.append(f"DRC Anchor={applied['drc_anchor']}")
    decisions.append(f"Lens Profile={applied['lens_profile_applied']}")

    return out_profile, decisions, decision_values

def process_raw(file_path, output_dir, keep=False, bw=False):
    """The full pipeline for one file. Now designed to be run in a process pool."""
    file_id = Path(file_path).stem
    print(f"📸 Processing {file_id}...")
    
    report: dict[str, object] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "file": str(file_path),
        "file_id": file_id,
        "status": "failed",
        "reason": "",
        "output_file": "",
        "output_profile": "",
        "profile": "",
        "analysis_method": "",
        "overexposed_pct": "",
        "underexposed_pct": "",
        "sensor_clip_percent": "",
        "dynamic_range_ev": "",
        "mean_green": "",
        "target_green": "",
        "estimated_shift_ev": "",
        "percentile_low_0_1": "",
        "iso": "",
        "camera": "",
        "lens": "",
        "decisions_summary": "",
        "exposure_compensation_ev": "",
        "drc_enabled": "",
        "drc_amount": "",
        "drc_dampened": "",
        "low_dr_contrast_enabled": "",
        "exposure_contrast": "",
        "hl_recovery_enabled": "",
        "hl_recovery_method": "",
        "hl_recovery_hlth": "",
        "denoise_enabled": "",
        "denoise_luma": "",
        "denoise_chroma": "",
        "denoise_ldetail": "",
        "denoise_median": "",
        "denoise_reason": "",
        "shadow_lift_amount": "",
        "shadow_highlights_amount": "",
        "headroom_ratio": "",
        "drc_anchor": "",
        "lens_profile_applied": "",
        "lens_camera_model": "",
    }
    
    analysis = analyze_file(file_path)
    if not analysis:
        report["reason"] = "analysis error"
        return report

    over = analysis['stats']['overexposed_pct']
    under = analysis['stats']['underexposed_pct']
    try:
        iso = int(analysis['exif'].get('ISO', 0))
    except (ValueError, TypeError):
        iso = 0
    camera = analysis['exif'].get('Model', 'ILCE-6100')
    lens = analysis['exif'].get('LensModel', 'Unknown Lens')
    stats = analysis["stats"]

    report.update({
        "analysis_method": stats.get("analysis_method", "unknown"),
        "overexposed_pct": over,
        "underexposed_pct": under,
        "sensor_clip_percent": stats.get("sensor_clip_percent", ""),
        "dynamic_range_ev": stats.get("dynamic_range_ev", ""),
        "mean_green": stats.get("mean_green", ""),
        "target_green": stats.get("target_green", ""),
        "estimated_shift_ev": stats.get("estimated_shift_ev", ""),
        "percentile_low_0_1": stats.get("percentile_low_0_1", ""),
        "iso": iso,
        "camera": camera,
        "lens": lens,
    })
    
    try:
        profile, decisions, decision_values = optimize_profile(
            file_path, file_id, stats, camera, lens, iso, keep=keep, bw=bw
        )
    except Exception as e:
        report["reason"] = f"profile optimization error: {e}"
        return report

    report["profile"] = profile
    report["decisions_summary"] = " | ".join(decisions)
    report.update(decision_values)
    
    os.makedirs(output_dir, exist_ok=True)
    output_name = f"{file_id}_BW" if bw else file_id
    out_path = Path(output_dir) / f"{output_name}.jpg"
    if out_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(output_dir) / f"{output_name}_v{timestamp}.jpg"
    
    temp_out_dir = Path(f"/tmp/rt_out_{file_id}_{datetime.now().strftime('%S')}")
    temp_out_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # -O (not -o) additionally copies the .pp3 actually used into the
        # output folder, matching it to the output image name — only when
        # --keep is passed, mirroring the existing sidecar-next-to-the-ARW
        # behavior below rather than always cluttering the output directory.
        rt_output_flag = '-O' if keep else '-o'
        process = subprocess.run([RAWTHERAPEE_BIN, rt_output_flag, str(temp_out_dir), '-p', profile, '-j95','-js3', '-b8', '-c', str(file_path)], 
                                capture_output=True, text=True)
        
        if process.returncode != 0:
            report["reason"] = process.stderr.strip() or "rawtherapee returned non-zero exit code"
            return report

        generated_files = list(temp_out_dir.glob("*.jpg"))
        if not generated_files:
            report["reason"] = process.stdout.strip() or "no JPG generated"
            return report

        # shutil.move() falls back to copy+delete automatically when src/dst
        # are on different filesystems (e.g. /tmp on internal disk vs an
        # external USB output drive) — plain os.rename() raises EXDEV there.
        shutil.move(str(generated_files[0]), str(out_path))
        report["status"] = "OK"
        report["reason"] = ""
        report["output_file"] = str(out_path)

        if keep:
            generated_pp3s = list(temp_out_dir.glob("*.pp3"))
            if generated_pp3s:
                out_pp3_path = out_path.with_suffix(".pp3")
                shutil.move(str(generated_pp3s[0]), str(out_pp3_path))
                report["output_profile"] = str(out_pp3_path)
        
    finally:
        if not keep and os.path.exists(profile):
            os.remove(profile)
            report["profile"] = ""
        subprocess.run(['rm', '-rf', str(temp_out_dir)])
        
    return report

def write_report(report_path, rows):
    if not rows:
        return
    fieldnames = [
        "file_id", "timestamp", "status", "reason",
        "analysis_method", "overexposed_pct", "underexposed_pct", "sensor_clip_percent",
        "dynamic_range_ev", "mean_green", "target_green", "estimated_shift_ev", "percentile_low_0_1", "iso", "camera", "lens",
        "exposure_compensation_ev", "drc_enabled", "drc_amount", "drc_dampened",
        "low_dr_contrast_enabled", "exposure_contrast", "hl_recovery_enabled",
        "hl_recovery_method", "hl_recovery_hlth", "denoise_enabled", "denoise_luma",
        "denoise_chroma", "denoise_ldetail", "denoise_median", "denoise_reason",
        "shadow_lift_amount", "shadow_highlights_amount", "headroom_ratio",
        "drc_anchor", "lens_profile_applied", "lens_camera_model",
        "decisions_summary", "file", "output_file", "output_profile",
        "profile",
    ]
    with open(report_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def main():
    parser = argparse.ArgumentParser(description="Raw Photo Optimizer Pipeline")
    parser.add_argument("input_dir", nargs="?", default=DEFAULT_RAW_DIR, help="Input directory with .ARW files")
    parser.add_argument("output_dir", nargs="?", default=DEFAULT_OUTPUT_DIR, help="Output directory for JPGs")
    parser.add_argument("--keep", action="store_true", help="Keep generated .pp3 profiles in the input directory")
    parser.add_argument("--log", action="store_true", help="Write a CSV processing report to the output directory")
    parser.add_argument("--BW", action="store_true", help="Process photos in black and white")
    
    args = parser.parse_args()
    raw_dir = args.input_dir
    output_dir = args.output_dir
    keep = args.keep
    log_enabled = args.log
    bw = args.BW
        
    print(f"📂 Input Directory: {raw_dir}")
    print(f"📂 Output Directory: {output_dir}")
    print(f"💾 Keep Profiles: {'Yes' if keep else 'No'}")
    print(f"🧾 CSV Log: {'Yes' if log_enabled else 'No'}")
    print(f"⚫ Black & White: {'Yes' if bw else 'No'}")
    
    raw_path = Path(raw_dir)
    if not raw_path.exists() or not raw_path.is_dir():
        print(f"❌ Error: Input directory {raw_dir} does not exist.")
        sys.exit(1)

    raw_files = sorted([f for f in raw_path.glob("*.ARW") if not f.name.startswith('.')])
    if not raw_files:
        print("No ARW files found.")
        return

    print(f"🚀 Found {len(raw_files)} files. Starting Parallel ULTIMATE-SENSITIVE PRO pipeline...")
    print(f"⚙️ Using {MAX_WORKERS} worker processes.")

    report_rows = []
    
    # Parallel execution using ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Map process_raw to all raw_files
        future_to_file = {
            executor.submit(process_raw, raw_file, output_dir, keep=keep, bw=bw): raw_file
            for raw_file in raw_files
        }
        
        for future in as_completed(future_to_file):
            raw_file = future_to_file[future]
            try:
                result = future.result()
                report_rows.append(result)
                print(f"✅ Finished {raw_file.name}")
            except Exception as e:
                print(f"❌ Critical failure on {raw_file.name}: {e}")
                report_rows.append({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "file": str(raw_file),
                    "file_id": raw_file.stem,
                    "status": "failed",
                    "reason": f"critical failure: {e}",
                })

    if log_enabled:
        os.makedirs(output_dir, exist_ok=True)
        report_name = f"_report {datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        report_path = Path(output_dir) / report_name
        
        # Sort report rows by file_id for consistency
        report_rows.sort(key=lambda x: x.get('file_id', ''))
        
        write_report(report_path, report_rows)
        print(f"🧾 Report saved: {report_path}")

if __name__ == "__main__":
    main()
