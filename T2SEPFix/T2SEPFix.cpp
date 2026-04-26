// T2SEPFix.cpp — IOKit kext for MacBookAir8,1 / MacBookAir8,2 T2 chip fix.
//
// Two personalities live in this single translation unit:
//
//   T2SEPFix   — system driver matched against IOResources (IOResourceMatch = "IOKit").
//                Runs early, deletes sep-booted from NVRAM before AppleKeyStore reads it.
//
//   T2PCIeFix  — PCI driver matched against the T2 PCIe endpoint (IOPCIMatch 0x1801106b).
//                Ensures D0 power, MSI enabled, and reads mailbox reply counter.
//
// See T2SEPFix.hpp for the full register-level commentary.

#include "T2SEPFix.hpp"

#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/pci/IOPCIDevice.h>
#include <IOKit/IONVRAM.h>

// ---------------------------------------------------------------------------
// OSDefineMetaClassAndStructors — required glue for each IOService subclass
// ---------------------------------------------------------------------------
OSDefineMetaClassAndStructors(T2SEPFix,   IOService)
OSDefineMetaClassAndStructors(T2PCIeFix,  IOService)

// ===========================================================================
// T2SEPFix — NVRAM personality
// ===========================================================================

bool T2SEPFix::init(OSDictionary *dict)
{
    if (!IOService::init(dict)) {
        IOLog("T2SEPFix: IOService::init failed\n");
        return false;
    }
    IOLog("T2SEPFix: init\n");
    return true;
}

bool T2SEPFix::start(IOService *provider)
{
    if (!IOService::start(provider)) {
        IOLog("T2SEPFix: IOService::start failed\n");
        return false;
    }

    IOLog("T2SEPFix: start — will attempt NVRAM sep-booted removal\n");

    bool removed = removeSEPBootedNVRAM();
    if (removed) {
        IOLog("T2SEPFix: sep-booted NVRAM variable removed successfully\n");
    } else {
        IOLog("T2SEPFix: sep-booted was not present or could not be removed\n");
    }

    // We have done our job; there is no reason to stay matched.
    // Returning false from start() releases us cleanly.
    IOService::stop(provider);
    return false;
}

void T2SEPFix::stop(IOService *provider)
{
    IOLog("T2SEPFix: stop\n");
    IOService::stop(provider);
}

void T2SEPFix::free()
{
    IOService::free();
}

// ---------------------------------------------------------------------------
// removeSEPBootedNVRAM
//
// Walks the IOKit registry to find the IODTNVRAM service, then removes the
// "7C436110-...:sep-booted" property from it.  The IODTNVRAM service exposes
// NVRAM variables as properties in the IOKit registry; removing a property
// from the service removes it from NVRAM as well.
//
// We use waitForMatchingService() with a generous 8-second timeout because
// IODTNVRAM may not yet be published when we are first started.
// ---------------------------------------------------------------------------
bool T2SEPFix::removeSEPBootedNVRAM()
{
    // Build a matching dictionary for the IODTNVRAM IOKit service.
    OSDictionary *nvramMatch = serviceMatching("IODTNVRAM");
    if (!nvramMatch) {
        IOLog("T2SEPFix: could not create IODTNVRAM matching dictionary\n");
        return false;
    }

    // waitForMatchingService takes ownership of the dictionary.
    IOService *nvramService = waitForMatchingService(nvramMatch, kNVRAMWaitTimeoutNs);
    if (!nvramService) {
        IOLog("T2SEPFix: IODTNVRAM service not found within timeout\n");
        // nvramMatch was consumed by waitForMatchingService.
        return false;
    }

    IOLog("T2SEPFix: found IODTNVRAM service at %p\n", nvramService);

    // Check whether the variable is present before attempting removal.
    OSObject *existing = nvramService->getProperty(kSEPBootedNVRAMKey);
    if (!existing) {
        IOLog("T2SEPFix: sep-booted key (%s) not present in NVRAM — nothing to do\n",
              kSEPBootedNVRAMKey);
        nvramService->release();
        return true;  // Not an error; variable was already absent.
    }

    IOLog("T2SEPFix: sep-booted key found — removing\n");

    // Remove the property from the IODTNVRAM service node.
    // IODTNVRAM overrides removeProperty() to also commit the change to
    // non-volatile storage, so this is the correct mechanism.
    nvramService->removeProperty(kSEPBootedNVRAMKey);

    // Verify removal.
    OSObject *verify = nvramService->getProperty(kSEPBootedNVRAMKey);
    if (verify) {
        IOLog("T2SEPFix: WARNING — sep-booted key still present after removal attempt\n");
        nvramService->release();
        return false;
    }

    IOLog("T2SEPFix: sep-booted key removed and verified absent\n");
    nvramService->release();
    return true;
}

// ===========================================================================
// T2PCIeFix — PCIe personality
// ===========================================================================

bool T2PCIeFix::init(OSDictionary *dict)
{
    if (!IOService::init(dict)) {
        IOLog("T2PCIeFix: IOService::init failed\n");
        return false;
    }

    mT2Device = nullptr;
    mBAR4Map  = nullptr;

    IOLog("T2PCIeFix: init\n");
    return true;
}

bool T2PCIeFix::start(IOService *provider)
{
    if (!IOService::start(provider)) {
        IOLog("T2PCIeFix: IOService::start failed\n");
        return false;
    }

    // The provider must be the T2 PCIe device.
    mT2Device = OSDynamicCast(IOPCIDevice, provider);
    if (!mT2Device) {
        IOLog("T2PCIeFix: provider is not IOPCIDevice — aborting\n");
        IOService::stop(provider);
        return false;
    }

    IOLog("T2PCIeFix: start — provider is IOPCIDevice at %p\n", mT2Device);

    // Step 1: Log current device state for diagnostics.
    logDeviceInfo(mT2Device);

    // Step 2: Ensure the device is in D0 with bus-master + memory-decode enabled.
    if (!ensureD0AndBusMaster(mT2Device)) {
        IOLog("T2PCIeFix: WARNING — could not fully bring device to D0/bus-master\n");
        // Non-fatal: continue and at least attempt MSI and mailbox probing.
    }

    // Step 3: Check and enable MSI.
    if (!enableMSI(mT2Device)) {
        IOLog("T2PCIeFix: WARNING — MSI enablement failed or not supported\n");
    }

    // Step 4: Probe the mailbox reply counter via BAR4.
    if (!probeMailbox(mT2Device)) {
        IOLog("T2PCIeFix: WARNING — BAR4 mailbox probe failed\n");
    }

    IOLog("T2PCIeFix: start complete\n");
    return true;
}

void T2PCIeFix::stop(IOService *provider)
{
    IOLog("T2PCIeFix: stop\n");

    if (mBAR4Map) {
        mBAR4Map->release();
        mBAR4Map = nullptr;
    }

    // mT2Device is a weak reference owned by the IOKit tree; do not release.
    mT2Device = nullptr;

    IOService::stop(provider);
}

void T2PCIeFix::free()
{
    // Defensive: release mapping if stop() was not called cleanly.
    if (mBAR4Map) {
        mBAR4Map->release();
        mBAR4Map = nullptr;
    }
    IOService::free();
}

// ---------------------------------------------------------------------------
// logDeviceInfo
//
// Reads and logs the PCI vendor/device IDs, the four BAR addresses, and the
// PCI command register from config space.  Pure diagnostics; no side effects.
// ---------------------------------------------------------------------------
void T2PCIeFix::logDeviceInfo(IOPCIDevice *dev)
{
    uint16_t vendorID = dev->configRead16(kIOPCIConfigVendorID);
    uint16_t deviceID = dev->configRead16(kIOPCIConfigDeviceID);
    uint16_t command  = dev->configRead16(kIOPCIConfigCommand);
    uint16_t status   = dev->configRead16(kIOPCIConfigStatus);

    uint32_t bar0 = dev->configRead32(kIOPCIConfigBaseAddress0);
    uint32_t bar1 = dev->configRead32(kIOPCIConfigBaseAddress1);
    uint32_t bar2 = dev->configRead32(kIOPCIConfigBaseAddress2);
    uint32_t bar3 = dev->configRead32(kIOPCIConfigBaseAddress3);
    uint32_t bar4 = dev->configRead32(kIOPCIConfigBaseAddress4);
    uint32_t bar5 = dev->configRead32(kIOPCIConfigBaseAddress5);

    IOLog("T2PCIeFix: T2 device info:\n");
    IOLog("T2PCIeFix:   VendorID=0x%04x DeviceID=0x%04x\n", vendorID, deviceID);
    IOLog("T2PCIeFix:   Command=0x%04x  Status=0x%04x\n",   command,  status);
    IOLog("T2PCIeFix:   BAR0=0x%08x  BAR1=0x%08x\n",        bar0, bar1);
    IOLog("T2PCIeFix:   BAR2=0x%08x  BAR3=0x%08x\n",        bar2, bar3);
    IOLog("T2PCIeFix:   BAR4=0x%08x  BAR5=0x%08x\n",        bar4, bar5);

    // Decode command register bits relevant to us.
    IOLog("T2PCIeFix:   MemorySpace=%s  BusMaster=%s\n",
          (command & kPCICmdMemorySpace) ? "ON" : "OFF",
          (command & kPCICmdBusMaster)   ? "ON" : "OFF");

    // Capabilities list present?
    IOLog("T2PCIeFix:   CapabilitiesListPresent=%s\n",
          (status & 0x0010) ? "YES" : "NO");
}

// ---------------------------------------------------------------------------
// ensureD0AndBusMaster
//
// Sets the Memory Space and Bus Master bits in the PCI command register so
// that the Intel CPU can reach the T2's BARs and the T2 can DMA to host
// memory.  This mirrors what a proper PCIe driver does in probe().
//
// We do not attempt full PCI power-management state transitions here because
// the T2 is always brought up in D0 by the firmware; we are just making sure
// the command register reflects that.
// ---------------------------------------------------------------------------
bool T2PCIeFix::ensureD0AndBusMaster(IOPCIDevice *dev)
{
    // setMemoryEnable(true) sets bit 1 (Memory Space) in the command register.
    dev->setMemoryEnable(true);

    // setBusMasterEnable(true) sets bit 2 (Bus Master) in the command register.
    dev->setBusMasterEnable(true);

    // Verify.
    uint16_t cmd = dev->configRead16(kIOPCIConfigCommand);
    bool memOK   = (cmd & kPCICmdMemorySpace) != 0;
    bool bmOK    = (cmd & kPCICmdBusMaster)   != 0;

    IOLog("T2PCIeFix: after D0/bus-master setup: Command=0x%04x "
          "MemSpace=%s BusMaster=%s\n",
          cmd,
          memOK ? "ON" : "OFF",
          bmOK  ? "ON" : "OFF");

    return memOK && bmOK;
}

// ---------------------------------------------------------------------------
// findPCICapability
//
// Standard PCI capability-list walker.  Begins at the pointer in config
// register 0x34, follows the linked list (next-cap pointer is at offset +1
// of each capability header), and returns the config-space byte offset of
// the first capability whose ID byte matches capID.
//
// Returns 0 if the capability is not found or if the list appears malformed.
// The loop limit (48 iterations) guards against circular lists.
// ---------------------------------------------------------------------------
uint8_t T2PCIeFix::findPCICapability(IOPCIDevice *dev, uint8_t capID)
{
    // Bit 4 of the Status register indicates whether a capabilities list exists.
    uint16_t status = dev->configRead16(kIOPCIConfigStatus);
    if (!(status & 0x0010)) {
        IOLog("T2PCIeFix: findPCICapability: capabilities list not present\n");
        return 0;
    }

    // kIOPCIConfigCapabilitiesPointer == 0x34
    uint8_t cap = dev->configRead8(kIOPCIConfigCapabilitiesPointer) & 0xFC;
    if (cap < 0x40) {
        IOLog("T2PCIeFix: findPCICapability: capabilities pointer 0x%02x is invalid\n", cap);
        return 0;
    }

    for (int i = 0; i < 48 && cap != 0; i++) {
        uint8_t id   = dev->configRead8(cap);
        uint8_t next = dev->configRead8(cap + 1) & 0xFC;

        IOLog("T2PCIeFix: capability at 0x%02x: ID=0x%02x next=0x%02x\n", cap, id, next);

        if (id == capID) {
            return cap;
        }
        cap = next;
    }

    IOLog("T2PCIeFix: capability ID 0x%02x not found\n", capID);
    return 0;
}

// ---------------------------------------------------------------------------
// enableMSI
//
// Locates the MSI capability structure and enables MSI with up to 8 vectors
// (log2(8) = 3, encoded in the Multiple Message Enable field of the Message
// Control register).
//
// MSI capability layout (from PCIe base spec §7.7.1):
//   Offset 0  : Capability ID  (0x05)
//   Offset 1  : Next Pointer
//   Offset 2  : Message Control [15:0]
//     bit  0   : MSI Enable
//     bits 3:1 : Multiple Message Capable  (read-only)
//     bits 6:4 : Multiple Message Enable   (r/w, log2 of vectors granted)
//     bit  7   : 64-bit Address Capable    (read-only)
//   Offset 4  : Message Address Lo
//   Offset 8  : Message Address Hi         (only if bit 7 set)
//   Offset 8 or 12: Message Data
// ---------------------------------------------------------------------------
bool T2PCIeFix::enableMSI(IOPCIDevice *dev)
{
    uint8_t msiCap = findPCICapability(dev, kPCICapMSI);
    if (msiCap == 0) {
        IOLog("T2PCIeFix: MSI capability not found — cannot enable MSI\n");
        return false;
    }

    IOLog("T2PCIeFix: MSI capability at config offset 0x%02x\n", msiCap);

    uint16_t ctrl = dev->configRead16(msiCap + 2);
    IOLog("T2PCIeFix: MSI Message Control: 0x%04x\n", ctrl);

    if (ctrl & kMSICtrlEnable) {
        IOLog("T2PCIeFix: MSI already enabled (ctrl=0x%04x)\n", ctrl);
        return true;
    }

    // How many vectors does the device advertise it is capable of?
    uint8_t mmc = (ctrl & kMSICtrlMMCMask) >> 1;  // bits [3:1] -> log2(vecs capable)
    IOLog("T2PCIeFix: T2 advertises %u MSI vector(s) capable (MMC=%u)\n",
          (1u << mmc), mmc);

    // Request up to 8 vectors (MME = 3 = log2(8)); cap to what device supports.
    uint8_t mmeVal = 3;  // request log2(8) = 3
    if (mmeVal > mmc) {
        mmeVal = mmc;    // can't request more than device supports
    }

    // Build new control word: enable MSI + set MME field.
    uint16_t newCtrl = (ctrl & ~(kMSICtrlMMEMask)) |
                       ((uint16_t)(mmeVal << kMSICtrlMMEShift) & kMSICtrlMMEMask) |
                       kMSICtrlEnable;

    IOLog("T2PCIeFix: writing MSI control 0x%04x (enable + %u vector(s))\n",
          newCtrl, (1u << mmeVal));

    dev->configWrite16(msiCap + 2, newCtrl);

    // Verify.
    uint16_t verify = dev->configRead16(msiCap + 2);
    IOLog("T2PCIeFix: MSI control after write: 0x%04x\n", verify);

    if (!(verify & kMSICtrlEnable)) {
        IOLog("T2PCIeFix: ERROR — MSI enable bit did not stick\n");
        return false;
    }

    IOLog("T2PCIeFix: MSI enabled successfully with %u vector(s)\n",
          (1u << ((verify & kMSICtrlMMEMask) >> kMSICtrlMMEShift)));
    return true;
}

// ---------------------------------------------------------------------------
// probeMailbox
//
// Maps BAR4 (the T2 mailbox register window) using mapDeviceMemoryWithRegister
// and reads the reply counter register at offset 0x108.  Bits [23:20] contain
// the count of pending replies — a non-zero value indicates the T2 is alive
// and has queued responses.
//
// We map only the first page (minimum granularity) because we only need to
// read a diagnostic register, not drive the full mailbox protocol.
//
// The mapping is retained in mBAR4Map so callers can extend this for deeper
// diagnosis; it is released in stop().
// ---------------------------------------------------------------------------
bool T2PCIeFix::probeMailbox(IOPCIDevice *dev)
{
    IOLog("T2PCIeFix: mapping BAR4 (mailbox registers)\n");

    // mapDeviceMemoryWithRegister returns a retained IOMemoryMap* or nullptr.
    mBAR4Map = dev->mapDeviceMemoryWithRegister(kT2BAR4Index);
    if (!mBAR4Map) {
        IOLog("T2PCIeFix: ERROR — failed to map BAR4\n");
        return false;
    }

    IOVirtualAddress bar4VA = mBAR4Map->getVirtualAddress();
    IOPhysicalAddress bar4PA = mBAR4Map->getPhysicalAddress();
    IOByteCount       bar4Len = mBAR4Map->getLength();

    IOLog("T2PCIeFix: BAR4 mapped: VA=0x%llx PA=0x%llx length=0x%llx\n",
          (uint64_t)bar4VA, (uint64_t)bar4PA, (uint64_t)bar4Len);

    // Sanity check: we need at least 0x109 bytes to read the counter register.
    if (bar4Len < (kT2ReplyCounterOffset + 4)) {
        IOLog("T2PCIeFix: BAR4 too small (0x%llx bytes) to reach reply counter\n",
              (uint64_t)bar4Len);
        // Keep the map for diagnostics but report failure.
        return false;
    }

    // Read the reply counter register.
    // Use volatile to prevent the compiler from caching the hardware read.
    volatile uint32_t *replyCounterReg =
        reinterpret_cast<volatile uint32_t *>(bar4VA + kT2ReplyCounterOffset);
    uint32_t counterVal = *replyCounterReg;

    uint8_t pendingReplies = static_cast<uint8_t>(
        (counterVal >> kT2ReplyCountShift) & kT2ReplyCountMask);

    IOLog("T2PCIeFix: BAR4+0x108 (reply counter register) = 0x%08x\n", counterVal);
    IOLog("T2PCIeFix:   bits[23:20] pending reply count = %u\n", pendingReplies);

    if (pendingReplies > 0) {
        IOLog("T2PCIeFix:   T2 has %u pending reply/replies — mailbox appears active\n",
              pendingReplies);
    } else {
        IOLog("T2PCIeFix:   No pending replies — T2 mailbox may be idle or uninitialized\n");
    }

    // Also log the reply base and outbound mailbox registers for completeness.
    if (bar4Len >= (kT2OutboundMailboxOffset + 4)) {
        volatile uint32_t *replyBaseReg =
            reinterpret_cast<volatile uint32_t *>(bar4VA + kT2ReplyBaseOffset);
        volatile uint32_t *outboxReg =
            reinterpret_cast<volatile uint32_t *>(bar4VA + kT2OutboundMailboxOffset);

        IOLog("T2PCIeFix:   BAR4+0x810 (reply base)        = 0x%08x\n", *replyBaseReg);
        IOLog("T2PCIeFix:   BAR4+0x820 (outbound mailbox)  = 0x%08x\n", *outboxReg);
    }

    return true;
}
