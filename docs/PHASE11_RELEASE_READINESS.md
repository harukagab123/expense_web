# Phase 11 Release Readiness

Validation date: 2026-08-26 (America/Los_Angeles)

## Release candidate

- Application version: `1.0.0`
- Database schema revision: `202608270012`
- Installer: `outputs/release/PersonalFinanceManager-1.0.0-Setup.exe`
- Portable package: `outputs/release/PersonalFinanceManager-1.0.0-Portable.zip`
- Installer SHA-256: `3AB2A08A9A284793C922E6AE1CE9BAD8766175CA5A32BE886DC7B1390C57D03B`

## Result

The packaged Windows application passed clean install, first launch, duplicate launch, multi-institution statement analysis, correction/learning, selection persistence, notifications, five-file retention, summary/export reconciliation, backup/restore, in-place update, update failure recovery, diagnostics, uninstall/reinstall, performance, integrity, privacy, and final clean-data smoke validation.

No separately installed Python, Node.js, Git, editor, or terminal is required for normal use. The packaged backend listened only on `127.0.0.1`.

## Reconciliation

The retained multi-institution synthetic QA dataset reconciled as follows:

| Source | Total |
| --- | ---: |
| Database summary | $3,122.44 |
| Packaged UI/API summary | $3,122.44 |
| Excel Summary | $3,122.44 |
| Excel Transaction Detail (46 rows) | $3,122.44 |
| Difference | $0.00 |

The workbook contained `Summary` and `Transaction Detail`, used the approved category order, placed Other Supplies last, had zero formula errors, and rendered in the requested minimal black-and-white style.

## Category and selection audit

- Runtime category priority: exact approved top-to-bottom order
- Other Supplies rows: 9 of 46 included expenses (19.57%)
- Expected ambiguous fallbacks: 9
- Unexpected Other Supplies: 0
- Invalid active Personal/Internal, Personal, Other Personal Items, or Uncategorized classifications: 0
- Unexpected selection resets across refresh, navigation, restart, Analyze Again, correction, notification navigation, restore, and update: 0

## Backup, update, and lifecycle

- Valid backup restore returned the exact edited transaction, learned rule, excluded selection, reviewed state, and `$3,122.44` total.
- Restore created and validated an automatic pre-restore safety backup.
- Invalid restore returned a clear error and left current state unchanged.
- In-place installer update created a validated pre-update backup before stopping the running application.
- Post-update state, schema, retained files, manual edits, learned rules, selections, review state, and total were unchanged.
- Synthetic migration failure restored the prior database and stopped the update; synthetic backup failure prevented migration from starting.
- Uninstall removed program files and shortcuts while preserving user data; reinstall rediscovered the existing database automatically.

## Performance

An isolated 2,500-transaction synthetic dataset produced:

| Operation | Elapsed |
| --- | ---: |
| Transaction list | 1.03 s |
| Notification count | 0.19 s |
| Notification list | 0.16 s |
| Summary | 0.46 s |
| Excel export | 4.68 s |
| Bulk selection update (100 rows) | 0.11 s |

Summary and notifications queried structured database records; no PDFs were reread.

## Integrity and privacy

- SQLite integrity check: `ok`
- Foreign-key violations: 0
- Orphan statements: 0
- Orphan transactions: 0
- Orphan normalization, type, or category rule references: 0
- Removed retained sources with preserved historical statements: 2
- Historical transactions still linked to removed sources: 7
- Diagnostic sensitive-data matches: 0
- Exposed secret matches in tracked repository and final release artifacts: 0
- Packaged development databases, statements, logs, backups, diagnostics, exports, and `.env` files: 0

## Defects found and fixed

1. High — `ACME MATERIALS SUPPLY` fell through to Other Supplies. The Materials matcher did not recognize the word order. Added a deterministic Materials pattern and regression coverage. Final result: Materials.
2. Critical — editing a normalized merchant name could reset a user-confirmed category to Not Applicable through downstream type invalidation. Manual category authority was not included in the type-reset guard. Preserved the existing expense-eligible type when either type or category is user-authoritative and added endpoint regression coverage. Final result: manual type/category and selection remain intact.
3. Critical — an in-place update could create its safety backup but fail because Restart Manager could not close the windowless application. Setup now stops the named application processes only after the validated backup succeeds. Final result: same-directory update succeeds with data unchanged.
4. High — uninstalling while the windowless backend was active could leave a locked executable pending removal. The uninstaller now closes the named application processes before deleting program files. Final result: clean uninstall without restart, with user data preserved.

## Automated release gates

- `powershell -ExecutionPolicy Bypass -File scripts/build-release.ps1` — frontend install/audit, lint, typecheck, production build, 204 backend tests, PyInstaller executable, portable ZIP, and Inno Setup installer: PASS
- `pytest backend/tests/test_transaction_normalization_api.py backend/tests/test_transaction_categorization_api.py backend/tests/test_statement_analysis_api.py -q` — 23 passed
- Packaged 13-transaction Chase re-analysis — all 8 stages completed
- Final exact-installer clean-data smoke — install, launch, upload, Analyze, review, Summary, Excel export, backup, close/reopen: PASS

## Remaining issues and manual action

No blocking release issues remain. Developer-only, non-blocking warnings remain for Starlette's pending `python_multipart` import transition, Alembic's legacy `prepend_sys_path` parsing default, and the installed ESLint 9 support window. They do not affect the packaged runtime. No manual action is required before release.

PHASE 11 STATUS: COMPLETE — READY FOR RELEASE
