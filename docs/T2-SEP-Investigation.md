# T2 (MacBookAir8,x) SEP boot investigation

Goal: get a **fully working OpenCore Legacy Patcher boot/install of macOS
Sequoia** on the MacBookAir8,1 / 8,2 (Amber Lake, Apple T2 / T8012), which
natively supports only up to Sonoma.

This document is the single place where every useful finding is collected, so
that once enough data is gathered the picture is complete enough to act on. It
is written to be read with a screen reader — every section has a heading, and
there are no screenshots or diagrams that require sight.

---

## 1. The exact failure

When the Sequoia installer (or macOS) is booted **through OpenCore** on a
MacBookAir8,x, the Secure Enclave handshake fails shortly after
ExitBootServices:

```
AppleSEPManager panic for "AppleKeyStore": sks request timeout
@AppleSEPManagerIntel.cpp:809
```

- `sks` = Secure Key Store. `AppleKeyStore` asks the SEP (over the SEP mailbox)
  to service a key-store request; the SEP never answers in time, so the driver
  times out.
- Depending on quirks it either **panics** (writes `aapl,panic-info` to NVRAM,
  readable back in Sonoma) or **silently hangs** (grey screen with a movable
  mouse, UI never finishes — this is the state the user actually sees).
- The user confirmed the grey screen is **not** a framebuffer/GPU problem: the
  UI simply never finishes coming up because the SEP/activation path stalls.

## 2. What WORKS (the crucial asymmetry)

- **Booting the installer WITHOUT OpenCore**: the SEP works, VoiceOver works,
  the GUI renders, and the installer even asks for a password. It then stops at
  the installer's own **board-id compatibility gate** ("macOS Sequoia is not
  compatible with this Mac"). So the SEP itself is fine — OpenCore's *presence*
  is what breaks it.
- **Other T2 models** (Macmini8,1, MacBookPro15,2) survive the same OpenCore
  handoff. So the fault is **specific to the Air's firmware**, not to T2 in
  general. This is the single most important clue.

## 3. Why OpenCore breaks it — hypotheses (unconfirmed)

The SEP firmware blob is left in a reserved memory region by iBoot/bridgeOS,
and the kernel re-bootstraps the SEP across the boot.efi → kernel handoff.
Candidate reasons the Air specifically fails only under OpenCore:

1. **Memory map / reserved-region handling** — OpenCore's
   `RebuildAppleMemoryMap` / `OcAfterBootCompatLib` reshuffles the UEFI memory
   map and KASLR. If the Air's bridgeOS marks the SEP mailbox / reserved region
   differently from other T2 models, OpenCore may relocate or mis-describe it.
   (Source review confirmed OcAfterBootCompatLib does not *intentionally* touch
   SEP/MSI/interrupts — but it does rewrite the memory map, which is adjacent.)
2. **Board-id duplication under SMBIOS spoof** — with SMBIOS spoofing the
   machine exposes two board-ids (real from T2 + spoofed); this is a documented
   red flag that can wedge the KeyStore. Real board-id: `Mac-827FAC58A8FDFA22`.
3. **Timing** — the SEP mailbox may have a tighter post-EXITBS deadline on the
   Air; the extra work OpenCore does before handoff could blow it.

None of these is proven. Hypothesis (1) or (2) is most likely because the fault
is firmware-specific and triggered purely by OpenCore's presence.

## 4. The one known bypass — T1 keystore substitution

OCLP's `_t1_handling` can block the T2 keystore stack (AppleKeyStore / AppleSSE
/ AppleCredentialManager) and inject the **T1-era** keystore + `corecrypto_T1`
+ `KernelRelayHost`. That older stack does **not** perform the T2 SKS mailbox
handshake, so it slips past the timeout.

- **Pro**: clears the SEP hang; an April-2026 build reached EXITBS this way.
- **Con**: loses everything the SEP provides — storage-encryption keys and
  activation/device-identity. The internal (SEP-backed ANS2) disk is unusable
  without the SEP; only an external/USB target can work.

This is currently the **only** real lever we have, and it is a bypass, not a
fix. It is gated per-model in `misc.py::_t1_handling`.

## 5. The analytical lever that could actually crack it

Because the machine **works natively and breaks only under OpenCore**, the
answer is in the **difference** between those two states. The plan:

1. Capture a full snapshot **natively** (no OpenCore — SEP alive): the SEP /
   AppleKeyStore ioreg nodes, memory map, board-id, boot-args, kexts, logs.
2. Capture a full snapshot **after an OpenCore boot attempt** (from the NVRAM
   panic / preoslog + OpenCore's own log + whatever ioreg is reachable).
3. **Diff** them. The delta — which SEP/mailbox property or memory descriptor
   changed, or which board-id/quirk differs — is the concrete thing to target.

The in-app collectors exist to build exactly this dataset (see §6).

## 6. Data-collection protocol (what to gather, using the app)

All buttons are in **Settings → Developer** (the tab is always shown now) and
write plain, heading-delimited text so they are fully screen-reader accessible.

- **Save T2 / SEP info report** — the live SEP subsystem state (hardware + T2
  controller, board-id, boot-args, the SEP/AppleKeyStore ioreg nodes, loaded
  keystore kexts, recent SEP kernel log). Run this **natively in Sonoma** for
  the known-good baseline.
- **Save T2 boot diagnostics** — NVRAM `AAPL,preoslog` + `aapl,panic-info`,
  kernel panic reports, and the OpenCore log + SysReport from a mounted EFI.
  Run this **back in Sonoma after a failed OpenCore boot** to capture the
  broken side.
- **Collect T2 master bundle** — one labelled folder ("native" or "opencore")
  bundling everything above plus the full ioreg / system_profiler / all NVRAM /
  the config.plist actually in use, so two snapshots can be diffed directly.

Checklist to reach a complete dataset:

- [ ] Native master bundle (label: `native`), SEP alive.
- [ ] OpenCore-boot master bundle (label: `opencore`), captured back in Sonoma.
- [ ] The OpenCore `opencore-*.txt` DEBUG log from the failed boot (T2 builds
      force DEBUG + file logging, so this exists on the ESP).
- [ ] NVRAM `aapl,panic-info` from the failed boot (present if it panicked
      rather than silently hung).

## 7. Decision tree / next steps

- If the diff points at a **memory-map / reserved-region** difference → try
  OpenCore quirks around the memory map for this model, and compare against the
  Macmini8,1 map (a T2 model that survives).
- If it points at **board-id duplication** → avoid SMBIOS spoof for this model
  and inject compatibility another way (the installer board-id gate, not the
  kernel `-no_compat_check`).
- If the SEP simply cannot be handed off under OpenCore on this firmware →
  the **T1 keystore bypass to an external target** is the realistic path to a
  *booting* (if SEP-limited) install, and native **Sonoma** remains the
  guaranteed fully-working fallback.

## 7a. Findings from the native baseline (2026-07-25)

First `native` master bundle captured on the actual MacBookAir8,1 (SEP alive):

- **Identity**: board-id `Mac-827FAC58A8FDFA22`, bridge-model `J140kAP`, serial
  `FVFYJ0BKJK7L`, `apple-coprocessor-version = 0x00020000`, T2 firmware
  `23P5067` / iBridge `23.16.15067`.
- **The whole genuine SEP stack is healthy**: AppleSEPIntelIOP → `iop-nub,sep`
  → AppleSEPManager, plus AppleKeyStore (59 retains, many user clients),
  AppleCredentialManager, AppleSSE, AppleFDEKeyStore, AppleEffaceableStorage /
  AppleEffaceableNOR, ANS2 — all registered/matched/active. **No** T1
  substitution kexts (this is the real T2 stack).
- **🔴 Activation Lock is ENABLED, and the T2 is bound to an iCloud account.**
  NVRAM carries `fm-activation-locked`, `fm-spstatus`,
  `fmm-mobileme-token-FMM` and, crucially,
  `fmm-mobileme-token-FMM-BridgeHasAccount`. So during boot the SEP + Find My
  actively enforce device identity tied to the real serial/board-id and an
  Apple ID. This matches the user's own observation that the failed boot heads
  toward an activation-lock / password step and then stalls.

Implication: the SEP is fully functional and identity-locked to the machine's
**real** identity. Anything that makes the machine present a different identity
under OpenCore — or that changes the memory region the SEP mailbox lives in —
is a prime suspect for the post-EXITBS `sks request timeout`.

Note on the OCLP build config for this model (from source):
`set_smbios_model_spoof("MacBookAir8,1")` returns MacBookAir8,1 itself and the
default `serial_settings = "None"`, so by default OCLP keeps the real board-id
and serial and applies the `sbvmm` installer bypass. The `opencore` snapshot is
needed to confirm the identity actually presented under OpenCore matches native.

### Highest-value next experiment (safe, reversible, user-only)

**Turn OFF Activation Lock / Find My before the next OpenCore boot test** (System
Settings → Apple Account → Find My → turn off, i.e. sign the Mac out of Find My;
needs the owner's Apple ID password). Native boot proves the SEP works *with*
Activation Lock on — but only because the identity matches. Removing Activation
Lock takes the identity-enforcement variable out of the OpenCore boot entirely:

- If the OpenCore boot then completes → the wall was activation/identity, and
  the path forward is identity-preserving OpenCore settings (real SMBIOS +
  sbvmm), not model spoofing.
- If it still hangs with the same `sks request timeout` → identity is ruled
  out, and the fault is the SEP mailbox / memory-map handoff, to be chased via
  the native-vs-opencore memory-map diff.

Either outcome is progress: it splits the problem in two.

## 7b. BREAKTHROUGH (2026-07-25): OpenCore boots Sequoia on the T2

The SEP wall was **not** a SEP wall. With Full Disk Access granted (unsigned fork
builds cannot write to USB volumes otherwise — see README), OpenCore actually
landed on the ESP for the first time, and the machine booted the **macOS Sequoia
installer through OpenCore** with VoiceOver working and the GUI fully rendered.

Every earlier "grey screen / SEP hang" was therefore a red herring: the EFI
partition had been empty all along, so OpenCore never ran. The original
`PermissionError [Errno 1] Operation not permitted: /Volumes/EFI/EFI/BOOT` was
the very first symptom of that, long before any SEP theory.

### Remaining blocker and its root cause

The booted installer stops at its own compatibility gate:
"macOS Sequoia is not compatible with this Mac."

Root cause traced in `support/defaults.py::_smbios_probe`:

- MacBookAir8,1 has `SecureBootModel: "j140k"` and `Max OS Supported: sonoma`.
- With SIP enabled, the generic logic set `secure_status = True`, `force_vmm = False`.
- That has two fatal consequences for Sequoia:
  1. `efi_builder/misc.py::_re_generate_patch_arguments` only adds the VMM spoof
     (`sbvmm`) when `serial_settings == "None"` **or** `secure_status is False`.
     With `serial_settings = "Minimal"` and `secure_status = True`, **sbvmm was
     never added**, so RestrictEvents was not injected at all and the installer's
     board-id gate was never bypassed. (Confirmed by the install log: it copied
     `EFICheckDisabler.kext` — which is only enabled when RestrictEvents is
     disabled — and no `RestrictEvents.kext`.)
  2. `efi_builder/security.py` only disables `SecureBootModel` when
     `secure_status is False`; leaving it at `j140k` makes Apple Secure Boot
     reject Sequoia, which that board was never signed for.

Fix: special-case `model_array.T2_MacBookAir` in `_smbios_probe` to force
`secure_status = False` / `force_vmm = True`, plus a belt-and-braces force of
`sbvmm` in `_re_generate_patch_arguments` (secure_status is user-toggleable in
Settings).

## 7c. Keystore comparison on hardware (2026-07-25)

Both keystores were tested on the MacBookAir8,1 booting the **internal Sonoma**
through OpenCore:

| Keystore | Result |
|---|---|
| Real T2 keystore | Boots to the **login screen** (kernel up, WindowServer rendering), hangs at authentication |
| T1 substitution   | Hangs earlier, at the **Apple logo** |

The T1 stack blocks AppleKeyStore / AppleSSE / AppleCredentialManager, but the
internal volume is SEP-backed, so without them it cannot even be unlocked and
mounted — the boot dies before WindowServer. **The T1 substitution is therefore
the wrong tool for booting an installed, SEP-backed system**, and the default is
now off (`constants.t2_t1_keystore = False`), toggleable in
Settings > Security for further experiments.

Note the login-screen hang only blocks booting the *installed internal* system.
It does **not** block the USB installer / recovery route, which boots fine with
the real keystore because it never has to unlock the internal volume.

## 7d. The T1 substitution is not a SEP bypass — settled by a panic log

Booting the **Sequoia installer** (`root-dmg=file:///BaseSystem/BaseSystem.dmg`,
Darwin 24.6.0 / 24G720) with the T1 stack enabled panics:

```
panic: "AppleSEPManager panic for "AppleKeyStore": sks request timeout"
       @AppleSEPManagerIntel.cpp:809

AppleMobileFileIntegrity : AMFIInitializeLocalSigningPublicKey_Thread
  -> AppleKeyStore : aks_system_key_get_public -> _aks_operation
    -> perform_operation -> sep_deliver_msg -> init_sep_endpoint
      -> SEP request times out -> panic
```

Two conclusions:

1. **The trigger is AMFI**, initialising its local signing public key, which asks
   the keystore for a system key and therefore the SEP.
2. **The "T1 keystore" still talks to the SEP.** Its payload declares
   `CFBundleIdentifier com.apple.driver.AppleKeyStore`, `CFBundleVersion 2` — the
   same version the real one reports, so the backtrace cannot distinguish them.
   More importantly the payload is macOS 13.6's AppleKeyStore, i.e. the very
   binary that also serves T2 Macs; it is an *older* keystore, not a *SEP-free*
   one. On a T2 it still performs SEP mailbox IPC.

So the T1 substitution was never capable of bypassing the T2 SEP. That matches
the observed behaviour (worse, not better: Apple-logo hang / panic) and settles
the question — this line of attack is closed. Default stays off.

Note the real keystore does **not** panic here: with it, the same Sequoia
installer boots fine and reaches its compatibility dialog, so the SEP answers
AMFI correctly. The remaining work is purely the installer's compatibility gates.

## 7e. The compatibility gate, mapped (2026-07-26)

Three separate gates exist, and they are not equivalent:

| Gate | Where it runs | Bypass |
|---|---|---|
| Kernel | after boot.efi | `-no_compat_check` |
| `boot.efi` board-id | EFI, reads `PlatformSupport.plist` | "Skip Board ID check" Booter patch |
| **Installer app** | InstallAssistant GUI | model must look supported |

Hardware results:

- **`startosinstall` does NOT perform the GUI gate.** Run from a natively booted
  Sonoma — no OpenCore at all — it went straight past the licence step to the
  authorisation password prompt. The "macOS Sequoia is not compatible with this
  Mac" dialog is specific to the InstallAssistant **GUI**. Its flag list
  (`--usage`) contains no compatibility override, so this is not a flag, it is
  simply a different code path.
- **Moderate spoof + a Sequoia-supported model passes the GUI gate**, and the
  installer reaches disk selection with the internal **Macintosh HD visible and
  selectable** — the old "cannot even format the internal disk" symptom is gone.
- **But Moderate never prompts for the admin password.** Its full identity
  rewrite (PlatformInfo Automatic/Generic, DataHub protocol override,
  UpdateNVRAM/UpdateSMBIOS) breaks Secure Token on a T2: no volume owner is
  found, so the install cannot be authorised.
- **Minimal keeps Secure Token intact** and behaves "like native", but by
  upstream design it spoofs only the board-id and keeps the real model name
  (`_minimal_serial_patch`: `SystemProductName = self.model`). The gate keys on
  the model, so Minimal can never pass it.

Resolution: `constants.t2_minimal_model_spoof` makes Minimal set
SystemProductName/BoardVersion to the spoofed model as well — the one field the
gate needs — leaving the rest of the identity, and Secure Token, untouched.

| Configuration | Model seen | Gate | Secure Token |
|---|---|---|---|
| Minimal + Default | real | fails | works |
| Minimal + model spoof (toggle off) | real | fails | works |
| **Minimal + model spoof (toggle on)** | spoofed | **passes** | **works** |
| Moderate + model spoof | spoofed | passes | **breaks** |

Note the SEP is not implicated in any of this: with the real keystore the
installer boots and runs normally. The SEP timeout only blocks booting the
*installed internal* system through OpenCore.

## 8. Honest assessment

This is a genuinely hard, upstream-unsolved problem as of early 2026. Collecting
the native-vs-OpenCore diff is the most promising concrete lead we have and is
worth doing methodically. It may yield a fix; it may instead confirm that the
SEP cannot be handed off under OpenCore on this firmware, in which case the T1
bypass (external target) or native Sonoma are the working outcomes. Either way,
the data removes guesswork — which is the point of this document.
