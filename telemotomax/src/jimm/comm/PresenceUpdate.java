package jimm.comm;

import jimm.ContactItem;
import jimm.ContactList;
import jimm.JimmException;

/** Read immutable user-info records on the UI thread, without TLV copies. */
public final class PresenceUpdate {
    private static JimmException invalid() { return new JimmException(133, 4, false); }

    public static void apply(byte[] data, boolean arrived) throws JimmException {
        boolean batch = false;
        try {
            int offset = 0;
            while (offset < data.length) {
                int nameLength = Util.getByte(data, offset);
                int marker = offset + 1 + nameLength;
                if (data.length - marker < 4) throw invalid();
                String uin = Util.byteArrayToString(data, offset + 1, nameLength);
                int count = Util.getWord(data, marker + 2);
                marker += 4;
                int status = arrived ? ContactList.STATUS_ONLINE : ContactList.STATUS_OFFLINE;
                int signon = -1, online = -1, idle = -1, regdate = -1;
                int capsOffset = 0, capsLength = 0, shortOffset = 0, shortLength = 0;
                //#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
                byte[] hash = arrived ? new byte[16] : null;
                //#sijapp cond.end#
                for (int i = 0; i < count; i++) {
                    if (data.length - marker < 4) throw invalid();
                    int type = Util.getWord(data, marker), length = Util.getWord(data, marker + 2);
                    marker += 4;
                    if (length > data.length - marker) throw invalid();
                    if (type == 0x0006) {
                        if (length < 4) throw invalid();
                        status = (int)Util.getDWord(data, marker);
                    } else if (type == 0x000D) {
                        capsOffset = marker; capsLength = length;
                    } else if (type == 0x0019) {
                        shortOffset = marker; shortLength = length;
                    } else if (type == 0x001D) {
                        int end = marker + length, part = marker;
                        while (part < end) {
                            if (end - part < 4) throw invalid();
                            int id = Util.getWord(data, part), flags = Util.getByte(data, part + 2);
                            int size = Util.getByte(data, part + 3);
                            part += 4;
                            if (size > end - part) throw invalid();
                            //#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
                            if (arrived && id == 1 && flags == 1)
                                System.arraycopy(data, part, hash, 0, Math.min(size, 16));
                            //#sijapp cond.end#
                            part += size;
                        }
                    } else if (type == 0x0003) {
                        signon = (int)Util.gmtTimeToLocalTime(number(data, marker, length));
                    } else if (type == 0x0004) {
                        idle = (int)number(data, marker, length) / (length == 2 ? 1 : 256);
                    } else if (type == 0x000F) {
                        online = (int)number(data, marker, length);
                    } else if (type == 0x0005) {
                        regdate = (int)number(data, marker, length);
                    }
                    marker += length;
                }
                if (!batch && marker < data.length) {
                    ContactList.beginPresenceUpdates();
                    batch = true;
                }
                if (arrived) {
                    ContactItem item = ContactList.getItembyUIN(uin);
                    if (item != null)
                        Icq.parseCapabilities(item, data, capsOffset, capsLength, shortOffset, shortLength);
                    ContactList.update(uin, status, null, null, 0, 0, 0, 0, signon, online, idle, regdate
                        //#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
                        , hash
                        //#sijapp cond.end#
                    );
                } else ContactList.update(uin, ContactList.STATUS_OFFLINE);
                offset = marker;
            }
        } finally {
            if (batch) ContactList.endPresenceUpdates();
        }
    }

    private static long number(byte[] data, int offset, int length) {
        long value = 0;
        for (int i = 0; i < length; i++) value = (value << 8) | Util.getByte(data, offset + i);
        return value;
    }
}
