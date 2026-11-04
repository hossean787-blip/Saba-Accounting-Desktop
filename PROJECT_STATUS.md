# Saba Accounting Desktop — Commercial 1.0 status

Updated: 2026-11-04

## Goal and constraints

Evolve the independent 0.6.5 codebase toward commercial 1.0 without rewriting
from scratch. Work occurs on `develop`; `main`, public Releases, sales claims,
permissions, purchases, and destructive data operations require owner approval.

Rollback tag: `pre-commercial-1.0-baseline-20261104` at `02199a4`.

## Verified baseline

- Python 3.12/Linux: syntax check and 180 tests passed before commercial changes.
- Upgraded Windows CI run `41822229276`: success at commit `f5f7e3e`.
- Commercial source of truth: `docs/COMMERCIAL_RELEASE_GATE_FA.md` and Issue 2.

## Work ledger

| Priority | Work item | Status |
|---|---|---|
| P0 | Mandatory named-admin bootstrap and fail-closed persistent startup | Implemented; Linux + Windows CI passed; interactive GUI acceptance pending |
| P0 | Authorization audit of every public business service | Explicit registry + coverage test; Linux/Windows CI passed |
| P0 | Audit handoff viewer/export boundary | Viewer reduced to read-only; exhaustive sensitive-API regression passed on Linux and Windows CI |
| P0 | At-rest database and encrypted-backup/key-recovery design | Encrypted backup implemented; active SQLite encryption remains open |
| P0 | Independent accounting reconciliation and statutory sign-off | Needs independent accountant/owner action |
| P1 | Installer, upgrade preservation, least-privileged Windows acceptance | Per-user silent install/CLI/uninstall CI passed; real standard-user GUI and upgrade-data acceptance pending |
| P1 | Interactive Windows 10/11 GUI, DPI, Persian print acceptance | Needs real Windows test machines |
| P1 | Dependency/provenance, malware reputation and code signing | Partial; signing needs owner certificate |
| P1 | User/admin/backup/support/licensing documentation | Pending |

## Release decision

FAIL-CLOSED. The product is not commercial 1.0 and is not ready for sale while
any mandatory gate remains open. Automated tests and an EXE alone are not a
substitute for interactive Windows, independent accounting, tax, legal, privacy,
and signing approvals.

## Latest build evidence

- Commit: `826b823d04ab6e4977cb7657f179f5004546464f`
- Windows run: `41826844614` — success (syntax, 180 tests, PE build,
  checksum, `--help` smoke, artifact upload).
- EXE: 12,563,961 bytes; SHA-256
  `cd838643303912910cd43037a0c48fbc37779ad99af374ee9cd23c4b2ad42201`.
- Artifact archive digest: SHA-256
  `bcdbd8a86f5a45b63d7bdace3a14ffb1da73908df9e8be582361fa7d41a7b96b`.

Commercial-hardening preview commit `93ae74f` passed Windows run
`41829974148`: dependency/static scans, syntax, 185 tests, EXE build/smoke,
per-user installer build, silent install, installed CLI smoke, uninstall, source
archive and artifact upload. EXE SHA-256:
`3d36cd4417208f1b875852275306f18027a6610c8b73f1a8fa6837993cffbf54`.
Artifact bundle digest:
`8effc02efba4a8294fcd9d339a3aa74e0062890d3c2e2e73d529d869d56a71e8`.

Latest checksum-reporting run `41831250581` at commit `c3245af` also passed.
Output SHA-256 values:

- `SabaAccounting.exe`: `f33deda285f1c69ca02b6c64273e72bbace3862e1f90bd150820bd89f6ae95b9`
- `SabaAccounting-Setup.exe`: `20f73d57f3fb5ae7911c59f038a0e08363ce3c8c89d7a012bbef1dbbf956996b`
- `SabaAccounting-Source.zip`: `e64dce7ac33f367d8dd30f444c13640735c92d931d464ce02d9b4f9fde173ad9`
- Artifact bundle digest: `b67af545bed8465bc6169895aa496bcbbdac093b5bc8888a22e802d05764f066`

The 0.6.5 audit handoff was compared with the full source at `1fb0cfa`.
Locally, 191 tests pass after adding regression coverage for concurrent journal
creation, old/new line schemas, cross-company report scope, viewer denial,
non-overwriting backup and non-legal report labels. See
`docs/AUDIT_HANDOFF_065_REPORT_FA.md`.

Audit-handoff commit `4474741` passed Windows run `41836670336`: security
checks, syntax, 191 tests, EXE build/smoke, per-user installer build, silent
install/installed smoke/uninstall, source packaging and artifact upload. Windows
artifact digest: `6a9d4947211268f565b126ec0405b8afbce36e201fffcf9f14aa289c7fe73834`.
The artifact service returned a time-bound HTTP 403 to this Codex environment,
so individual output hashes inside `SHA256SUMS.txt` were not independently
downloaded and are not claimed here.
