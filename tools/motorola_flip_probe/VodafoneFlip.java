import com.vodafone.system.BodyOpenListener;
import com.vodafone.system.DeviceControl;

/** Loaded separately so absent vendor APIs cannot prevent the MIDP probe starting. */
public final class VodafoneFlip implements FlipReader, BodyOpenListener {
    private FlipProbe probe;

    public VodafoneFlip() { }

    public void attach(FlipProbe target) {
        probe = target;
        DeviceControl.setBodyOpenListener(this);
    }

    public int readState() {
        // Selector 7 is the FLIP_STATE branch of R4515_G_08.BD.B3R's native handler.
        return DeviceControl.getDefaultDeviceControl().getDeviceState(7);
    }

    public void bodyOpened() { probe.log("BodyOpenListener.bodyOpened"); }
    public void bodyClosed() { probe.log("BodyOpenListener.bodyClosed"); }
    public void detach() { DeviceControl.setBodyOpenListener(null); }
}
