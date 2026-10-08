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
public class PhotoViewer extends Canvas implements CommandListener, JimmScreen, RequestBartAction.ErrorListener
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
			viewer.onBartError(e.getMessage());
		}
	}

	// Called from the comm thread when the picture (or a failure) arrives.
	public void onBart(byte[] data)
	{
		if (current != this) return;     // screen already left — drop it
		if (data == null)
		{
			onBartError(null);
			return;
		}
		// Decoding a big picture takes a while; onBart runs on the comm thread,
		// so decode on a thread of its own or the connection would stall.
		final byte[] raw = data;
		new Thread() {
			public void run()
			{
				if (current != PhotoViewer.this) return;
				// Release temporary handshake/packet buffers before the native
				// JPEG decoder allocates its bitmap in the small phone heap.
				System.gc();
				ConnLog.note("фото: получено " + raw.length + " байт; свободно "
						+ (Runtime.getRuntime().freeMemory() / 1024) + " КБ");
				Image img = null;
				String failure = null;
				try { img = Image.createImage(raw, 0, raw.length); }
				catch (OutOfMemoryError e)
				{
					System.gc();
					failure = ResourceBundle.getString("photo_memory");
					ConnLog.note("фото: не хватило памяти для JPEG");
				}
				catch (Throwable e)
				{
					failure = ResourceBundle.getString("photo_format");
					ConnLog.note("фото: JPEG не открыт — " + e.getClass().getName());
				}
				if (img == null && failure == null) failure = ResourceBundle.getString("photo_format");
				if (current != PhotoViewer.this) return;
				image = img;
				status = failure;
				if (img != null) ConnLog.note("фото: JPEG открыт");
				repaint();
			}
		}.start();
	}

	public void onBartError(String reason)
	{
		if (current != this) return;
		image = null;
		status = ResourceBundle.getString("photo_download_failed");
		if (reason != null && reason.length() > 0) status += ": " + reason;
		ConnLog.note("фото: " + status);
		repaint();
	}

	protected void paint(Graphics g)
	{
		g.setColor(0x000000);
		g.fillRect(0, 0, getWidth(), getHeight());
		Image picture = image;
		if (picture != null)
		{
			g.drawImage(picture, getWidth() / 2, getHeight() / 2, Graphics.HCENTER | Graphics.VCENTER);
		}
		String text = status;
		if (text != null)
		{
			g.setColor(0xFFFFFF);
			Font font = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
			g.setFont(font);
			int width = Math.max(1, getWidth() - 12), lines = 0;
			for (int at = 0; at < text.length();)
			{
				at = nextLine(text, lineEnd(text, font, at, width));
				lines++;
			}
			int y = Math.max(4, (getHeight() - lines * font.getHeight()) / 2);
			for (int at = 0; at < text.length() && y + font.getHeight() <= getHeight();)
			{
				int end = lineEnd(text, font, at, width);
				g.drawString(text.substring(at, end), getWidth() / 2, y, Graphics.HCENTER | Graphics.TOP);
				at = nextLine(text, end);
				y += font.getHeight();
			}
		}
	}

	private static int lineEnd(String text, Font font, int start, int width)
	{
		int end = start, space = -1;
		while (end < text.length() && text.charAt(end) != '\n')
		{
			if (font.stringWidth(text.substring(start, end + 1)) > width) break;
			if (text.charAt(end) == ' ') space = end;
			end++;
		}
		if (end == start) return start + 1;
		return end < text.length() && text.charAt(end) != '\n' && space > start ? space : end;
	}

	private static int nextLine(String text, int end)
	{
		while (end < text.length() && text.charAt(end) <= ' ') end++;
		return end;
	}

	// Закрывают только «выбор» (или «5»), «0» и «Назад». Любая другая
	// клавиша просто будит подсветку: на V3 она гаснет быстро, и нажатие
	// «чтобы увидеть», роняющее фото, раздражало.
	protected void keyPressed(int keyCode)
	{
		DrawControls.VirtualList.touch();
		int action = 0;
		try { action = getGameAction(keyCode); } catch (Exception ignore) {}
		if (action == FIRE || keyCode == KEY_NUM5 || keyCode == KEY_NUM0) close();
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
