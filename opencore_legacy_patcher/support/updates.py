"""
updates.py: Check for OpenCore Legacy Patcher binary updates

Call check_binary_updates() to determine if any updates are available
Returns dict with Link and Version of the latest binary update if available
"""

import re
import logging

from typing import Optional, Union
from packaging import version

from . import network_handler

from .. import constants


# This fork ships rolling test builds versioned X.Y.Z-YYYYMMDD-HHMM. That form is
# not PEP440, so PEP440-based comparison (and the upstream dortania updater) can't
# rank them — they are compared by their embedded build timestamp instead. The
# rolling build is published under the tag "latest" and marked prerelease, so the
# GitHub /releases/latest endpoint (which skips prereleases) can't see it; fetch
# the tag directly. All installs (dated builds and older plain 2.5.x) update from
# here; upstream dortania is never used as an update source in this fork.
FORK_ROLLING_RELEASE_URL: str = "https://api.github.com/repos/vytska69/OpenCore-Legacy-Patcher/releases/tags/latest"
FORK_RELEASES_URL:        str = "https://github.com/vytska69/OpenCore-Legacy-Patcher/releases"

# Matches the trailing "-YYYYMMDD-HHMM" of a fork test-build version.
_BUILD_STAMP_RE = re.compile(r"-(\d{8})-(\d{4})$")


def _build_stamp(version_str: Union[str, "version.Version", None]) -> Optional[int]:
    """
    Extract the build timestamp of a fork test build (X.Y.Z-YYYYMMDD-HHMM) as a
    single comparable integer (YYYYMMDDHHMM). Returns None for any version that
    does not carry such a stamp (e.g. official PEP440 releases like 2.5.1/2.5.2).
    """
    if version_str is None:
        return None
    match = _BUILD_STAMP_RE.search(str(version_str))
    if match is None:
        return None
    return int(match.group(1) + match.group(2))


def _base_version(version_str: Union[str, "version.Version", None]) -> str:
    """
    Strip a trailing build stamp, leaving the base version. "2.5.2-20260723-1732"
    -> "2.5.2"; a plain "2.5.2" is returned unchanged.
    """
    if version_str is None:
        return ""
    return _BUILD_STAMP_RE.sub("", str(version_str))


class CheckBinaryUpdates:
    def __init__(self, global_constants: constants.Constants) -> None:
        self.constants: constants.Constants = global_constants
        # If this is a fork test build, its timestamp is what we compare on.
        self.local_stamp: Optional[int] = _build_stamp(self.constants.patcher_version)
        try:
            self.binary_version = version.parse(self.constants.patcher_version)
        except version.InvalidVersion:
            assert self.constants.special_build is True, "Invalid version number for binary"
            # Special builds will not have a proper version number
            self.binary_version = version.parse("0.0.0")

        self.latest_details = None

    def check_if_newer(self, version: Union[str, version.Version]) -> bool:
        """
        Check if the provided version is newer than the local version

        Parameters:
            version (str): Version to compare against

        Returns:
            bool: True if the provided version is newer, False if not
        """
        # Fork test build: rank by embedded build timestamp.
        if self.local_stamp is not None:
            other_stamp = _build_stamp(version)
            if other_stamp is None:
                return False
            return other_stamp > self.local_stamp

        if self.constants.special_build is True:
            return False

        return self._check_if_build_newer(version, self.binary_version)

    def _check_if_build_newer(self, first_version: Union[str, version.Version], second_version: Union[str, version.Version]) -> bool:
        """
        Check if the first version is newer than the second version

        Parameters:
            first_version_str (str): First version to compare against (generally local)
            second_version_str (str): Second version to compare against (generally remote)

        Returns:
            bool: True if first version is newer, False if not
        """

        if not isinstance(first_version, version.Version):
            try:
                first_version = version.parse(first_version)
            except version.InvalidVersion:
                # Special build > release build: assume special build is newer
                return True

        if not isinstance(second_version, version.Version):
            try:
                second_version = version.parse(second_version)
            except version.InvalidVersion:
                # Release build > special build: assume special build is newer
                return False

        if first_version == second_version:
            if not self.constants.commit_info[0].startswith("refs/tags"):
                # Check for nightly builds
                return True

        return first_version > second_version


    def check_binary_updates(self) -> Optional[dict]:
        """
        Check if any updates are available for the OpenCore Legacy Patcher binary

        Returns:
            dict: Dictionary with Link and Version of the latest binary update if available
        """

        if self.latest_details:
            # We already checked
            return self.latest_details

        # This fork's only meaningful update source is its own rolling "latest"
        # release. EVERY install is checked against it — a dated test build
        # (2.5.2-YYYYMMDD-HHMM) as well as an older plain release (2.5.1 / 2.5.2)
        # from before stamping existed. Upstream dortania is never used: it has
        # no T2 support, so "updating" to it would strip this fork's changes.
        return self._check_fork_rolling_update()


    def _fork_build_is_newer(self, remote_version: str, remote_stamp: int) -> bool:
        """
        Decide whether the fork's rolling build is newer than the local install.

        Compares base versions (PEP440) first; on an equal base, the build stamp
        breaks the tie (an unstamped install counts as stamp 0, so an old plain
        2.5.2 is always older than any 2.5.2-dated rolling build). A higher local
        base (e.g. a future 2.6.0) is never offered a downgrade.
        """
        remote_base_str = _base_version(remote_version)
        local_base_str  = _base_version(self.constants.patcher_version)
        try:
            remote_base = version.parse(remote_base_str)
            local_base  = version.parse(local_base_str)
        except version.InvalidVersion:
            # Unparseable base on either side: fall back to stamp-only ranking.
            return remote_stamp > (self.local_stamp or 0)

        if remote_base != local_base:
            return remote_base > local_base

        # Same base version: newer build stamp wins (unstamped install == 0).
        return remote_stamp > (self.local_stamp or 0)


    def _check_fork_rolling_update(self) -> Optional[dict]:
        """
        Update path against this fork's rolling "latest" release, whose name CI
        sets to the exact build version (X.Y.Z-YYYYMMDD-HHMM). Returns the newer
        OpenCore-Patcher.pkg if one is available, for both stamped and older
        plain installs.

        Returns:
            dict: Name/Version/Link/Github Link of the newer build, or None.
        """
        if not network_handler.NetworkUtilities(FORK_ROLLING_RELEASE_URL).verify_network_connection():
            return None

        response = network_handler.NetworkUtilities().get(FORK_ROLLING_RELEASE_URL)
        if response is None:
            return None

        try:
            data_set = response.json()
        except ValueError:
            return None

        # CI stamps the rolling release name with the build version; fall back to
        # the tag if the name is missing (the tag "latest" carries no stamp, so
        # that path simply yields no update).
        remote_version = data_set.get("name") or data_set.get("tag_name", "")
        remote_stamp = _build_stamp(remote_version)
        if remote_stamp is None:
            # Remote isn't a stamped rolling build; nothing to compare against.
            return None

        if not self._fork_build_is_newer(remote_version, remote_stamp):
            return None

        for asset in data_set.get("assets", []):
            logging.info(f"Found asset: {asset['name']}")
            if asset["name"] == "OpenCore-Patcher.pkg":
                self.latest_details = {
                    "Name": asset["name"],
                    "Version": remote_version,
                    "Link": asset["browser_download_url"],
                    "Github Link": data_set.get("html_url", FORK_RELEASES_URL),
                }
                return self.latest_details

        return None
