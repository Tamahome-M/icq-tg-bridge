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
import javax.microedition.media.Manager;
import javax.microedition.media.Player;
import javax.microedition.media.control.VideoControl;

import jimm.comm.Icq;
import jimm.util.ResourceBundle;

/**
 * Takes a picture with the phone's camera and sends it to the chat through
 * the bridge. The viewfinder is a canvas of its own: the fire key (or "5")
 * takes the shot, "Back" leaves. The picture is sent in parts over the main
 * connection (SNAC 10/02) and the bridge answers 10/03 — sent or not.
 */
//#sijapp cond.if modules_CAMERA="true"#
public class CameraShot extends Canvas implements CommandListener, JimmScreen
{
	/** Столько ждём от моста ответа «ушло или нет». */
	public static final int ANSWER_WAIT = 45 * 1000;

	private static CameraShot current;

	private final JimmScreen back;
	private final String uin;
	private Player player;
	private VideoControl video;
	private String status;
	private String[] details;          // что телефон отвечает про съёмку
	private boolean sending;

	private CameraShot(String uin, JimmScreen back)
	{
		this.uin = uin;
		this.back = back;
		setFullScreenMode(true);
		addCommand(JimmUI.cmdBack);
		setCommandListener(this);
	}

	static public void show(String uin, JimmScreen back)
	{
		CameraShot shot = new CameraShot(uin, back);
		current = shot;
		Jimm.display.setCurrent(shot);
		shot.open();
	}

	// Opening the camera blocks for a while — do it off the UI thread.
	private void open()
	{
		status = ResourceBundle.getString("camera_opening");
		repaint();
		new Thread() {
			public void run()
			{
				try
				{
					Player p;
					try { p = Manager.createPlayer("capture://image"); }
					catch (Exception first) { p = Manager.createPlayer("capture://video"); }
					p.realize();
					VideoControl vc = (VideoControl) p.getControl("VideoControl");
					if (vc == null) throw new Exception("no VideoControl");
					vc.initDisplayMode(VideoControl.USE_DIRECT_VIDEO, CameraShot.this);
					vc.setDisplaySize(getWidth(), getHeight());
					vc.setDisplayLocation(0, 0);
					vc.setVisible(true);
					p.start();
					if (current != CameraShot.this) { try { p.close(); } catch (Exception ig) {} return; }
					player = p;
					video = vc;
					status = null;
					repaint();
				}
				catch (Exception e)
				{
					failed(e);
				}
			}
		}.start();
	}

	// The camera refused: show what the phone itself says about capture, so
	// it is clear whether a MIDlet may use it here at all.
	private void failed(Exception e)
	{
		status = ResourceBundle.getString("camera_failed") + " " + shortName(e);
		String types = "";
		try
		{
			String[] list = Manager.getSupportedContentTypes("capture");
			for (int i = 0; i < list.length; i++)
				types += (types.length() > 0 ? ", " : "") + list[i];
		}
		catch (Exception ex) { types = shortName(ex); }
		if (types.length() == 0) types = "нет";
		if (types.length() > 60) types = types.substring(0, 60);
		details = new String[] {
			"снимки: " + property("video.snapshot.encodings"),
			"видео: " + property("supports.video.capture")
					+ ", звук: " + property("supports.audio.capture"),
			"capture: " + types,
		};
		repaint();
	}

	private static String property(String name)
	{
		try
		{
			String value = System.getProperty(name);
			if (value == null || value.length() == 0) return "нет";
			if (value.length() > 40) value = value.substring(0, 40);
			return value;
		}
		catch (Exception e) { return "?"; }
	}

	private static String shortName(Exception e)
	{
		if (e == null) return "?";
		String name = e.getClass().getName();
		int dot = name.lastIndexOf('.');
		if (dot >= 0) name = name.substring(dot + 1);
		String msg = e.getMessage();
		if (msg != null && msg.length() > 0)
		{
			if (msg.length() > 30) msg = msg.substring(0, 30);
			name += ": " + msg;
		}
		return name;
	}

	// Размеры JPEG-снимка, которые телефон объявляет в video.snapshot.encodings
	// («encoding=jpeg&width=640&height=480 ...»), — строками «640x480», без
	// повторов. Пусто — телефон не говорит, тогда снимок «как есть».
	// Обычные размеры на случай, если телефон в свойстве размеры не называет
	// (V8 перечисляет там только форматы): getSnapshot с неподдерживаемым
	// размером бросит исключение, и снимок уйдёт «как есть».
	private static final String[] COMMON_SIZES =
		{ "160x120", "320x240", "640x480", "1024x768", "1280x1024", "1600x1200", "2048x1536" };

	public static String[] snapshotSizes()
	{
		java.util.Vector out = new java.util.Vector();
		try
		{
			String all = System.getProperty("video.snapshot.encodings");
			if (all != null)
			{
				String lower = all.toLowerCase();
				int pos = 0;
				while (pos < lower.length())
				{
					int end = lower.indexOf(' ', pos);
					if (end < 0) end = lower.length();
					String enc = lower.substring(pos, end);
					pos = end + 1;
					// Регистр и имя формата не важны: берём любой размер.
					int w = enc.indexOf("width=");
					int h = enc.indexOf("height=");
					if (w < 0 || h < 0) continue;
					String size = number(enc, w + 6) + "x" + number(enc, h + 7);
					if (size.length() > 2 && !out.contains(size)) out.addElement(size);
				}
			}
		}
		catch (Exception ignore) {}
		if (out.isEmpty()) return COMMON_SIZES;
		String[] sizes = new String[out.size()];
		out.copyInto(sizes);
		return sizes;
	}

	private static String number(String s, int from)
	{
		int to = from;
		while (to < s.length() && Character.isDigit(s.charAt(to))) to++;
		return s.substring(from, to);
	}

	// Snapshot and send: both are slow, so they run on their own thread.
	private void shoot()
	{
		if (video == null || sending) return;
		sending = true;
		status = ResourceBundle.getString("camera_sending");
		repaint();
		new Thread() {
			public void run()
			{
				byte[] shot = null;
				Exception err = null;
				// Размер из настроек — если телефон его знает; иначе как есть.
				String size = Options.getString(Options.OPTION_CAMERA_SIZE);
				if (size != null && size.length() > 0)
				{
					int x = size.indexOf('x');
					try
					{
						shot = video.getSnapshot("encoding=jpeg&width=" + size.substring(0, x)
								+ "&height=" + size.substring(x + 1));
					}
					catch (Exception e) { err = e; }
				}
				if (shot == null)
				{
					try { shot = video.getSnapshot("encoding=jpeg"); err = null; }
					catch (Exception e) { if (err == null) err = e; }
				}
				if (shot == null)
				{
					try { shot = video.getSnapshot(null); err = null; }
					catch (Exception e) { if (err == null) err = e; }
				}
				stopCamera();
				if (shot == null)
				{
					sending = false;
					failed(err);
					return;
				}
				try
				{
					Icq.sendPhoto(uin, shot);
					status = ResourceBundle.getString("camera_sending")
							+ " " + (shot.length / 1024) + " КБ";
					waitForBridge();
				}
				catch (Exception e)
				{
					sending = false;
					status = ResourceBundle.getString("camera_failed") + " " + shortName(e);
				}
				repaint();
			}
		}.start();
	}

	// Мост отвечает 10/03 — ушло или нет. Ответ может и не прийти (оборвалась
	// связь на последней части), и тогда экран должен сказать это сам, а не
	// висеть с «Отправляю».
	private void waitForBridge()
	{
		new Thread() {
			public void run()
			{
				try { Thread.sleep(ANSWER_WAIT); } catch (Exception ignore) {}
				if (current != CameraShot.this || !sending) return;
				sending = false;
				status = ResourceBundle.getString("camera_not_sent");
				repaint();
			}
		}.start();
	}

	// The bridge said whether the picture reached the chat.
	static public void photoSent(String uin, boolean ok)
	{
		CameraShot shot = current;
		if (shot == null || !shot.uin.equals(uin)) return;
		shot.sending = false;
		if (ok)
		{
			shot.close();
			return;
		}
		shot.status = ResourceBundle.getString("camera_not_sent");
		shot.repaint();
	}

	protected void paint(Graphics g)
	{
		if (video == null)
		{
			g.setColor(0x000000);
			g.fillRect(0, 0, getWidth(), getHeight());
		}
		if (status != null)
		{
			Font font = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
			g.setFont(font);
			int step = font.getHeight();
			int lines = 1 + (details == null ? 0 : details.length);
			int top = getHeight() - lines * step - 4;
			g.setColor(0x000000);
			g.fillRect(0, top, getWidth(), lines * step + 4);
			g.setColor(0xFFFFFF);
			int y = top + step;
			g.drawString(status, 2, y, Graphics.LEFT | Graphics.BASELINE);
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

	protected void keyPressed(int keyCode)
	{
		DrawControls.VirtualList.touch();
		int action = 0;
		try { action = getGameAction(keyCode); } catch (Exception ignore) {}
		if (action == FIRE || keyCode == KEY_NUM5) shoot();
	}

	private void stopCamera()
	{
		video = null;
		if (player != null)
		{
			try { player.stop(); } catch (Exception ignore) {}
			try { player.close(); } catch (Exception ignore) {}
			player = null;
		}
	}

	public void commandAction(Command c, Displayable d)
	{
		close();
	}

	private void close()
	{
		if (current == this) current = null;
		stopCamera();
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
//#sijapp cond.end#
