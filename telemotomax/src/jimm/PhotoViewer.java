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

import javax.microedition.lcdui.Canvas;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;
import javax.microedition.lcdui.Graphics;
import javax.microedition.lcdui.Image;

import jimm.comm.Icq;
import jimm.comm.RequestBartAction;
import jimm.util.ResourceBundle;

/**
 * Full-screen view of a picture attached to a message. The picture lives
 * only while this screen is open: "Back" drops it and the memory with it —
 * a decoded 176x176 image is ~120 KB of the phone's heap, so one at a time.
 */
public class PhotoViewer extends Canvas implements CommandListener, JimmScreen, RequestBartAction.Listener
{
	private static PhotoViewer current;

	private final JimmScreen back;
	private Image image;
	private String status;

	private PhotoViewer(JimmScreen back)
	{
		this.back = back;
		setFullScreenMode(true);
		addCommand(JimmUI.cmdBack);
		setCommandListener(this);
	}

	// Opens the viewer and asks the bridge for the picture.
	static public void show(String uin, byte[] token, JimmScreen back)
	{
		PhotoViewer viewer = new PhotoViewer(back);
		viewer.status = ResourceBundle.getString("photo_loading");
		current = viewer;
		Jimm.display.setCurrent(viewer);
		try
		{
			Icq.requestAction(new RequestBartAction(uin, RequestBartAction.BART_PHOTO, token, viewer));
		}
		catch (JimmException e)
		{
			viewer.onBart(null);
		}
	}

	// Called from the comm thread when the picture (or a failure) arrives.
	public void onBart(byte[] data)
	{
		if (current != this) return;     // screen already left — drop it
		if (data == null)
		{
			image = null;
			status = ResourceBundle.getString("photo_failed");
			repaint();
			return;
		}
		// Decoding a big picture takes a while; onBart runs on the comm thread,
		// so decode on a thread of its own or the connection would stall.
		final byte[] raw = data;
		new Thread() {
			public void run()
			{
				Image img = null;
				try { img = Image.createImage(raw, 0, raw.length); }
				catch (Exception ignore) {}
				if (current != PhotoViewer.this) return;
				image = img;
				status = (img == null) ? ResourceBundle.getString("photo_failed") : null;
				repaint();
			}
		}.start();
	}

	protected void paint(Graphics g)
	{
		g.setColor(0x000000);
		g.fillRect(0, 0, getWidth(), getHeight());
		if (image != null)
		{
			g.drawImage(image, getWidth() / 2, getHeight() / 2, Graphics.HCENTER | Graphics.VCENTER);
		}
		if (status != null)
		{
			g.setColor(0xFFFFFF);
			g.setFont(Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL));
			g.drawString(status, getWidth() / 2, getHeight() / 2, Graphics.HCENTER | Graphics.BASELINE);
		}
	}

	protected void keyPressed(int keyCode)
	{
		DrawControls.VirtualList.touch();
		close();
	}

	protected void pointerPressed(int x, int y)
	{
		close();
	}

	public void commandAction(Command c, Displayable d)
	{
		close();
	}

	private void close()
	{
		if (current == this) current = null;
		image = null;                     // free the picture first
		if (back != null) back.activate();
		else JimmUI.backToLastScreen();
	}

	public void activate()
	{
		Jimm.display.setCurrent(this);
	}

	public boolean isScreenActive()
	{
		return isShown();
	}
}
