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

import java.io.ByteArrayOutputStream;
import java.io.InputStream;

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
import javax.microedition.media.control.RecordControl;
import javax.microedition.media.control.VideoControl;

import jimm.comm.Icq;
import jimm.util.ResourceBundle;

/**
 * «Кружок»: короткое видео с камеры телефона в чат. Видоискатель на весь
 * экран, «выбор» (или «5») начинает и заканчивает запись, стоп сам на
 * MAX_SECONDS. Запись идёт во временный файл (JSR-75), если есть куда, —
 * иначе в память; потом уходит частями (SNAC 10/05) с длительностью, мост
 * перекодирует в квадратный MP4 и отправляет кружком. Ответ 10/03 — ушло
 * или нет. Мотороле V3 камера из Java недоступна; на V8 — работает.
 */
//#sijapp cond.if modules_CAMERA="true"#
public class VideoRecorder extends Canvas implements CommandListener, JimmScreen
{
	public static final int MAX_SECONDS = 30;
	private static final long ANSWER_WAIT = 180 * 1000L;

	private static VideoRecorder current;

	private final JimmScreen back;
	private final String uin;
	private Player player;
	private VideoControl video;
	private RecordControl record;
	private ByteArrayOutputStream sink;      // запись в память, если нет файла
	private String tempUrl;                  // или во временный файл
	private long startedAt;
	private String status;
	private String[] details;
	private boolean recording;
	private boolean sending;
	private int sentParts, totalParts;

	private VideoRecorder(String uin, JimmScreen back)
	{
		this.uin = uin;
		this.back = back;
		setFullScreenMode(true);
		addCommand(JimmUI.cmdBack);
		setCommandListener(this);
	}

	static public void show(String uin, JimmScreen back)
	{
		VideoRecorder rec = new VideoRecorder(uin, back);
		current = rec;
		Jimm.display.setCurrent(rec);
		rec.open();
	}

	// Камера открывается долго — не в потоке интерфейса.
	private void open()
	{
		status = ResourceBundle.getString("camera_opening");
		repaint();
		new Thread() {
			public void run()
			{
				Player p = null;
				try
				{
					p = Manager.createPlayer("capture://video");
					p.realize();
					VideoControl vc = (VideoControl) p.getControl("VideoControl");
					if (vc == null) throw new Exception("no VideoControl");
					vc.initDisplayMode(VideoControl.USE_DIRECT_VIDEO, VideoRecorder.this);
					vc.setDisplaySize(getWidth(), getHeight());
					vc.setDisplayLocation(0, 0);
					vc.setVisible(true);
					p.start();
					if (current != VideoRecorder.this) { try { p.close(); } catch (Exception ig) {} return; }
					player = p;
					video = vc;
					status = null;
					repaint();
				}
				catch (Exception e)
				{
					// Незакрытый плеер копит «too many players» — см. CameraShot.
					if (p != null) { try { p.close(); } catch (Exception ig) {} }
					failed(e);
				}
			}
		}.start();
	}

	private void start()
	{
		if (player == null || recording || sending) return;
		recording = true;
		status = ResourceBundle.getString("video_recording");
		repaint();
		new Thread() {
			public void run()
			{
				try
				{
					RecordControl rc = (RecordControl) player.getControl("RecordControl");
					if (rc == null) throw new Exception("no RecordControl");
					tempUrl = tempFileUrl();
					if (tempUrl != null)
					{
						rc.setRecordLocation(tempUrl);
					}
					else
					{
						sink = new ByteArrayOutputStream();
						rc.setRecordStream(sink);
					}
					rc.startRecord();
					record = rc;
					startedAt = System.currentTimeMillis();
					tick();
				}
				catch (Exception e)
				{
					recording = false;
					failed(e);
				}
			}
		}.start();
	}

	private void tick()
	{
		new Thread() {
			public void run()
			{
				while (recording && current == VideoRecorder.this)
				{
					int secs = seconds();
					status = ResourceBundle.getString("video_recording") + " " + secs + "/" + MAX_SECONDS;
					repaint();
					if (secs >= MAX_SECONDS) { stopAndSend(); return; }
					try { Thread.sleep(500); } catch (Exception ignore) {}
				}
			}
		}.start();
	}

	private int seconds()
	{
		if (startedAt == 0) return 0;
		return (int) ((System.currentTimeMillis() - startedAt) / 1000);
	}

	private void stopAndSend()
	{
		if (!recording || sending) return;
		recording = false;
		sending = true;
		final int secs = Math.max(1, seconds());
		status = ResourceBundle.getString("camera_sending");
		repaint();
		new Thread() {
			public void run()
			{
				byte[] data = null;
				Exception err = null;
				String type = null;
				try
				{
					record.commit();
					try { type = record.getContentType(); } catch (Exception ignore) {}
					data = (sink != null) ? sink.toByteArray() : readTemp();
				}
				catch (Exception e) { err = e; }
				stopCamera();
				if (data == null || data.length == 0)
				{
					sending = false;
					failed(err);
					return;
				}
				final int size = data.length;
				try
				{
					Icq.sendVideo(uin, data, secs, type, new Icq.UploadProgress() {
						public void onPart(int part, int total)
						{
							sentParts = part; totalParts = total;
							status = ResourceBundle.getString("camera_sending") + " " + part + "/" + total
									+ " (" + (size / 1024) + " КБ)";
							repaint();
						}
					});
					data = null;
					deleteTemp();
					status = ResourceBundle.getString("video_waiting_bridge");
					waitForBridge();
				}
				catch (Exception e)
				{
					sending = false;
					deleteTemp();
					status = ResourceBundle.getString("camera_failed") + " " + shortName(e);
				}
				repaint();
			}
		}.start();
	}

	private byte[] readTemp() throws Exception
	{
		FileConnection fc = (FileConnection) Connector.open(tempUrl, Connector.READ);
		InputStream in = null;
		try
		{
			long size = fc.fileSize();
			if (size <= 0 || size > 8 * 1024 * 1024) throw new Exception("size " + size);
			byte[] buf = new byte[(int) size];
			in = fc.openInputStream();
			int got = 0;
			while (got < buf.length)
			{
				int n = in.read(buf, got, buf.length - got);
				if (n < 0) break;
				got += n;
			}
			return buf;
		}
		finally
		{
			try { if (in != null) in.close(); } catch (Exception ignore) {}
			try { fc.close(); } catch (Exception ignore) {}
		}
	}

	private static String tempFileUrl()
	{
		try
		{
			java.util.Enumeration roots = FileSystemRegistry.listRoots();
			while (roots.hasMoreElements())
			{
				String root = (String) roots.nextElement();
				while (root.length() > 0 && root.charAt(0) == '/') root = root.substring(1);
				String url = "file:///" + root + "tmm_note.3gp";
				try
				{
					FileConnection fc = (FileConnection) Connector.open(url, Connector.READ_WRITE);
					boolean ok = fc.canWrite();
					if (ok && fc.exists()) fc.delete();
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
		String url = tempUrl;
		tempUrl = null;
		if (url == null) return;
		try
		{
			FileConnection fc = (FileConnection) Connector.open(url, Connector.READ_WRITE);
			if (fc.exists()) fc.delete();
			fc.close();
		}
		catch (Exception ignore) {}
	}

	// Мост отвечает 10/03. Не ответил — не висим вечно.
	private void waitForBridge()
	{
		new Thread() {
			public void run()
			{
				try { Thread.sleep(ANSWER_WAIT); } catch (Exception ignore) {}
				if (current != VideoRecorder.this || !sending) return;
				sending = false;
				status = ResourceBundle.getString("video_not_sent");
				repaint();
			}
		}.start();
	}

	static public void videoSent(String uin, boolean ok)
	{
		VideoRecorder rec = current;
		if (rec == null || !rec.uin.equals(uin)) return;
		rec.sending = false;
		if (ok)
		{
			rec.close();
			return;
		}
		rec.status = ResourceBundle.getString("video_not_sent");
		rec.repaint();
	}

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
		catch (Exception ex) { types = "?"; }
		if (types.length() == 0) types = "нет";
		if (types.length() > 60) types = types.substring(0, 60);
		String supports;
		try { supports = String.valueOf(System.getProperty("supports.video.capture")); }
		catch (Exception ex) { supports = "?"; }
		details = new String[] { "видео: " + supports, "capture: " + types };
		repaint();
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

	protected void paint(Graphics g)
	{
		// Видоискатель рисует телефон; поверх — только строка состояния.
		if (video == null || status != null || details != null)
		{
			Font font = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
			g.setFont(font);
			int step = font.getHeight();
			if (video == null)
			{
				g.setColor(0x000000);
				g.fillRect(0, 0, getWidth(), getHeight());
			}
			else
			{
				g.setColor(0x000000);
				g.fillRect(0, 0, getWidth(), step + 4);
			}
			g.setColor(0xFFFFFF);
			if (status != null) g.drawString(status, getWidth() / 2, 2, Graphics.HCENTER | Graphics.TOP);
			if (details != null)
			{
				int y = getHeight() / 2;
				for (int i = 0; i < details.length; i++)
				{
					g.drawString(details[i], 2, y, Graphics.LEFT | Graphics.TOP);
					y += step;
				}
			}
		}
		else
		{
			Font font = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
			g.setFont(font);
			g.setColor(0xC0C0C0);
			g.drawString(ResourceBundle.getString("video_keys"), getWidth() / 2, 2, Graphics.HCENTER | Graphics.TOP);
		}
	}

	protected void keyPressed(int keyCode)
	{
		DrawControls.VirtualList.touch();
		int action = 0;
		try { action = getGameAction(keyCode); } catch (Exception ignore) {}
		if (action != FIRE && keyCode != KEY_NUM5) return;
		if (recording) stopAndSend();
		else start();
	}

	private void stopCamera()
	{
		video = null;
		record = null;
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
		recording = false;
		stopCamera();
		sink = null;
		deleteTemp();
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
