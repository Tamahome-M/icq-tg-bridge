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

import java.io.ByteArrayInputStream;
import java.io.OutputStream;
import java.util.Enumeration;

import javax.microedition.io.Connector;
import javax.microedition.io.file.FileConnection;
import javax.microedition.io.file.FileSystemRegistry;
import javax.microedition.lcdui.Canvas;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;
import javax.microedition.lcdui.Graphics;
import javax.microedition.media.Manager;
import javax.microedition.media.Player;
import javax.microedition.media.control.VideoControl;

import jimm.comm.Icq;
import jimm.comm.RequestBartAction;
import jimm.util.ResourceBundle;

/**
 * Plays the first seconds of a video attached to a message. The clip comes
 * from the bridge over the BART service (type 0x0082), already transcoded to
 * what the phone's player takes (3GP, H.263 or MPEG-4 SP, AMR).
 *
 * The Motorola V3 player does not accept video from an in-memory stream, so
 * the clip is written to a temporary file (JSR-75) and played from there;
 * both the file and the player are dropped when the screen is closed.
 */
public class VideoPlayer extends Canvas implements CommandListener, JimmScreen,
		RequestBartAction.ProgressListener
{
	private static VideoPlayer current;

	private final JimmScreen back;
	private String status;
	private String[] details;          // why it did not play, shown under the status
	private Player player;
	private String filePath;           // temp file URL, or null if played from memory
	private int clipSize;

	private VideoPlayer(JimmScreen back)
	{
		this.back = back;
		setFullScreenMode(true);
		addCommand(JimmUI.cmdBack);
		setCommandListener(this);
	}

	static public void show(String uin, byte[] token, JimmScreen back)
	{
		VideoPlayer viewer = new VideoPlayer(back);
		viewer.status = ResourceBundle.getString("video_loading");
		current = viewer;
		Jimm.display.setCurrent(viewer);
		try
		{
			Icq.requestAction(new RequestBartAction(uin, RequestBartAction.BART_VIDEO, token, viewer));
		}
		catch (JimmException e)
		{
			viewer.onBart(null);
		}
	}

	public void onBartProgress(int part, int total)
	{
		if (current != this) return;
		status = ResourceBundle.getString("video_loading") + " " + part + "/" + total;
		repaint();
	}

	// Called from the comm thread with the whole clip (or null).
	public void onBart(byte[] data)
	{
		if (current != this) return;
		if (data == null)
		{
			status = ResourceBundle.getString("video_failed");
			repaint();
			return;
		}
		status = null;
		repaint();
		// Setting up the player (writing the temp file, createPlayer, start)
		// blocks; it must not run on the comm thread that called us, or the
		// whole connection freezes. Do it on a thread of its own.
		final byte[] clip = data;
		new Thread() {
			public void run()
			{
				if (current != VideoPlayer.this) return;
				clipSize = clip.length;
				Exception fileErr = playFromFile(clip);
				if (fileErr == null) return;
				Exception streamErr = playFromStream(clip);
				if (streamErr == null) return;
				fail(fileErr, streamErr);
			}
		}.start();
	}

	private Exception playFromFile(byte[] data)
	{
		String url = tempFileUrl();
		if (url == null) return new Exception("no writable root");
		FileConnection fc = null;
		OutputStream os = null;
		try
		{
			fc = (FileConnection) Connector.open(url, Connector.READ_WRITE);
			if (fc.exists()) fc.delete();
			fc.create();
			os = fc.openOutputStream();
			os.write(data);
			os.flush();
			os.close(); os = null;
			fc.close(); fc = null;
			filePath = url;
			start(Manager.createPlayer(url));
			return null;
		}
		catch (Exception e)
		{
			try { if (os != null) os.close(); } catch (Exception ignore) {}
			try { if (fc != null) fc.close(); } catch (Exception ignore) {}
			deleteTemp();
			return e;
		}
	}

	private Exception playFromStream(byte[] data)
	{
		try
		{
			start(Manager.createPlayer(new ByteArrayInputStream(data), "video/3gpp"));
			return null;
		}
		catch (Exception e)
		{
			return e;
		}
	}

	private void start(Player p) throws Exception
	{
		player = p;
		player.realize();
		VideoControl vc = (VideoControl) player.getControl("VideoControl");
		if (vc != null)
		{
			vc.initDisplayMode(VideoControl.USE_DIRECT_VIDEO, this);
			int w = vc.getSourceWidth(), h = vc.getSourceHeight();
			if (w <= 0 || h <= 0) { w = getWidth(); h = getHeight(); }
			int dw = getWidth(), dh = h * dw / w;
			if (dh > getHeight()) { dh = getHeight(); dw = w * dh / h; }
			vc.setDisplaySize(dw, dh);
			vc.setDisplayLocation((getWidth() - dw) / 2, (getHeight() - dh) / 2);
			vc.setVisible(true);
		}
		player.prefetch();
		player.start();
	}

	// A writable temp file URL, or null if no root is available.
	private static String tempFileUrl()
	{
		try
		{
			Enumeration roots = FileSystemRegistry.listRoots();
			while (roots.hasMoreElements())
			{
				String root = (String) roots.nextElement();
				while (root.length() > 0 && root.charAt(0) == '/') root = root.substring(1);
				String url = "file:///" + root + "tmm_video.3gp";
				try
				{
					FileConnection fc = (FileConnection) Connector.open(url, Connector.READ_WRITE);
					boolean ok = fc.canWrite();
					fc.close();
					if (ok) return url;
				}
				catch (Exception ignore) {}
			}
		}
		catch (Exception ignore) {}
		return null;
	}

	private void deleteTemp()
	{
		if (filePath == null) return;
		try
		{
			FileConnection fc = (FileConnection) Connector.open(filePath, Connector.READ_WRITE);
			if (fc.exists()) fc.delete();
			fc.close();
		}
		catch (Exception ignore) {}
		filePath = null;
	}

	// Short name of an exception: "javax.microedition.media.MediaException"
	// does not fit the screen, "MediaException" does.
	private static String shortName(Exception e)
	{
		if (e == null) return "?";
		String name = e.getClass().getName();
		int dot = name.lastIndexOf('.');
		if (dot >= 0) name = name.substring(dot + 1);
		String msg = e.getMessage();
		if (msg != null && msg.length() > 0)
		{
			if (msg.length() > 40) msg = msg.substring(0, 40);
			name += ": " + msg;
		}
		return name;
	}

	private void fail(Exception fileErr, Exception streamErr)
	{
		status = ResourceBundle.getString("video_failed");
		String types = "";
		try
		{
			String[] list = Manager.getSupportedContentTypes(null);
			for (int i = 0; i < list.length; i++)
			{
				if (list[i].indexOf("video") < 0 && list[i].indexOf("3gp") < 0) continue;
				types += (types.length() > 0 ? ", " : "") + list[i];
			}
			if (types.length() == 0) types = "нет видео";
		}
		catch (Exception e) { types = shortName(e); }
		details = new String[] {
			(clipSize / 1024) + " КБ",
			"файл: " + shortName(fileErr),
			"память: " + shortName(streamErr),
			"плеер: " + types,
		};
		repaint();
	}

	protected void paint(Graphics g)
	{
		g.setColor(0x000000);
		g.fillRect(0, 0, getWidth(), getHeight());
		if (status != null)
		{
			Font font = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
			g.setColor(0xFFFFFF);
			g.setFont(font);
			int step = font.getHeight();
			int lines = 1 + (details == null ? 0 : details.length);
			int y = (getHeight() - lines * step) / 2 + step;
			g.drawString(status, getWidth() / 2, y, Graphics.HCENTER | Graphics.BASELINE);
			if (details != null)
			{
				g.setColor(0xC0C0C0);
				for (int i = 0; i < details.length; i++)
				{
					y += step;
					g.drawString(details[i], 2, y, Graphics.LEFT | Graphics.BASELINE);
				}
			}
		}
	}

	private void stop()
	{
		if (player != null)
		{
			try { player.stop(); } catch (Exception ignore) {}
			try { player.close(); } catch (Exception ignore) {}
			player = null;
		}
		deleteTemp();
	}

	protected void keyPressed(int keyCode)
	{
		DrawControls.VirtualList.touch();
		close();
	}

	public void commandAction(Command c, Displayable d)
	{
		close();
	}

	private void close()
	{
		if (current == this) current = null;
		stop();                            // free the player and the temp file first
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
