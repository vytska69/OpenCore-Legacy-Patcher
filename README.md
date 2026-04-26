# ⛔ DISCONTINUED — MacBookAir8,1 / MacBookAir8,2 + macOS Sequoia via OCLP

> **This fork is no longer maintained.** All attempted approaches to make macOS Sequoia boot on MacBookAir8,1 and MacBookAir8,2 via OpenCore Legacy Patcher have been exhausted without success. The underlying problem is a hardware-level incompatibility between Apple's T2 chip firmware on these machines and macOS Sequoia's kernel. See the full technical explanation below.

---

## What this fork attempted

This was a fork of [dortania/OpenCore-Legacy-Patcher](https://github.com/dortania/OpenCore-Legacy-Patcher) with experimental patches targeting **MacBookAir8,1** (2018) and **MacBookAir8,2** (2019) — the only Intel MacBook Air models equipped with Apple's T2 security chip — to enable booting macOS Sequoia (15.x).

Apple dropped official support for these models in Sequoia. OCLP supports them up to Sonoma (14.x). This fork tried to extend that to Sequoia.

---

## What was implemented

### OpenCore config patches (`efi_builder/misc.py`)
- `AAPL,ig-platform-id = 0x87C00005` — Intel UHD 617 (Amber Lake / GT3e) framebuffer injection. Without this, bridgeOS EFI injects it at UEFI time but OpenCore does not relay EFI DeviceProperties from T2 firmware, causing the display pipeline to stall (gray screen / no verbose output).
- `igfxfw=2 igfxonln=1` — Force Intel GPU firmware load from kext and force iGPU online through the OpenCore→kernel handoff.
- `amfi=0x80 -no_compat_check` — AMFI and compat check bypass required for unsigned kext injection.
- `sep-booted` NVRAM Delete — Attempt to remove the NVRAM variable that bridgeOS writes after signalling SEP boot, to prevent AppleKeyStore from waiting forever for a SEP response.
- `SSDT-T2-SPOOF.aml` — Injects `apple-coprocessor-version` into the ACPI device tree to spoof T2 coprocessor presence to macOS.
- `XhciDxe.efi` + `UsbBusDxe.efi` — USB root device fix for T2 Mac boot path.
- `AMFIPass.kext` — Allows unsigned kexts to load with AMFI active.
- `PowerTimeoutKernelPanic`, `ProtectMemoryRegions`, `SyncRuntimePermissions` — Booter/Kernel quirks required for T2-era Apple firmware.
- OpenCore debug logging (`DisableWatchDog`, `Target=0x43`).

### Security patches (`efi_builder/security.py`)
- `SecureBootModel = Disabled` — The T2 chip's own EFI code always reports `j140kap.im4m` as its hardware Secure Boot manifest regardless of this setting. OpenCore's `SecureBootModel` does not override T2 hardware Secure Boot. Setting it to any named model (e.g. `j140k`) causes OpenCore to additionally attempt to validate `OS.dmg.root_hash` against that manifest — a file that does not exist for Sequoia on these Macs — resulting in `Err(0xE)` at every boot. Boot proceeds despite this error, but the setting was incorrect and has been removed.

### T2 Debug settings UI (`wx_gui/gui_settings.py`, `constants.py`)
A dedicated **"T2 Debug"** tab was added to OCLP's settings window with individual toggles for every T2-specific patch, allowing each to be tested independently without code changes:
- SEP Fast-fail (sep-booted NVRAM Delete)
- SSDT apple-coprocessor-version injection
- SEP Panic Patch
- IOMMU Passthrough (`DisableIoMapperMapping`)
- GPU Firmware Fix (`igfxfw=2 igfxonln=1`)
- Disable WhateverGreen
- Debug Logging (DebugEnhancer.kext + `-liludbgall`)

---

## The fundamental problem

### T2 PCIe mailbox communication failure

When macOS Sequoia boots on MacBookAir8,1/8,2 via OpenCore, the T2 chip's PCIe mailbox (BCE — Buffer Copy Engine) fails to initialise. This appears in verbose boot as a repeated DMA retry loop:

```
DMA reply ... 3 tries remaining
DMA reply ... 2 tries remaining
DMA reply ... failed
```

The T2 chip is a PCIe device (vendor `0x106b`, device `0x1801`) with:
- **BAR2** — DMA registers
- **BAR4** — mailbox registers (`+0x108` reply counter, `+0x810` reply base, `+0x820` outbound mailbox)
- Up to **8 MSI vectors** (IRQ0 = mailbox, IRQ4 = DMA), 37-bit DMA mask

On native Sonoma boot (without OCLP), the T2 communicates correctly — the hardware is not defective. When OpenCore is inserted into the boot path, something in the UEFI→kernel handoff breaks the PCIe DMA communication between the Intel CPU and the T2 chip.

### Why keybagd / AppleKeyStore hangs

With T2 mailbox communication broken, `AppleKeyStore` cannot reach the Secure Enclave Processor (SEP) inside the T2. On Sequoia, `keybagd` calls `AppleKeyStore` during early userspace initialisation. If SEP does not respond, `keybagd` blocks indefinitely — producing the characteristic **100% progress bar hang** with a spinning cursor that never becomes a login screen.

This hang occurs even with:
- FileVault **disabled**
- T2 security set to **No Security** (via Startup Security Utility)
- T2 jailbreak applied (checkm8/checkra1n)
- `sep-booted` NVRAM variable deleted
- `CryptexFixup.kext` injected
- `SecureBootModel = Disabled`

### Why this cannot be fixed from outside the kernel

The BCE driver (`AppleT2` family) is compiled into the sealed system volume's kernel collection. It cannot be replaced or patched via OpenCore kext injection at boot time without modifying the sealed volume (which requires booting macOS first — a circular dependency when macOS cannot boot).

A custom IOKit kext (`T2SEPFix.kext`) was written to remove `sep-booted` from IODTNVRAM via `waitForMatchingService` and to re-enable T2 PCIe D0 state + MSI interrupts via `mapDeviceMemoryWithRegister`. The kext source is preserved in git history (commit `66f38d5`). It was never compiled because no macOS system was available, and the GitHub Actions CI build failed before the error could be diagnosed.

---

## What was confirmed working

- Intel UHD 617 framebuffer initialises correctly with `AAPL,ig-platform-id = 0x87C00005` + `igfxfw=2 igfxonln=1` — **the gray screen is resolved**.
- OpenCore debug logging (`EFI/OC/OpenCore.txt`) produces usable boot logs.
- The T2 Debug UI tab works correctly and all toggles function as expected.

---

## Upstream issue

This is a known open issue in the main OCLP project:

**[dortania/OpenCore-Legacy-Patcher#1136](https://github.com/dortania/OpenCore-Legacy-Patcher/issues/1136)**

MacBookAir8,1 and MacBookAir8,2 are the only Intel Mac models where this problem exists. Other T2 Macs (MacBookPro15,x, Macmini8,1) work fine with OCLP on Sequoia. The difference is unknown.

If a fix is ever found upstream, this fork's OCLP patches (iGPU framebuffer, T2 Debug UI tab) remain valid and can be merged forward.

---

## Sonoma

MacBookAir8,1 and MacBookAir8,2 are **natively supported** in macOS Sonoma (14.x) — OCLP is not needed. If you are on one of these machines, use Sonoma without OCLP.
