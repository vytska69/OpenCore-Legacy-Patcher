// T2SEPFix.hpp — IOKit kext fixing T2 chip communication on MacBookAir8,1 / MacBookAir8,2
// under macOS Sequoia booted via OpenCore Legacy Patcher.
//
// Two-pronged strategy:
//   1. NVRAM fix  — remove "sep-booted" from IODTNVRAM before AppleKeyStore reads it,
//      breaking the race that causes AppleKeyStore to block forever waiting for SEP.
//   2. PCIe fix   — when the T2 PCIe device (0x106b:0x1801) appears, ensure it is in D0,
//      that MSI is enabled, and probe the mailbox reply counter via BAR4 for diagnostics.
//
// Apple T2 PCIe register map (from t2linux/apple-bce):
//   BAR2  = DMA registers
//   BAR4  = mailbox registers
//     BAR4+0x108  [bits 23:20] = pending-reply count (reply counter)
//     BAR4+0x810  = reply base
//     BAR4+0x820  = outbound mailbox
//
// Build with Xcode kext target or the supplied Makefile.
// Targets: macOS 14 / 15 (arm64 not needed; this is an Intel-only path via OCLP).

#ifndef T2SEPFix_hpp
#define T2SEPFix_hpp

#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/pci/IOPCIDevice.h>

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Apple T2 PCIe identity
static constexpr uint16_t kT2VendorID    = 0x106b;
static constexpr uint16_t kT2DeviceID    = 0x1801;

// BAR register offsets in PCI config space
// kIOPCIConfigBaseAddress0 == 0x10, each BAR is 4 bytes wide
static constexpr uint8_t  kT2BAR2Index   = kIOPCIConfigBaseAddress2;   // 0x18
static constexpr uint8_t  kT2BAR4Index   = kIOPCIConfigBaseAddress4;   // 0x20

// BAR4 mailbox register offsets
static constexpr uint32_t kT2ReplyCounterOffset   = 0x108;
static constexpr uint32_t kT2ReplyBaseOffset       = 0x810;
static constexpr uint32_t kT2OutboundMailboxOffset = 0x820;

// Bits 23:20 of the reply counter register hold the pending-reply count
static constexpr uint32_t kT2ReplyCountShift = 20;
static constexpr uint32_t kT2ReplyCountMask  = 0xF;   // 4 bits -> 0-15

// PCI command register bits  (offset 0x04)
static constexpr uint16_t kPCICmdMemorySpace  = 0x0002;
static constexpr uint16_t kPCICmdBusMaster    = 0x0004;

// PCI capability IDs
static constexpr uint8_t kPCICapMSI     = 0x05;
static constexpr uint8_t kPCICapPCIExp  = 0x10;

// MSI Message Control bits  (offset +2 from cap header)
static constexpr uint16_t kMSICtrlEnable      = 0x0001;
static constexpr uint16_t kMSICtrl64Bit       = 0x0080;
static constexpr uint16_t kMSICtrlMMCMask     = 0x000E;  // multiple-message capable
static constexpr uint16_t kMSICtrlMMEShift    = 4;       // multiple-message enable field start
static constexpr uint16_t kMSICtrlMMEMask     = 0x0070;  // multiple-message enable field mask
// Encode log2(8) = 3 into bits [6:4] to request up to 8 vectors
static constexpr uint16_t kMSICtrlMME8Vec     = (3u << 4) & kMSICtrlMMEMask;

// NVRAM sep-booted variable
// Format: <GUID>:<name>  (EFI NVRAM GUID for Apple system variables)
static const char * const kSEPBootedNVRAMKey =
    "7C436110-AB2A-4BBB-A880-FE41995C9F82:sep-booted";

// waitForMatchingService timeout: 8 seconds expressed in nanoseconds
static constexpr uint64_t kNVRAMWaitTimeoutNs = 8ULL * 1000ULL * 1000ULL * 1000ULL;

// ---------------------------------------------------------------------------
// T2SEPFix — system (NVRAM) personality
//
// Matched via IOResourceMatch = "IOKit" against IOResources.
// Runs as early as possible; its sole job is to delete sep-booted from NVRAM.
// ---------------------------------------------------------------------------
class T2SEPFix : public IOService
{
    OSDeclareDefaultStructors(T2SEPFix)

public:
    // IOService overrides
    bool  init(OSDictionary *dict = nullptr) override;
    bool  start(IOService *provider) override;
    void  stop(IOService *provider) override;
    void  free() override;

private:
    // Remove the sep-booted NVRAM variable through the IODTNVRAM IOKit service.
    // Returns true if the variable was removed (or was not present).
    bool  removeSEPBootedNVRAM();
};

// ---------------------------------------------------------------------------
// T2PCIeFix — PCIe (T2 device) personality
//
// Matched via IOPCIMatch = "0x1801106b" against the T2 PCIe endpoint.
// Initialises the device, enables MSI, and probes the mailbox.
// ---------------------------------------------------------------------------
class T2PCIeFix : public IOService
{
    OSDeclareDefaultStructors(T2PCIeFix)

public:
    // IOService overrides
    bool  init(OSDictionary *dict = nullptr) override;
    bool  start(IOService *provider) override;
    void  stop(IOService *provider) override;
    void  free() override;

private:
    IOPCIDevice   *mT2Device;   // weak ref — owned by IOKit tree
    IOMemoryMap   *mBAR4Map;    // strong ref — retained until stop()

    // Log PCI identity, BAR addresses, and command register of the T2 device.
    void     logDeviceInfo(IOPCIDevice *dev);

    // Set PCI command register bits to ensure Memory Space + Bus Master are set.
    // Returns true on success.
    bool     ensureD0AndBusMaster(IOPCIDevice *dev);

    // Walk PCI capability list looking for capability ID capID.
    // Returns the byte offset of the capability header, or 0 if not found.
    uint8_t  findPCICapability(IOPCIDevice *dev, uint8_t capID);

    // Inspect MSI capability; enable MSI (up to 8 vectors) if not already enabled.
    // Returns true on success / already enabled.
    bool     enableMSI(IOPCIDevice *dev);

    // Map BAR4 and read the reply counter register for diagnostics.
    // Stores the mapping in mBAR4Map (released in stop()).
    // Returns true if BAR4 could be mapped and the counter was read.
    bool     probeMailbox(IOPCIDevice *dev);
};

#endif // T2SEPFix_hpp
