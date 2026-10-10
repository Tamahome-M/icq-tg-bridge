package jimm;

import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.*;
import jimm.comm.Util;
import jimm.comm.UrlMessage;

/** Tests the actual chat queue/layout and portable text conversion. */
public final class ChatMemoryTest {
    static boolean baseline;
    static volatile Object sink;
    static final int ROUNDS = 4096;
    static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    static Field field(Class type, String name) throws Exception {
        Field f = type.getDeclaredField(name); f.setAccessible(true); return f;
    }
    static Method method(Class type, String name, Class... args) throws Exception {
        Method m = type.getDeclaredMethod(name, args); m.setAccessible(true); return m;
    }
    static Vector lines(TextList list) throws Exception { return (Vector)field(TextList.class, "lines").get(list); }
    static void flush(ChatTextList chat) throws Exception { method(ChatTextList.class, "flushDeferred").invoke(chat); }
    static ChatTextList chat() {
        ChatHistory.currentChat = null; Jimm.display.setCurrent((Displayable)null);
        return new ChatTextList("test", new ContactItem(1, 1, "1000001", "test", false, true));
    }
    static void add(ChatTextList chat, int id) {
        chat.addTextToForm("author", "body" + id + "\nsecond", "", 120000 + id, true, false, id);
    }
    static void boundsAndOrder() throws Exception {
        ChatTextList chat = chat(); ChatHistory.currentChat = chat;
        for (int i = 0; i < 15; i++) add(chat, i);
        chat.textList.selectTextByIndex(14);
        ChatHistory.currentChat = null;
        add(chat, 15);
        System.out.println("METRIC chat: 15 shown + 1 background = " + chat.messageCount());
        if (!baseline) {
            check(chat.messageCount() == 15, "background messages bypass the combined chat limit");
            check(chat.textList.getCurrTextIndex() == 14, "oldest-message eviction moved the selected message");
        }
        for (int i = 16; i < 60; i++) {
            add(chat, i);
            if (!baseline) check(chat.messageCount() <= 15, "chat retained more than its configured total");
        }
        if (!baseline) {
            check(chat.getMessData().isEmpty(), "obsolete formatted messages remain beside the background queue");
            final Vector pending = chat.deferred;
            Font.beforeMeasure = new Runnable() { public void run() {
                check(pending.firstElement() == null, "source strings retained while their replacement rows are formatted");
            }};
        }
        flush(chat);
        check(chat.deferred == null && chat.messageCount() == 15, "queue was not drained to the chat limit");
        int first = field(ChatTextList.class, "firstMess").getInt(chat);
        for (int i = 0; i < 15; i++) {
            MessData md = (MessData)chat.getMessData().elementAt(i);
            check(md.getMessId() == 45 + i, "eviction changed chronological order");
            check(chat.textList.getTextByIndex(md.getOffset(), false, first + i).indexOf("body" + (45 + i)) >= 0,
                "text no longer matches message metadata after eviction");
        }
        if (!baseline) {
            ChatHistory.currentChat = null; Options.setInt(Options.OPTION_CHAT_MESSAGES, 5); add(chat, 60);
            check(chat.messageCount() == 5, "a reduced chat limit did not evict old formatted messages");
            flush(chat); check(((MessData)chat.getMessData().firstElement()).getMessId() == 56, "limit change removed the newest messages");
            Options.setInt(Options.OPTION_CHAT_MESSAGES, 15);
            chat = chat(); add(chat, 1); add(chat, 2); add(chat, 3);
            ChatHistory.currentChat = chat; add(chat, 4);
            check(chat.deferred == null && chat.getMessData().size() == 4, "visible chat did not flush older background messages");
            for (int i = 0; i < 4; i++) check(((MessData)chat.getMessData().elementAt(i)).getMessId() == i + 1,
                "visible message overtook the background queue");
        }
        System.out.println("PASS: combined chat limit, oldest eviction, selection, chronological text/IDs and draining on return");
    }
    static boolean hasImage(TextList list, int textIndex, Image image) throws Exception {
        for (Object line : lines(list)) {
            if (field(line.getClass(), "bigTextIndex").getInt(line) != textIndex) continue;
            int count = ((Integer)method(line.getClass(), "size").invoke(line)).intValue();
            Method at = method(line.getClass(), "elementAt", int.class);
            for (int i = 0; i < count; i++) {
                Object item = at.invoke(line, i); Image[] images = (Image[])field(item.getClass(), "image").get(item);
                if (images != null && images[0] == image) return true;
            }
        }
        return false;
    }
    static void metadataAndDelivery() throws Exception {
        ChatTextList chat = chat(); Hashtable chats = (Hashtable)field(ChatHistory.class, "historyTable").get(null);
        chats.put("1000001", chat); Options.setBoolean(Options.OPTION_DELIV_MES_INFO, true);
        byte[][] tokens = new byte[4][], refs = new byte[4][];
        Font.measured = 0;
        for (int i = 0; i < 4; i++) {
            tokens[i] = new byte[]{(byte)i}; refs[i] = new byte[]{(byte)(128 + i)};
            String body = i == 1 ? "[видео](http://host/v/token) подпись" : "body" + i;
            chat.addTextToForm("author", body, "", 120000 + i, i != 1, true, i < 2 ? 9001 : 9001 + i,
                tokens[i], i + 1, "10000" + i, refs[i]);
        }
        check(chat.getMessData().isEmpty() && Font.measured == 0, "background text was laid out before opening its chat");
        byte[] outgoingRef = new byte[]{99}; ChatHistory.setMessageRef("1000001", 9001, outgoingRef);
        ChatHistory.messageIsDelivered("1000001", 9001);
        flush(chat);
        for (int i = 0; i < 4; i++) {
            MessData md = (MessData)chat.getMessData().elementAt(i);
            check(md.attach == tokens[i] && md.attachKind == i + 1, "attachment token/type changed during deferred layout");
            check(md.messageRef == (i == 1 ? outgoingRef : refs[i]), "quote reference changed or was assigned to an incoming message");
            check(("10000" + i).equals(md.thread), "discussion reference changed during deferred layout");
            check(md.getIncoming() == (i != 1) && md.getTime() == 120000 + i, "primitive message metadata changed");
            check(i == 1 ? "http://host/v/token".equals(md.videoUrl) : md.videoUrl == null, "browser video URL lost in deferred layout");
        }
        if (!baseline) {
            check(hasImage(chat.textList, 1, JimmUI.imgMessDeliv) && !hasImage(chat.textList, 1, JimmUI.eventPlainMessageImg),
                "delivery acknowledgement was lost while the outgoing message was deferred");
            check(hasImage(chat.textList, 0, JimmUI.eventPlainMessageImg), "outgoing acknowledgement changed an incoming message");
        }
        chats.remove("1000001");
        if (!baseline) {
            chat = chat(); chats.put("1000001", chat); new ChatHistory();
            UrlMessage url = new UrlMessage("1000001", "100500", 120123, "http://host/v/token", "[видео]");
            url.setAttach(tokens[1], 2); url.setMessageRef(refs[1]);
            ChatHistory.addMessage(chat.contact, url); flush(chat);
            MessData md = (MessData)chat.getMessData().firstElement();
            check(md.getIncoming() && md.attach == tokens[1] && md.messageRef == refs[1], "incoming URL message lost direction, media or quote reference");
            check(md.isURL() && "http://host/v/token".equals(md.videoUrl), "video URL message lost browser action");
            chats.remove("1000001");
        }
        System.out.println("PASS: background photo/video/voice/file metadata, quote references, timestamps and delivery acknowledgements");
    }
    static void compactRows() throws Exception {
        String text = new String(new char[280]).replace('\0', 'W'); TextList list = new TextList("rows");
        for (int i = 0; i < 100; i++) { list.addBigText(text, 0, Font.STYLE_PLAIN, i); list.doCRLF(i); }
        int containers = 0, slots = 0; Vector rows = lines(list);
        for (Object line : rows) for (Field f : line.getClass().getDeclaredFields()) {
            if (f.getType() != Vector.class) continue; f.setAccessible(true); Vector v = (Vector)f.get(line);
            if (v != null) { containers++; slots += v.capacity(); }
        }
        System.out.println("METRIC plain history: rows=" + rows.size() + ", auxiliary Vectors=" + containers + ", slots=" + slots);
        if (!baseline) check(containers == 0, "single-fragment text lines still allocate separate containers");
        Vector before = (Vector)rows.clone(); list.selectTextByIndex(2); int removed = list.removeTextByIndex(0);
        check(removed > 1 && list.getCurrTextIndex() == 2, "bulk row removal changed selection");
        for (int i = 0; i < rows.size(); i++) check(rows.elementAt(i) == before.elementAt(i + removed),
            "bulk oldest removal rebuilt, reordered or lost remaining rows");
        check(list.getTextByIndex(0, false, 0) == null && (text + "\n").equals(list.getTextByIndex(0, false, 1)),
            "bulk row removal changed retained message text");
        System.out.println("PASS: plain history avoids per-row containers; bulk eviction preserves remaining rows, text and selection");
    }
    static void utf8() throws Exception {
        String[] cases = {"", "plain", "Привет, мир!", "x\0y", "\u007f\u0080\u07ff\u0800\uffff", "emoji \ud83d\ude00 !",
            "\ud800x\udc00", "\udbff\udfff", "\ud800\udc00"};
        for (String value : cases) {
            byte[] expected = value.getBytes("UTF-8");
            if (!baseline) {
                check(Arrays.equals(expected, Util.stringToByteArray(value, true)), "UTF-8 encoding differs from the JDK oracle");
                byte[] padded = new byte[expected.length + 7]; Arrays.fill(padded, (byte)255);
                System.arraycopy(expected, 0, padded, 3, expected.length); padded[3 + expected.length] = 0; padded[4 + expected.length] = 0;
                check(new String(expected, "UTF-8").equals(Util.byteArrayToString(padded, 3, expected.length + 2, true)),
                    "standard UTF-8 decoding/offset/NUL trimming differs from the JDK oracle");
            }
            if (value.indexOf('\ud800') < 0 && value.indexOf('\udbff') < 0) {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream(); new DataOutputStream(bytes).writeUTF(value);
                byte[] legacy = bytes.toByteArray();
                check(value.equals(Util.byteArrayToString(legacy, 2, legacy.length - 2, true)), "legacy Jimm modified UTF-8 no longer decodes");
            }
        }
        if (!baseline) {
            StringBuffer all = new StringBuffer();
            for (int c = 0; c < 65536; c++) all.append((char)c);
            String value = all.toString(); byte[] expected = value.getBytes("UTF-8");
            check(Arrays.equals(expected, Util.stringToByteArray(value, true)), "full BMP encoding differs from the independent charset oracle");
            check(new String(expected, "UTF-8").equals(Util.byteArrayToString(expected, true)), "full BMP decoding or >64-KB text conversion failed");
            Random random = new Random(17); StringBuffer astral = new StringBuffer();
            for (int i = 0; i < 1024; i++) astral.append(Character.toChars(0x10000 + random.nextInt(0x100000)));
            value = astral.toString(); expected = value.getBytes("UTF-8");
            check(Arrays.equals(expected, Util.stringToByteArray(value, true)) && value.equals(Util.byteArrayToString(expected, true)),
                "supplementary Unicode encoding/decoding differs from the JDK oracle");
            byte[][] bad = {{(byte)0x80}, {(byte)0xC2}, {(byte)0xC2, 'A'}, {(byte)0xC1,(byte)0xBF},
                {(byte)0xE0,(byte)0x80,(byte)0x80}, {(byte)0xF0,(byte)0x80,(byte)0x80,(byte)0x80},
                {(byte)0xF4,(byte)0x90,(byte)0x80,(byte)0x80}, {(byte)0xF5,(byte)0x80,(byte)0x80,(byte)0x80},
                {(byte)0xE2,(byte)0x82}, {(byte)0xFF}};
            for (boolean cp1251 : new boolean[]{false, true}) {
                Options.setBoolean(Options.OPTION_CP1251_HACK, cp1251);
                for (byte[] b : bad) check(Util.byteArrayToString(b, false).equals(Util.byteArrayToString(b, true)),
                    "malformed UTF-8 lost the configured legacy encoding fallback");
            }
            byte[] b = new byte[4];
            for (int[] bounds : new int[][]{{-1,1},{0,-1},{5,0},{3,2},{Integer.MAX_VALUE,1},{1,Integer.MAX_VALUE}})
                check(Util.byteArrayToString(b, bounds[0], bounds[1], true) == null, "invalid text range was not rejected");
        }
        System.out.println("PASS: standard UTF-8 against JDK oracle, supplementary characters, legacy modified UTF-8, bounds and fallback");
    }
    static void allocations() throws Exception {
        com.sun.management.ThreadMXBean meter = (com.sun.management.ThreadMXBean)java.lang.management.ManagementFactory.getThreadMXBean();
        check(meter.isThreadAllocatedMemorySupported(), "desktop allocation meter unavailable"); meter.setThreadAllocatedMemoryEnabled(true);
        long id = Thread.currentThread().getId(); String value = new String(new char[900]).replace('\0', 'Ж');
        byte[] raw = value.getBytes("UTF-8"); ChatTextList chat = chat();
        for (int i = 0; i < 1024; i++) {
            sink = Util.stringToByteArray(value, true); sink = Util.byteArrayToString(raw, true);
            chat.addTextToForm("author", "message", "", 120000 + i, true, false, 9001 + i, null, 1, null, null);
        }
        long before = meter.getThreadAllocatedBytes(id);
        for (int i = 0; i < ROUNDS; i++) sink = Util.stringToByteArray(value, true);
        long encoded = meter.getThreadAllocatedBytes(id) - before; before = meter.getThreadAllocatedBytes(id);
        for (int i = 0; i < ROUNDS; i++) sink = Util.byteArrayToString(raw, true);
        long decoded = meter.getThreadAllocatedBytes(id) - before; before = meter.getThreadAllocatedBytes(id);
        for (int i = 0; i < ROUNDS; i++) chat.addTextToForm("author", "message", "", 120000 + i, true, false, 9001 + i, null, 1, null, null);
        long queued = meter.getThreadAllocatedBytes(id) - before;
        System.out.println("METRIC desktop 4096 x 900 Cyrillic chars: encode=" + encoded + ", decode=" + decoded + "; enqueue=" + queued);
        if (!baseline) {
            check(encoded <= ROUNDS * (raw.length + 96L), "encoding still allocates several full byte buffers");
            check(decoded <= ROUNDS * (value.length() * 4L + 256), "decoding still retains redundant packet copies");
            check(queued <= ROUNDS * 96L, "deferred metadata still allocates boxed values and an Object[] per message");
        }
        System.out.println("PASS: bounded text-conversion and deferred-message allocation on desktop VM with escape analysis disabled");
    }
    public static void main(String[] args) throws Exception {
        baseline = args.length > 0 && args[0].equals("baseline");
        try {
            field(Options.class, "options").set(null, new Hashtable()); method(Options.class, "setDefaults").invoke(null);
            Constructor main = MainThread.class.getDeclaredConstructor(); main.setAccessible(true); main.newInstance();
            Options.setBoolean(Options.OPTION_USE_SMILES, false); Options.setInt(Options.OPTION_CHAT_MESSAGES, 15);
            boundsAndOrder(); metadataAndDelivery(); compactRows(); utf8(); allocations();
        } finally {
            Font.beforeMeasure = null; Jimm.getTimerRef().cancel();
            Object canvas = field(VirtualList.class, "virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(), "repeatTimer").get(canvas)).cancel();
        }
    }
}
