import java.lang.reflect.*;
import java.util.*;
import jimm.Options;
import javax.microedition.lcdui.ChoiceGroup;

public final class VideoSettingsTest {
    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    public static void main(String[] args) throws Exception {
        boolean v8 = args[0].equals("v8");
        Field options = Options.class.getDeclaredField("options");
        options.setAccessible(true);
        Hashtable values = new Hashtable();
        for (int i=0;i<64;i++) values.put(new Integer(i), "");
        for (int i=64;i<128;i++) values.put(new Integer(i), new Integer(0));
        for (int i=128;i<192;i++) values.put(new Integer(i), Boolean.FALSE);
        options.set(null, values);
        Field sizeField = Options.class.getDeclaredField("MEDIA_VIDEO_SIZES");
        Field bitField = Options.class.getDeclaredField("MEDIA_VIDEO_KBPS");
        sizeField.setAccessible(true); bitField.setAccessible(true);
        String[] sizes = (String[])sizeField.get(null);
        int[] rates = (int[])bitField.get(null);
        check(Arrays.equals(sizes, v8 ? new String[]{"176x144","144x176","240x180","320x240","240x320","480x640","640x480"}
            : new String[]{"128x96","176x144"}), "wrong resolution choices");
        check(Arrays.equals(rates, v8 ? new int[]{32,48,64,96,128,192,256,384}
            : new int[]{16,24,32,48,64,96,120}), "wrong bitrate choices");
        Class formClass = Class.forName("jimm.OptionsForm");
        Field unsafeField = sun.misc.Unsafe.class.getDeclaredField("theUnsafe");
        unsafeField.setAccessible(true);
        Object form = ((sun.misc.Unsafe)unsafeField.get(null)).allocateInstance(formClass);
        Method choiceSize = formClass.getDeclaredMethod("mediaChoice", String.class, String[].class, String.class);
        Method choiceBit = formClass.getDeclaredMethod("mediaChoice", String.class, int[].class, Integer.TYPE, Boolean.TYPE);
        Method valueSize = formClass.getDeclaredMethod("mediaValue", ChoiceGroup.class, String[].class);
        Method valueBit = formClass.getDeclaredMethod("mediaValue", ChoiceGroup.class, int[].class);
        Method pairs = jimm.comm.Icq.class.getDeclaredMethod("mediaPairs");
        for (Method method : new Method[]{choiceSize,choiceBit,valueSize,valueBit,pairs}) method.setAccessible(true);
        for (String size : sizes) for (int rate : rates) {
            ChoiceGroup sg = (ChoiceGroup)choiceSize.invoke(form, "size", sizes, size);
            ChoiceGroup bg = (ChoiceGroup)choiceBit.invoke(form, "rate", rates, rate, false);
            check(sg.size()==sizes.length+1 && bg.size()==rates.length+1, "choices must include profile default");
            check(size.equals(sg.getString(sg.getSelectedIndex())), "resolution selection lost");
            check(String.valueOf(rate).equals(bg.getString(bg.getSelectedIndex())), "bitrate selection lost");
            Options.setString(Options.OPTION_MEDIA_VIDEO_SIZE, (String)valueSize.invoke(null, sg, sizes));
            Options.setInt(Options.OPTION_MEDIA_VIDEO_KBPS, ((Integer)valueBit.invoke(null,bg,rates)).intValue());
            int[] dimensions = Options.mediaSize(Options.OPTION_MEDIA_VIDEO_SIZE);
            check((dimensions[0]+"x"+dimensions[1]).equals(size), "saved resolution changed");
            check(Options.mediaVideoKbps()==rate, "saved bitrate changed");
            int[] sent = (int[])pairs.invoke(null);
            Map map = new HashMap();
            for (int i=0;i<sent.length;i+=2) map.put(sent[i],sent[i+1]);
            check(map.get(4).equals(dimensions[0]) && map.get(5).equals(dimensions[1]) && map.get(6).equals(rate),
                "client must transmit the selected width, height and bitrate");
        }
        Options.setString(Options.OPTION_MEDIA_VIDEO_SIZE, "320x240");
        Options.setInt(Options.OPTION_MEDIA_VIDEO_KBPS, 128);
        check(Options.mediaVideoKbps()==(v8?128:120), "legacy bitrate migration failed");
        check(v8 ? Options.mediaSize(Options.OPTION_MEDIA_VIDEO_SIZE)[0]==320
            : Options.mediaSize(Options.OPTION_MEDIA_VIDEO_SIZE)==null, "legacy resolution migration failed");
        Options.setString(Options.OPTION_MEDIA_VIDEO_SIZE, "");
        Options.setInt(Options.OPTION_MEDIA_VIDEO_KBPS, 0);
        check(Options.mediaSize(Options.OPTION_MEDIA_VIDEO_SIZE)==null && Options.mediaVideoKbps()==0, "profile default changed");
        System.out.println("PASS: "+args[0]+" actual Options choices, RMS values and Icq media pairs; legacy migration");
    }
}
