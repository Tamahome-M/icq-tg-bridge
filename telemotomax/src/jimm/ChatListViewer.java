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
 * chat is in MAX, bit 2 — it is in the contact list, bit 3 — the chat is
 * in eXpress), how many days it has
 * been quiet (2 bytes, 0xFFFF — never), and the name in UTF-8. Choosing a
 * chat asks the bridge to bring it back: it unhides the chat and sends its
 * last message, so the conversation shows up in the client.
 */
public class ChatListViewer implements CommandListener, VirtualListCommands, JimmScreen,
		RequestBartAction.ErrorListener, RequestBartAction.RangeListener
{
	private static volatile ChatListViewer current;
	private static final int PAGE_SIZE = 20;
	private int pageOffset;
	private RequestBartAction request;
	private boolean loading, opening, hasMore;
	private final Command more = new Command(ResourceBundle.getString("more"), Command.SCREEN, 2);

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
		viewer.request();
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

	private void request()
	{
		if (loading || current != this) return;
		byte[] token = new byte[16];
		token[0] = 'P'; token[1] = '1';
		Util.putWord(token, 2, pageOffset); token[4] = PAGE_SIZE;
		Util.putDWord(token, 12, Util.getCounter());
		loading = true;
		try { request = new RequestBartAction(own(), RequestBartAction.BART_CHATS, token, this); Icq.requestAction(request); }
		catch (JimmException error) { onBartError(error.getMessage()); }
	}

	public void onBart(byte[] data) { onBart(data, 0, data == null ? 0 : data.length); }
	public void onBart(byte[] data, int offset, int length) { receive(data, offset, length, null); }
	public void onBartError(String reason) { receive(null, 0, 0, reason); }

	private void receive(byte[] data, int offset, int length, String reason)
	{
		if (current != this || list == null) return;
		try { MainThread.runSerially(new Page(data, offset, length, reason)); }
		catch (OutOfMemoryError error) { loading = false; System.gc(); }
	}

	private final class Page implements Runnable
	{
		private byte[] data;
		private int marker, end, skip, added;
		private final String reason;
		private final TextList target = list;
		private boolean started;
		Page(byte[] data, int offset, int length, String reason)
		{
			this.data = data; marker = offset; end = offset + length; this.reason = reason;
			if (data != null && length >= 4 && data[offset] == 'C' && data[offset + 1] == 'P' && data[offset + 2] == '1')
			{
				hasMore = data[offset + 3] != 0;
				marker += 4;
			}
			else { skip = pageOffset; hasMore = false; }
		}
		public void run()
		{
			if (current != ChatListViewer.this || list != target) { data = null; return; }
			target.lock();
			try
			{
				if (!started) { target.clear(); uins.removeAllElements(); started = true; }
				if (data == null) addLine(reason == null ? ResourceBundle.getString("chats_failed") : reason, null);
				else
				{
					int batch = 0;
					while (marker + 9 <= end)
					{
						long uin = Util.getDWord(data, marker); marker += 4;
						int flags = Util.getByte(data, marker++);
						int days = Util.getWord(data, marker); marker += 2;
						int len = Util.getWord(data, marker); marker += 2;
						if (marker + len > end) throw new IllegalArgumentException();
						if (skip > 0) { skip--; marker += len; continue; }
						if (added == PAGE_SIZE) { hasMore = true; marker = end; break; }
						String name = Util.byteArrayToString(data, marker, len, true); marker += len;
						addLine(line(flags, days, name), String.valueOf(uin)); added++;
						if (++batch == 4 && marker + 9 <= end) { MainThread.runSerially(this); return; }
					}
					if (added == 0) addLine(ResourceBundle.getString("chats_empty"), null);
				}
				loading = false; data = null;
				target.setCaption(ResourceBundle.getString("all_chats")); target.setTopItem(0);
				if (hasMore) target.addCommandEx(more, VirtualList.MENU_TYPE_RIGHT);
				else target.removeCommandEx(more);
			}
			catch (Throwable failure)
			{
				data = null; loading = false;
				target.setCaption(ResourceBundle.getString("chats_failed"));
			}
			finally { target.unlock(); }
			target.repaint();
		}
	}

	// «[M] Таня, 12 дн.» — сеть ([T]elegram, [M]AX, [E]xpress), название и
	// сколько там тихо.
	private String line(int flags, int days, String name)
	{
		String text = ((flags & 4) != 0 ? "[E] " : (flags & 1) != 0 ? "[M] " : "[T] ") + name;
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
		if (uin == null || loading || opening) return;
		opening = true;
		byte[] token = new byte[16];
		try { Util.putDWord(token, 0, Long.parseLong(uin)); }
		catch (Exception e) { return; }
		list.setCaption(ResourceBundle.getString("chats_opening"));
		RequestBartAction.ErrorListener done = new RequestBartAction.ErrorListener() {
			public void onBart(byte[] answer)
			{
				boolean ok = answer != null && answer.length > 0 && answer[0] == 0;
				if (current != ChatListViewer.this) return;
				opening = false;
				if (ok) close();
				else onBartError(null);
			}
			public void onBartError(final String reason)
			{
				opening = false;
				MainThread.runSerially(new Runnable() { public void run() {
					if (current == ChatListViewer.this && list != null)
					{
						list.setCaption(reason == null ? ResourceBundle.getString("chats_failed") : reason);
						list.repaint();
					}
				} });
			}
		};
		try
		{
			request = new RequestBartAction(own(), RequestBartAction.BART_OPEN, token, done); Icq.requestAction(request);
		}
		catch (JimmException e)
		{
			done.onBartError(e.getMessage());
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
		if (c == more && hasMore && !loading && !opening) { pageOffset += PAGE_SIZE; request(); }
		else if (c != more) close();
	}

	private void close()
	{
		MainThread.runSerially(new Runnable() { public void run() { closeNow(); } });
	}

	private void closeNow()
	{
		if (current != this) return;
		Icq.cancelAction(request);
		if (current == this) current = null;
		list = null;
		uins.removeAllElements();
		MainThread.activateScreenMT(back);
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
