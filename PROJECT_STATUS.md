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
| P0 | Mandatory named-admin bootstrap and fail-closed persistent startup | Implemented locally; CI pending |
| P0 | Authorization audit of every public business service | Pending |
| P0 | At-rest database and encrypted-backup/key-recovery design | Pending architecture/security review |
| P0 | Independent accounting reconciliation and statutory sign-off | Needs independent accountant/owner action |
| P1 | Installer, upgrade preservation, least-privileged Windows acceptance | Pending |
| P1 | Interactive Windows 10/11 GUI, DPI, Persian print acceptance | Needs real Windows test machines |
| P1 | Dependency/provenance, malware reputation and code signing | Partial; signing needs owner certificate |
| P1 | User/admin/backup/support/licensing documentation | Pending |

## Release decision

FAIL-CLOSED. The product is not commercial 1.0 and is not ready for sale while
any mandatory gate remains open. Automated tests and an EXE alone are not a
substitute for interactive Windows, independent accounting, tax, legal, privacy,
and signing approvals.
