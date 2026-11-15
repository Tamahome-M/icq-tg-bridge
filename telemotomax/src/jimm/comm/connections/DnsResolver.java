package jimm.comm.connections;

import java.io.IOException;
import java.util.Random;
import java.util.Timer;
import java.util.TimerTask;
import javax.microedition.io.Connector;
import javax.microedition.io.Datagram;
import javax.microedition.io.DatagramConnection;

/** One bounded startup DNS lookup. No platform name lookup or persistent worker. */
public final class DnsResolver {
    private static final int TIMEOUT = 12000;
    private static final int MAX_ALIASES = 8;
    private static final int MAX_PACKETS = 16;
    private DatagramConnection connection;
    private Timer timer;
    private boolean used, cancelled, expired;
    private long deadline;

    /** IPv4 literals are decimal, with no ambiguous leading zeroes. */
    public static boolean isIPv4(String value) {
        if (value == null || value.length() < 7 || value.length() > 15) return false;
        int parts = 0, number = 0, digits = 0;
        for (int i = 0; i <= value.length(); i++) {
            char c = i == value.length() ? '.' : value.charAt(i);
            if (c == '.') {
                if (digits == 0 || ++parts > 4) return false;
                number = digits = 0;
            } else {
                if (c < '0' || c > '9' || digits == 3 || (digits != 0 && number == 0)) return false;
                number = number * 10 + c - '0';
                if (number > 255) return false;
                digits++;
            }
        }
        return parts == 4;
    }

    private static int address(String value) {
        int result = 0, number = 0;
        for (int i = 0; i <= value.length(); i++) {
            char c = i == value.length() ? '.' : value.charAt(i);
            if (c == '.') { result = (result << 8) | number; number = 0; }
            else number = number * 10 + c - '0';
        }
        return result;
    }

    public static String ipv4(int value) {
        return ((value >>> 24) & 255) + "." + ((value >>> 16) & 255)
                + "." + ((value >>> 8) & 255) + "." + (value & 255);
    }

    private static boolean usable(int value) {
        int first = value >>> 24;
        return value != 0 && value != -1 && (first < 224 || first > 239);
    }

    private static String hostname(String value) throws IOException {
        if (value == null) throw new IOException("Invalid DNS host");
        int length = value.length();
        if (length != 0 && value.charAt(length - 1) == '.') length--;
        if (length == 0 || length > 253) throw new IOException("Invalid DNS host");
        StringBuffer result = new StringBuffer(length);
        int label = 0;
        for (int i = 0; i < length; i++) {
            char c = value.charAt(i);
            if (c == '.') {
                if (label == 0) throw new IOException("Invalid DNS host");
                label = 0;
            } else {
                if (!nameChar(c) || ++label > 63) throw new IOException("Invalid DNS host");
                if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
            }
            result.append(c);
        }
        if (label == 0) throw new IOException("Invalid DNS host");
        return result.toString();
    }

    private static boolean nameChar(char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
                || (c >= '0' && c <= '9') || c == '-' || c == '_';
    }

    public int[] lookup(String host, String dnsServer) throws IOException {
        String name = hostname(host);
        if (!isIPv4(dnsServer) || !usable(address(dnsServer)))
            throw new IOException("Invalid DNS server");
        boolean owner = false;
        try {
            synchronized (this) {
                if (used || cancelled) throw new IOException("DNS cancelled or already used");
                used = owner = true;
                if (isIPv4(name)) {
                    if (!usable(address(name))) throw new IOException("Invalid IPv4 host");
                    return new int[] {address(name)};
                }
                deadline = System.currentTimeMillis() + TIMEOUT;
                timer = new Timer();
                timer.schedule(new TimerTask() {
                    public void run() { expire(); }
                }, TIMEOUT);
            }
            String remote = "datagram://" + dnsServer + ":53";
            // A native Connector.open may itself ignore the timeout hint. Do
            // not hold our monitor: cancel/expiry must still mark a late open.
            DatagramConnection opened = (DatagramConnection)Connector.open(remote, Connector.READ_WRITE, true);
            boolean admitted = false;
            synchronized (this) {
                if (!cancelled && !expired && System.currentTimeMillis() < deadline) {
                    connection = opened;
                    admitted = true;
                }
            }
            if (!admitted) { close(opened); check(); throw new IOException("DNS timed out"); }
            byte[] buffer = new byte[512];
            Datagram packet = opened.newDatagram(buffer, buffer.length, remote);
            String[] chain = new String[MAX_ALIASES + 1];
            chain[0] = name;
            int chainSize = 1;
            int[] answers = new int[4];
            Random random = new Random();
            for (int exchange = 0; exchange <= MAX_ALIASES; exchange++) {
                check();
                int id = random.nextInt() & 65535;
                int size = query(buffer, id, name);
                packet.setData(buffer, 0, size);
                packet.setAddress(remote);
                opened.send(packet);
                Packet reply = null;
                for (int received = 0; received < MAX_PACKETS; received++) {
                    check();
                    packet.setData(buffer, 0, buffer.length);
                    opened.receive(packet);
                    check();
                    if (!source(packet.getAddress(), dnsServer)) continue;
                    int offset = packet.getOffset();
                    size = packet.getLength();
                    byte[] data = packet.getData();
                    if (offset < 0 || size < 2 || size > buffer.length || offset > data.length - size) continue;
                    if (word(data, offset) != id) continue;
                    if (data != buffer || offset != 0) System.arraycopy(data, offset, buffer, 0, size);
                    Packet candidate = new Packet(buffer, size);
                    if (!candidate.question(name)) continue;
                    reply = candidate;
                    break;
                }
                if (reply == null) throw new IOException("DNS reply not received");
                int count = reply.answers(name, chain, chainSize, answers);
                chainSize = reply.chainSize;
                if (count != 0) {
                    int[] result = new int[count];
                    System.arraycopy(answers, 0, result, 0, count);
                    check();
                    return result;
                }
                name = chain[chainSize - 1];
            }
            throw new IOException("DNS CNAME limit");
        } catch (IOException failure) {
            if (owner) check();
            throw failure;
        } catch (SecurityException denied) {
            if (owner) check();
            throw new IOException("DNS permission denied");
        } finally {
            if (owner) release(false, false);
        }
    }

    public void cancel() { release(true, false); }
    private void expire() { release(false, true); }

    private void release(boolean cancel, boolean timeout) {
        DatagramConnection pending;
        Timer clock;
        synchronized (this) {
            cancelled |= cancel;
            expired |= timeout;
            pending = connection; connection = null;
            clock = timer; timer = null;
        }
        if (clock != null) clock.cancel();
        close(pending);
    }

    private static void close(DatagramConnection pending) {
        if (pending != null) try { pending.close(); } catch (IOException ignored) { }
    }

    private synchronized void check() throws IOException {
        if (cancelled) throw new IOException("DNS cancelled");
        if (expired || (deadline != 0 && System.currentTimeMillis() >= deadline))
            throw new IOException("DNS timed out");
    }

    private static boolean source(String source, String server) {
        if (source == null) return false;
        if (source.startsWith("datagram://")) source = source.substring(11);
        else if (source.startsWith("//")) source = source.substring(2);
        return source.equals(server + ":53");
    }

    private static int word(byte[] data, int at) { return ((data[at] & 255) << 8) | (data[at + 1] & 255); }
    private static void put(byte[] data, int at, int value) { data[at] = (byte)(value >>> 8); data[at + 1] = (byte)value; }

    private static int query(byte[] data, int id, String name) {
        for (int i = 0; i < 12; i++) data[i] = 0;
        put(data, 0, id); put(data, 2, 0x0100); put(data, 4, 1);
        int at = 12, start = 0;
        for (int i = 0; i <= name.length(); i++) if (i == name.length() || name.charAt(i) == '.') {
            data[at++] = (byte)(i - start);
            while (start < i) data[at++] = (byte)name.charAt(start++);
            start = i + 1;
        }
        data[at++] = 0;
        put(data, at, 1); put(data, at + 2, 1);
        return at + 4;
    }

    /** Packet cursors never follow a pointer outside this 512-byte reply. */
    private static final class Packet {
        private final byte[] data;
        private final int length;
        private int at, answerCount, recordCount;
        private int[] records;
        int chainSize;

        Packet(byte[] data, int length) throws IOException {
            this.data = data; this.length = length;
            if (length < 12) bad();
        }
        private static void bad() throws IOException { throw new IOException("Invalid DNS reply"); }
        private void skip(int count) throws IOException {
            if (count < 0 || count > length - at) bad();
            at += count;
        }
        private int number() throws IOException {
            int start = at; skip(2); return word(data, start);
        }
        private String name() throws IOException {
            int position = at, end = -1, jumps = 0;
            StringBuffer result = new StringBuffer(64);
            while (true) {
                if (position >= length) { bad(); }
                int size = data[position++] & 255;
                if (size == 0) { at = end < 0 ? position : end; return result.toString(); }
                if ((size & 192) == 192) {
                    if (position >= length || ++jumps > 128) bad();
                    int pointer = ((size & 63) << 8) | (data[position] & 255);
                    // RFC 1035 compression refers to a prior occurrence.
                    if (pointer < 12 || pointer >= position - 1) bad();
                    if (end < 0) end = position + 1;
                    position = pointer;
                    continue;
                }
                if (size > 63 || size > length - position) bad();
                if (result.length() != 0) result.append('.');
                if (result.length() + size > 253) bad();
                for (int i = 0; i < size; i++) {
                    char c = (char)(data[position++] & 255);
                    if (!nameChar(c)) bad();
                    if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
                    result.append(c);
                }
            }
        }
        boolean question(String expected) throws IOException {
            int flags = word(data, 2);
            if ((flags & 0x8000) == 0 || (flags & 0x7840) != 0 || word(data, 4) != 1) bad();
            if ((flags & 0x0200) != 0) throw new IOException("DNS truncated reply");
            answerCount = word(data, 6);
            recordCount = answerCount + word(data, 8) + word(data, 10);
            at = 12;
            String asked = name();
            int type = number(), cls = number();
            if (!asked.equals(expected) || type != 1 || cls != 1) return false;
            if ((flags & 15) != 0) throw new IOException("DNS server error " + (flags & 15));
            if (recordCount > (length - at) / 11) bad();
            records = new int[answerCount];
            for (int i = 0; i < recordCount; i++) {
                if (i < answerCount) records[i] = at;
                name(); type = number(); cls = number(); skip(4);
                int size = number(), start = at;
                skip(size);
                if (i < answerCount && cls == 1) {
                    if (type == 1 && size != 4) bad();
                    if (type == 5) {
                        int end = at; at = start; name();
                        if (at != end) bad();
                    }
                }
            }
            if (at != length) bad();
            return true;
        }
        int answers(String query, String[] chain, int used, int[] results) throws IOException {
            chainSize = used;
            String current = query;
            while (true) {
                String alias = null;
                int count = 0;
                boolean hasAddress = false;
                for (int i = 0; i < records.length; i++) {
                    at = records[i];
                    String owner = name();
                    int type = number(), cls = number(); skip(4);
                    int size = number();
                    if (cls != 1 || !owner.equals(current)) continue;
                    if (type == 5) {
                        String target = name();
                        if (target.length() == 0 || (alias != null && !alias.equals(target))) bad();
                        alias = target;
                    } else if (type == 1) {
                        hasAddress = true;
                        int value = (word(data, at) << 16) | word(data, at + 2);
                        boolean duplicate = false;
                        for (int n = 0; n < count; n++) if (results[n] == value) duplicate = true;
                        if (usable(value) && !duplicate && count < results.length) results[count++] = value;
                    }
                }
                if (alias == null) {
                    if (count == 0 && current.equals(query)) throw new IOException("DNS IPv4 answer missing");
                    return count;
                }
                if (hasAddress) bad();
                if (chainSize == chain.length) throw new IOException("DNS CNAME limit");
                for (int n = 0; n < chainSize; n++) if (chain[n].equals(alias)) throw new IOException("DNS CNAME loop");
                chain[chainSize++] = alias;
                current = alias;
            }
        }
    }
}
