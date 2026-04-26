# Makefile — T2SEPFix.kext
#
# Builds the T2SEPFix IOKit kernel extension for Intel Macs running
# macOS Sequoia (15.x) via OpenCore Legacy Patcher.
#
# Requirements:
#   - Xcode Command Line Tools installed (provides clang, xcrun, kextutil)
#   - macOS 14 (Sonoma) or 15 (Sequoia) SDK
#   - SIP disabled OR the kext must be code-signed with a kernel-extension
#     entitlement for testing on a real machine.
#
# Targets:
#   all      — build the kext bundle (default)
#   clean    — remove build artefacts
#   sign     — ad-hoc sign the kext for local testing
#   verify   — run kextutil -n to check linkage without loading
#   install  — copy to /Library/Extensions (requires sudo)
#   load     — kextload (requires sudo + SIP partial-disable)
#   unload   — kextunload (requires sudo)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BUNDLE_ID    := com.oclp.kext.T2SEPFix
BUNDLE_NAME  := T2SEPFix
KEXT_DIR     := $(BUNDLE_NAME).kext
CONTENTS_DIR := $(KEXT_DIR)/Contents
MACOS_DIR    := $(CONTENTS_DIR)/MacOS

SRCS         := T2SEPFix.cpp
OBJS         := $(SRCS:.cpp=.o)
PRODUCT      := $(MACOS_DIR)/$(BUNDLE_NAME)

# ---------------------------------------------------------------------------
# Compiler / SDK selection
# ---------------------------------------------------------------------------

# Use xcrun to locate the active Xcode toolchain.  Override CC/CXX if you
# need a specific compiler (e.g., CC=/usr/bin/clang).
CC           := $(shell xcrun -f clang)
CXX          := $(shell xcrun -f clang++)

# Detect SDK path automatically.  On a standard Xcode installation this
# resolves to something like:
#   /Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/
#       Developer/SDKs/MacOSX.sdk
SDK          := $(shell xcrun --sdk macosx --show-sdk-path)

# Deployment target: Sonoma (14.0) minimum, Sequoia (15.x) primary target.
MACOSX_DEPLOYMENT_TARGET := 14.0

# Target architecture: x86_64 only (T2 Macs are all Intel).
ARCH         := x86_64

# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

# Kernel headers live under System/Library/Frameworks/Kernel.framework.
KERNEL_FRAMEWORK := $(SDK)/System/Library/Frameworks/Kernel.framework

CXXFLAGS := \
    -arch $(ARCH) \
    -isysroot $(SDK) \
    -mmacosx-version-min=$(MACOSX_DEPLOYMENT_TARGET) \
    -F$(SDK)/System/Library/Frameworks \
    -I$(KERNEL_FRAMEWORK)/Headers \
    -I$(KERNEL_FRAMEWORK)/PrivateHeaders \
    -std=c++14 \
    -fno-rtti \
    -fno-exceptions \
    -fno-builtin \
    -fno-common \
    -msoft-float \
    -mkernel \
    -DKERNEL \
    -DKERNEL_PRIVATE \
    -DDRIVER_PRIVATE \
    -DAPPLE \
    -DNeXT \
    -Wall \
    -Wextra \
    -Wno-unused-parameter \
    -O2 \
    -g

KEXT_LIB_DIR := $(SDK)/usr/lib/kext

# Linker flags for a kext bundle.
LDFLAGS := \
    -arch $(ARCH) \
    -isysroot $(SDK) \
    -mmacosx-version-min=$(MACOSX_DEPLOYMENT_TARGET) \
    -L$(KEXT_LIB_DIR) \
    -Xlinker -kext \
    -nostdlib \
    -lkmodc++ \
    -lkmod \
    -lcc_kext

# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

.PHONY: all clean sign verify install load unload

all: $(PRODUCT) $(CONTENTS_DIR)/Info.plist
	@echo ""
	@echo "Built $(KEXT_DIR)"
	@echo "  Run 'make verify'  to check linkage"
	@echo "  Run 'make sign'    to ad-hoc sign for local testing"
	@echo "  Run 'sudo make install && sudo make load' to install"

# --- Link ---
$(PRODUCT): $(OBJS) | $(MACOS_DIR)
	$(CXX) $(LDFLAGS) -o $@ $^
	@echo "Linked $@"

# --- Compile ---
%.o: %.cpp T2SEPFix.hpp
	$(CXX) $(CXXFLAGS) -c -o $@ $<
	@echo "Compiled $<"

# --- Bundle scaffold ---
$(MACOS_DIR):
	mkdir -p $(MACOS_DIR)

$(CONTENTS_DIR)/Info.plist: Info.plist | $(CONTENTS_DIR)
	cp Info.plist $(CONTENTS_DIR)/Info.plist

$(CONTENTS_DIR):
	mkdir -p $(CONTENTS_DIR)

# --- Clean ---
clean:
	rm -rf $(OBJS) $(KEXT_DIR)
	@echo "Cleaned"

# --- Ad-hoc sign (for local testing with SIP partially disabled) ---
sign: all
	codesign --force --sign - --timestamp=none $(KEXT_DIR)
	@echo "Ad-hoc signed $(KEXT_DIR)"

# --- Verify linkage without loading ---
verify: all
	kextutil -n -print-diagnostics $(KEXT_DIR) || true
	@echo "kextutil check complete"

# --- Install to /Library/Extensions (requires sudo) ---
install: all
	cp -R $(KEXT_DIR) /Library/Extensions/
	chown -R root:wheel /Library/Extensions/$(KEXT_DIR)
	chmod -R 755       /Library/Extensions/$(KEXT_DIR)
	kextcache -i /
	@echo "Installed $(KEXT_DIR) to /Library/Extensions"

# --- Load (requires sudo + appropriate SIP settings) ---
load:
	kextload /Library/Extensions/$(KEXT_DIR)
	@echo "Loaded $(BUNDLE_ID)"

# --- Unload ---
unload:
	kextunload -b $(BUNDLE_ID)
	@echo "Unloaded $(BUNDLE_ID)"
