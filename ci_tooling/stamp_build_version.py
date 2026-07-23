#!/usr/bin/env python3
"""
stamp_build_version.py: give every CI build a unique, human-readable version.

Rewrites `self.patcher_version` in constants.py from its base semver (X.Y.Z) to
`X.Y.Z-DDMMYY-HHMM` using the current build time. Any existing `-...` suffix is
stripped first, so re-stamping never compounds.

The dashed form is intentionally NOT PEP 440 valid: OCLP treats a non-PEP440
version as a `special_build` (see constants.special_build / support/updates.py),
which suppresses the auto-updater and marks the binary as a test build. This
gives the tester an unambiguous identifier — visible in the About box, the log
filename, config.plist #Revision/Build-Version and the NVRAM OCLP-Version — so
there is never any doubt about which build is being tested.

Prints the stamped version to stdout so CI can capture it for release notes.
Usage: python3 ci_tooling/stamp_build_version.py [DDMMYY-HHMM]
       (no argument -> use the current local time)
"""

import re
import sys
import pathlib
from datetime import datetime

CONSTANTS = pathlib.Path(__file__).resolve().parent.parent / "opencore_legacy_patcher" / "constants.py"
PATTERN = re.compile(r'(self\.patcher_version:\s*str\s*=\s*")([^"]*)(")')


def main() -> int:
    stamp = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%d%m%y-%H%M")

    source = CONSTANTS.read_text()
    match = PATTERN.search(source)
    if match is None:
        print("error: patcher_version assignment not found in constants.py", file=sys.stderr)
        return 1

    base = re.match(r"\d+\.\d+\.\d+", match.group(2))
    if base is None:
        print(f"error: could not parse base semver from '{match.group(2)}'", file=sys.stderr)
        return 1

    stamped = f"{base.group(0)}-{stamp}"
    source = source[:match.start()] + f"{match.group(1)}{stamped}{match.group(3)}" + source[match.end():]
    CONSTANTS.write_text(source)

    print(stamped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
