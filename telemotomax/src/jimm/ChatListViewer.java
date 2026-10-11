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
	private int pageOffset, requestOffset;
	private RequestBartAction request;
	private boolean loading, opening, hasMore = true, havePage;
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
		list = createList();
		list.activate(Jimm.display);
	}

	private TextList createList()
	{
		TextList result = new TextList(null);
		JimmUI.setColorScheme(result, false, -1, true);
		result.setCaption(ResourceBundle.getString("all_chats"));
		result.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR);
		result.addCommandEx(JimmUI.cmdMenu, VirtualList.MENU_TYPE_RIGHT_BAR);
		result.setCommandListener(this);
		result.setVLCommands(this);
		return result;
	}

	private void addLine(String text, String uin) { addLine(list, uins, text, uin); }

	private void addLine(TextList target, Vector rows, String text, String uin)
	{
		int index = rows.size();
		rows.addElement(uin);
		target.addBigText(text, -1, Font.STYLE_PLAIN, index);
		target.doCRLF(index);
	}

	private void request()
	{
		if (loading || current != this) return;
		try
		{
			byte[] token = new byte[16];
			token[0] = 'P'; token[1] = '1';
			Util.putWord(token, 2, requestOffset); token[4] = PAGE_SIZE;
			Util.putDWord(token, 12, Util.getCounter());
			loading = true;
			request = new RequestBartAction(own(), RequestBartAction.BART_CHATS, token, this);
			Icq.requestAction(request);
		}
		catch (JimmException error) { onBartError(error.getMessage()); }
		catch (Throwable failure) { loading = false; try { failedPage(null); } catch (Throwable ignore) {} }

	}

	public void onBart(byte[] data) { onBart(data, 0, data == null ? 0 : data.length); }
	public void onBart(byte[] data, int offset, int length) { receive(data, offset, length, null); }
	public void onBartError(String reason) { receive(null, 0, 0, reason); }

	private void receive(byte[] data, int offset, int length, String reason)
	{
		if (current != this || list == null) return;
		try { MainThread.runSerially(new Page(data, offset, length, reason)); }
		catch (Throwable error) { loading = false; try { failedPage(reason); } catch (Throwable ignore) {} }
	}

	private final class Page implements Runnable
	{
		private byte[] data;
		private int marker, end, skip, added;
		private final String reason;
		private final TextList previous = list;
		private final int offset = requestOffset;
		private TextList target;
		private Vector rows;
		private boolean nextMore;
		Page(byte[] data, int offset, int length, String reason)
		{
			this.data = data; marker = offset; end = offset + length; this.reason = reason;
			if (data != null && (offset < 0 || length < 0 || offset > data.length - length))
				throw new IllegalArgumentException();
			if (data != null && length >= 4 && data[offset] == 'C' && data[offset + 1] == 'P' && data[offset + 2] == '1')
			{ nextMore = data[offset + 3] != 0; marker += 4; }
			else skip = this.offset;
		}
		public void run()
		{
			if (current != ChatListViewer.this || list != previous) { data = null; return; }
			try
			{
				if (data == null) { failedPage(reason); return; }
				if (target == null) { target = createList(); rows = new Vector(PAGE_SIZE); }
				int batch = 0;
				while (marker + 9 <= end)
				{
					long uin = Util.getDWord(data, marker); marker += 4;
					int flags = Util.getByte(data, marker++);
					int days = Util.getWord(data, marker); marker += 2;
					int len = Util.getWord(data, marker); marker += 2;
					if (len > end - marker) throw new IllegalArgumentException();
					if (skip > 0) { skip--; marker += len; continue; }
					if (added == PAGE_SIZE) { nextMore = true; marker = end; break; }
					String name = Util.byteArrayToString(data, marker, len, true); marker += len;
					addLine(target, rows, line(flags, days, name), String.valueOf(uin)); added++;
					if (++batch == 4 && marker + 9 <= end) { MainThread.runSerially(this); return; }
				}
				if (marker != end) throw new IllegalArgumentException();
				if (added == 0) addLine(target, rows, ResourceBundle.getString("chats_empty"), null);
				data = null;
				if (current != ChatListViewer.this || list != previous) return;
				if (nextMore) target.addCommandEx(more, VirtualList.MENU_TYPE_RIGHT);
				boolean active = previous.isActive();
				list = target; uins = rows; pageOffset = offset;
				hasMore = nextMore; havePage = true; loading = false;
				previous.clear();
				if (active) target.activate(Jimm.display);
			}
			catch (Throwable failure) { data = null; target = null; rows = null; failedPage(null); }
		}
	}

	private void failedPage(String reason)
	{
		loading = false;
		if (current != this || list == null) return;
		list.setCaption(reason == null ? ResourceBundle.getString("chats_failed") : reason);
		// Keep both the previous page and the offset of the failed request.
		list.addCommandEx(more, VirtualList.MENU_TYPE_RIGHT);
		list.repaint();
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
		catch (Exception e) { opening = false; return; }
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
		if (c == more && hasMore && !loading && !opening) { if (havePage && requestOffset == pageOffset) requestOffset += PAGE_SIZE; request(); }
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
