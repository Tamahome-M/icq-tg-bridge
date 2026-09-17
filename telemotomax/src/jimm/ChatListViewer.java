/*******************************************************************************
 TeleMotoMax - Jimm fork for icq-tg-bridge

 This program is free software; you can redistribute it and/or
 modify it under the terms of the GNU General Public License
 as published by the Free Software Foundation; either version 2
 of the License, or (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.
 *******************************************************************************/

package jimm;

import java.util.Vector;

import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;

import DrawControls.TextList;
import DrawControls.VirtualList;
import DrawControls.VirtualListCommands;
import jimm.comm.Icq;
import jimm.comm.RequestBartAction;
import jimm.comm.Util;
import jimm.util.ResourceBundle;

/**
 * Every chat the bridge knows about, on its own screen — not just the ones
 * that fit into the contact list. The contact list is cut to a limit, so a
 * chat nobody has written to for a while drops out of it and there is no way
 * back to it from the phone; this screen is that way back.
 *
 * The bridge sends one record per chat: UIN (4 bytes), flags (bit 1 — the
 * chat is in MAX, bit 2 — it is in the contact list), how many days it has
 * been quiet (2 bytes, 0xFFFF — never), and the name in UTF-8. Choosing a
 * chat asks the bridge to bring it back: it unhides the chat and sends its
 * last message, so the conversation shows up in the client.
 */
public class ChatListViewer implements CommandListener, VirtualListCommands, JimmScreen,
		RequestBartAction.Listener
{
	private static ChatListViewer current;

	private final JimmScreen back;
	private TextList list;
	private Vector uins = new Vector();      // per line: String uin, or null

	private ChatListViewer(JimmScreen back)
	{
		this.back = back;
	}

	static public void show(JimmScreen back)
	{
		ChatListViewer viewer = new ChatListViewer(back);
		current = viewer;
		viewer.build();
		viewer.addLine(ResourceBundle.getString("chats_loading"), null);
		try
		{
			Icq.requestAction(new RequestBartAction(own(), RequestBartAction.BART_CHATS,
					new byte[16], viewer));
		}
		catch (JimmException e)
		{
			viewer.onBart(null);
		}
	}

	// The list is not about one contact, so the request goes out under our
	// own number — the bridge only needs somebody to answer to.
	private static String own()
	{
		String uin = Options.getString(Options.OPTION_UIN);
		return (uin == null || uin.length() == 0) ? "1" : uin;
	}

	private void build()
	{
		list = new TextList(null);
		JimmUI.setColorScheme(list, false, -1, true);
		list.setCaption(ResourceBundle.getString("all_chats"));
		list.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR);
		// Правая софт-клавиша с меню: в него попадают «Ещё», «Показать фото»
		// и «Прослушать» — без неё они некуда было бы нажать.
		list.addCommandEx(JimmUI.cmdMenu, VirtualList.MENU_TYPE_RIGHT_BAR);
		list.setCommandListener(this);
		list.setVLCommands(this);
		list.activate(Jimm.display);
	}

	private void addLine(String text, String uin)
	{
		int index = uins.size();
		uins.addElement(uin);
		list.addBigText(text, -1, Font.STYLE_PLAIN, index);
		list.doCRLF(index);
	}

	// Called from the comm thread; laying out a few hundred lines takes long
	// enough to hold up messages, so it happens on a thread of its own.
	public void onBart(final byte[] data)
	{
		if (current != this) return;
		new Thread() {
			public void run() { render(data); }
		}.start();
	}

	private void render(byte[] data)
	{
		if (current != this) return;
		list.lock();
		list.clear();
		uins.removeAllElements();
		if (data == null)
		{
			addLine(ResourceBundle.getString("chats_failed"), null);
		}
		else
		{
			int marker = 0;
			while (marker + 9 <= data.length)
			{
				long uin = Util.getDWord(data, marker); marker += 4;
				int flags = Util.getByte(data, marker); marker += 1;
				int days = Util.getWord(data, marker); marker += 2;
				int len = Util.getWord(data, marker); marker += 2;
				if (marker + len > data.length) break;
				String name = Util.byteArrayToString(data, marker, len, true);
				marker += len;
				addLine(line(flags, days, name), String.valueOf(uin));
			}
			if (uins.size() == 0) addLine(ResourceBundle.getString("chats_empty"), null);
		}
		data = null;
		list.unlock();
		list.setTopItem(0);
		list.repaint();
	}

	// «[M] Таня, 12 дн.» — сеть, название и сколько там тихо.
	private String line(int flags, int days, String name)
	{
		String text = ((flags & 1) != 0 ? "[M] " : "[T] ") + name;
		if (days == 0xFFFF) return text;
		if (days == 0) return text + ", " + ResourceBundle.getString("chats_today");
		return text + ", " + days + " " + ResourceBundle.getString("chats_days");
	}

	private String currentUin()
	{
		int index = list.getCurrTextIndex();
		if (index < 0 || index >= uins.size()) return null;
		return (String) uins.elementAt(index);
	}

	// Asks the bridge to bring the chat back to the phone; the answer is a
	// single byte — done or not — and the chat's last message follows it as
	// an ordinary incoming message.
	private void open()
	{
		final String uin = currentUin();
		if (uin == null) return;
		byte[] token = new byte[16];
		try { Util.putDWord(token, 0, Long.parseLong(uin)); }
		catch (Exception e) { return; }
		list.setCaption(ResourceBundle.getString("chats_opening"));
		RequestBartAction.Listener done = new RequestBartAction.Listener() {
			public void onBart(byte[] answer)
			{
				boolean ok = answer != null && answer.length > 0 && answer[0] == 0;
				if (current != ChatListViewer.this) return;
				if (ok) close();
				else
				{
					list.setCaption(ResourceBundle.getString("chats_failed"));
					list.repaint();
				}
			}
		};
		try
		{
			Icq.requestAction(new RequestBartAction(own(), RequestBartAction.BART_OPEN, token, done));
		}
		catch (JimmException e)
		{
			list.setCaption(ResourceBundle.getString("chats_failed"));
			list.repaint();
		}
	}

	public void vlItemClicked(VirtualList sender)
	{
		open();
	}

	public void vlCursorMoved(VirtualList sender) {}

	public void vlKeyPress(VirtualList sender, int keyCode, int type) {}

	public void commandAction(Command c, Displayable d)
	{
		close();
	}

	private void close()
	{
		if (current == this) current = null;
		list = null;
		uins.removeAllElements();
		if (back != null) back.activate();
		else JimmUI.backToLastScreen();
	}

	public void activate()
	{
		if (list != null) list.activate(Jimm.display);
	}

	public boolean isScreenActive()
	{
		return list != null && list.isActive();
	}
}
