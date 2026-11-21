package jimm;

import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;
import DrawControls.TextList;
import DrawControls.VirtualList;
import DrawControls.VirtualListCommands;
import jimm.util.ResourceBundle;

/** Keep only the tokens while choosing or viewing a single album photo. */
final class PhotoAlbum implements JimmScreen, CommandListener, VirtualListCommands
{
	private final String uin;
	private final byte[] tokens;
	private final JimmScreen back;
	private final TextList list;

	PhotoAlbum(String uin, byte[] tokens, JimmScreen back)
	{
		this.uin = uin;
		this.tokens = tokens;
		this.back = back;
		list = new TextList(ResourceBundle.getString("show_photo"));
		JimmUI.setColorScheme(list, false, -1, true);
		list.setMode(VirtualList.CURSOR_MODE_ENABLED);
		int count = tokens.length / 16;
		String label = ResourceBundle.getString("cam_photo");
		for (int i = 0; i < count; i++)
			list.addBigText(label + " " + (i + 1) + "/" + count, list.getTextColor(),
				Font.STYLE_PLAIN, i).doCRLF(i);
		list.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR);
		list.addCommandEx(JimmUI.cmdSelect, VirtualList.MENU_TYPE_RIGHT_BAR);
		list.setCommandListener(this);
		list.setVLCommands(this);
	}

	public void activate() { list.activate(Jimm.display); }
	public boolean isScreenActive() { return list.isActive(); }

	private void select()
	{
		int i = list.getCurrTextIndex();
		if (!list.isActive() || i < 0 || i >= tokens.length / 16) return;
		byte[] token = new byte[16];
		System.arraycopy(tokens, i * 16, token, 0, 16);
		PhotoViewer.show(uin, token, this);
	}

	public void commandAction(Command c, Displayable d)
	{
		if (c == JimmUI.cmdBack) back.activate();
		else if (c == JimmUI.cmdSelect) select();
	}
	public void vlItemClicked(VirtualList sender) { select(); }
	public void vlCursorMoved(VirtualList sender) {}
	public void vlKeyPress(VirtualList sender, int key, int type) {}
}
