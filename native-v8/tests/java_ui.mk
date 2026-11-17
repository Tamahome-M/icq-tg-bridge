# Compare native navigation with the MOTOROLA Java V8 build.
.PHONY: java-ui-probe
java-ui-probe: $(BUILD)/java-ui-probe $(BUILD)/statuses.png $(BUILD)/messages.png $(BUILD)/back.png $(BUILD)/smiles.txt $(BUILD)/smiles.png
$(BUILD)/java-ui-probe: tests/java_ui_probe.cpp $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) $(BUILD)/sdk-link/.ready Makefile
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) -Wl,--wrap=_ZN3tmm6Client6submitERKNS_7CommandE,--wrap=_ZN3tmm12SystemChrome10drawFooterER8QPainterRK5QRectRK7QStringS8_ $< $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) -lezxsound -lqte-mt -lezxappbase -lezxpm -lm -ldl -lpthread -lrt -lresolv -o $@
