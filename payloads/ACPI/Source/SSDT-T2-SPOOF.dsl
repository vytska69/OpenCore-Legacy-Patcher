/*
 * SSDT-T2-SPOOF.dsl
 *
 * Injects apple-coprocessor-version onto the RP01 PCIe root port so
 * macOS's AppleT2.kext can identify the T2 security chip and initialise
 * the SEP, iBridge, and audio subsystems correctly.
 *
 * Without this property the DSDT _DSM may not be evaluated in time or
 * may be shadowed by OpenCore ACPI patching; AppleT2 then fails to
 * configure the SEP, causing AppleSEPManager to time out and keybagd
 * to block indefinitely before the installer UI can appear.
 *
 * The _DSM fallback (XDSM) preserves the original DSDT _DSM behaviour
 * for all other UUIDs.  Version string matches bridgeOS on MBA8,1/8,2.
 */
DefinitionBlock ("", "SSDT", 2, "T2FIX", "T2SPOOF", 0x00001000)
{
    External (_SB.PCI0.RP01, DeviceObj)
    External (_SB.PCI0.RP01.XDSM, MethodObj)

    Scope (_SB.PCI0.RP01)
    {
        Method (_DSM, 4, NotSerialized)
        {
            If (LEqual (Arg0, ToUUID ("a0b5b7c6-2d8a-4c2f-81d1-05d54930d0a5")))
            {
                Return (Package ()
                {
                    "apple-coprocessor-version",
                    Buffer () { "23.16.14000.0.0,0" }
                })
            }

            Return (XDSM (Arg0, Arg1, Arg2, Arg3))
        }
    }
}
