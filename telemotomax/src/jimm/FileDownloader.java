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

import java.io.OutputStream;
import java.util.Enumeration;
import java.util.Vector;

import javax.microedition.io.Connector;
import javax.microedition.io.file.FileConnection;
import javax.microedition.io.file.FileSystemRegistry;
import javax.microedition.lcdui.Canvas;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;
import javax.microedition.lcdui.Graphics;

import jimm.comm.Icq;
import jimm.comm.RequestBartAction;
import jimm.comm.Util;
import jimm.util.ResourceBundle;

//#sijapp cond.if modules_CAMERA="true"#
/**
 * «Скачать файл»: документ из сообщения по токену (тип приметы 0x0086)
 * приходит частями; первая начинается с имени файла. Части пишутся
 * писателем в своём потоке прямо в файл на телефоне — в память ничего не
 * копится. Куда: первый корень JSR-75, куда можно писать, папка tmm/.
 */
public class FileDownloader extends Canvas implements CommandListener, JimmScreen,
		RequestBartAction.PartSink
{
	private static FileDownloader current;

	private final JimmScreen back;
	private final String uin;
	private String status;
	private String fileName;
	private String filePath;
	private long got;
	private Vector partQueue;
	private Thread writer;
	private boolean partsDone, partsOk, failed;

	private FileDownloader(String uin, JimmScreen back)
	{
		this.uin = uin;
		this.back = back;
		setFullScreenMode(true);
		addCommand(JimmUI.cmdBack);
		setCommandListener(this);
	}

	// Java к файлам не пускают (на MOTOMAGX JSR-75 закрыт для неподписанных
	// приложений, и владелец этого не изменит) — тогда просим у моста ссылку
	// и отдаём её браузеру телефона: тот качает и сохраняет с полными правами.
	private boolean viaBrowser;

	static public void show(String uin, byte[] token, JimmScreen back)
	{
		FileDownloader dl = new FileDownloader(uin, back);
		current = dl;
		Jimm.display.setCurrent(dl);
		// Есть ли куда писать — проверяем до запроса, а не после первой
		// части: иначе 60 КБ скачались бы впустую.
		dl.viaBrowser = (targetUrl("tmm_probe.tmp") == null);
		if (!dl.viaBrowser) deleteFile(probeUrl);
		dl.status = ResourceBundle.getString(dl.viaBrowser ? "file_link_wait" : "file_loading");
		dl.repaint();
		try
		{
			RequestBartAction act = new RequestBartAction(uin, RequestBartAction.BART_FILE, token, dl);
			if (dl.viaBrowser) act.setFlags(0x40);
			Icq.requestAction(act);
		}
		catch (JimmException e)
		{
			dl.onBart(null);
		}
	}

	public void onBartProgress(int part, int total)
	{
		if (current != this) return;
		status = ResourceBundle.getString("file_loading") + " " + part + "/" + total;
		repaint();
	}

	// Ответ целиком (если части не пошли потоком) — тоже в файл; в режиме
	// браузера ответ — это ссылка.
	public void onBart(byte[] data)
	{
		if (current != this) return;
		if (data == null)
		{
			status = ResourceBundle.getString("file_failed") + (viaBrowser ? "" : "\n" + rootsError);
			repaint();
			return;
		}
		if (viaBrowser)
		{
			String url = Util.byteArrayToString(data, 0, data.length, true);
			boolean ok = false;
			try { Jimm.jimm.platformRequest(url); ok = true; }
			catch (Exception e) { status = ResourceBundle.getString("file_failed") + " " + shortName(e); }
			if (ok) status = ResourceBundle.getString("file_in_browser") + "\n" + url;
			repaint();
			return;
		}
		if (onBartPart(data, 0, data.length, 1, 1)) onBartDone(true);
		else
		{
			status = ResourceBundle.getString("file_failed") + " некуда писать\nкорни: "
					+ (rootsSeen.length() > 0 ? rootsSeen : "нет") + "\n" + rootsError;
			repaint();
		}
	}

	public synchronized boolean onBartPart(byte[] buf, int off, int len, int part, int total)
	{
		if (current != this || failed || viaBrowser) return false;
		if (partQueue == null)
		{
			// Первая часть: имя файла в голове.
			if (len < 1) return false;
			int nameLen = buf[off] & 0xFF;
			if (len < 1 + nameLen) return false;
			fileName = Util.byteArrayToString(buf, off + 1, nameLen, true);
			off += 1 + nameLen;
			len -= 1 + nameLen;
			filePath = targetUrl(fileName);
			if (filePath == null) return false;
			partQueue = new Vector();
			writer = new Thread() { public void run() { writeParts(); } };
			writer.start();
		}
		byte[] copy = new byte[len];
		System.arraycopy(buf, off, copy, 0, len);
		partQueue.addElement(copy);
		got += len;
		notifyAll();
		return true;
	}

	public synchronized void onBartDone(boolean ok)
	{
		partsDone = true;
		partsOk = ok;
		notifyAll();
	}

	private void writeParts()
	{
		Exception err = null;
		FileConnection fc = null;
		OutputStream out = null;
		final String path = filePath;
		try
		{
			fc = (FileConnection) Connector.open(path, Connector.READ_WRITE);
			if (fc.exists()) fc.delete();
			fc.create();
			out = fc.openOutputStream();
			for (;;)
			{
				byte[] chunk;
				synchronized (this)
				{
					while (partQueue.isEmpty() && !partsDone && current == this)
					{
						try { wait(); } catch (InterruptedException ignore) {}
					}
					if (current != this) break;
					if (partQueue.isEmpty())
					{
						if (partsDone) break;
						continue;
					}
					chunk = (byte[]) partQueue.elementAt(0);
					partQueue.removeElementAt(0);
				}
				out.write(chunk);
			}
			out.flush();
		}
		catch (Exception e) { err = e; failed = true; }
		try { if (out != null) out.close(); } catch (Exception ignore) {}
		try { if (fc != null) fc.close(); } catch (Exception ignore) {}
		if (current != this || err != null || !partsOk)
		{
			deleteFile(path);
			if (current == this)
			{
				status = ResourceBundle.getString("file_failed") + (err != null ? " " + shortName(err) : "");
				repaint();
			}
			return;
		}
		status = ResourceBundle.getString("file_saved") + "\n" + shown(path) + "\n" + (got / 1024) + " КБ";
		repaint();
	}

	// file:///c/tmm/name — путь без схемы, чтобы влез на экран.
	private static String shown(String url)
	{
		return url.startsWith("file://") ? url.substring(7) : url;
	}

	// Что телефон ответил, когда искали, куда писать: корни и последняя
	// ошибка — показываются на экране, если места не нашлось.
	private static String rootsSeen = "";
	private static String rootsError = "";
	private static String probeUrl;

	// Куда сохранять. Пробуем по очереди на каждом корне: папку tmm/, потом
	// сам корень — и не спрашиваем canWrite (на Motorola он врёт), а честно
	// создаём файл: получилось — сюда и пишем.
	private static String targetUrl(String name)
	{
		String safe = name.replace('/', '_').replace('\\', '_');
		if (safe.length() == 0) safe = "file.bin";
		rootsSeen = "";
		rootsError = "";
		try
		{
			Enumeration roots = FileSystemRegistry.listRoots();
			while (roots.hasMoreElements())
			{
				String root = (String) roots.nextElement();
				rootsSeen += (rootsSeen.length() > 0 ? ", " : "") + root;
				while (root.length() > 0 && root.charAt(0) == '/') root = root.substring(1);
				if (root.length() > 0 && !root.endsWith("/")) root += "/";
				String[] dirs = { "file:///" + root + "tmm/", "file:///" + root };
				for (int i = 0; i < dirs.length; i++)
				{
					String url = dirs[i] + safe;
					try
					{
						if (i == 0)
						{
							FileConnection d = (FileConnection) Connector.open(dirs[0], Connector.READ_WRITE);
							try { if (!d.exists()) d.mkdir(); } finally { d.close(); }
						}
						FileConnection fc = (FileConnection) Connector.open(url, Connector.READ_WRITE);
						try
						{
							if (fc.exists()) fc.delete();
							fc.create();
						}
						finally { fc.close(); }
						probeUrl = url;
						return url;
					}
					catch (Exception e)
					{
						rootsError = shortName(e);
					}
				}
			}
		}
		catch (Exception e) { rootsError = shortName(e); }
		return null;
	}

	private static void deleteFile(String url)
	{
		if (url == null) return;
		try
		{
			FileConnection fc = (FileConnection) Connector.open(url, Connector.READ_WRITE);
			if (fc.exists()) fc.delete();
			fc.close();
		}
		catch (Exception ignore) {}
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

	protected void keyPressed(int keyCode)
	{
		DrawControls.VirtualList.touch();
		int action = 0;
		try { action = getGameAction(keyCode); } catch (Exception ignore) {}
		if (action == FIRE || keyCode == KEY_NUM5 || keyCode == KEY_NUM0) close();
	}

	public void commandAction(Command c, Displayable d)
	{
		close();
	}

	private void close()
	{
		if (current == this) current = null;
		synchronized (this) { notifyAll(); }
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
