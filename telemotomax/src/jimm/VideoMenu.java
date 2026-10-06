package jimm;

import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.List;
import jimm.util.ResourceBundle;

/** Choose the player or browser before requesting any video bytes. */
public final class VideoMenu implements CommandListener
{
	private final String uin;
	private final byte[] token;
	private final String url;
	private final JimmScreen back;
	private final List list;

	private VideoMenu(String uin, byte[] token, String url, JimmScreen back)
	{
		this.uin = uin;
		this.token = token;
		this.url = url;
		this.back = back;
		list = new List(ResourceBundle.getString("play_video"), List.IMPLICIT);
		if (token != null) list.append(ResourceBundle.getString("video_watch"), null);
		if (url != null) list.append(ResourceBundle.getString("video_browser"), null);
		list.addCommand(JimmUI.cmdBack);
		list.setCommandListener(this);
	}

	public static void show(String uin, byte[] token, String url, JimmScreen back)
	{
		if (token == null && url == null) return;
		VideoMenu menu = new VideoMenu(uin, token, url, back);
		Jimm.display.setCurrent(menu.list);
	}

	public void commandAction(Command command, Displayable displayable)
	{
		if (command == JimmUI.cmdBack) { back.activate(); return; }
		if (command != List.SELECT_COMMAND) return;
		int choice = list.getSelectedIndex();
		back.activate();
		if (token != null && choice == 0) MediaPlayer.show(uin, token, back);
		else if (url != null) VideoLink.open(url);
	}
}
