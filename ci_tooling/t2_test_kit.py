"""
t2_test_kit.py: Build the MacBookAir8,x boot-chain test kit

Builds the minimal T2 EFI with the patcher's own builder, then derives one
variant per OpenCore feature under test. Each variant changes a single thing
relative to B0, so a hardware run tells which OpenCore behaviour breaks the
T2 (AppleKeyStore "sks request timeout").

Runs on macOS and Linux; macOS-only modules are stubbed, as EFI building
does not touch them.

Usage: python3 ci_tooling/t2_test_kit.py <output-folder> [--model MacBookAir8,1]
"""

import sys
import copy
import types
import shutil
import logging
import plistlib
import argparse

from pathlib import Path


REPO = Path(__file__).resolve().parent.parent

MACOS_ONLY_MODULES = [
    "objc", "CoreFoundation", "Foundation", "AppKit", "Cocoa", "SystemConfiguration", "IOKit",
    "PyObjCTools", "PyObjCTools.Conversion", "py_sip_xnu", "applescript", "pyobjc",
    "wx", "wx.adv", "wx.lib", "wx.lib.agw", "wx.lib.agw.hyperlink",
]

GUID_APPLE = "7C436110-AB2A-4BBB-A880-FE41995C9F82"


class _Anything:
    def __call__(self, *args, **kwargs):
        return _Anything()

    def __getattr__(self, name):
        return _Anything()

    def __or__(self, other):
        return 0

    __ror__ = __or__


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Anything()


def _load_patcher():
    for name in MACOS_ONLY_MODULES:
        sys.modules.setdefault(name, _StubModule(name))
    # Skip the package __init__ (it pulls in the GUI)
    package = types.ModuleType("opencore_legacy_patcher")
    package.__path__ = [str(REPO / "opencore_legacy_patcher")]
    sys.modules["opencore_legacy_patcher"] = package
    sys.path.insert(0, str(REPO))

    from opencore_legacy_patcher import constants
    from opencore_legacy_patcher.support import defaults
    from opencore_legacy_patcher.efi_builder import build
    from opencore_legacy_patcher.datasets import os_data
    return constants, defaults, build, os_data


def _variant_b1(config: dict) -> None:
    """Apple Secure Boot emulation off"""
    config["Misc"]["Security"]["SecureBootModel"] = "Disabled"


def _variant_b2(config: dict) -> None:
    """OpenCore leaves NVRAM alone"""
    config["UEFI"]["Quirks"]["RequestBootVarRouting"] = False
    config["NVRAM"]["WriteFlash"] = False
    config["NVRAM"]["Add"] = {}
    config["NVRAM"]["Delete"] = {}


def _variant_b3(config: dict) -> None:
    """B1 + B2"""
    _variant_b1(config)
    _variant_b2(config)


def _variant_b4(config: dict) -> None:
    """Firmware's own AppleBootPolicy protocol"""
    config["UEFI"]["ProtocolOverrides"]["AppleBootPolicy"] = False


def _variant_b5(config: dict) -> None:
    """No booter quirks"""
    for quirk in ["ForceBooterSignature", "ProtectSecureBoot"]:
        config["Booter"]["Quirks"][quirk] = False


def _variant_b6(config: dict) -> None:
    """IOMMU/VT-d off (the documented MacPro7,1 T2 fix)"""
    # acidanthera/bugtracker#1487: the same "macOS cannot connect to the bridge"
    # symptom on another T2 Mac (MacPro7,1) was cleared by DisableIoMapper. The
    # T2's SEP mailbox uses Apple-PCIe DMA (APCIE_EP_FIFO), so with VT-d active
    # but the SEP's DMA window missing from the IOMMU map, the mailbox DMA can
    # time out -> "sks request timeout". OCLP's config is byte-identical between
    # a working T2 Mac (Macmini8,1) and this one, so a global quirk is the only
    # lever left.
    config["Kernel"]["Quirks"]["DisableIoMapper"] = True
    config["Kernel"]["Quirks"]["DisableIoMapperMapping"] = True


VARIANTS = {
    "B0-minimalus":           (None,        "Grynas OpenCore: be kext'u ir booter patch'u (bazinis testas B)"),
    "B1-be-SecureBoot":       (_variant_b1, "B0 + SecureBootModel Disabled (OpenCore neemuliuoja Apple Secure Boot)"),
    "B2-be-NVRAM":            (_variant_b2, "B0 + OpenCore nieko nerasyo ir neperima NVRAM"),
    "B3-be-SecureBoot-NVRAM": (_variant_b3, "B1 ir B2 kartu (artimiausia natūraliam bootinimui)"),
    "B4-be-BootPolicy":       (_variant_b4, "B0 + firmware'o AppleBootPolicy protokolas"),
    "B5-be-booter-quirks":    (_variant_b5, "B0 + be ForceBooterSignature ir ProtectSecureBoot"),
    "B6-be-IOMMU":            (_variant_b6, "B0 + DisableIoMapper (dokumentuotas MacPro7,1 T2 pataisymas, acidanthera#1487)"),
}


def build_base(model: str) -> Path:
    constants, defaults, build, os_data = _load_patcher()
    Path("/Users/Shared").mkdir(parents=True, exist_ok=True)

    c = constants.Constants()
    c.custom_model = model
    c.computer = None
    c.detected_os = os_data.os_data.sonoma
    defaults.GenerateDefaults(model, False, c)
    assert c.t2_minimal_boot is True and c.boot_efi is True, "T2 minimal defaults not applied"
    build.BuildOpenCore(model, c)
    return Path(c.opencore_release_folder)


def lay_out_variant(base: Path, out: Path, name: str, edit) -> None:
    target = out / name
    shutil.copytree(base / "EFI", target / "EFI")
    (target / "EFI" / "BOOT").mkdir(exist_ok=True)
    shutil.copy(base / "System/Library/CoreServices/boot.efi", target / "EFI/BOOT/BOOTx64.efi")
    # Unreferenced kext bundles left by the builder: keep the USB minimal
    shutil.rmtree(target / "EFI/OC/Kexts", ignore_errors=True)
    (target / "EFI/OC/Kexts").mkdir()
    for junk in target.rglob(".DS_Store"):
        junk.unlink()

    config_path = target / "EFI/OC/config.plist"
    config = plistlib.load(config_path.open("rb"))
    assert config["Kernel"]["Add"] == [] and config["Booter"]["Patch"] == [], "base is not minimal"
    # OCLP adds this on purpose outside its own CI validation; OpenCore finds Windows without it
    config["Misc"]["BlessOverride"] = [b for b in config["Misc"]["BlessOverride"] if b != "\\EFI\\Microsoft\\Boot\\bootmgfw.efi"]
    if edit:
        edit(config)
    plistlib.dump(config, config_path.open("wb"), sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--model", default="MacBookAir8,1")
    args = parser.parse_args()
    # The patcher parses sys.argv on import
    sys.argv = sys.argv[:1]

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out = Path(args.output).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    base = build_base(args.model)
    for name, (edit, _description) in VARIANTS.items():
        lay_out_variant(base, out, name, edit)
        logging.info(f"- Variant ready: {name}")

    for extra in ["SKAITYK-PIRMA.txt", "collect.sh"]:
        shutil.copy(REPO / "ci_tooling/t2_test_kit" / extra, out / extra)
    (out / "collect.sh").chmod(0o755)

    with (out / "VARIANTAI.txt").open("w") as f:
        for name, (_edit, description) in VARIANTS.items():
            f.write(f"{name}: {description}\n")

    logging.info(f"Test kit built at: {out}")


if __name__ == "__main__":
    main()
