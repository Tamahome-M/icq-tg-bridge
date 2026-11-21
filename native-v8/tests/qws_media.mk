# Optional media workflow checks with the real ARM Window and V8 Qt widgets.
# The test substitutes command submission and the decoder while retaining the native widget.
.PHONY: media-workflow-probe
media-workflow-probe: $(BUILD)/media-workflow-probe
$(BUILD)/media-workflow-probe: tests/media_workflow_probe.cpp $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) -Wl,--wrap=_ZN3tmm6Client6submitERKNS_7CommandE,--wrap=_ZN3tmm15MediaController4playERK7QStringib,--wrap=_ZN3tmm15MediaController4seekEj,--wrap=_ZN3tmm15MediaController9setVolumeEi -lezxsound -lqte-mt -lezxappbase -lezxpm -lm -ldl -lpthread -lrt -lresolv -o $@
