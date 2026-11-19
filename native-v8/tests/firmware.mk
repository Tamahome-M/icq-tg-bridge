# Build with: make -f Makefile -f tests/firmware.mk SDK=... firmware-tests
# Run only against an extracted, matching V8 firmware under ARM QEMU.
# FIRMWARE_LIBS must resolve firmware absolute symlinks (host-side links).
# TEST_HARDWARE_LIBS contains host-only OTP stubs; never ship it to a phone.
QEMU_ARM ?= /tmp/yam-qemu/qemu-arm-static
FIRMWARE_ROOT ?= /tmp/yam-firmware-017/root
FIRMWARE_LIBS ?= /tmp/yam-firmware-link
TEST_HARDWARE_LIBS ?=
FW_LIBRARY_PATH := $(TEST_HARDWARE_LIBS):$(FIRMWARE_LIBS):$(FIRMWARE_ROOT)/usr/lib/ezx/lib:$(FIRMWARE_ROOT)/usr/lib:$(FIRMWARE_ROOT)/lib
FW_RUN = $(QEMU_ARM) -L $(FIRMWARE_ROOT) -E LD_LIBRARY_PATH=$(FW_LIBRARY_PATH)
FW_TESTS := qt-object-test notification-audio-test notification-format-test capture-codec-test capture-media-test capture-lifecycle-test camera-filename-test media-lifecycle-test media-start-test platform-firmware-test platform-widget-test toolchain-vector-test

.PHONY: firmware-tests firmware-check
firmware-tests: $(addprefix $(BUILD)/,$(FW_TESTS))
$(BUILD)/qt-object-test: tests/qt_object_test.cpp $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< -lqte-mt -o $@
$(BUILD)/notification-audio-test: tests/notification_audio_test.cpp $(BUILD)/platform.o $(BUILD)/media.o $(BUILD)/external_display.o $(BUILD)/moc_platform.o $(BUILD)/moc_media.o $(BUILD)/moc_external_display.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) -Wl,--wrap=_ZN3tmm15MediaController4playERK7QStringib $< $(BUILD)/platform.o $(BUILD)/media.o $(BUILD)/external_display.o $(BUILD)/moc_platform.o $(BUILD)/moc_media.o $(BUILD)/moc_external_display.o -lezxsound -lezxappbase -lqte-mt -ldl -lm -o $@
$(BUILD)/notification-format-test: tests/notification_format_test.cpp $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< -ldl -o $@
$(BUILD)/capture-codec-test: tests/capture_codec_test.cpp $(BUILD)/capture_codec.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(BUILD)/capture_codec.o -ldl -o $@
$(BUILD)/capture-media-test: tests/capture_media_test.cpp $(BUILD)/capture_media.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(BUILD)/capture_media.o -o $@
$(BUILD)/moc_capture_test_observer.cpp: tests/capture_test_observer.h | $(BUILD)
	$(MOC) $< -o $@
$(BUILD)/moc_capture_test_observer.o: $(BUILD)/moc_capture_test_observer.cpp tests/capture_test_observer.h $(QT_COMPAT)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -Itests -c $< -o $@
$(BUILD)/capture-lifecycle-test: tests/capture_lifecycle_test.cpp tests/capture_test_observer.h $(BUILD)/capture.o $(BUILD)/camera_ui_v8.o $(BUILD)/capture_codec.o $(BUILD)/capture_media.o $(BUILD)/moc_capture.o $(BUILD)/moc_capture_test_observer.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) -Wl,-E $< $(BUILD)/capture.o $(BUILD)/camera_ui_v8.o $(BUILD)/capture_codec.o $(BUILD)/capture_media.o $(BUILD)/moc_capture.o $(BUILD)/moc_capture_test_observer.o -lezxsound -lqte-mt -ldl -lpthread -o $@
$(BUILD)/camera-filename-test: tests/camera_filename_test.cpp $(BUILD)/capture.o $(BUILD)/camera_ui_v8.o $(BUILD)/capture_codec.o $(BUILD)/capture_media.o $(BUILD)/moc_capture.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(BUILD)/capture.o $(BUILD)/camera_ui_v8.o $(BUILD)/capture_codec.o $(BUILD)/capture_media.o $(BUILD)/moc_capture.o -lezxsound -lqte-mt -ldl -lpthread -o $@
$(BUILD)/media-lifecycle-test: tests/media_lifecycle_test.cpp $(BUILD)/media.o $(BUILD)/moc_media.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(BUILD)/media.o $(BUILD)/moc_media.o -lezxsound -lqte-mt -ldl -o $@
$(BUILD)/moc_media_test_observer.cpp: tests/media_test_observer.h | $(BUILD)
	$(MOC) $< -o $@
$(BUILD)/moc_media_test_observer.o: $(BUILD)/moc_media_test_observer.cpp tests/media_test_observer.h $(QT_COMPAT)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -Itests -c $< -o $@
$(BUILD)/media-start-test: tests/media_start_test.cpp tests/media_test_observer.h $(BUILD)/media.o $(BUILD)/moc_media.o $(BUILD)/moc_media_test_observer.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) -Wl,--wrap=dlsym $< $(BUILD)/media.o $(BUILD)/moc_media.o $(BUILD)/moc_media_test_observer.o -lezxsound -lqte-mt -ldl -o $@
$(BUILD)/platform-firmware-test: tests/platform_firmware_test.cpp $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< -lqte-mt -ldl -o $@
$(BUILD)/platform-widget-test: tests/platform_widget_test.cpp $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< -lezxappbase -lqte-mt -ldl -o $@
firmware-check: firmware-tests
	@test -n "$(TEST_HARDWARE_LIBS)" || { echo 'Set TEST_HARDWARE_LIBS to the emulator-only OTP stub directory; never distribute it'; exit 1; }
	$(FW_RUN) $(BUILD)/qt-object-test
	$(FW_RUN) $(BUILD)/notification-audio-test
	$(FW_RUN) $(BUILD)/notification-format-test
	$(FW_RUN) $(BUILD)/capture-codec-test $(abspath $(BUILD))/test-codec.amr
	$(FW_RUN) $(BUILD)/capture-media-test $(abspath $(BUILD))/test-codec.amr
	$(FW_RUN) $(BUILD)/capture-lifecycle-test
	$(FW_RUN) $(BUILD)/camera-filename-test
	$(FW_RUN) $(BUILD)/media-lifecycle-test
	$(FW_RUN) $(BUILD)/media-start-test
	$(FW_RUN) $(BUILD)/platform-firmware-test
	$(FW_RUN) $(BUILD)/toolchain-vector-test
	@echo 'platform-widget-test requires the isolated QWS/framebuffer runner; see VALIDATION.md'

# Native camera widget flow requires QWS; run with tests/run_qws.py.
$(BUILD)/camera-ui-v8-test: tests/camera_ui_v8_test.cpp $(BUILD)/camera_ui_v8.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(BUILD)/camera_ui_v8.o -lqte-mt -lezxappbase -ldl -o $@

.PHONY: camera-ui-v8-test
camera-ui-v8-test: $(BUILD)/camera-ui-v8-test

# Test only in an isolated Qt/QWS server, not against the phone's header daemon.
$(BUILD)/moc_status_icon_observer.cpp: tests/status_icon_observer.h | $(BUILD)
	$(MOC) $< -o $@
$(BUILD)/moc_status_icon_observer.o: $(BUILD)/moc_status_icon_observer.cpp tests/status_icon_observer.h $(QT_COMPAT)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -Itests -c $< -o $@
$(BUILD)/status-icon-test: tests/status_icon_test.cpp $(BUILD)/moc_status_icon_observer.o $(BUILD)/status_icon_v8.o $(BUILD)/theme_patch.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -Itests $(LDFLAGS) $< $(BUILD)/moc_status_icon_observer.o $(BUILD)/status_icon_v8.o $(BUILD)/theme_patch.o -lezxappbase -lqte-mt -ldl -o $@
.PHONY: status-icon-test
status-icon-test: $(BUILD)/status-icon-test $(BUILD)/status-icons.ezx
$(BUILD)/status-icons.ezx: resources/status-icons.ezx | $(BUILD)
	cp $< $@

.PHONY: system-chrome-test roster-order-test
system-chrome-test: $(BUILD)/system-chrome-test
$(BUILD)/system-chrome-test: tests/system_chrome_test.cpp $(BUILD)/system_chrome.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) -Wl,--wrap=_ZN8ZSoftKeyC1ERK7QStringP7QWidgetS4_ $< $(BUILD)/system_chrome.o -lezxappbase -lqte-mt -ldl -o $@
roster-order-test: $(BUILD)/roster-order-test
$(BUILD)/roster-order-test: tests/roster_order_test.cpp $(BUILD)/roster_order.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(BUILD)/roster_order.o -lqte-mt -o $@
.PHONY: chat-layout-test
chat-layout-test: $(BUILD)/chat-layout-test
$(BUILD)/chat-layout-test: tests/chat_layout_test.cpp $(BUILD)/chat_layout.o $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(BUILD)/chat_layout.o -lezxappbase -lqte-mt -ldl -o $@
