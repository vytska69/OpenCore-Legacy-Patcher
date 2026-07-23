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


REPO_LATEST_RELEASE_URL: str = "https://api.github.com/repos/dortania/OpenCore-Legacy-Patcher/releases/latest"

# This fork ships rolling test builds versioned X.Y.Z-YYYYMMDD-HHMM. That form is
# not PEP440, so PEP440-based comparison (and the upstream dortania updater) can't
# rank them — they are compared by their embedded build timestamp instead. The
# rolling build is published under the tag "latest" and marked prerelease, so the
# GitHub /releases/latest endpoint (which skips prereleases) can't see it; fetch
# the tag directly.
FORK_ROLLING_RELEASE_URL: str = "https://api.github.com/repos/vytska69/OpenCore-Legacy-Patcher/releases/tags/latest"
FORK_RELEASES_URL:        str = "https://github.com/vytska69/OpenCore-Legacy-Patcher/releases"

# Matches the trailing "-YYYYMMDD-HHMM" of a fork test-build version.
_BUILD_STAMP_RE = re.compile(r"-(\d{8})-(\d{4})$")


def _build_stamp(version_str: Union[str, "version.Version", None]) -> Optional[int]:
    """
    Extract the build timestamp of a fork test build (X.Y.Z-YYYYMMDD-HHMM) as a
    single comparable integer (YYYYMMDDHHMM). Returns None for any version that
    does not carry such a stamp (e.g. official PEP440 releases).
    """
    if version_str is None:
        return None
    match = _BUILD_STAMP_RE.search(str(version_str))
    if match is None:
        return None
    return int(match.group(1) + match.group(2))


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

        # Fork test builds (X.Y.Z-YYYYMMDD-HHMM) get updates from the fork's
        # rolling release, ranked by build timestamp rather than PEP440.
        if self.local_stamp is not None:
            return self._check_fork_rolling_update()

        if self.constants.special_build is True:
            # A special build without a build stamp has no reliable version to
            # compare, so it cannot be updated through the updater.
            return None

        if not network_handler.NetworkUtilities(REPO_LATEST_RELEASE_URL).verify_network_connection():
            return None

        response = network_handler.NetworkUtilities().get(REPO_LATEST_RELEASE_URL)
        data_set = response.json()

        if "tag_name" not in data_set:
            return None

        # The release marked as latest will always be stable, and thus, have a proper version number
        # But if not, let's not crash the program
        try:
            latest_remote_version = version.parse(data_set["tag_name"])
        except version.InvalidVersion:
            return None

        if not self._check_if_build_newer(latest_remote_version, self.binary_version):
            return None

        for asset in data_set["assets"]:
            logging.info(f"Found asset: {asset['name']}")
            if asset["name"] == "OpenCore-Patcher.pkg":
                self.latest_details = {
                    "Name": asset["name"],
                    "Version": latest_remote_version,
                    "Link": asset["browser_download_url"],
                    "Github Link": f"https://github.com/dortania/OpenCore-Legacy-Patcher/releases/{latest_remote_version}",
                }
                return self.latest_details

        return None


    def _check_fork_rolling_update(self) -> Optional[dict]:
        """
        Update path for this fork's rolling test builds (X.Y.Z-YYYYMMDD-HHMM).

        Compares the local build timestamp against the fork's rolling "latest"
        release (whose name CI sets to the build version) and returns the newer
        OpenCore-Patcher.pkg if one is available.

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
        if remote_stamp is None or remote_stamp <= self.local_stamp:
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
