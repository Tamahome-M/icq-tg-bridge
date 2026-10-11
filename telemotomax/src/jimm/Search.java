/*******************************************************************************
 Jimm - Mobile Messaging - J2ME ICQ clone
 Copyright (C) 2003-05  Jimm Project

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
 File: src/jimm/Search.java
 Version: ###VERSION###  Date: ###DATE###
 Author(s): Andreas Rossbacher
 *******************************************************************************/

package jimm;

import java.util.Vector;
import javax.microedition.lcdui.*;
import DrawControls.TextList;
import DrawControls.VirtualList;
import jimm.comm.Icq;
import jimm.comm.SearchAction;
import jimm.util.ResourceBundle;

/** Bridge chat-name search and UIN lookup, without legacy ICQ filters. */
public final class Search implements CommandListener, JimmScreen
{
    private final JimmScreen back;
    private Form query;
    private TextField text;
    private TextList results, groups;
    private final Vector found = new Vector(); // UIN, name, authorization only
    private boolean byUin;
    private final Command search = new Command(ResourceBundle.getString("search_user"), Command.OK, 1);
    private final Command add = new Command(ResourceBundle.getString("add_to_list"), Command.ITEM, 1);
    private final Command message = new Command(ResourceBundle.getString("send_message"), Command.ITEM, 2);
    private final Command info = new Command(ResourceBundle.getString("info"), Command.ITEM, 3);

    public Search(JimmScreen back) { this.back = back; }

    public void show()
    {
        query = new Form(ResourceBundle.getString("search_user"));
        text = new TextField(ResourceBundle.getString("keyword"), "", 64, TextField.ANY);
        query.append(text);
        query.addCommand(search); query.addCommand(JimmUI.cmdBack);
        query.setCommandListener(this);
        activate();
    }

    public boolean lookup(String value, boolean byUin)
    {
        this.byUin = byUin;
        found.removeAllElements();
        SearchAction action = new SearchAction(this, value, byUin);
        try { Icq.requestAction(action); }
        catch (JimmException error) { JimmException.handleException(error); return false; }
        SplashCanvas.addTimerTask("wait", action, true);
        return true;
    }

    public void addResult(String uin, String name, boolean auth)
    { found.addElement(new String[] { uin, name, auth ? "1" : "0" }); }

    public void finished(final int event)
    {
        MainThread.runSerially(new Runnable() { public void run() {
            if (event == jimm.comm.Action.ON_CANCEL) { leave(); return; }
            if (found.isEmpty())
            {
                if (byUin) leave(); else activate();
                Alert alert = new Alert(ResourceBundle.getString("search_user"),
                        ResourceBundle.getString("no_results"), null, AlertType.INFO);
                alert.setTimeout(Alert.FOREVER);
                Jimm.display.setCurrent(alert, Jimm.display.getCurrent());
                return;
            }
            results = new TextList(ResourceBundle.getString("results"));
            JimmUI.setColorScheme(results, false, -1, true);
            results.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR);
            results.addCommandEx(JimmUI.cmdMenu, VirtualList.MENU_TYPE_RIGHT_BAR);
            results.addCommandEx(add, VirtualList.MENU_TYPE_RIGHT);
            results.addCommandEx(message, VirtualList.MENU_TYPE_RIGHT);
            results.addCommandEx(info, VirtualList.MENU_TYPE_RIGHT);
            results.setCommandListener(Search.this);
            for (int i = 0; i < found.size(); i++)
            {
                String[] row = (String[])found.elementAt(i);
                results.addBigText(row[1] + " (" + row[0] + ")", -1, Font.STYLE_PLAIN, i);
                results.doCRLF(i);
            }
            activate();
        } });
    }

    public void commandAction(Command command, Displayable display)
    {
        if (command == JimmUI.cmdBack || command == JimmUI.cmdCancel)
        {
            if (groups != null) { groups = null; activate(); }
            else if (results != null && !byUin) { results.clear(); results = null; activate(); }
            else leave();
            return;
        }
        if (display == query && command == search) { lookup(text.getString(), false); return; }
        if (results == null || found.isEmpty()) return;
        int index = results.getCurrTextIndex();
        if (index < 0 || index >= found.size()) return;
        String[] row = (String[])found.elementAt(index);
        if (command == add)
        {
            groups = JimmUI.showGroupSelector("whichgroup", this, JimmUI.SHS_TYPE_ALL, -1);
        }
        else if (command == JimmUI.cmdOk && groups != null)
        {
            int group = groups.getCurrTextIndex();
            if (group < 0) return;
            ContactItem item = new ContactItem(-1, group, row[0], row[1], false, false);
            item.setBooleanValue(ContactItem.CONTACTITEM_NO_AUTH, row[2].equals("1"));
            item.setBooleanValue(ContactItem.CONTACTITEM_IS_TEMP, true);
            item.setIntValue(ContactItem.CONTACTITEM_STATUS, ContactList.STATUS_OFFLINE);
            Icq.addToContactList(item);
        }
        else if (command == message)
        {
            ContactItem item = ContactList.createTempContact(row[0]);
            item.setStringValue(ContactItem.CONTACTITEM_NAME, row[1]);
            JimmUI.writeMessage(item, "");
        }
        else if (command == info) JimmUI.requiestUserInfo(row[0], row[1]
            //#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
            , null
            //#sijapp cond.end#
        );
    }

    private void leave() { JimmUI.removeScreen(this); MainThread.activateScreenMT(back); }

    public void activate()
    {
        if (groups != null) groups.activate(Jimm.display);
        else if (results != null) results.activate(Jimm.display);
        else if (query != null) Jimm.display.setCurrent(query);
        else { leave(); return; }
        JimmUI.setLastScreen(this, false);
    }

    public boolean isScreenActive()
    { return (query != null && query.isShown()) || (results != null && results.isActive()) || (groups != null && groups.isActive()); }
}
