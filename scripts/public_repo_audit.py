from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PATHS = (
    Path("snapshots"),
    Path("reports/live"),
    Path("examples/historical_runs"),
    Path("data/2026"),
    Path("data/mlb-2026-asplayed.csv"),
    Path(".streamlit/secrets.toml"),
)

FORBIDDEN_FILENAMES = {".env", "secrets.toml"}
SECRET_PATTERNS = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}"),
    "API secret pattern": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
TEXT_SUFFIXES = {
    "", ".py", ".toml", ".yaml", ".yml", ".json", ".md", ".txt", ".csv",
    ".ini", ".cfg", ".sh", ".ps1", ".example",
}


def main() -> int:
    errors: list[str] = []

    for rel in FORBIDDEN_PATHS:
        if (ROOT / rel).exists():
            errors.append(f"forbidden public path exists: {rel.as_posix()}")

    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = path.relative_to(ROOT)
        if path.name in FORBIDDEN_FILENAMES and path.name != ".env.example":
            errors.append(f"forbidden secret filename: {rel.as_posix()}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".env.example":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"possible {label} in {rel.as_posix()}")

    required = [ROOT / "COPYRIGHT.md", ROOT / "NOTICE.md", ROOT / "docs/THIRD_PARTY_DATA.md"]
    for path in required:
        if not path.exists():
            errors.append(f"required public-readiness file missing: {path.relative_to(ROOT)}")

    if errors:
        print("PUBLIC REPOSITORY AUDIT FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PUBLIC REPOSITORY AUDIT PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
