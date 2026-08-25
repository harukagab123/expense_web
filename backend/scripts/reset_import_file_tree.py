from __future__ import annotations

import argparse
from pathlib import Path
import sys

from app.db.session import get_session_factory
from app.services.bulk_file_import import (
    BulkImportReport,
    SourceManifest,
    SourceSpec,
    SourceValidationError,
    database_content_counts,
    replace_file_manager_contents,
    scan_source_trees,
)


def _format_manifest(manifest: SourceManifest) -> list[str]:
    return [
        f"Source: {manifest.source_path}",
        f"Destination root: {manifest.destination_root_name}",
        f"Folders found: {manifest.folder_count}",
        f"Files found: {manifest.file_count}",
    ]


def _print_manifest_summary(manifests: tuple[SourceManifest, ...]) -> None:
    print("Source validation: OK")
    for manifest in manifests:
        print("")
        for line in _format_manifest(manifest):
            print(line)


def _print_import_report(report: BulkImportReport) -> None:
    print("Import complete")
    print("")
    print("Old data reset")
    print(f"Folders removed: {report.old_counts.folders}")
    print(f"Files removed: {report.old_counts.files}")
    print(f"Statements removed: {report.old_counts.statements}")
    print(f"Transaction extractions removed: {report.old_counts.transaction_extractions}")
    print(f"Transactions removed: {report.old_counts.transactions}")
    print("")

    for result in report.source_results:
        print(result.destination_root_name)
        print(f"Folders found: {result.source_folder_count}")
        print(f"Files found: {result.source_file_count}")
        print(f"Folders imported: {result.imported_folder_count}")
        print(f"Files imported: {result.imported_file_count}")
        print(f"Relative paths matched: {result.relative_paths_matched} / {result.source_file_count}")
        print(f"Physical files present: {result.physical_files_present} / {result.source_file_count}")
        print(f"Failures: {', '.join(result.failures) if result.failures else 'None'}")
        print("")

    print("New database counts")
    print(f"Folders: {report.new_counts.folders}")
    print(f"Files: {report.new_counts.files}")
    print(f"Statements: {report.new_counts.statements}")
    print(f"Transaction extractions: {report.new_counts.transaction_extractions}")
    print(f"Transactions: {report.new_counts.transactions}")
    print("")
    print(
        "Old storage cleanup failures: "
        f"{', '.join(report.old_storage_cleanup_failures) if report.old_storage_cleanup_failures else 'None'}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset app-managed files/folders and import source folder trees.")
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="Source directory to import. Repeat for multiple root-level source folders.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and summarize source directories without modifying the app database or storage.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_specs = [SourceSpec(Path(source)) for source in args.source]

    try:
        if args.dry_run:
            manifests = scan_source_trees(source_specs)
            _print_manifest_summary(manifests)
            with get_session_factory()() as session:
                counts = database_content_counts(session)
            print("")
            print("Current app-managed content")
            print(f"Folders: {counts.folders}")
            print(f"Files: {counts.files}")
            print(f"Statements: {counts.statements}")
            print(f"Transaction extractions: {counts.transaction_extractions}")
            print(f"Transactions: {counts.transactions}")
            return 0

        with get_session_factory()() as session:
            report = replace_file_manager_contents(session, source_specs)
        _print_import_report(report)
        return 1 if report.has_failures else 0
    except SourceValidationError as exc:
        print("Source validation failed. Existing app-managed content was not deleted.", file=sys.stderr)
        for issue in exc.issues:
            print(f"{issue.source_path} :: {issue.relative_path}: {issue.error}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
