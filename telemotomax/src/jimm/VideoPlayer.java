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
 * from the bridge in parts over the BART service (type 0x0082), already
 * transcoded to what the phone's player takes (3GP, H.263 or MPEG-4 SP,
 * AMR); it is played straight from memory and dropped with the screen.
 */
public class VideoPlayer extends Canvas implements CommandListener, JimmScreen,
		RequestBartAction.ProgressListener
{
	private static VideoPlayer current;

	private final JimmScreen back;
	private String status;
	private Player player;
	private byte[] clip;

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
		clip = data;
		status = null;
		repaint();
		try
		{
			player = Manager.createPlayer(new ByteArrayInputStream(clip), "video/3gpp");
			player.realize();
			VideoControl vc = (VideoControl) player.getControl("VideoControl");
			if (vc != null)
			{
				vc.initDisplayMode(VideoControl.USE_DIRECT_VIDEO, this);
				int w = vc.getSourceWidth(), h = vc.getSourceHeight();
				if (w <= 0 || h <= 0) { w = getWidth(); h = getHeight(); }
				// Fit the frame into the screen, keep the aspect.
				int dw = getWidth(), dh = h * dw / w;
				if (dh > getHeight()) { dh = getHeight(); dw = w * dh / h; }
				vc.setDisplaySize(dw, dh);
				vc.setDisplayLocation((getWidth() - dw) / 2, (getHeight() - dh) / 2);
				vc.setVisible(true);
			}
			player.prefetch();
			player.start();
		}
		catch (Exception e)
		{
			status = ResourceBundle.getString("video_failed") + " (" + e.getClass().getName() + ")";
			stop();
			repaint();
		}
	}

	protected void paint(Graphics g)
	{
		g.setColor(0x000000);
		g.fillRect(0, 0, getWidth(), getHeight());
		if (status != null)
		{
			g.setColor(0xFFFFFF);
			g.setFont(Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL));
			g.drawString(status, getWidth() / 2, getHeight() / 2, Graphics.HCENTER | Graphics.BASELINE);
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
		clip = null;
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
		stop();                            // free the player and the clip first
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
