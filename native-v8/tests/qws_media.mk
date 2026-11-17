# Optional media workflow checks with the real ARM Window and V8 Qt widgets.
# Only the test executable intercepts submit; the application has no test hooks.
.PHONY: media-workflow-probe
media-workflow-probe: $(BUILD)/media-workflow-probe
$(BUILD)/media-workflow-probe: tests/media_workflow_probe.cpp $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) -Wl,--wrap=_ZN3tmm6Client6submitERKNS_7CommandE -lezxsound -lqte-mt -lezxappbase -lezxpm -lm -ldl -lpthread -lrt -lresolv -o $@
