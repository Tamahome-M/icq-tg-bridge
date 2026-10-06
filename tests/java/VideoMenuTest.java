import jimm.Jimm;
import jimm.JimmScreen;
import jimm.JimmUI;
import jimm.MediaPlayer;
import jimm.VideoMenu;
import javax.microedition.lcdui.List;

public final class VideoMenuTest {
    private static final class Back implements JimmScreen {
        int activations;
        public void activate() { activations++; }
        public boolean isScreenActive() { return false; }
    }
    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    public static void main(String[] args) {
        Back back = new Back();
        byte[] token = new byte[16];
        String url = "http://host/v/Abc_123-token4567";
        VideoMenu.show("123", token, url, back);
        List menu = (List) Jimm.display.getCurrent();
        check(menu.labels.size() == 2, "both choices must be visible");
        check(Jimm.openedUrl == null && MediaPlayer.playedToken == null,
            "showing the menu must not fetch video or open the browser");
        menu.choose(0);
        check(MediaPlayer.playedToken == token && MediaPlayer.playedUin.equals("123"),
            "Watch must request the captured video in the native player");
        check(MediaPlayer.playedBack == back, "native player lost the return screen");
        MediaPlayer.playedToken = null;
        VideoMenu.show("123", token, url, back);
        ((List) Jimm.display.getCurrent()).choose(1);
        check(url.equals(Jimm.openedUrl) && MediaPlayer.playedToken == null,
            "browser choice must open exactly the URL without requesting native video");
        Jimm.openedUrl = null;
        VideoMenu.show("123", token, url, back);
        menu = (List) Jimm.display.getCurrent();
        menu.listener.commandAction(JimmUI.cmdBack, menu);
        check(Jimm.openedUrl == null && MediaPlayer.playedToken == null && back.activations == 3,
            "Back must cancel without downloading video");
        VideoMenu.show("123", null, url, back);
        menu = (List) Jimm.display.getCurrent();
        check(menu.labels.size() == 1, "missing attachment must not offer a broken player");
        menu.choose(0);
        check(url.equals(Jimm.openedUrl), "URL-only choice failed");
        VideoMenu.show("123", token, null, back);
        menu = (List) Jimm.display.getCurrent();
        check(menu.labels.size() == 1, "old bridge must not offer an empty browser link");
        menu.choose(0);
        check(MediaPlayer.playedToken == token, "old bridge native video failed");
        System.out.println("PASS: video menu, player, browser, cancellation and legacy bridge");
    }
}
