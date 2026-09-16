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

import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;

import DrawControls.TextList;
import DrawControls.VirtualList;
import jimm.comm.Icq;
import jimm.comm.RequestBartAction;
import jimm.comm.Util;
import jimm.util.ResourceBundle;

/**
 * Chat history fetched from the bridge, on its own screen. Unlike "!last",
 * which pours the messages into the chat where they stay in memory, this
 * screen is thrown away on "Back" together with all its text.
 */
public class HistoryViewer implements CommandListener, JimmScreen, RequestBartAction.Listener
{
	public static final int COUNT = 30;

	private static HistoryViewer current;

	private final JimmScreen back;
	private final String name;
	private TextList list;

	private HistoryViewer(JimmScreen back, String name)
	{
		this.back = back;
		this.name = name;
	}

	// Opens the screen and asks the bridge for the last COUNT messages.
	static public void show(String uin, String name, JimmScreen back)
	{
		HistoryViewer viewer = new HistoryViewer(back, name);
		current = viewer;
		viewer.build(ResourceBundle.getString("history_loading"));
		byte[] token = new byte[16];
		Util.putWord(token, 0, COUNT);
		try
		{
			Icq.requestAction(new RequestBartAction(uin, RequestBartAction.BART_HISTORY, token, viewer));
		}
		catch (JimmException e)
		{
			viewer.onBart(null);
		}
	}

	private void build(String text)
	{
		list = new TextList(null);
		list.setMode(VirtualList.CURSOR_MODE_DISABLED);
		JimmUI.setColorScheme(list, false, -1, true);
		list.setCaption(name);
		list.addBigText(text, -1, Font.STYLE_PLAIN, -1);
		list.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR);
		list.setCommandListener(this);
		list.activate(Jimm.display);
	}

	// Called from the comm thread with the history text (UTF-8) or null.
	public void onBart(byte[] data)
	{
		if (current != this) return;
		String text = (data == null) ? ResourceBundle.getString("history_failed")
				: Util.byteArrayToString(data, true);
		data = null;
		list.lock();
		list.clear();
		list.addBigText(text, -1, Font.STYLE_PLAIN, -1);
		list.unlock();
		list.setTopItem(list.getSize());
		list.repaint();
	}

	public void commandAction(Command c, Displayable d)
	{
		if (current == this) current = null;
		list = null;                       // the text goes with the screen
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
