# Public source import report — 0.6.5

Date: 2026-11-04

## Provenance and scope

- Source archive: `Saba_Accounting_Public_Source_0_6_5_REVIEWED.zip`
- Verified SHA-256: `43e0eff6de39dc8a8aca09020d999b8d320a1253eed0ea885ffb10ad57b8df8b`
- Imported with the repository-owned, hash-pinned `tools/import_public_source.py`.
- Target branch: `develop`; no merge or write to `main`.
- The repository-owned Windows workflow and `.gitignore` were retained.

The importer excluded `docs/reference`, previews/assets pending provenance review,
databases, backups, credentials, private keys, caches, binary files, and the
workflow bundled inside the ZIP. A filename/content credential scan found no
publishable secret. No proprietary Sepidar manuals or extracted documentation
are present in the imported tree.

## Local verification

- `python -m compileall -q main.py saba_accounting tests`: PASS
- `python -m unittest discover -s tests -v`: PASS
- Result: 180 tests passed on Python 3.12/Linux.

## Windows output

Pushes affecting `main.py`, `saba_accounting/`, or `tests/` trigger
`.github/workflows/windows-release.yml` on `windows-2022`. The job runs all tests,
builds `dist/SabaAccounting.exe` with PyInstaller, and uploads the
`SabaAccounting-Windows` artifact. The Actions run and artifact must be inspected
before claiming the EXE is installable; this source import does not publish a
GitHub Release.
