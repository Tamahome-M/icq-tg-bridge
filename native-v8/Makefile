SDK ?= /arm-eabi
.DEFAULT_GOAL := all
QT := $(SDK)/lib/qt-v8
EZX := $(SDK)/lib/ezx-v8
SYS := $(SDK)/arm-linux-gnueabi
CXX := $(SDK)/bin/arm-linux-gnueabi-g++
MOC ?= $(QT)/bin/moc
BUILD ?= build
QT_COMPAT := $(BUILD)/qt-compat/qobject.h
VERSION := $(shell cat VERSION)
CPPFLAGS := -D_FILE_OFFSET_BITS=64 -DQWS -DEZX_V8 -DTMM_NATIVE_VERSION='"$(VERSION)"' -I$(QT)/include -I$(EZX)/include -I$(SYS)/include -Isrc -include $(QT_COMPAT)
# MontaVista GCC 3.4.3 otherwise miscompiles unsigned vector-size comparisons
# (CMN vs CMP when size==0); see tests/toolchain_vector_test.cpp.
CXXFLAGS := -std=c++98 -Os -fno-expensive-optimizations -Wall -Wextra -fno-exceptions -fno-rtti -ffunction-sections -fdata-sections
# The SDK's old linker drops non-COMDAT .ARM.exidx/.ARM.extab with
# --gc-sections, even for live functions (e.g. Transport::connect).
# Exceptions then terminate the process instead of reaching Client's catch.
# Keep unwind tables; exception-test exercises throws across real object files.
LDFLAGS := -L$(BUILD)/sdk-link -L$(QT)/lib -L$(EZX)/lib -L$(SYS)/lib -Wl,-rpath-link,$(QT)/lib:$(EZX)/lib:$(SYS)/lib
SOURCES := $(wildcard src/*.cpp)
OBJECTS := $(patsubst src/%.cpp,$(BUILD)/%.o,$(SOURCES))
MOCS := window platform media capture external_display
MOC_OBJECTS := $(addprefix $(BUILD)/moc_,$(addsuffix .o,$(MOCS)))
CORE := $(BUILD)/crypto.o $(BUILD)/settings.o $(BUILD)/storage.o
$(BUILD)/client.o $(BUILD)/transport.o $(BUILD)/oscar.o $(BUILD)/dns.o $(BUILD)/main.o: CXXFLAGS += -fexceptions
$(BUILD)/main.o $(BUILD)/window.o $(BUILD)/ui_actions.o $(BUILD)/ui_java_menus.o $(BUILD)/ui_progress.o: VERSION

.PHONY: all clean package check-sdk core-tests ui-probe input-probe
all: check-sdk $(BUILD)/telemotomax-native
check-sdk: $(QT_COMPAT)
	@test -x "$(CXX)" || { echo 'Set SDK to the MotoMAGX SDK path'; exit 1; }
	@test -f "$(EZX)/include/ZApplication.h" || { echo 'V8 headers missing'; exit 1; }
	@test -x "$(MOC)" || { echo 'Qt 2 moc missing'; exit 1; }
$(BUILD):
	mkdir -p $@
$(QT_COMPAT): tools/prepare_qt_compat.py $(QT)/include/qobject.h | $(BUILD)
	python3 $< --header $(QT)/include/qobject.h --output $@
$(BUILD)/sdk-link/.ready: tools/relocate_sdk.py $(SYS)/lib/libc.so $(SYS)/lib/libpthread.so $(QT_COMPAT) | $(BUILD)
	python3 $< --sdk "$(SDK)" --output $(BUILD)/sdk-link
$(BUILD)/%.o: src/%.cpp $(QT_COMPAT) | $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@
$(BUILD)/moc_%.cpp: src/%.h | $(BUILD)
	$(MOC) $< -o $@
$(BUILD)/moc_%.o: $(BUILD)/moc_%.cpp $(QT_COMPAT)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@
$(BUILD)/telemotomax-native: $(OBJECTS) $(MOC_OBJECTS) $(BUILD)/sdk-link/.ready Makefile
	$(CXX) $(LDFLAGS) $(OBJECTS) $(MOC_OBJECTS) -lezxsound -lqte-mt -lezxappbase -lezxpm -lm -ldl -lpthread -lrt -lresolv -o $@
$(BUILD)/crypto-driver: tests/crypto_driver.cpp $(BUILD)/crypto.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(BUILD)/crypto.o -o $@
$(BUILD)/storage-test: tests/storage_test.cpp $(CORE) $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(CORE) -o $@
$(BUILD)/toolchain-vector-test: tests/toolchain_vector_test.cpp src/client.h $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< -o $@
$(BUILD)/exception-test: tests/exception_test.cpp $(BUILD)/transport.o $(BUILD)/oscar.o $(BUILD)/crypto.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -fexceptions $(LDFLAGS) $< $(BUILD)/transport.o $(BUILD)/oscar.o $(BUILD)/crypto.o -lrt -o $@
$(BUILD)/password-test: tests/password_test.cpp $(BUILD)/oscar.o $(BUILD)/crypto.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -fexceptions $(LDFLAGS) $< $(BUILD)/oscar.o $(BUILD)/crypto.o -o $@
$(BUILD)/media-cache-test: tests/media_cache_test.cpp $(BUILD)/media_cache.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(BUILD)/media_cache.o -o $@
core-tests: $(BUILD)/crypto-driver $(BUILD)/storage-test $(BUILD)/toolchain-vector-test $(BUILD)/exception-test $(BUILD)/password-test $(BUILD)/media-cache-test
ui-probe: $(BUILD)/ui-probe $(BUILD)/logo.png $(BUILD)/statuses.png $(BUILD)/messages.png $(BUILD)/smiles.txt $(BUILD)/smiles.png
$(BUILD)/logo.png: ../telemotomax/res/GRAPHICS_32BIT/COMMON/logo.png | $(BUILD)
	cp $< $@
$(BUILD)/messages.png: ../telemotomax/res/GRAPHICS_8BIT/COMMON/messages.png | $(BUILD)
	cp $< $@
$(BUILD)/statuses.png: ../telemotomax/res/GRAPHICS_8BIT/COMMON/statuses.png | $(BUILD)
	cp $< $@
$(BUILD)/smiles.txt: ../telemotomax/res/GRAPHICS_32BIT/MODULES/SMILES_STD/smiles.txt | $(BUILD)
	cp $< $@
$(BUILD)/smiles.png: ../telemotomax/res/GRAPHICS_32BIT/MODULES/SMILES_STD/smiles.png | $(BUILD)
	cp $< $@
input-probe: $(BUILD)/input-password-probe $(BUILD)/input-text-probe
$(BUILD)/input-password-probe: tests/input_editor_probe.cpp tests/input_keymap_fixture.cpp $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) $(BUILD)/sdk-link/.ready Makefile
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -fexceptions $(LDFLAGS) -Wl,--export-dynamic tests/input_editor_probe.cpp tests/input_keymap_fixture.cpp $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) -lezxsound -lqte-mt -lezxappbase -lezxpm -lm -ldl -lpthread -lrt -lresolv -o $@
$(BUILD)/input-text-probe: $(BUILD)/input-password-probe
	ln -sf input-password-probe $@
UI_TESTS := tests/ui_probe.cpp tests/ui_paint_probe.cpp tests/ui_connection_probe.cpp tests/input_indicator_test.cpp tests/foreground_probe.cpp tests/video_parent_probe.cpp
UI_TEST_OBJECTS := $(patsubst tests/%.cpp,$(BUILD)/test_%.o,$(UI_TESTS))
$(BUILD)/test_%.o: tests/%.cpp $(QT_COMPAT) | $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@
$(BUILD)/ui-probe: $(UI_TEST_OBJECTS) $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) $(BUILD)/sdk-link/.ready Makefile
	$(CXX) $(LDFLAGS) $(UI_TEST_OBJECTS) $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) -Wl,--wrap=_ZN3tmm8Platform13notifyMessageERK7QStringii,--wrap=_ZN8QPainter8fillRectEiiiiRK6QBrush,--wrap=_ZN8QPainter10drawPixmapEiiRK7QPixmapiiii,--wrap=pthread_create,--wrap=pthread_join,--wrap=connect,--wrap=dlsym -lezxsound -lqte-mt -lezxappbase -lezxpm -lm -ldl -lpthread -lrt -lresolv -o $@
package: all
	python3 tools/package.py --binary $(BUILD)/telemotomax-native --output dist
clean:
	rm -rf $(BUILD)
-include $(OBJECTS:.o=.d) $(MOC_OBJECTS:.o=.d) $(UI_TEST_OBJECTS:.o=.d)
