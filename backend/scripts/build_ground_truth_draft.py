"""Build a first-draft ground-truth CSV from the extraction pipeline's own output.

There is no ground truth yet, so there is nothing to compare the pipeline
against. This script does not create ground truth -- it creates a *draft* to
edit into ground truth: it runs every PDF in a directory through OCR +
extraction (same as compare_home_reports.py) and writes one row per
(report, system) with the pipeline's own age/condition/findings, pre-filled so
there is something to correct rather than 90-odd empty cells to fill by hand.

Every value in the output still needs checking against the actual PDF -- the
whole reason this project extracts with confidence scores is that the model
gets things wrong sometimes. Open the CSV, and for each row: fix the age and
condition if they're off, and add/remove findings so the list matches what the
report actually says. Once a row is checked, it's ground truth; until then, it
is only ever the model's guess about itself.

Each report's extraction result is cached under data/extraction_cache/ after a
successful run, so re-running this script (e.g. after tweaking the CSV
generation, or adding a 6th report) does not re-pay for OCR + Claude on
reports it already has a cached result for. Pass --refresh to force a re-run.

    python scripts/build_ground_truth_draft.py [reports_dir] [-o output.csv]

reports_dir defaults to ../tests-reports, output defaults to
../data/ground_truth.csv. Requires the same DOCAI_* and
GOOGLE_APPLICATION_CREDENTIALS / ANTHROPIC_API_KEY configuration as
extract_home_inspection.py -- see that script's docstring. Refuses to
overwrite an existing output file unless --force is given, since that file is
meant to accumulate hand-verified corrections over time.
"""

import argparse
import csv
import sys
from pathlib import Path

# Run directly (`python scripts/build_ground_truth_draft.py`) and only this
# folder is importable, so put the backend root on the path before importing
# app.*. compare_home_reports imports fine without this since it lives in the
# same directory, which Python already puts on sys.path for the entry script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extraction.home_inspection import SYSTEM_NAMES, HomeInspectionReport  # noqa: E402

from compare_home_reports import DEFAULT_REPORTS_DIR, run_one  # noqa: E402

# The report can contain characters the Windows console's default cp1252
# codepage renders as "?". Ask for UTF-8 explicitly.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "extraction_cache"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "ground_truth.csv"

CSV_HEADER = ["report", "system", "age_years", "condition", "findings"]


def load_or_run(path: Path, *, refresh: bool) -> HomeInspectionReport | str:
    """As `run_one`, but reuses a cached result from a previous run when there
    is one, so re-generating the draft doesn't re-pay for OCR + Claude on
    every report every time."""
    cache_path = CACHE_DIR / f"{path.stem}.json"
    if not refresh and cache_path.exists():
        return HomeInspectionReport.model_validate_json(cache_path.read_text(encoding="utf-8"))

    result = run_one(path)
    if isinstance(result, HomeInspectionReport):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


def write_draft(
    output_path: Path, names: list[str], reports: dict[str, HomeInspectionReport]
) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for name in names:
            by_system = {system.name: system for system in reports[name].systems}
            for system_name in SYSTEM_NAMES:
                system = by_system.get(system_name)
                if system is None:
                    # The schema guarantees all six systems come back, but a
                    # row is still written for a system a future model
                    # version somehow omits, rather than silently dropping it.
                    writer.writerow([name, system_name, "", "not_mentioned", ""])
                    continue
                age_years = system.estimated_age.years
                writer.writerow(
                    [
                        name,
                        system_name,
                        age_years if age_years is not None else "",
                        system.condition.rating,
                        "; ".join(system.findings.items),
                    ]
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "reports_dir",
        type=Path,
        nargs="?",
        default=DEFAULT_REPORTS_DIR,
        help=f"directory of PDFs to run (default: {DEFAULT_REPORTS_DIR})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"where to write the draft CSV (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-run OCR + extraction even for reports with a cached result",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite the output file if it already exists",
    )
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        print(f"{args.output} already exists. Pass --force to overwrite it (this discards any hand edits already made).")
        return 1

    paths = sorted(args.reports_dir.glob("*.pdf"))
    if not paths:
        print(f"No PDFs found in {args.reports_dir}")
        return 1

    results: dict[str, HomeInspectionReport | str] = {}
    for path in paths:
        cached = not args.refresh and (CACHE_DIR / f"{path.stem}.json").exists()
        print(f"{'Loading cached' if cached else 'Running'} {path.name}...", file=sys.stderr)
        results[path.stem] = load_or_run(path, refresh=args.refresh)

    names = [path.stem for path in paths]
    failed = {name: result for name, result in results.items() if isinstance(result, str)}
    for name, message in failed.items():
        print(f"{name}: {message}")

    ok_names = [name for name in names if name not in failed]
    if not ok_names:
        return 1

    reports: dict[str, HomeInspectionReport] = {name: results[name] for name in ok_names}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_draft(args.output, ok_names, reports)
    print(f"\nWrote a draft for {len(ok_names)} report(s) to {args.output}")
    print("Every row is the model's own guess -- check each one against its PDF before treating it as ground truth.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
