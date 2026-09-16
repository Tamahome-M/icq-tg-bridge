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
 * Chat history fetched from the bridge, on its own screen. Unlike "!last",
 * which pours the messages into the chat where they stay in memory, this
 * screen is thrown away on "Back" together with all its text.
 *
 * The bridge sends one record per message: text length (2 bytes), UTF-8
 * text, a flag byte and, if the flag is set, a 16-byte photo token — so a
 * message with a picture can be opened with "Show photo" right here.
 */
public class HistoryViewer implements CommandListener, VirtualListCommands, JimmScreen,
		RequestBartAction.Listener
{
	private static HistoryViewer current;

	private final JimmScreen back;
	private final String uin;
	private final String name;
	private TextList list;
	private Vector tokens = new Vector();    // per message: byte[16] or null

	private HistoryViewer(JimmScreen back, String uin, String name)
	{
		this.back = back;
		this.uin = uin;
		this.name = name;
	}

	// Opens the screen and asks the bridge for the last N messages (Options).
	static public void show(String uin, String name, JimmScreen back)
	{
		HistoryViewer viewer = new HistoryViewer(back, uin, name);
		current = viewer;
		viewer.build();
		viewer.addLine(ResourceBundle.getString("history_loading"), null);
		byte[] token = new byte[16];
		int count = Options.getInt(Options.OPTION_HISTORY_COUNT);
		if (count < 1) count = 10;
		Util.putWord(token, 0, count);
		try
		{
			Icq.requestAction(new RequestBartAction(uin, RequestBartAction.BART_HISTORY, token, viewer));
		}
		catch (JimmException e)
		{
			viewer.onBart(null);
		}
	}

	// Last message of a chat that has none yet: asked from the bridge and
	// put into the chat itself, token and all.
	static public void preloadLast(final String uin, final ChatTextList chat)
	{
		byte[] token = new byte[16];
		Util.putWord(token, 0, 1);
		RequestBartAction.Listener into = new RequestBartAction.Listener() {
			public void onBart(byte[] data)
			{
				if (data == null || data.length < 3) return;
				int len = Util.getWord(data, 0);
				if (2 + len + 1 > data.length) return;
				String text = Util.byteArrayToString(data, 2, len, true);
				int flag = Util.getByte(data, 2 + len);
				byte[] photo = null;
				if ((flag & 1) != 0 && 2 + len + 1 + 16 <= data.length)
				{
					photo = new byte[16];
					System.arraycopy(data, 2 + len + 1, photo, 0, 16);
				}
				ChatHistory.addHistoryLine(uin, text, photo);
			}
		};
		try
		{
			Icq.requestAction(new RequestBartAction(uin, RequestBartAction.BART_HISTORY, token, into));
		}
		catch (JimmException ignore) {}
	}

	private void build()
	{
		list = new TextList(null);
		JimmUI.setColorScheme(list, false, -1, true);
		list.setCaption(name);
		list.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR);
		list.setCommandListener(this);
		list.setVLCommands(this);
		list.activate(Jimm.display);
	}

	private void addLine(String text, byte[] token)
	{
		int index = tokens.size();
		tokens.addElement(token);
		list.addBigText(text, -1, Font.STYLE_PLAIN, index);
		list.doCRLF(index);
	}

	// Called from the comm thread with the history records or null.
	public void onBart(byte[] data)
	{
		if (current != this) return;
		list.lock();
		list.clear();
		tokens.removeAllElements();
		if (data == null)
		{
			addLine(ResourceBundle.getString("history_failed"), null);
		}
		else
		{
			int marker = 0;
			while (marker + 3 <= data.length)
			{
				int len = Util.getWord(data, marker);
				marker += 2;
				if (marker + len + 1 > data.length) break;
				String text = Util.byteArrayToString(data, marker, len, true);
				marker += len;
				int flag = Util.getByte(data, marker);
				marker += 1;
				byte[] token = null;
				if ((flag & 1) != 0 && marker + 16 <= data.length)
				{
					token = new byte[16];
					System.arraycopy(data, marker, token, 0, 16);
					marker += 16;
				}
				addLine(text, token);
			}
			if (tokens.size() == 0) addLine(ResourceBundle.getString("history_empty"), null);
		}
		data = null;
		list.unlock();
		list.setTopItem(list.getSize());
		checkPhoto();
		list.repaint();
	}

	private byte[] currentToken()
	{
		int index = list.getCurrTextIndex();
		if (index < 0 || index >= tokens.size()) return null;
		return (byte[]) tokens.elementAt(index);
	}

	private void checkPhoto()
	{
		list.removeCommandEx(ChatTextList.cmdShowPhoto);
		if (currentToken() != null)
			list.addCommandEx(ChatTextList.cmdShowPhoto, VirtualList.MENU_TYPE_RIGHT);
	}

	public void vlCursorMoved(VirtualList sender)
	{
		checkPhoto();
	}

	public void vlItemClicked(VirtualList sender)
	{
		byte[] token = currentToken();
		if (token != null) PhotoViewer.show(uin, token, this);
	}

	public void vlKeyPress(VirtualList sender, int keyCode, int type) {}

	public void commandAction(Command c, Displayable d)
	{
		if (c == ChatTextList.cmdShowPhoto)
		{
			byte[] token = currentToken();
			if (token != null) PhotoViewer.show(uin, token, this);
			return;
		}
		if (current == this) current = null;
		list = null;                       // the text goes with the screen
		tokens = null;
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
