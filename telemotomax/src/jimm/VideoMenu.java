package jimm;

import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;
import DrawControls.TextList;
import DrawControls.VirtualList;
import DrawControls.VirtualListCommands;
import jimm.util.ResourceBundle;

/** Choose the player or browser before requesting any video bytes. */
public final class VideoMenu implements CommandListener, VirtualListCommands
{
	private final String uin;
	private final byte[] token;
	private final String url;
	private final JimmScreen back;
	private final TextList list;
	private boolean closed;

	private VideoMenu(String uin, byte[] token, String url, JimmScreen back)
	{
		this.uin = uin;
		this.token = token;
		this.url = url;
		this.back = back;
		list = new TextList(ResourceBundle.getString("play_video"));
		JimmUI.setColorScheme(list, false, -1, true);
		list.setMode(VirtualList.CURSOR_MODE_ENABLED);
		if (token != null) addChoice("video_watch", 0);
		if (url != null) addChoice("video_browser", token == null ? 0 : 1);
		list.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR);
		list.addCommandEx(JimmUI.cmdSelect, VirtualList.MENU_TYPE_RIGHT_BAR);
		list.setCommandListener(this);
		list.setVLCommands(this);
	}

	private void addChoice(String label, int index)
	{
		list.addBigText(ResourceBundle.getString(label), list.getTextColor(),
			Font.STYLE_PLAIN, index).doCRLF(index);
	}

	public static void show(String uin, byte[] token, String url, JimmScreen back)
	{
		if (token == null && url == null) return;
		VideoMenu menu = new VideoMenu(uin, token, url, back);
		menu.list.activate(Jimm.display);
	}

	public void commandAction(Command command, Displayable displayable)
	{
		if (closed) return;
		if (command == JimmUI.cmdBack)
		{
			closed = true;
			back.activate();
		}
		else if (command == JimmUI.cmdSelect) select();
	}

	private void select()
	{
		if (closed || !list.isActive()) return;
		int choice = list.getCurrTextIndex();
		closed = true;
		back.activate();
		if (token != null && choice == 0) MediaPlayer.show(uin, token, back);
		else if (url != null) VideoLink.open(url);
	}

	public void vlItemClicked(VirtualList sender) { if (sender == list) select(); }
	public void vlCursorMoved(VirtualList sender) {}
	public void vlKeyPress(VirtualList sender, int keyCode, int type) {}
}
