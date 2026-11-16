# Optional real two-process QWS regression, run with tests/run_qws.py.
# Uses only this probe's executable; no test hooks are linked into the client.
.PHONY: input-client-probe
input-client-probe: $(BUILD)/input-client-probe
$(BUILD)/input-client-probe: tests/input_client_probe.cpp $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) -lezxsound -lqte-mt -lezxappbase -lezxpm -lm -ldl -lpthread -lrt -lresolv -o $@
.PHONY: input-late-controller-probe
input-late-controller-probe: $(BUILD)/input-late-controller-probe
$(BUILD)/input-late-controller-probe: tests/input_late_controller_probe.cpp $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) $(BUILD)/sdk-link/.ready
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< $(filter-out $(BUILD)/main.o,$(OBJECTS)) $(MOC_OBJECTS) -lezxsound -lqte-mt -lezxappbase -lezxpm -lm -ldl -lpthread -lrt -lresolv -o $@
