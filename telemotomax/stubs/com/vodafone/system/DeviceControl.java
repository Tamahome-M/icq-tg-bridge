package com.vodafone.system;

/** Compile-only signatures; this class must never be packaged in the MIDlet. */
public class DeviceControl
{
	public static DeviceControl getDefaultDeviceControl() { throw new RuntimeException("compile-only"); }
	public int getDeviceState(int selector) { throw new RuntimeException("compile-only"); }
}
