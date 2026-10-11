/*******************************************************************************
 Jimm - Mobile Messaging - J2ME ICQ clone
 Copyright (C) 2003-04  Jimm Project

 This program is free software; you can redistribute it and/or
 modify it under the terms of the GNU General Public License
 as published by the Free Software Foundation; either version 2
 of the License, or (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program; if not, write to the Free Software
 Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
 ********************************************************************************
 File: src/jimm/comm/SearchAction.java
 Version: ###VERSION###  Date: ###DATE###
 Author(s): Andreas Rossbacher
 *******************************************************************************/

package jimm.comm;

import java.io.ByteArrayOutputStream;
import jimm.JimmException;
import jimm.Options;
import jimm.Search;

/** UIN lookup or a single chat-name query; retains only bridge result fields. */
public final class SearchAction extends Action
{
    public static final int TLV_TYPE_UIN = 0x3601, TLV_TYPE_KEYWORD = 0x2602;
    private Search owner;
    private final String query;
    private final boolean byUin;
    private boolean done, failed, notified;
    private long lastActivity;

    public SearchAction(Search owner, String query, boolean byUin)
    { super(true, true); this.owner = owner; this.query = query; this.byUin = byUin; }

    protected void init() throws JimmException
    {
        ByteArrayOutputStream body = new ByteArrayOutputStream();
        Util.writeWord(body, 0x5f05, true);
        if (byUin)
        {
            int uin;
            try { uin = Integer.parseInt(query); }
            catch (NumberFormatException error) { failed = true; return; }
            Util.writeWord(body, TLV_TYPE_UIN, true);
            Util.writeWord(body, 4, false);
            Util.writeDWord(body, uin, false);
        }
        else Util.writeAsciizTLV(TLV_TYPE_KEYWORD, body, query);
        Icq.sendPacket(new ToIcqSrvPacket(SnacPacket.CLI_TOICQSRV_COMMAND, 2,
                Options.getString(Options.OPTION_UIN), 0x07D0, new byte[0], body.toByteArray()));
        lastActivity = System.currentTimeMillis();
    }

    protected boolean forward(Packet packet) throws JimmException
    {
        if (done || failed || !(packet instanceof FromIcqSrvPacket)) return false;
        byte[] data = ((FromIcqSrvPacket)packet).getDataRef();
        if (data.length < 3) return false;
        int type = Util.getWord(data, 0);
        if (type != 0xa401 && type != 0xae01) return false;
        lastActivity = System.currentTimeMillis();
        if (data[2] != 10) { failed = true; return true; }
        try
        {
            if (data.length < 9) throw new IllegalArgumentException();
            String uin = String.valueOf(Util.getDWord(data, 5, false));
            String name = uin;
            int at = 9;
            for (int i = 0; i < 4; i++)
            {
                if (at + 2 > data.length) throw new IllegalArgumentException();
                int length = Util.getWord(data, at, false); at += 2;
                if (length > data.length - at) throw new IllegalArgumentException();
                if (i == 0) name = Util.byteArrayToString(data, at, length);
                at += length;
            }
            if (at >= data.length) throw new IllegalArgumentException();
            owner.addResult(uin, name, data[at] == 0);
            done = type == 0xae01;
        }
        catch (RuntimeException malformed) { failed = true; }
        return true;
    }

    public void onEvent(int event)
    {
        if (notified) return;
        notified = true; done = true;
        Search result = owner; owner = null;
        if (result != null) result.finished(event);
    }
    public boolean isCompleted() { return done; }
    public long getDeadline() { return lastActivity == 0 || done ? Long.MAX_VALUE : lastActivity + 60000; }
    public boolean isError() { return failed || System.currentTimeMillis() >= getDeadline(); }
}
