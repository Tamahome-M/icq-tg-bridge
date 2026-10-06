import jimm.Jimm;
import jimm.VideoLink;

public final class VideoLinkTest {
    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        String url = "http://host:8080/s/session/v/Abc_123-token4567";
        String message = "[06.10 12:00] [видео](" + url + ") 2:05\nПодпись :)";
        java.lang.reflect.Method media = jimm.comm.Icq.class.getDeclaredMethod("mediaPairs", new Class[0]);
        media.setAccessible(true);
        int[] pairs = (int[]) media.invoke(null, new Object[0]);
        int mode = 0;
        for (int i = 0; i < pairs.length; i += 2) if (pairs[i] == 20) mode = pairs[i + 1];
        check(mode == 3, "client must announce both video actions to the bridge");
        check(url.equals(VideoLink.url(message)), "video URL was not extracted");
        check(VideoLink.start(message) == message.indexOf("[видео]("), "wrong label position");
        check(message.substring(VideoLink.end(message)).equals(" 2:05\nПодпись :)"),
            "duration or caption was lost");
        for (String plain : new String[] {null, "обычное сообщение", "[видео 2:05]",
                "[видео](javascript:alert)", "[видео](/v/token)", "[видео](http://host bad)",
                "[видео](http://host\n/v/token)", "[видео](http://host"}) {
            check(VideoLink.url(plain) == null, "invalid marker accepted: " + plain);
        }
        check("https://host/v/token".equals(VideoLink.url("[видео](https://host/v/token)")),
            "HTTPS video link was lost");
        VideoLink.open(VideoLink.url(message));
        check(url.equals(Jimm.openedUrl), "browser received a label or caption instead of the URL");
        System.out.println("PASS: labelled video links preserve captions and open the exact browser URL");
    }
}
