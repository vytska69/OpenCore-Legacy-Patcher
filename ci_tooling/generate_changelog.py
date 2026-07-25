#!/usr/bin/env python3
"""
generate_changelog.py: build a human-readable changelog for a CI release.

Reads the git commit subjects in a range and formats them into grouped, plain
markdown that is easy to follow with a screen reader — one bullet per change,
grouped under friendly section headings derived from the commit's area prefix
(e.g. "efi:", "updates:").

Usage:
    generate_changelog.py [SINCE_REF]

  SINCE_REF  commit/tag to start after (exclusive). Range is SINCE_REF..HEAD.
             If omitted, empty, or not a valid ref, falls back to the last 20
             commits so the notes are never empty.

Prints the markdown to stdout.
"""

import re
import sys
import subprocess


# Commit-subject area prefix -> friendly section heading. Anything not listed
# (or with no "area:" prefix) lands under "Other changes".
AREA_TITLES = {
    "efi":      "OpenCore / EFI",
    "updates":  "In-app updater",
    "update":   "In-app updater",
    "package":  "Installer package",
    "install":  "Installer / disk writing",
    "version":  "Versioning",
    "fix":      "Fixes",
    "efi_builder": "OpenCore / EFI",
    "payloads": "Bundled payloads (OpenCore + kexts)",
    "ci":       "Build / CI",
    "readme":   "Documentation",
    "docs":     "Documentation",
    "gui":      "App interface",
    "t2":       "T2 Mac support",
    "t1":       "T1 Mac support",
    "smbios":   "SMBIOS",
    "security": "Security",
}

SECTION_ORDER = [
    "T2 Mac support",
    "OpenCore / EFI",
    "In-app updater",
    "Installer package",
    "Installer / disk writing",
    "App interface",
    "Bundled payloads (OpenCore + kexts)",
    "SMBIOS",
    "Security",
    "T1 Mac support",
    "Versioning",
    "Fixes",
    "Build / CI",
    "Documentation",
    "Other changes",
]


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return result.stdout


def _ref_exists(ref: str) -> bool:
    if not ref:
        return False
    return subprocess.run(
        ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
        capture_output=True,
    ).returncode == 0


def _subjects(since_ref: str) -> list:
    if _ref_exists(since_ref):
        log_range = [f"{since_ref}..HEAD"]
    else:
        log_range = ["-20"]
    out = _git("log", *log_range, "--no-merges", "--pretty=format:%s")
    seen = set()
    subjects = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        subjects.append(line)
    return subjects


def _classify(subject: str):
    """Return (section_title, message) for a commit subject."""
    match = re.match(r"^([a-zA-Z0-9_\-]+)(?:\([^)]*\))?:\s*(.*)$", subject)
    if match:
        area = match.group(1).lower()
        message = match.group(2).strip() or subject
        title = AREA_TITLES.get(area, "Other changes")
        return title, message
    return "Other changes", subject


def build_changelog(since_ref: str) -> str:
    subjects = _subjects(since_ref)
    if not subjects:
        return "## What changed in this build\n\n- No code changes since the previous build.\n"

    grouped = {}
    for subject in subjects:
        title, message = _classify(subject)
        message = message[0].upper() + message[1:] if message else message
        grouped.setdefault(title, []).append(message)

    lines = ["## What changed in this build", ""]
    for title in SECTION_ORDER:
        if title not in grouped:
            continue
        lines.append(f"### {title}")
        for message in grouped[title]:
            lines.append(f"- {message}")
        lines.append("")

    # Any section not in SECTION_ORDER (defensive; shouldn't happen).
    for title, messages in grouped.items():
        if title in SECTION_ORDER:
            continue
        lines.append(f"### {title}")
        for message in messages:
            lines.append(f"- {message}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    since_ref = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.stdout.write(build_changelog(since_ref))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
