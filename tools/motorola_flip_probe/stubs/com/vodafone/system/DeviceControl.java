package com.vodafone.system;

/** Compile-time signatures only; implementation comes from the phone firmware. */
public class DeviceControl {
    public static DeviceControl getDefaultDeviceControl() { return null; }
    public int getDeviceState(int selector) { return 0; }
    public static void setBodyOpenListener(BodyOpenListener listener) { }
}
