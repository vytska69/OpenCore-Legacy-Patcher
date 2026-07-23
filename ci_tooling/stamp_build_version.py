#!/usr/bin/env python3
"""
stamp_build_version.py: give every CI build a unique, human-readable version.

Rewrites `self.patcher_version` in constants.py from its version prefix to
`<ver>-YYYYMMDD-HHMM` using the current build time, e.g. `252-20260723-1732`.
The prefix is whatever precedes the first `-` in the current value, so any
existing date/time suffix is stripped first and re-stamping never compounds.

The dashed form is intentionally NOT PEP 440 valid: OCLP treats a non-PEP440
version as a `special_build` (see constants.special_build / support/updates.py),
which suppresses the auto-updater and marks the binary as a test build. This
gives the tester an unambiguous identifier — visible in the About box, the log
filename, config.plist #Revision/Build-Version and the NVRAM OCLP-Version — so
there is never any doubt about which build is being tested.

Prints the stamped version to stdout so CI can capture it for release notes.
Usage: python3 ci_tooling/stamp_build_version.py [YYYYMMDD-HHMM]
       (no argument -> use the current local time)
"""

import sys
import pathlib
from datetime import datetime

CONSTANTS = pathlib.Path(__file__).resolve().parent.parent / "opencore_legacy_patcher" / "constants.py"
MARKER = "self.patcher_version:"


def main() -> int:
    stamp = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d-%H%M")

    lines = CONSTANTS.read_text().splitlines(keepends=True)
    for i, line in enumerate(lines):
        if MARKER not in line:
            continue

        start = line.index('"')
        end = line.index('"', start + 1)
        current = line[start + 1:end]

        prefix = current.split("-", 1)[0]  # version prefix, e.g. "252" (date/time suffix, if any, dropped)
        if not prefix:
            print(f"error: could not parse version prefix from '{current}'", file=sys.stderr)
            return 1

        stamped = f"{prefix}-{stamp}"
        lines[i] = line[:start + 1] + stamped + line[end:]
        CONSTANTS.write_text("".join(lines))
        print(stamped)
        return 0

    print("error: patcher_version assignment not found in constants.py", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
