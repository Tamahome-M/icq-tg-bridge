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

import java.io.InputStream;

import javax.microedition.io.Connector;
import javax.microedition.lcdui.Canvas;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;
import javax.microedition.lcdui.Graphics;

import jimm.comm.Icq;
import jimm.util.ResourceBundle;

//#sijapp cond.if modules_CAMERA="true"#
/**
 * «Отправить файл»: обозреватель файлов Jimm (JSR-75) выбирает файл, он
 * уходит на мост частями (SNAC 10/06) прямо из потока — в памяти одна
 * часть, а не весь файл, — мост отдаёт его в чат документом и отвечает
 * 10/03. Потолок — MAX_BYTES здесь и file_max_mb в профиле на мосте.
 */
public class FileSender extends Canvas implements CommandListener, JimmScreen
{
	public static final long MAX_BYTES = 5L * 1024 * 1024;
	private static final long ANSWER_WAIT = 180 * 1000L;

	private static FileSender current;

	private final JimmScreen back;
	private final String uin;
	private FileSystem2 browser;
	private String status;
	private String fileName;
	private boolean sending;
	private final boolean media;             // «как фото/видео»: вид по расширению

	private FileSender(String uin, JimmScreen back, boolean media)
	{
		this.uin = uin;
		this.back = back;
		this.media = media;
		setFullScreenMode(true);
		addCommand(JimmUI.cmdBack);
		setCommandListener(this);
	}

	static public void show(String uin, JimmScreen back)
	{
		show(uin, back, false);
	}

	// media — отправить как фото или видео (по расширению файла): снимок
	// 1200×1600 и ролик штатной камеры так и приходят в чат, а не файлом.
	static public void show(String uin, JimmScreen back, boolean media)
	{
		FileSender sender = new FileSender(uin, back, media);
		current = sender;
		sender.browser = new FileSystem2();
		sender.browser.browse(null, sender, false);
	}

	// Обозреватель: «выбор» на файле — cmdOk, «назад» — cmdBack.
	public void commandAction(Command c, Displayable d)
	{
		if (c == JimmUI.cmdOk && browser != null && !sending)
		{
			String path = browser.getValue();
			if (path == null || path.endsWith("/")) return;
			int slash = path.lastIndexOf('/');
			fileName = slash >= 0 ? path.substring(slash + 1) : path;
			Jimm.display.setCurrent(this);
			send(path);
			return;
		}
		close();
	}

	private void send(final String path)
	{
		sending = true;
		status = ResourceBundle.getString("file_sending") + " " + fileName;
		repaint();
		new Thread() {
			public void run()
			{
				InputStream in = null;
				try
				{
					browser.openFile(path, Connector.READ);
					long size = browser.fileSize();
					if (size <= 0) throw new Exception("empty file");
					if (size > MAX_BYTES) throw new Exception("too big: " + (size / 1024) + " KB");
					in = browser.openInputStream();
					final long total = size;
					Icq.sendFile(uin, in, size, fileName, new Icq.UploadProgress() {
						public void onPart(int part, int parts)
						{
							Jimm.wakeBacklight();
							status = ResourceBundle.getString("file_sending") + " " + part + "/" + parts
									+ " (" + (total / 1024) + " КБ)";
							repaint();
						}
					}, media ? kindOf(fileName) : 0);
					status = ResourceBundle.getString("video_waiting_bridge");
					waitForBridge();
				}
				catch (Exception e)
				{
					sending = false;
					status = ResourceBundle.getString("file_failed") + " " + shortName(e);
				}
				finally
				{
					try { if (in != null) in.close(); } catch (Exception ignore) {}
					try { browser.close(); } catch (Exception ignore) {}
				}
				repaint();
			}
		}.start();
	}

	private void waitForBridge()
	{
		new Thread() {
			public void run()
			{
				try { Thread.sleep(ANSWER_WAIT); } catch (Exception ignore) {}
				if (current != FileSender.this || !sending) return;
				sending = false;
				status = ResourceBundle.getString("file_not_sent");
				repaint();
			}
		}.start();
	}

	// Мост ответил 10/03.
	static public void fileSent(String uin, boolean ok)
	{
		FileSender sender = current;
		if (sender == null || !sender.uin.equals(uin)) return;
		sender.sending = false;
		if (ok)
		{
			sender.close();
			return;
		}
		sender.status = ResourceBundle.getString("file_not_sent");
		sender.repaint();
	}

	// Вид по расширению: 1 фото, 2 видео, иначе 0 — обычным файлом.
	static int kindOf(String name)
	{
		String n = name == null ? "" : name.toLowerCase();
		if (n.endsWith(".jpg") || n.endsWith(".jpeg") || n.endsWith(".png")) return 1;
		if (n.endsWith(".3gp") || n.endsWith(".mp4") || n.endsWith(".3g2") || n.endsWith(".avi")
				|| n.endsWith(".mov")) return 2;
		return 0;
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
			if (msg.length() > 40) msg = msg.substring(0, 40);
			name += ": " + msg;
		}
		return name;
	}

	protected void paint(Graphics g)
	{
		g.setColor(0x000000);
		g.fillRect(0, 0, getWidth(), getHeight());
		Font font = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
		g.setFont(font);
		g.setColor(0xFFFFFF);
		if (status != null)
			JimmUI.drawWrapped(g, status, 2, getHeight() / 2 - font.getHeight(), getWidth() - 4, font);
	}

	private void close()
	{
		if (current == this) current = null;
		sending = false;
		try { if (browser != null) browser.close(); } catch (Exception ignore) {}
		browser = null;
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
