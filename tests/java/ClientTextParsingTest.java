package jimm;

import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.*;
import jimm.comm.Util;

/** Real parsers; an independent greedy oracle uses all aliases in the resource. */
public final class ClientTextParsingTest {
    static boolean baseline;
    static volatile int sink;
    static final int ROUNDS = 256;
    static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    static Field field(Class type, String name) throws Exception {
        Field f = type.getDeclaredField(name); f.setAccessible(true); return f;
    }
    static class Alias {
        String word; int image, order;
        Alias(String w, int i, int o) { word = w.toLowerCase(Locale.ROOT); image = i; order = o; }
    }
    static ArrayList<Alias> aliases(String file) throws Exception {
        ArrayList<Alias> all = new ArrayList<Alias>();
        BufferedReader reader = new BufferedReader(new InputStreamReader(new FileInputStream(file), "UTF-8"));
        try {
            for (String line; (line = reader.readLine()) != null;) {
                String[] pieces = line.split(" +");
                if (pieces.length < 3 || pieces[0].startsWith("#")) continue;
                int image = Integer.parseInt(pieces[0]);
                for (int i = 2; i < pieces.length; i++) {
                    all.add(new Alias(pieces[i], image, all.size()));
                    if (pieces[i].indexOf('_') >= 0 && pieces[i].length() > 3)
                        all.add(new Alias(pieces[i].replace('_', ' '), image, all.size()));
                }
            }
        } finally { reader.close(); }
        Collections.sort(all, new Comparator<Alias>() {
            public int compare(Alias a, Alias b) {
                int length = b.word.length() - a.word.length();
                return length == 0 ? b.order - a.order : length;
            }
        });
        return all;
    }
    static void rendering(TextList list, String text, ArrayList<Alias> all) {
        list.clear(); Emoticons.addTextWithEmotions(list, text, Font.STYLE_BOLD, 0x123456, 42);
        StringBuffer restored = new StringBuffer();
        ArrayList<String> images = new ArrayList<String>();
        int offset = 0;
        for (int i = 0; i < list.labels.size(); i++) {
            String part = (String)list.labels.elementAt(i); int image = ((Integer)list.icons.elementAt(i)).intValue();
            if (image >= 0) images.add(offset + ":" + part.length() + ":" + image);
            restored.append(part); offset += part.length();
        }
        check(text.equals(restored.toString()), "parser lost characters: " + text);
        ArrayList<String> expected = new ArrayList<String>(); String lowered = text.toLowerCase(Locale.ROOT);
        for (int i = 0; i < text.length();) {
            Alias found = null;
            for (Alias candidate : all) if (lowered.startsWith(candidate.word, i)) { found = candidate; break; }
            if (found == null) { i++; continue; }
            expected.add(i + ":" + found.word.length() + ":" + found.image); i += found.word.length();
        }
        check(expected.equals(images), "wrong position, longest alias or image: " + text + " / " + images + " / " + expected);
    }
    static String repeat(String s, int length) {
        StringBuffer b = new StringBuffer(); while (b.length() < length) b.append(s); return b.substring(0, length);
    }
    static void smileChecks(String file) throws Exception {
        new Emoticons(); check(field(Emoticons.class, "used").getBoolean(null), "resource load failed");
        ArrayList<Alias> all = aliases(file); TextList list = new TextList("smiles");
        Options.setBoolean(Options.OPTION_USE_SMILES, true);
        for (Alias alias : all) {
            rendering(list, "before " + alias.word + " after", all);
            rendering(list, alias.word.toUpperCase(Locale.ROOT), all);
        }
        for (String text : new String[] {"", "обычный текст", "СООБЩЕНИЕ БЕЗ СМАЙЛОВ", ":-))) :))) :-)) :)) :)",
                ":-P :p :-D :D *IN LOVE* *IN_LOVE*", "\n:):-):)\r\n:-) end", "🙂Ж😊 ABCI"}) rendering(list, text, all);
        rendering(list, repeat(":-) :P *IN_LOVE* normal ", 900), all);
        Random random = new Random(42);
        for (int n = 0; n < 100; n++) {
            StringBuffer message = new StringBuffer();
            for (int i = 0; i < 8; i++) message.append(i % 2 == 0 ? " ABCЖ\n " : all.get(random.nextInt(all.size())).word);
            rendering(list, message.toString(), all);
        }
        Options.setBoolean(Options.OPTION_USE_SMILES, false); list.clear();
        String source = new String(":-) *IN_LOVE*");
        Emoticons.addTextWithEmotions(list, source, Font.STYLE_BOLD, 0xabcdef, 123);
        check(list.lastText == source && list.lastStyle == Font.STYLE_BOLD && list.lastColor == 0xabcdef && list.lastIndex == 123,
            "disabled smiles copied text or changed its formatting");
        Options.setBoolean(Options.OPTION_USE_SMILES, true);
        System.out.println("PASS: all " + all.size() + " resource aliases, case, overlapping longest matches, images, Unicode, layout parameters and disabled smiles");
        list.capture = false;
        com.sun.management.ThreadMXBean meter = (com.sun.management.ThreadMXBean)java.lang.management.ManagementFactory.getThreadMXBean();
        meter.setThreadAllocatedMemoryEnabled(true); long id = Thread.currentThread().getId();
        for (String text : new String[] {repeat("СООБЩЕНИЕ БЕЗ СМАЙЛОВ AABC ", 900), repeat(":-) :P *IN_LOVE* ", 900)}) {
            for (int i = 0; i < 32; i++) Emoticons.addTextWithEmotions(list, text, 0, 0, 0);
            long before = meter.getThreadAllocatedBytes(id), started = System.nanoTime();
            for (int i = 0; i < ROUNDS; i++) Emoticons.addTextWithEmotions(list, text, 0, 0, 0);
            long time = System.nanoTime() - started, allocated = meter.getThreadAllocatedBytes(id) - before;
            boolean plain = text.charAt(0) == 'С';
            System.out.println("METRIC desktop " + ROUNDS + " x 900 chars, " + (plain ? "plain" : "dense smiles") + ": bytes=" + allocated + ", ns=" + time);
            if (!baseline && plain) check(allocated == 0, "ordinary text still allocates parsing buffers");
        }
        // Fail closed when image decoding cannot fit in the heap.
        ImageList.fail = true; new Emoticons();
        check(!field(Emoticons.class, "used").getBoolean(null), "partially loaded smile resources remain active");
        list.capture = true; list.clear(); Emoticons.addTextWithEmotions(list, source, 0, 0, 0);
        check(list.lastText == source && ((Integer)list.icons.firstElement()).intValue() == -1,
            "no-heap fallback lost ordinary text");
        System.out.println("PASS: smile image OOM disables the parser and preserves the text fallback");
    }
    static void urls() throws Exception {
        if (!baseline) {
            String message = "www.first.test https://second.test http://third.test ftp://fourth.test mailto:user@test.test";
            Vector links = Util.parseMessageForURL(message);
            check(links.equals(new Vector(Arrays.asList("http://www.first.test", "https://second.test", "http://third.test",
                    "ftp://fourth.test", "mailto:user@test.test"))), "schemes or source order lost: " + links);
            links = Util.parseMessageForURL("https://host.test\n https://host.test http://last.test\"");
            check(links.size() == 2 && links.firstElement().equals("https://host.test") && links.lastElement().equals("http://last.test"),
                "duplicate links or final delimiter not handled");
            for (String text : new String[] {null, "", "Привет", "http://", "https://x", "www. ", "mailto:"})
                check(!LinkCheck.has(text) && Util.parseMessageForURL(text) == null, "empty/invalid text offered URL action");
        }
        String video = "prefix [видео](http://host/v/token) caption";
        check(!LinkCheck.visible(video), "hidden video address offers ordinary URL action");
        if (!baseline) {
            check(LinkCheck.visible(video + " https://other.test"), "ordinary HTTPS caption URL was hidden");
            check(LinkCheck.visible("www.before.test " + video), "URL before the video label was hidden");
        }
        System.out.println("PASS: ordinary URLs, video-only labels, preserved caption actions and unique links");
        String text = repeat("HTTP TEXT Ж ", 700) + " http://host.test/" + repeat("x", 180);
        String labelled = "prefix [видео](http://host/v/" + repeat("x", 900) + ") caption";
        com.sun.management.ThreadMXBean meter = (com.sun.management.ThreadMXBean)java.lang.management.ManagementFactory.getThreadMXBean();
        meter.setThreadAllocatedMemoryEnabled(true); long id = Thread.currentThread().getId();
        for (int which = 0; which < 3; which++) {
            for (int i = 0; i < 32; i++) sink = which == 0 ? (LinkCheck.has(text) ? 1 : 0) : which == 1 ? VideoLink.start(labelled) : (LinkCheck.visible(labelled) ? 1 : 0);
            long before = meter.getThreadAllocatedBytes(id), started = System.nanoTime();
            for (int i = 0; i < ROUNDS; i++) sink = which == 0 ? (LinkCheck.has(text) ? 1 : 0) : which == 1 ? VideoLink.start(labelled) : (LinkCheck.visible(labelled) ? 1 : 0);
            long time = System.nanoTime() - started, allocated = meter.getThreadAllocatedBytes(id) - before;
            System.out.println("METRIC desktop " + ROUNDS + " x " + new String[]{"URL presence", "video validation", "visible URL presence"}[which] + ": bytes=" + allocated + ", ns=" + time);
            if (!baseline) check(allocated == 0, "presence/validation allocates discarded URL strings or collections");
        }
    }
    public static void main(String[] args) throws Exception {
        baseline = args[1].equals("baseline");
        field(Options.class, "options").set(null, new Hashtable());
        Method defaults = Options.class.getDeclaredMethod("setDefaults"); defaults.setAccessible(true); defaults.invoke(null);
        try { if (args[2].equals("smiles")) smileChecks(args[0]); urls(); }
        finally { Jimm.getTimerRef().cancel(); }
    }
}
