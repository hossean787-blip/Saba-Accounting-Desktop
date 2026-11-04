#!/usr/bin/env python3
"""Import the reviewed public-source ZIP into a local clone on develop.

Usage: python tools/import_public_source.py path/to/Saba_Accounting_Public_Source_0_6_5_REVIEWED.zip
Review git diff and scan for credentials before committing.
"""
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import argparse
import hashlib
import sys

EXPECTED_SHA256 = "43e0eff6de39dc8a8aca09020d999b8d320a1253eed0ea885ffb10ad57b8df8b"
ALLOWED_SUFFIXES = {".py", ".sql", ".md", ".csv", ".json", ".bat", ".txt", ".yml"}
SKIP_NAMES = {".gitignore"}
SKIP_PARTS = {"reference", "previews", "__pycache__", ".git", ".venv", ".pytest_cache"}
DENIED_EXT = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx"}
MAX_SIZE = 2_000_000

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    archive = args.archive.read_bytes()
    sha = hashlib.sha256(archive).hexdigest()
    if sha != EXPECTED_SHA256:
        raise SystemExit("Rejected: ZIP hash does not match the reviewed archive: " + sha)
    root = args.root.resolve()
    staged = []
    with ZipFile(args.archive) as z:
        if z.testzip():
            raise SystemExit("Rejected: corrupt ZIP")
        for info in z.infolist():
            if info.is_dir():
                continue
            p = PurePosixPath(info.filename.replace("\\", "/"))
            if p.is_absolute() or ".." in p.parts or p.name in SKIP_NAMES:
                raise SystemExit("Rejected path: " + info.filename)
            if any(part.lower() in SKIP_PARTS for part in p.parts):
                continue
            if p.suffix.lower() in DENIED_EXT:
                continue
            if p.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            if p.parts[:2] == (".github", "workflows"):
                continue  # retain the repository's audited workflow
            if info.file_size > MAX_SIZE:
                raise SystemExit("Rejected oversized file: " + info.filename)
            output = (root / str(p)).resolve()
            if not output.is_relative_to(root):
                raise SystemExit("Rejected traversal: " + info.filename)
            data = z.read(info)
            if b"\\x00" in data:
                raise SystemExit("Rejected non-text file: " + info.filename)
            staged.append((output, data))
    if not any(p.name == "main.py" for p, _ in staged):
        raise SystemExit("Rejected: no main.py")
    if not any(p.name == "test_accounting.py" for p, _ in staged):
        raise SystemExit("Rejected: no accounting tests")
    for output, data in staged:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    print("Imported", len(staged), "text files to", root)
    print("REQUIRED: inspect 'git status', license provenance and secrets before commit.")

if __name__ == "__main__":
    main()
