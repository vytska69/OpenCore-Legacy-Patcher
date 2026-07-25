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

        # T2 MacBookAir8,x always needs the VMM spoof: the Sequoia installer's
        # board-id gate ("macOS Sequoia is not compatible with this Mac") is only
        # bypassed through it, and the model's Max OS is Sonoma so the gate always
        # triggers. defaults.py forces secure_status False for these models, but
        # secure_status is user-toggleable in Settings, so guarantee it here too.
        if self.model in model_array.T2_MacBookAir and "sbvmm" not in re_patch_args:
            logging.info("- T2 Mac: forcing VMM spoof for the Sequoia installer compatibility gate")
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
        #
        # NOTE: MacBookAir8,x is listed in Missing_USB_Map, but that list exists
        # for OLD Macs whose USB ports macOS no longer declares. A 2018 T2 Mac
        # has full native USB support, and its internal keyboard and trackpad are
        # USB devices behind the T2. Injecting a port map that does not declare
        # them stops them enumerating, leaving the machine with no input at all —
        # which is exactly the "stuck, cannot move" state seen on the installer's
        # language screen. Skip the map on these models.
        usb_map_path = Path(self.constants.plist_folder_path) / Path("AppleUSBMaps/Info.plist")
        if self.model in model_array.T2_MacBookAir:
            logging.info("- T2 Mac: skipping USB-Map.kext (native USB support; map can kill the internal keyboard/trackpad)")
        elif (
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
        # T2 MacBookAir8,x is included deliberately, based on hardware evidence:
        # with the REAL T2 keystore the machine now boots all the way to the login
        # screen through OpenCore and then hangs there. On a T2 the login path
        # (password verification + keybag unlock) runs through AppleKeyStore ->
        # SEP, and that mailbox handshake is exactly what fails after the OpenCore
        # handoff. Substituting the T1-era keystore stack, which never performs
        # the T2 SKS handshake, is precisely what this bypass exists for.
        #
        # Trade-off: SEP-backed features are lost (FileVault/storage keys and
        # activation/device identity). Acceptable for reaching a usable desktop;
        # to test the real keystore again, drop T2_MacBookAir from the list.
        # Toggleable for T2 (Settings > Security > "T2: use T1 keystore
        # substitution") so both keystores can be compared by rebuilding locally,
        # without waiting on a new CI build.
        _t1_models = ["MacBookPro13,2", "MacBookPro13,3", "MacBookPro14,2", "MacBookPro14,3"]
        _is_t2 = self.model in model_array.T2_MacBookAir

        if self.model not in _t1_models and not _is_t2:
            return

        if _is_t2:
            if self.constants.t2_t1_keystore is False:
                logging.info("- T2 Mac: T1 keystore substitution disabled, using the real T2 keystore")
                return
            logging.info("- T2 Mac: substituting the T1 keystore stack to bypass the SEP login hang")
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

        Booting the Sequoia installer through OpenCore on the MacBookAir8,x
        breaks the T2 SEP/AppleKeyStore handshake (sks request timeout), which
        stalls the installer (grey screen / activation). Booting WITHOUT
        OpenCore leaves the SEP working but hits the installer's board-id
        compatibility gate instead. This handler is the OpenCore-side test path:
        it exercises the REAL keystore (the T1 bypass is disabled for T2 in
        _t1_handling), forces DEBUG OpenCore + file logging in build._build_efi()
        so there is an accessible EFI/OC/opencore-*.txt and a NVRAM panic log,
        enables AMFIPass (needed for Lilu plugins under Sequoia since the model's
        Max OS is Sonoma), and injects the native Intel UHD 617 framebuffer /
        panel DeviceProperties.
        """
        if self.model not in model_array.T2_MacBookAir:
            return

        # REAL-KEYSTORE TEST (T1 bypass NOT applied — see _t1_handling):
        # The actual T2 SEP/AppleKeyStore is exercised here. DEBUG OpenCore +
        # file logging is on (build._build_efi()), so EFI/OC/opencore-*.txt is a
        # readable record for the (blind) user to verify the build, and if the
        # SEP times out it panics ("AppleSEPManager ... sks request timeout"),
        # which is saved to NVRAM (aapl,panic-info) and readable back in Sonoma.
        # DisableWatchDog stops the firmware rebooting the machine before that
        # panic is written.
        logging.info("- T2 Mac: real-keystore test (accessible logging, panic capture)")
        self.config["Misc"]["Debug"]["DisableWatchDog"] = True
        self.config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"] += " -no_compat_check"

        # Compatibility gates. The Sequoia installer refused to run with
        # "macOS Sequoia is not compatible with this Mac", so close every gate,
        # not just the kernel one that -no_compat_check covers. These are plain
        # config writes, so they are order-independent with respect to the
        # firmware/smbios builders that normally own them.
        #
        # 1. boot.efi's board-id check. smbios.py only enables this Booter patch
        #    when serial_settings == "None"; this model defaults to "Minimal" and
        #    so got the SMC exemption path instead, leaving the board-id gate up.
        #    MacBookAir8,1's real board-id (Mac-827FAC58A8FDFA22) is not in
        #    Sequoia's supported list, so the check must be skipped.
        #    The patch rewrites the string "PlatformSupport.plist" inside boot.efi
        #    to dots (Count 0, no kernel constraints), so boot.efi cannot read the
        #    supported-board list. Toggleable because it was introduced in the
        #    same commit as the CPUID bit, which broke booting; keeping it
        #    isolatable lets it be ruled in or out on its own.
        if self.constants.t2_board_id_patch is True:
            logging.info("- T2 Mac: enabling Board ID exemption patch")
            support.BuildSupport(self.model, self.constants, self.config).get_item_by_kv(
                self.config["Booter"]["Patch"], "Comment", "Skip Board ID check"
            )["Enabled"] = True

        # 2. The installer app's own model check, bypassed by looking like a VM.
        #    RestrictEvents' "sbvmm" does this dynamically (forced on for this
        #    model in _re_generate_patch_arguments). A static CPUID hypervisor bit
        #    is the stronger alternative, but on this hardware it STOPPED THE
        #    INSTALLER FROM BOOTING AT ALL — with the bit set, macOS takes VM code
        #    paths that do not hold on a real T2. It is therefore off by default
        #    and opt-in via Settings > Security, kept only for experiments.
        if self.constants.t2_vmm_cpuid is True:
            logging.info("- T2 Mac: setting CPUID VMM bit (experimental, known to break booting)")
            self.config["Kernel"]["Emulate"]["Cpuid1Data"] = binascii.unhexlify("00000000000000000000008000000000")
            self.config["Kernel"]["Emulate"]["Cpuid1Mask"] = binascii.unhexlify("00000000000000000000008000000000")

        # AMFIPass is required for injected Lilu plugins (WhateverGreen, etc.) to
        # load under Sequoia's AMFI. security.py only enables it when the model's
        # Max OS is BELOW Sonoma; the MacBookAir8,x maxes at Sonoma, so that
        # condition skips it even though we run the newer Sequoia here. Enable it
        # explicitly (idempotent — no-op if already enabled).
        if not support.BuildSupport(self.model, self.constants, self.config).get_kext_by_bundle_path("AMFIPass.kext")["Enabled"] is True:
            logging.info("- T2 Mac: enabling AMFIPass for Sequoia kext injection")
            support.BuildSupport(self.model, self.constants, self.config).enable_kext("AMFIPass.kext", self.constants.amfipass_version, self.constants.amfipass_path)

        # Native Intel UHD 617 framebuffer / panel properties, replicated exactly
        # as the genuine machine's ioreg reports them on IGPU@2. NOTE: per the
        # user's testing the grey/half-loaded UI is NOT a framebuffer problem — it
        # is the SEP/activation path failing to complete, so the UI never finishes
        # coming up. These properties are therefore only kept so the panel is
        # driven by the same values the real firmware would inject (harmless on a
        # genuine Mac, since they match the hardware); they are not expected to
        # clear the SEP-induced stall on their own.
        #
        # WhateverGreen is intentionally NOT injected: this is a genuine Mac, and
        # the native ig-platform-id 0x87C00005 already provides the correct
        # connectors (ioreg: con0 eDP type 0x02, con1/con2 DP type 0x0400). WEG
        # applies hackintosh framebuffer patches that can cause a grey-screen on
        # real Macs, so the stock AppleIntelKBLGraphicsFramebuffer is left to
        # drive the panel from the injected native properties alone.
        logging.info("- T2 Mac: injecting native Intel UHD 617 framebuffer/panel properties")
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
