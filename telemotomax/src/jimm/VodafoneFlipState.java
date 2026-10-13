package jimm;

import com.vodafone.system.DeviceControl;

/** Loaded only through Class.forName; absent vendor APIs remain optional. */
public final class VodafoneFlipState extends FlipState
{
	private final DeviceControl device;

	public VodafoneFlipState() { device = DeviceControl.getDefaultDeviceControl(); }

	protected int readState()
	{
		// R4515_G_08.BD.B3R: selector 7 reads the physical cover; 0 open, 1 closed.
		return device.getDeviceState(7);
	}
}
