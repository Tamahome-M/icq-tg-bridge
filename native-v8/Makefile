SDK ?= /arm-eabi
QT := $(SDK)/lib/qt-v8
EZX := $(SDK)/lib/ezx-v8
SYS := $(SDK)/arm-linux-gnueabi
CXX := $(SDK)/bin/arm-linux-gnueabi-g++
MOC ?= $(QT)/bin/moc
BUILD ?= build
VERSION := $(shell cat VERSION)
CPPFLAGS := -D_FILE_OFFSET_BITS=64 -DQWS -DEZX_V8 -DTMM_NATIVE_VERSION='"$(VERSION)"' -I$(QT)/include -I$(EZX)/include -I$(SYS)/include -Isrc
# MontaVista GCC 3.4.3 otherwise miscompiles unsigned vector-size comparisons
# (CMN vs CMP when size==0); see tests/toolchain_vector_test.cpp.
CXXFLAGS := -std=c++98 -Os -fno-expensive-optimizations -Wall -Wextra -fno-exceptions -fno-rtti -ffunction-sections -fdata-sections
LDFLAGS := -L$(BUILD)/sdk-link -L$(QT)/lib -L$(EZX)/lib -L$(SYS)/lib -Wl,--gc-sections,-rpath-link,$(QT)/lib:$(EZX)/lib:$(SYS)/lib
SOURCES := $(wildcard src/*.cpp)
OBJECTS := $(patsubst src/%.cpp,$(BUILD)/%.o,$(SOURCES))
MOCS := window platform media capture external_display
MOC_OBJECTS := $(addprefix $(BUILD)/moc_,$(addsuffix .o,$(MOCS)))
CORE := $(BUILD)/crypto.o $(BUILD)/settings.o $(BUILD)/storage.o
$(BUILD)/client.o $(BUILD)/transport.o $(BUILD)/oscar.o $(BUILD)/dns.o $(BUILD)/main.o: CXXFLAGS += -fexceptions

.PHONY: all clean package check-sdk core-tests
all: check-sdk $(BUILD)/telemotomax-native
check-sdk:
	@test -x "$(CXX)" || { echo 'Set SDK to the MotoMAGX SDK path'; exit 1; }
	@test -f "$(EZX)/include/ZApplication.h" || { echo 'V8 headers missing'; exit 1; }
	@test -x "$(MOC)" || { echo 'Qt 2 moc missing'; exit 1; }
$(BUILD):
	mkdir -p $@
$(BUILD)/sdk-link/.ready: tools/relocate_sdk.py $(SYS)/lib/libc.so $(SYS)/lib/libpthread.so | $(BUILD)
	python3 $< --sdk "$(SDK)" --output $(BUILD)/sdk-link
$(BUILD)/%.o: src/%.cpp | $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@
$(BUILD)/moc_%.cpp: src/%.h | $(BUILD)
	$(MOC) $< -o $@
$(BUILD)/moc_%.o: $(BUILD)/moc_%.cpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@
$(BUILD)/telemotomax-native: $(OBJECTS) $(MOC_OBJECTS) $(BUILD)/sdk-link/.ready
	$(CXX) $(LDFLAGS) $(OBJECTS) $(MOC_OBJECTS) -lezxsound -lqte-mt -lezxappbase -lezxpm -lm -ldl -lpthread -lrt -lresolv -o $@
$(BUILD)/crypto-driver: tests/crypto_driver.cpp $(BUILD)/crypto.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(BUILD)/crypto.o -o $@
$(BUILD)/storage-test: tests/storage_test.cpp $(CORE) $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(CORE) -o $@
$(BUILD)/toolchain-vector-test: tests/toolchain_vector_test.cpp src/client.h $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< -o $@
core-tests: $(BUILD)/crypto-driver $(BUILD)/storage-test $(BUILD)/toolchain-vector-test
ui-probe: $(BUILD)/ui-probe
$(BUILD)/ui-probe: tests/ui_probe.cpp $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) tests/ui_probe.cpp $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) -lezxsound -lqte-mt -lezxappbase -lezxpm -lm -ldl -lpthread -lrt -lresolv -o $@
package: all
	python3 tools/package.py --binary $(BUILD)/telemotomax-native --output dist
clean:
	rm -rf $(BUILD)
-include $(OBJECTS:.o=.d) $(MOC_OBJECTS:.o=.d)
