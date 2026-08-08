"""Run every PDF in a directory through OCR + extraction and print the results side by side.

There is no ground-truth spreadsheet yet, so this does not grade the output --
it runs the real pipeline (`ocr_pdf.py` + `extract_home_inspection.py`, chained
the same way `extract_home_inspection.py` does for one file) on every report and
lays the six systems out in columns so a human can eyeball them for anything
off. It also flags one thing automatically: fields where the value and its
confidence disagree (e.g. a condition is given but confidence is 0.0, or
"not_mentioned" comes back with confidence above 0.0) -- the extraction prompt
guarantees these never happen, so a flag here means the pipeline output broke
that contract, not that the extracted value is "wrong".

    pip install anthropic
    python scripts/compare_home_reports.py [reports_dir]

reports_dir defaults to ../tests-reports. Requires the same DOCAI_* and
GOOGLE_APPLICATION_CREDENTIALS / ANTHROPIC_API_KEY configuration as
extract_home_inspection.py -- see that script's docstring.
"""

import argparse
import sys
from pathlib import Path

# Run directly (`python scripts/compare_home_reports.py`) and only this folder
# is importable, so put the backend root on the path before importing app.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extraction.home_inspection import (  # noqa: E402
    SYSTEM_NAMES,
    AgeEstimate,
    ConditionAssessment,
    ExtractionError,
    Findings,
    HomeInspectionReport,
    HomeSystem,
    extract_home_systems,
)
from app.ingestion.ocr import OcrError, extract_pdf  # noqa: E402
from app.ingestion.service import render_tables  # noqa: E402

# The report can contain characters the Windows console's default cp1252
# codepage renders as "?". Ask for UTF-8 explicitly.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_REPORTS_DIR = Path(__file__).resolve().parents[2] / "tests-reports"


def run_one(path: Path) -> HomeInspectionReport | str:
    """Run one PDF through the pipeline. Returns the report, or an error string
    if OCR or extraction failed -- callers show the message and move on rather
    than letting one bad file stop the whole comparison."""
    try:
        ocr_result = extract_pdf(path)
    except OcrError as e:
        return f"OCR failed: {e}"

    raw_text = "\n\n".join(
        section for section in (ocr_result.prose, render_tables(ocr_result.tables)) if section
    )

    try:
        return extract_home_systems(raw_text)
    except ExtractionError as e:
        return f"Extraction failed: {e}"


def format_age(age: AgeEstimate) -> str:
    value = f"{age.years}y" if age.years is not None else "-"
    return f"{value} ({age.confidence:.2f})"


def format_condition(condition: ConditionAssessment) -> str:
    return f"{condition.rating} ({condition.confidence:.2f})"


def format_findings(findings: Findings) -> str:
    if not findings.items:
        return f"(none) ({findings.confidence:.2f})"
    return f"{len(findings.items)} item(s) ({findings.confidence:.2f})"


def value_confidence_conflicts(system: HomeSystem) -> list[str]:
    """Fields with actual content but exactly 0.0 confidence.

    The extraction prompt says 0.0 means "there is nothing here to go on" --
    so a field carrying real content (a stated age, a condition other than
    not_mentioned, a non-empty findings list) can never legitimately score
    0.0. The reverse is not a conflict: a null/not_mentioned/empty field can
    still carry non-zero confidence within an otherwise-mentioned system --
    that is the model saying "I'm confident the report just doesn't state
    this," which the prompt only forbids when the *whole* system goes
    unmentioned (all three fields would be 0.0 together in that case).
    """
    conflicts = []

    age = system.estimated_age
    if age.years is not None and age.confidence == 0.0:
        conflicts.append("age has a value but confidence is 0.0")

    condition = system.condition
    if condition.rating != "not_mentioned" and condition.confidence == 0.0:
        conflicts.append("condition is set but confidence is 0.0")

    findings = system.findings
    if findings.items and findings.confidence == 0.0:
        conflicts.append("findings has items but confidence is 0.0")

    return conflicts


def print_summary_table(names: list[str], reports: dict[str, HomeInspectionReport]) -> None:
    col_width = max(20, max(len(name) for name in names) + 2)
    label_width = 12

    def row(label: str, cells: list[str]) -> str:
        return label.ljust(label_width) + "".join(cell.ljust(col_width) for cell in cells)

    for system_name in SYSTEM_NAMES:
        print(f"\n=== {system_name.upper()} ===")
        print(row("", names))

        by_report = {
            name: next((s for s in reports[name].systems if s.name == system_name), None)
            for name in names
        }

        print(
            row(
                "age",
                [format_age(s.estimated_age) if s else "MISSING" for s in by_report.values()],
            )
        )
        print(
            row(
                "condition",
                [format_condition(s.condition) if s else "MISSING" for s in by_report.values()],
            )
        )
        print(
            row(
                "findings",
                [format_findings(s.findings) if s else "MISSING" for s in by_report.values()],
            )
        )


def print_findings_detail(names: list[str], reports: dict[str, HomeInspectionReport]) -> None:
    print("\n\n=== FINDINGS DETAIL ===")
    for name in names:
        print(f"\n--- {name} ---")
        for system in reports[name].systems:
            if system.findings.items:
                print(f"  {system.name}:")
                for item in system.findings.items:
                    print(f"    - {item}")


def print_conflicts(names: list[str], reports: dict[str, HomeInspectionReport]) -> bool:
    print("\n\n=== VALUE / CONFIDENCE CONFLICTS ===")
    any_conflicts = False
    for name in names:
        for system in reports[name].systems:
            for conflict in value_confidence_conflicts(system):
                any_conflicts = True
                print(f"  {name} / {system.name}: {conflict}")
    if not any_conflicts:
        print("  none")
    return any_conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "reports_dir",
        type=Path,
        nargs="?",
        default=DEFAULT_REPORTS_DIR,
        help=f"directory of PDFs to run (default: {DEFAULT_REPORTS_DIR})",
    )
    args = parser.parse_args()

    paths = sorted(args.reports_dir.glob("*.pdf"))
    if not paths:
        print(f"No PDFs found in {args.reports_dir}")
        return 1

    results: dict[str, HomeInspectionReport | str] = {}
    for path in paths:
        print(f"Running {path.name}...", file=sys.stderr)
        results[path.stem] = run_one(path)

    names = [path.stem for path in paths]
    failed = {name: result for name, result in results.items() if isinstance(result, str)}
    for name, message in failed.items():
        print(f"{name}: {message}")

    ok_names = [name for name in names if name not in failed]
    if not ok_names:
        return 1

    reports: dict[str, HomeInspectionReport] = {name: results[name] for name in ok_names}

    print_summary_table(ok_names, reports)
    print_findings_detail(ok_names, reports)
    had_conflicts = print_conflicts(ok_names, reports)

    return 1 if failed or had_conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
