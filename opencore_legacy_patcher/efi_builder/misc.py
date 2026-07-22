"""
misc.py: Class for handling Misc Patches, invocation from build.py
"""

import shutil
import logging
import binascii

from pathlib import Path

from . import support

from .. import constants

from ..support import generate_smbios
from ..detections import device_probe

from ..datasets import (
    model_array,
    smbios_data,
    cpu_data,
    os_data
)


class BuildMiscellaneous:
    """
    Build Library for Miscellaneous Hardware and Software Support

    Invoke from build.py
    """

    def __init__(self, model: str, global_constants: constants.Constants, config: dict) -> None:
        self.model: str = model
        self.config: dict = config
        self.constants: constants.Constants = global_constants
        self.computer: device_probe.Computer = self.constants.computer

        self._build()


    def _build(self) -> None:
        """
        Kick off Misc Build Process
        """

        self._feature_unlock_handling()
        self._restrict_events_handling()
        self._firewire_handling()
        self._topcase_handling()
        self._thunderbolt_handling()
        self._webcam_handling()
        self._usb_handling()
        self._debug_handling()
        self._cpu_friend_handling()
        self._general_oc_handling()
        self._t1_handling()
        self._t2_handling()


    def _feature_unlock_handling(self) -> None:
        """
        FeatureUnlock Handler
        """

        if self.constants.fu_status is False:
            return

        if not self.model in smbios_data.smbios_dictionary:
            return

        if smbios_data.smbios_dictionary[self.model]["Max OS Supported"] >= os_data.os_data.sonoma:
            return

        support.BuildSupport(self.model, self.constants, self.config).enable_kext("FeatureUnlock.kext", self.constants.featureunlock_version, self.constants.featureunlock_path)
        if self.constants.fu_arguments is not None and self.constants.fu_arguments != "":
            logging.info(f"- Adding additional FeatureUnlock args: {self.constants.fu_arguments}")
            self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += self.constants.fu_arguments


    def _restrict_events_handling(self) -> None:
        """
        RestrictEvents Handler
        """

        block_args = ",".join(self._re_generate_block_arguments())
        patch_args = ",".join(self._re_generate_patch_arguments())

        if block_args != "":
            logging.info(f"- Setting RestrictEvents block arguments: {block_args}")
            support.BuildSupport(self.model, self.constants, self.config).enable_kext("RestrictEvents.kext", self.constants.restrictevents_version, self.constants.restrictevents_path)
            self.config["NVRAM"]["Add"]["4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"]["revblock"] = block_args

        if block_args != "" and patch_args == "":
            # Disable unneeded Userspace patching (cs_validate_page is quite expensive)
            patch_args = "none"

        if patch_args != "":
            logging.info(f"- Setting RestrictEvents patch arguments: {patch_args}")
            support.BuildSupport(self.model, self.constants, self.config).enable_kext("RestrictEvents.kext", self.constants.restrictevents_version, self.constants.restrictevents_path)
            self.config["NVRAM"]["Add"]["4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"]["revpatch"] = patch_args

        if support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("RestrictEvents.kext")["Enabled"] is False:
            # Ensure this is done at the end so all previous RestrictEvents patches are applied
            # RestrictEvents and EFICheckDisabler will conflict if both are injected
            support.BuildSupport(self.model, self.constants, self.config).enable_kext("EFICheckDisabler.kext", "", self.constants.efi_disabler_path)


    def _re_generate_block_arguments(self) -> list:
        """
        Generate RestrictEvents block arguments

        Returns:
            list: RestrictEvents block arguments
        """

        re_block_args = []

        # Resolve GMUX switching in Big Sur+
        if self.model in ["MacBookPro6,1", "MacBookPro6,2", "MacBookPro9,1", "MacBookPro10,1"]:
            re_block_args.append("gmux")

        # Resolve memory error reporting on MacPro7,1 SMBIOS
        if self.model in model_array.MacPro:
            logging.info("- Disabling memory error reporting")
            re_block_args.append("pcie")

        # Resolve mediaanalysisd crashing on 3802 GPUs
        # Applicable for systems that are the primary iCloud Photos library host, with large amounts of unprocessed faces
        if self.constants.disable_mediaanalysisd is True:
            logging.info("- Disabling mediaanalysisd")
            re_block_args.append("media")

        return re_block_args


    def _re_generate_patch_arguments(self) -> list:
        """
        Generate RestrictEvents patch arguments

        Returns:
            list: Patch arguments
        """

        re_patch_args = []

        # Alternative approach to the kern.hv_vmm_present patch
        # Dynamically sets the property to 1 if software update/installer is detected
        # Always enabled in installers/recovery environments
        if self.constants.allow_oc_everywhere is False and (self.constants.serial_settings == "None" or self.constants.secure_status is False):
            re_patch_args.append("sbvmm")

        # Resolve CoreGraphics.framework crashing on Ivy Bridge in macOS 13.3+
        # Ref: https://github.com/acidanthera/RestrictEvents/pull/12
        if smbios_data.smbios_dictionary[self.model]["CPU Generation"] == cpu_data.CPUGen.ivy_bridge.value:
            logging.info("- Fixing CoreGraphics support on Ivy Bridge")
            re_patch_args.append("f16c")

        # Patch AVX hardcoding in JavaScriptCore
        if smbios_data.smbios_dictionary[self.model]["CPU Generation"] < cpu_data.CPUGen.sandy_bridge.value:
            logging.info("- Fixing AVX hardcoding in JavaScriptCore")
            re_patch_args.append("jsc")

        return re_patch_args


    def _cpu_friend_handling(self) -> None:
        """
        CPUFriend Handler
        """

        if self.constants.allow_oc_everywhere is False and self.model not in ["iMac7,1", "Xserve2,1", "Dortania1,1"] and self.constants.disallow_cpufriend is False and self.constants.serial_settings != "None":
            support.BuildSupport(self.model, self.constants, self.config).enable_kext("CPUFriend.kext", self.constants.cpufriend_version, self.constants.cpufriend_path)

            # CPUFriendDataProvider handling
            pp_map_path = Path(self.constants.platform_plugin_plist_path) / Path(f"{self.model}/Info.plist")
            if not pp_map_path.exists():
                raise Exception(f"{pp_map_path} does not exist!!! Please file an issue stating file is missing for {self.model}.")
            Path(self.constants.pp_kext_folder).mkdir()
            Path(self.constants.pp_contents_folder).mkdir()
            shutil.copy(pp_map_path, self.constants.pp_contents_folder)
            support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("CPUFriendDataProvider.kext")["Enabled"] = True


    def _firewire_handling(self) -> None:
        """
        FireWire Handler
        """

        if self.constants.firewire_boot is False:
            return
        if generate_smbios.check_firewire(self.model) is False:
            return

        # Enable FireWire Boot Support
        # Applicable for both native FireWire and Thunderbolt to FireWire adapters
        logging.info("- Enabling FireWire Boot Support")
        support.BuildSupport(self.model, self.constants, self.config).enable_kext("IOFireWireFamily.kext", self.constants.fw_kext, self.constants.fw_family_path)
        support.BuildSupport(self.model, self.constants, self.config).enable_kext("IOFireWireSBP2.kext", self.constants.fw_kext, self.constants.fw_sbp2_path)
        support.BuildSupport(self.model, self.constants, self.config).enable_kext("IOFireWireSerialBusProtocolTransport.kext", self.constants.fw_kext, self.constants.fw_bus_path)
        support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("IOFireWireFamily.kext/Contents/PlugIns/AppleFWOHCI.kext")["Enabled"] = True


    def _topcase_handling(self) -> None:
        """
        USB/SPI Top Case Handler
        """

        # macOS 14.4 Beta 1 strips SPI-based top case support for Broadwell through Kaby Lake MacBooks (and MacBookAir6,x)
        if self.model.startswith("MacBook") and self.model in smbios_data.smbios_dictionary:
            if self.model.startswith("MacBookAir6") or (cpu_data.CPUGen.broadwell <= smbios_data.smbios_dictionary[self.model]["CPU Generation"] <= cpu_data.CPUGen.kaby_lake):
                logging.info("- Enabling SPI-based top case support")
                support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleHSSPISupport.kext", self.constants.apple_spi_version, self.constants.apple_spi_path)
                support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleHSSPIHIDDriver.kext", self.constants.apple_spi_hid_version, self.constants.apple_spi_hid_path)
                support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleTopCaseInjector.kext", self.constants.topcase_inj_version, self.constants.top_case_inj_path)


        #On-device probing
        if not self.constants.custom_model and self.computer.internal_keyboard_type and self.computer.trackpad_type:

            support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleUSBTopCase.kext", self.constants.topcase_version, self.constants.top_case_path)
            support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("AppleUSBTopCase.kext/Contents/PlugIns/AppleUSBTCButtons.kext")["Enabled"] = True
            support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("AppleUSBTopCase.kext/Contents/PlugIns/AppleUSBTCKeyboard.kext")["Enabled"] = True
            support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("AppleUSBTopCase.kext/Contents/PlugIns/AppleUSBTCKeyEventDriver.kext")["Enabled"] = True

            if self.computer.internal_keyboard_type == "Legacy":
                support.BuildSupport(self.model, self.constants, self.config).enable_kext("LegacyKeyboardInjector.kext", self.constants.legacy_keyboard, self.constants.legacy_keyboard_path)
            if self.computer.trackpad_type == "Legacy":
                support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleUSBTrackpad.kext", self.constants.apple_trackpad, self.constants.apple_trackpad_path)
            elif self.computer.trackpad_type == "Modern":
                support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleUSBMultitouch.kext", self.constants.multitouch_version, self.constants.multitouch_path)

        #Predefined fallback
        else:
            # Multi Touch Top Case support for macOS Ventura+
            if smbios_data.smbios_dictionary[self.model]["CPU Generation"] < cpu_data.CPUGen.skylake.value:
                if self.model.startswith("MacBook"):
                    # These units got the Force Touch top case, so ignore them
                    if self.model not in ["MacBookPro11,4", "MacBookPro11,5", "MacBookPro12,1", "MacBook8,1"]:
                        support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleUSBTopCase.kext", self.constants.topcase_version, self.constants.top_case_path)
                        support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("AppleUSBTopCase.kext/Contents/PlugIns/AppleUSBTCButtons.kext")["Enabled"] = True
                        support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("AppleUSBTopCase.kext/Contents/PlugIns/AppleUSBTCKeyboard.kext")["Enabled"] = True
                        support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("AppleUSBTopCase.kext/Contents/PlugIns/AppleUSBTCKeyEventDriver.kext")["Enabled"] = True
                        support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleUSBMultitouch.kext", self.constants.multitouch_version, self.constants.multitouch_path)

            # Two-finger Top Case support for macOS High Sierra+
            if self.model == "MacBook5,2":
                support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleUSBTrackpad.kext", self.constants.apple_trackpad, self.constants.apple_trackpad_path) # Also requires AppleUSBTopCase.kext
                support.BuildSupport(self.model, self.constants, self.config).enable_kext("LegacyKeyboardInjector.kext", self.constants.legacy_keyboard, self.constants.legacy_keyboard_path) # Inject legacy personalities into AppleUSBTCKeyboard and AppleUSBTCKeyEventDriver


    def _thunderbolt_handling(self) -> None:
        """
        Thunderbolt Handler
        """

        if self.constants.disable_tb is True and self.model in ["MacBookPro11,1", "MacBookPro11,2", "MacBookPro11,3", "MacBookPro11,4", "MacBookPro11,5"]:
            logging.info("- Disabling 2013-2014 laptop Thunderbolt Controller")
            if self.model in ["MacBookPro11,3", "MacBookPro11,5"]:
                # 15" dGPU models: IOACPIPlane:/_SB/PCI0@0/PEG1@10001/UPSB@0/DSB0@0/NHI0@0
                tb_device_path = "PciRoot(0x0)/Pci(0x1,0x1)/Pci(0x0,0x0)/Pci(0x0,0x0)/Pci(0x0,0x0)"
            else:
                # 13" and 15" iGPU 2013-2014 models: IOACPIPlane:/_SB/PCI0@0/P0P2@10000/UPSB@0/DSB0@0/NHI0@0
                tb_device_path = "PciRoot(0x0)/Pci(0x1,0x0)/Pci(0x0,0x0)/Pci(0x0,0x0)/Pci(0x0,0x0)"

            self.config["DeviceProperties"]["Add"][tb_device_path] = {"class-code": binascii.unhexlify("FFFFFFFF"), "device-id": binascii.unhexlify("FFFF0000")}


    def _webcam_handling(self) -> None:
        """
        iSight Handler
        """
        if self.model in smbios_data.smbios_dictionary:
            if "Legacy iSight" in smbios_data.smbios_dictionary[self.model]:
                if smbios_data.smbios_dictionary[self.model]["Legacy iSight"] is True:
                    support.BuildSupport(self.model, self.constants, self.config).enable_kext("LegacyUSBVideoSupport.kext", self.constants.apple_isight_version, self.constants.apple_isight_path)

        if not self.constants.custom_model:
            if self.constants.computer.pcie_webcam is True:
                support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleCameraInterface.kext", self.constants.apple_camera_version, self.constants.apple_camera_path)
        else:
            if self.model.startswith("MacBook") and self.model in smbios_data.smbios_dictionary:
                if cpu_data.CPUGen.haswell <= smbios_data.smbios_dictionary[self.model]["CPU Generation"] <= cpu_data.CPUGen.kaby_lake:
                    support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleCameraInterface.kext", self.constants.apple_camera_version, self.constants.apple_camera_path)


    def _usb_handling(self) -> None:
        """
        USB Handler
        """

        # USB Map
        usb_map_path = Path(self.constants.plist_folder_path) / Path("AppleUSBMaps/Info.plist")
        if (
            usb_map_path.exists()
            and (self.constants.allow_oc_everywhere is False or self.constants.allow_native_spoofs is True)
            and self.model not in ["Xserve2,1", "Dortania1,1"]
            and (
                (self.model in model_array.Missing_USB_Map or self.model in model_array.Missing_USB_Map_Ventura)
                or self.constants.serial_settings in ["Moderate", "Advanced"])
        ):
            logging.info("- Adding USB-Map.kext")
            Path(self.constants.map_kext_folder).mkdir()
            Path(self.constants.map_contents_folder).mkdir()
            shutil.copy(usb_map_path, self.constants.map_contents_folder)
            support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("USB-Map.kext")["Enabled"] = True
            if self.model in model_array.Missing_USB_Map_Ventura and self.constants.serial_settings not in ["Moderate", "Advanced"]:
                support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("USB-Map.kext")["MinKernel"] = "22.0.0"

        # Add UHCI/OHCI drivers
        # All Penryn Macs lack an internal USB hub to route USB 1.1 devices to the EHCI controller
        # And MacPro4,1, MacPro5,1 and Xserve3,1 are the only post-Penryn Macs that lack an internal USB hub
        # - Ref: https://techcommunity.microsoft.com/t5/microsoft-usb-blog/reasons-to-avoid-companion-controllers/ba-p/270710
        #
        # To be paired for usb11.py's 'Legacy USB 1.1' patchset
        #
        # Note: With macOS 14.1, injection of these kexts causes a panic.
        #       To avoid this, a MaxKernel is configured with XNU 23.0.0 (macOS 14.0).
        #       Additionally sys_patch.py stack will now patches the bins onto disk for 14.1+.
        #       Reason for keeping the dual logic is due to potential conflicts of in-cache vs injection if we start
        #       patching pre-14.1 hosts.
        if (
            smbios_data.smbios_dictionary[self.model]["CPU Generation"] <= cpu_data.CPUGen.penryn.value or \
            self.model in ["MacPro4,1", "MacPro5,1", "Xserve3,1"]
        ):
            logging.info("- Adding UHCI/OHCI USB support")
            shutil.copy(self.constants.apple_usb_11_injector_path, self.constants.kexts_path)
            support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("USB1.1-Injector.kext/Contents/PlugIns/AppleUSBOHCI.kext")["Enabled"] = True
            support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("USB1.1-Injector.kext/Contents/PlugIns/AppleUSBOHCIPCI.kext")["Enabled"] = True
            support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("USB1.1-Injector.kext/Contents/PlugIns/AppleUSBUHCI.kext")["Enabled"] = True
            support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("USB1.1-Injector.kext/Contents/PlugIns/AppleUSBUHCIPCI.kext")["Enabled"] = True


    def _debug_handling(self) -> None:
        """
        Debug Handler for OpenCorePkg and Kernel Space
        """

        if self.constants.verbose_debug is True:
            logging.info("- Enabling Verbose boot")
            self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += " -v"

        if self.constants.kext_debug is True:
            logging.info("- Enabling DEBUG Kexts")
            self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += " -liludbgall liludump=90"
            # Disabled due to macOS Monterey crashing shortly after kernel init
            # Use DebugEnhancer.kext instead
            # self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += " msgbuf=1048576"
            support.BuildSupport(self.model, self.constants, self.config).enable_kext("DebugEnhancer.kext", self.constants.debugenhancer_version, self.constants.debugenhancer_path)

        if self.constants.opencore_debug is True:
            logging.info("- Enabling DEBUG OpenCore")
            self.config["Misc"]["Debug"]["Target"] = 0x43
            self.config["Misc"]["Debug"]["DisplayLevel"] = 0x80000042


    def _general_oc_handling(self) -> None:
        """
        General OpenCorePkg Handler
        """

        logging.info("- Adding OpenCanopy GUI")
        shutil.copy(self.constants.gui_path, self.constants.oc_folder)
        support.BuildSupport(self.model, self.constants, self.config).get_efi_binary_by_path("OpenCanopy.efi", "UEFI", "Drivers")["Enabled"] = True
        support.BuildSupport(self.model, self.constants, self.config).get_efi_binary_by_path("OpenRuntime.efi", "UEFI", "Drivers")["Enabled"] = True
        support.BuildSupport(self.model, self.constants, self.config).get_efi_binary_by_path("OpenLinuxBoot.efi", "UEFI", "Drivers")["Enabled"] = True
        support.BuildSupport(self.model, self.constants, self.config).get_efi_binary_by_path("ResetNvramEntry.efi", "UEFI", "Drivers")["Enabled"] = True

        if self.constants.showpicker is False:
            logging.info("- Hiding OpenCore picker")
            self.config["Misc"]["Boot"]["ShowPicker"] = False

        if self.constants.oc_timeout != 5:
            logging.info(f"- Setting custom OpenCore picker timeout to {self.constants.oc_timeout} seconds")
            self.config["Misc"]["Boot"]["Timeout"] = self.constants.oc_timeout

        if self.constants.vault is True:
            logging.info("- Setting Vault configuration")
            self.config["Misc"]["Security"]["Vault"] = "Secure"

    def _t1_handling(self) -> None:
        """
        T1 Security Chip Handler

        Also applied to the MacBookAir8,x (T2) as an experimental SEP bypass.
        The native T2 keystore stack (AppleKeyStore/AppleSSE/AppleCredential-
        Manager) drives the Secure Enclave over the SEP mailbox, and on these
        models that handshake times out after ExitBootServices
        (AppleSEPManagerIntel.cpp:809). Substituting the older T1-era keystore
        stack — the same one OCLP injects on genuine T1 Macs, which does not
        perform the T2 SKS mailbox handshake — is the most principled attempt
        at getting past that hang, and is what an April 2026 build test used
        (confirmed reaching EXITBS in its OpenCore log). Whether it clears the
        post-EXITBS SEP timeout must be verified on hardware.
        """
        _t1_models = ["MacBookPro13,2", "MacBookPro13,3", "MacBookPro14,2", "MacBookPro14,3"]
        if self.model not in _t1_models and self.model not in model_array.T2_MacBookAir:
            return

        if self.model in model_array.T2_MacBookAir:
            logging.info("- Substituting T1 keystore stack on T2 Mac (SEP bypass attempt)")
        else:
            logging.info("- Enabling T1 Security Chip support")

        support.BuildSupport(self.model, self.constants, self.config).get_item_by_kv(self.config["Kernel"]["Block"], "Identifier", "com.apple.driver.AppleSSE")["Enabled"] = True
        support.BuildSupport(self.model, self.constants, self.config).get_item_by_kv(self.config["Kernel"]["Block"], "Identifier", "com.apple.driver.AppleKeyStore")["Enabled"] = True
        support.BuildSupport(self.model, self.constants, self.config).get_item_by_kv(self.config["Kernel"]["Block"], "Identifier", "com.apple.driver.AppleCredentialManager")["Enabled"] = True

        support.BuildSupport(self.model, self.constants, self.config).enable_kext("corecrypto_T1.kext", self.constants.t1_corecrypto_version, self.constants.t1_corecrypto_path)
        support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleSSE.kext", self.constants.t1_sse_version, self.constants.t1_sse_path)
        support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleKeyStore.kext", self.constants.t1_key_store_version, self.constants.t1_key_store_path)
        support.BuildSupport(self.model, self.constants, self.config).enable_kext("AppleCredentialManager.kext", self.constants.t1_credential_version, self.constants.t1_credential_path)
        support.BuildSupport(self.model, self.constants, self.config).enable_kext("KernelRelayHost.kext", self.constants.kernel_relay_version, self.constants.kernel_relay_path)


    def _t2_handling(self) -> None:
        """
        T2 Security Chip Handler (MacBookAir8,1 / 8,2) — diagnostic build

        Booting macOS through OpenCore on these models is a known-unsolved
        problem. On a T2 Mac the Secure Enclave firmware blob is left in a
        reserved memory region by iBoot/bridgeOS, and the macOS kernel must
        re-load and re-bootstrap the SEP across the boot.efi -> kernel
        handoff. On the MacBookAir8,x specifically that handoff fails, so
        AppleKeyStore's SKS requests to the SEP time out and panic:

            "AppleSEPManager panic for "AppleKeyStore": sks request timeout"
            @AppleSEPManagerIntel.cpp:809

        This is a firmware-level handoff failure below macOS; it cannot be
        fixed from injected kexts, ACPI, or boot-args (patching out the panic
        only converts it into a silent hang, since AppleKeyStore still has no
        keys). Other T2 models (MacBookPro15,2, Macmini8,1) survive the same
        handoff, so the fault is specific to the Air's firmware.

        Rather than ship futile boot patches, this handler configures DEBUG
        OpenCore file logging so the pre-ExitBootServices memory map — where
        RebuildAppleMemoryMap decides the fate of the bridgeOS/SEP reserved
        region — is captured to a file on the ESP for offline analysis. DEBUG
        OpenCore itself is selected in build._build_efi(), which runs before
        the OpenCore binaries are copied.
        """
        if self.model not in model_array.T2_MacBookAir:
            return

        # DEBUG OpenCore is selected in build._build_efi() (opencore_debug),
        # which makes _debug_handling() set Misc/Debug/Target 0x43 (console +
        # dated file on the ESP, EFI/OC/opencore-*.txt) and DisplayLevel
        # 0x80000042 — the latter includes DEBUG_INFO (0x40), the level at
        # which OcAfterBootCompatLib prints the memory map. Here we only add
        # DisableWatchDog so the firmware watchdog does not reboot the machine
        # while the long memory-map dump is being written before ExitBootServices.
        logging.info("- T2 Mac: disabling watchdog so the memory-map dump completes")
        self.config["Misc"]["Debug"]["DisableWatchDog"] = True

        # -no_compat_check lets the Sequoia installer proceed past the model
        # check so the boot reaches the memory-map handoff before the SEP
        # timeout. Verbose (-v) is forced separately via verbose_debug in
        # build._build_efi(), so it is not added here (avoids a duplicate -v).
        logging.info("- T2 Mac: adding -no_compat_check for the Sequoia installer")
        self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += " -no_compat_check"

        # With the T1 keystore stack in place the SEP hang is cleared and the
        # machine now reaches WindowServer — but shows a grey screen with only the
        # mouse cursor, because OpenCore does not relay the framebuffer
        # DeviceProperties that bridgeOS injects at UEFI time, so
        # AppleIntelKBLGraphicsFramebuffer comes up without a framebuffer/panel
        # config. Injecting AAPL,ig-platform-id alone is not enough (already tried);
        # the genuine hardware also carries the panel power sequence, Y-tiling and
        # graphic-options. Replicate the FULL set exactly as the real machine's
        # ioreg reports it on IGPU@2.
        #
        # WhateverGreen is intentionally NOT injected: this is a genuine Mac, and
        # the native ig-platform-id 0x87C00005 already provides the correct
        # connectors (ioreg: con0 eDP type 0x02, con1/con2 DP type 0x0400). WEG
        # applies hackintosh framebuffer patches that commonly cause exactly this
        # grey-screen on real Macs, so the stock AppleIntelKBLGraphicsFramebuffer
        # is left to drive the panel from the injected native properties alone.
        logging.info("- T2 Mac: injecting full Intel UHD 617 framebuffer/panel properties (grey-screen fix)")
        igpu_path = "PciRoot(0x0)/Pci(0x2,0x0)"
        if igpu_path not in self.config["DeviceProperties"]["Add"]:
            self.config["DeviceProperties"]["Add"][igpu_path] = {}
        _igpu_props = {
            "AAPL,ig-platform-id":    "0500C087",  # framebuffer id (0x87C00005)
            "AAPL,GfxYTile":          "01000000",
            "graphic-options":        "0C000000",
            "AAPL00,PanelPowerOn":    "19010000",  # eDP panel power-up sequencing
            "AAPL00,PanelPowerUp":    "30000000",
            "AAPL00,PanelPowerDown":  "3C000000",
            "AAPL00,PanelPowerOff":   "11000000",
            "AAPL00,PanelCycleDelay": "FA000000",
        }
        for _key, _hex in _igpu_props.items():
            self.config["DeviceProperties"]["Add"][igpu_path][_key] = binascii.unhexlify(_hex)
