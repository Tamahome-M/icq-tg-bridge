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
	private boolean flash;             // белый кадр на миг — снимок сделан
	private String progress;           // состояние справа в верхней полосе
	private String locator = "?";      // какой источник открылся: camera, image или video
	private static final Command cmdProbe = new Command(ResourceBundle.getString("cam_probe"), Command.ITEM, 2);
	private static final Command cmdProbeSend = new Command(ResourceBundle.getString("cam_probe_send"), Command.ITEM, 3);
	private boolean probing;

	private CameraShot(String uin, JimmScreen back)
	{
		this.uin = uin;
		this.back = back;
		setFullScreenMode(true);
		addCommand(JimmUI.cmdBack);
		addCommand(cmdProbe);
		addCommand(cmdProbeSend);
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
				// Плеер, который не удалось довести до видоискателя, закрываем
				// тут же: у Motorola число плееров на приложение ограничено,
				// и каждая незакрытая попытка приближала «too many players» —
				// после чего не открывались ни камера, ни микрофон.
				Player p = null;
				try
				{
					// Источник камеры у Motorola — capture://camera («Java ME
					// Developer Guide for MOTOMAGX»: camera player с getSnapshot);
					// capture://image — по MMAPI; capture://video — видеопоток,
					// на V8 открывался только он, а снимок с него — кадр
					// видеозахвата, не сенсора.
					// Кто из них не открылся и почему — в «Связь»: по одному
					// «capture://video» в журнале не понять, отвергает ли V8
					// сам локатор или что-то ещё.
					String[] tries = { "capture://camera", "capture://image", "capture://video" };
					String why = "";
					for (int i = 0; i < tries.length && p == null; i++)
					{
						try { p = Manager.createPlayer(tries[i]); locator = tries[i].substring(10); }
						catch (Exception e) { why += tries[i].substring(10) + ": " + shortName(e) + "; "; }
					}
					if (p == null) throw new Exception(why);
					if (why.length() > 0)
						ConnLog.note("камера: " + why + "открылся " + locator + "; capture: " + captureTypes());
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
					if (p != null) { try { p.close(); } catch (Exception ig) {} }
					failed(e);
				}
			}
		}.start();
	}

	// The camera refused: show what the phone itself says about capture, so
	// it is clear whether a MIDlet may use it here at all.
	// Что телефон объявляет для протокола capture (типы содержимого).
	private static String captureTypes()
	{
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
		return types;
	}

	private void failed(Exception e)
	{
		status = ResourceBundle.getString("camera_failed") + " " + shortName(e);
		String types = captureTypes();
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

	private static String shortName(Throwable e)
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
	// Что V8 принял по пробе (getSnapshot с размером, capture://video):
	// 960×1280, 480×640, 640×480, 320×240, 240×320 — с заголовком в этот
	// размер; 1200×1600 — «Invalid snapshot size», 1024×768 — пустой
	// массив. Целый ли кадр у каждого — проба со снимками («*»).
	private static final String[] COMMON_SIZES =
		{ "960x1280", "480x640", "640x480", "320x240", "240x320", "160x120" };

	public static String[] snapshotSizes()
	{
		java.util.Vector out = new java.util.Vector();
		// video.snapshot.encodings у V8 — только «encoding=jpeg»; размеры он
		// называет в video.encodings (кадры видеозахвата). Фото-размеры
		// камеры телефон в свойствах не называет вовсе — добавляем свои.
		sizesFrom("video.snapshot.encodings", out);
		if (out.isEmpty()) sizesFrom("video.encodings", out);
		for (int i = 0; i < COMMON_SIZES.length; i++)
			if (!out.contains(COMMON_SIZES[i])) out.addElement(COMMON_SIZES[i]);
		String[] sizes = new String[out.size()];
		out.copyInto(sizes);
		return sizes;
	}

	private static void sizesFrom(String property, java.util.Vector out)
	{
		try
		{
			String all = System.getProperty(property);
			if (all == null) return;
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
		catch (Exception ignore) {}
	}

	// Размер JPEG по заголовку кадра (SOF), без раскодирования: «640x480»
	// или null. Идём по маркерам: у сегментов с длиной перескакиваем её,
	// у SOI и RSTn длины нет.
	static String jpegSize(byte[] d)
	{
		try
		{
			int i = 2;
			while (i + 9 < d.length)
			{
				if ((d[i] & 0xFF) != 0xFF) { i++; continue; }
				int m = d[i + 1] & 0xFF;
				if (m == 0xFF) { i++; continue; }
				if (m == 0xD8 || m == 0x01 || (m >= 0xD0 && m <= 0xD7)) { i += 2; continue; }
				if (m >= 0xC0 && m <= 0xCF && m != 0xC4 && m != 0xC8 && m != 0xCC)
				{
					int h = ((d[i + 5] & 0xFF) << 8) | (d[i + 6] & 0xFF);
					int w = ((d[i + 7] & 0xFF) << 8) | (d[i + 8] & 0xFF);
					return w + "x" + h;
				}
				i += 2 + (((d[i + 2] & 0xFF) << 8) | (d[i + 3] & 0xFF));
			}
		}
		catch (Exception ignore) {}
		return null;
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
		status = null;
		progress = ResourceBundle.getString("cam_shooting");
		repaint();
		new Thread() {
			public void run()
			{
				byte[] shot = null;
				Exception err = null;
				String how = "";
				// Размер из настроек — если телефон его знает; иначе как есть.
				String size = Options.getString(Options.OPTION_CAMERA_SIZE);
				if (size != null && size.length() > 0)
				{
					int x = size.indexOf('x');
					String w = size.substring(0, x), h = size.substring(x + 1);
					try
					{
						shot = video.getSnapshot("encoding=jpeg&width=" + w + "&height=" + h);
					}
					catch (Exception e) { err = e; }
					// V8 на неподдерживаемый размер не бросает исключение, а
					// отдаёт пустой массив (1024×768 — «?, 0 КБ») — это не
					// снимок, идём к следующей попытке.
					if (shot != null && jpegSize(shot) == null)
					{
						ConnLog.note("снимок " + size + ": не JPEG, " + shot.length + " Б — без размера");
						shot = null;
					}
				}
				if (shot == null)
				{
					try { shot = video.getSnapshot("encoding=jpeg"); err = null; }
					catch (Exception e) { if (err == null) err = e; }
					if (shot != null && jpegSize(shot) == null) shot = null;
				}
				if (shot == null)
				{
					try { shot = video.getSnapshot(null); err = null; }
					catch (Exception e) { if (err == null) err = e; }
				}
				stopCamera();
				// Вспышка на экране — снимок сделан: видоискатель уже закрыт,
				// белый кадр на чёрном виден отчётливо.
				flash = true;
				repaint();
				try { Thread.sleep(150); } catch (Exception ignore) {}
				flash = false;
				repaint();
				if (shot == null)
				{
					sending = false;
					failed(err);
					return;
				}
				// Что вышло на самом деле — по заголовку JPEG, не по настройке:
				// телефон может молча дать другой размер (или «тот», но битый).
				String got = jpegSize(shot);
				String info = (got == null ? "?" : got) + ", " + (shot.length / 1024) + " КБ";
				ConnLog.note("снимок " + info + " (" + how + "capture://" + locator
						+ (size != null && size.length() > 0 ? ", просили " + size : "") + ")");
				try
				{
					final String sent = info;
					progress = sent;
					repaint();
					Icq.sendPhoto(uin, shot, new Icq.UploadProgress() {
						public void onPart(int part, int total)
						{
							progress = sent + " \u00b7 " + part + "/" + total;
							repaint();
						}
					});
					progress = ResourceBundle.getString("cam_wait_bridge");
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
		if (shot.probing) return;          // проба шлёт несколько снимков подряд
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
		int w = getWidth(), h = getHeight();
		if (flash)
		{
			g.setColor(0xFFFFFF);
			g.fillRect(0, 0, w, h);
			return;
		}
		// Видоискатель рисует телефон; без него — чёрный фон.
		if (video == null)
		{
			g.setColor(0x000000);
			g.fillRect(0, 0, w, h);
		}
		String left = ResourceBundle.getString("cam_photo");
		if (sending)
			CameraHud.top(g, w, left, progress, CameraHud.WARN);
		else
		{
			String size = Options.getString(Options.OPTION_CAMERA_SIZE);
			if (size == null || size.length() == 0) size = ResourceBundle.getString("camera_size_default");
			CameraHud.top(g, w, left, size, CameraHud.DIM);
			if (video != null && status == null)
				CameraHud.bottom(g, w, h, ResourceBundle.getString("cam_hint_shoot"),
						ResourceBundle.getString("cam_hint_back"));
		}
		if (status != null)
		{
			if (details != null && details.length > 4) CameraHud.list(g, w, h, status, details);
			else CameraHud.box(g, w, h, status, details);
		}
	}

	protected void keyPressed(int keyCode)
	{
		DrawControls.VirtualList.touch();
		int action = 0;
		try { action = getGameAction(keyCode); } catch (Exception ignore) {}
		if (action == FIRE || keyCode == KEY_NUM5) shoot();
		else if (keyCode == KEY_POUND) probe();
		else if (keyCode == KEY_STAR) probeSend();
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
		if (c == cmdProbe) { probe(); return; }
		if (c == cmdProbeSend) { probeSend(); return; }
		close();
	}

	// Проба: что телефон отдаёт на каждый вариант строки getSnapshot — по
	// одному снимку за круг это не выяснить. Ничего не отправляет; итог —
	// на экране и в «Связи» (размер по заголовку JPEG, пусто, исключение).
	private static final String[] PROBES = {
		"encoding=jpeg",
		"encoding=jpeg&width=480&height=640",
		"encoding=jpeg&width=640&height=480",
		"encoding=jpeg&width=320&height=240",
		"encoding=jpeg&width=960&height=1280",
		"encoding=jpeg&width=1200&height=1600",
		"encoding=image/jpeg&width=480&height=640",
		"width=480&height=640",
		"encoding=rgb565&width=480&height=640",
		"encoding=png",
	};

	private void probe()
	{
		if (video == null || sending || probing) return;
		probing = true;
		status = ResourceBundle.getString("cam_probing");
		details = null;
		repaint();
		new Thread() {
			public void run()
			{
				String[] out = new String[PROBES.length + 2];
				out[0] = "video.encodings: " + longProperty("video.encodings");
				out[1] = "показ " + getWidth() + "x" + getHeight() + ", " + locator;
				for (int i = 0; i < PROBES.length; i++)
				{
					String what = PROBES[i];
					String res;
					try
					{
						byte[] shot = video.getSnapshot(what);
						if (shot == null) res = "null";
						else if (shot.length == 0) res = "пусто";
						else
						{
							String size = jpegSize(shot);
							res = (size == null ? "не JPEG" : size) + ", " + shot.length + " Б";
						}
					}
					catch (Throwable t) { res = shortName(t); }
					out[i + 2] = what.replace('&', ' ') + " -> " + res;
					ConnLog.note("проба " + out[i + 2]);
					if (video == null) break;
				}
				probing = false;
				status = ResourceBundle.getString("cam_probe_done");
				details = out;
				repaint();
				// Отчёт — в этот же чат сообщением: читать с экрана телефона
				// и фотографировать его не надо.
				StringBuffer sb = new StringBuffer("Проба камеры:");
				for (int i = 0; i < out.length; i++) if (out[i] != null) sb.append('\n').append(out[i]);
				sendToChat(sb.toString());
			}
		}.start();
	}

	// Текст в тот чат, из которого открыт экран: журнал и отчёты — туда.
	private void sendToChat(String text)
	{
		try
		{
			ContactItem contact = ContactList.getItembyUIN(uin);
			if (contact != null) JimmUI.sendMessage(text, contact);
		}
		catch (Exception ignore) {}
	}

	// Проба со снимками: размеры, которые телефон принял по заголовку, но
	// про которые не ясно, целый ли кадр (640×480 когда-то приходил
	// «завёрнутым»), — снимаем и отправляем в чат подряд, сравнивать глазами.
	private static final String[] PROBE_SEND = {
		"encoding=jpeg&width=480&height=640",
		"encoding=jpeg&width=640&height=480",
		"encoding=jpeg&width=960&height=1280",
	};

	private void probeSend()
	{
		if (video == null || sending || probing) return;
		probing = true;
		sending = true;
		status = null;
		details = null;
		progress = ResourceBundle.getString("cam_probing");
		repaint();
		new Thread() {
			public void run()
			{
				StringBuffer report = new StringBuffer("Проба со снимками:");
				for (int i = 0; i < PROBE_SEND.length && video != null; i++)
				{
					String what = PROBE_SEND[i];
					String res;
					try
					{
						byte[] shot = video.getSnapshot(what);
						String size = (shot == null) ? null : jpegSize(shot);
						if (size == null) res = "нет JPEG";
						else
						{
							final String tag = size + ", " + (shot.length / 1024) + " КБ";
							progress = tag;
							repaint();
							Icq.sendPhoto(uin, shot, new Icq.UploadProgress() {
								public void onPart(int part, int total)
								{
									progress = tag + " \u00b7 " + part + "/" + total;
									repaint();
								}
							});
							res = tag + " — ушло";
						}
					}
					catch (Throwable t) { res = shortName(t); }
					report.append('\n').append(what.replace('&', ' ')).append(" -> ").append(res);
					ConnLog.note("проба " + what.replace('&', ' ') + " -> " + res);
				}
				probing = false;
				sending = false;
				status = ResourceBundle.getString("cam_probe_done");
				repaint();
				sendToChat(report.toString());
			}
		}.start();
	}

	private static String longProperty(String name)
	{
		try
		{
			String v = System.getProperty(name);
			return v == null ? "нет" : v;
		}
		catch (Exception e) { return "?"; }
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
