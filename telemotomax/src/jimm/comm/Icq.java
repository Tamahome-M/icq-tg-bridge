/*******************************************************************************
 Jimm - Mobile Messaging - J2ME ICQ clone
 Copyright (C) 2003-05  Jimm Project

 This program is free software; you can redistribute it and/or
 modify it under the terms of the GNU General Public License
 as published by the Free Software Foundation; either version 2
 of the License, or (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program; if not, write to the Free Software
 Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
 ********************************************************************************
 File: src/jimm/comm/Icq.java
 Version: ###VERSION###  Date: ###DATE###
 Author: Manuel Linsmayer, Andreas Rossbacher
 *******************************************************************************/

package jimm.comm;

import java.io.ByteArrayOutputStream;
import java.util.Hashtable;
import java.util.Vector;

import javax.microedition.io.Connector;
import javax.microedition.io.ContentConnection;

import jimm.ContactItem;
import jimm.DebugLog;
import jimm.Jimm;
import jimm.JimmUI;
import jimm.JimmException;
import jimm.Options;
import jimm.SplashCanvas;
import jimm.StatusInfo;
import jimm.comm.connections.*;
import jimm.util.ResourceBundle;
import jimm.ContactList;
import jimm.MainThread;
import jimm.TimerTasks;

//#sijapp cond.if modules_TRAFFIC is "true" #
import jimm.Traffic;
//#sijapp cond.end#



public class Icq implements Runnable
{
	private static Icq _this;

	public static final byte[] MTN_PACKET_BEGIN =
	{ (byte) 0x00, (byte) 0x00, (byte) 0x00, (byte) 0x00, (byte) 0x00,
			(byte) 0x00, (byte) 0x00, (byte) 0x00, (byte) 0x00, (byte) 0x01 };
	
	// Current state
	static private boolean connected = false;

	static private boolean disconnected = false;

	// Requested actions
	static private Vector reqAction = new Vector();

	// Thread
	static volatile Thread thread;

	// Current visibility mode
	static private int currentVisibility;

	
	// Wait object
	static private Object wait = new Object();
	
	// Connection to peer

	// All currently active actions
	static private Vector actAction;

	// Action listener
	static private ActionListener actListener;

	// Keep alive timer task
	static private TimerTasks keepAliveTimerTask;

	// Сторож связи. На GPRS оборванное соединение остаётся открытым: сокет
	// жив, клиент считает себя в сети, а мост давно закрыл сессию. Мост
	// отвечает на каждый наш keepalive, поэтому молчание в ответ на
	// несколько пингов подряд — верный признак, что канала больше нет.
	static private long lastServerData;
	static private long lastPingAt;
	static private int pingMisses;

	/** Сколько пингов подряд остались без единого байта в ответ. */
	static public int getPingMisses()
	{
		return pingMisses;
	}

	static public void noteServerData()
	{
		lastServerData = System.currentTimeMillis();
		pingMisses = 0;
	}

	static public void notePingSent()
	{
		long now = System.currentTimeMillis();
		if (lastPingAt != 0 && lastServerData < lastPingAt) pingMisses++;
		else pingMisses = 0;
		lastPingAt = now;
	}

	static public synchronized void notePingSent(Thread owner, Connection connection)
	{
		if (isCurrentConnection(owner, connection) && connected) notePingSent();
	}

	static public void resetPingWatch()
	{
		lastServerData = System.currentTimeMillis();
		lastPingAt = 0;
		pingMisses = 0;
	}

	public static int reconnect_attempts;

	public Icq()
	{
		_this = this;
	}
	

	// Flag for indicate that connection was reset _by_user_
	public static synchronized boolean isDisconnected()
	{
		return disconnected;
	}
	
	public static synchronized void setDisconnected(boolean value)
	{
		disconnected = value;
	}

	public static synchronized boolean isConnecting()
	{
		return thread != null && !connected;
	}

	public static synchronized boolean isCurrentConnection(Thread owner, Connection connection)
	{
		return owner != null && owner == thread && connection == c;
	}

	private static void cancelKeepAlive()
	{
		if (keepAliveTimerTask != null)
		{
			keepAliveTimerTask.cancel();
			keepAliveTimerTask = null;
		}
	}

	// Request an action
	static public void requestAction(Action act) throws JimmException
	{
		// Set reference to this ICQ object for callbacks
		act.setIcq(_this);

		if (act instanceof ConnectAction)
		{
			// «Не в сети» означает и незаконченный вход. Проверка и
			// запуск под одним замком: второй вход не создаёт ещё один
			// поток и таймер, пока первый подключается.
			synchronized (Icq.class)
			{
				if (connected || thread != null) return;
				Thread next = new Thread(_this);
				reqAction.addElement(act);
				thread = next;
				try { next.start(); }
				catch (RuntimeException t)
				{
					thread = null;
					reqAction.removeElement(act);
					throw t;
				}
				catch (Error t)
				{
					thread = null;
					reqAction.removeElement(act);
					throw t;
				}
			}
		}
		else
		{
			if (!act.isExecutable()) throw new JimmException(140, 0);
			synchronized (_this) { reqAction.addElement(act); }
		}

		// Notify main loop
		synchronized (wait)
		{
			wait.notify();
		}

	}

	// Connects to the ICQ network
	static public synchronized void connect()
	{
		connect(false);
	}

	// quiet — переподключение само по себе. Раньше и оно показывало заставку
	// «Подключение…» с командой «Отмена»: открыл телефон, нажал клавишу —
	// отмена, а отмена у Jimm означает «отключился руками»: автоматика
	// выключается насовсем, и клиент лежит «отключён», пока не нажмёшь
	// «Подключиться». Тихий вход заставку не трогает, отмены у него нет.
	static public synchronized void connect(boolean quiet)
	{
		if (connected || thread != null)
		{
			jimm.ConnLog.note(connected ? "вход пропущен: уже в сети" :
					"вход пропущен: уже подключаемся");
			return;
		}
		setDisconnected(false);
		//#sijapp cond.if target isnot "MOTOROLA"#
		if (Options.getBoolean(Options.OPTION_SHADOW_CON))
		{
			// Make the shadow connection for Nokia 6230 of other devices if
			// needed
			ContentConnection ctemp = null;
			try
			{
				String url = "http://shadow.jimm.org/";
				ctemp = (ContentConnection) Connector.open(url);

				ctemp.openDataInputStream();
			} catch (Exception e)
			{
				// Do nothing
			}
		}
		//#sijapp cond.end#
		// Connect
		ConnectAction act = new ConnectAction(
				Options.getString(Options.OPTION_UIN), 
				Options.getString(Options.OPTION_PASSWORD), 
				getFirstServerAddr(), 
				Options.getString(Options.OPTION_SRV_PORT),
				quiet);
		try
		{
			requestAction(act);

		} catch (JimmException e)
		{
			JimmException.handleException(e);
		}

		StatusInfo statInfo = JimmUI.findStatus(StatusInfo.TYPE_STATUS, (int)Options.getLong(Options.OPTION_ONLINE_STATUS));
		SplashCanvas.setStatusToDraw(statInfo != null ? statInfo.getImage() : null);
		
		// Start timer
		if (quiet) SplashCanvas.addTimerTask(act);          // без заставки и отмены
		else SplashCanvas.addTimerTask("connecting", act, true);

	}


	/* Disconnects from the ICQ network */
	static public synchronized void disconnect(boolean force)
	{
		//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
		disconnectBart(force);
		//#sijapp cond.end#


		setDisconnected(true);
		cancelKeepAlive();
		
		thread = null;
		setNotConnected();
		synchronized (wait) { wait.notifyAll(); }		
		// Отключение могло прийти до того, как новый поток создал сокет.
		if (c == null) return;
		
		if (force) c.forceDisconnect();
		else c.notifyToDisconnect();

		//#sijapp cond.if modules_TRAFFIC is "true" #
		try
		{
			Traffic.save();
		} catch (Exception e)
		{ /* Do nothing */
		}
		//#sijapp cond.end#

		/* Reset all contacts offine */
		MainThread.resetContactsOffline();
		
		setNotConnected();

		if (c.haveToSetNullAfterDisconnect()) c = null;
	}

	/* Disconnects from the ICQ network */
	//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
	static public synchronized void disconnectBart(boolean force)
	{
		if (bartC == null) return;
		
		if (force) bartC.forceDisconnect();
		else bartC.notifyToDisconnect();

		if (bartC.haveToSetNullAfterDisconnect()) bartC = null;
	}

	// Когда служебным соединением пользовались в последний раз: мост
	// закрывает его после трёх минут тишины, а на GPRS его FIN до телефона
	// может и не дойти — сокет тогда выглядит живым, но всё, что в него
	// пишут, уходит в никуда.
	static private long bartLastUse;
	static public final long BART_REUSE_MS = 120 * 1000;

	static public void noteBartUse()
	{
		bartLastUse = System.currentTimeMillis();
	}

	// Есть ли служебное соединение, которым ещё можно пользоваться. Залежалое
	// или сломанное закрываем сразу: иначе следующий запрос уйдёт в мёртвый
	// сокет и повиснет до таймаута, а сам сокет останется занимать место —
	// у телефона их немного, и однажды новое соединение просто не откроется.
	// TeleMotoMax: сведения о телефоне для моста (SNAC 01/F2) — платформа,
	// экран, куча. По ним мост выбирает профиль: размер снимка, длину
	// ролика, битрейт голосового. Обычный Jimm такого не шлёт, мост без
	// обработчика такой SNAC просто пропустит.
	static public void sendClientInfo(Connection conn) throws JimmException
	{
		String platform = jimm.Jimm.microeditionPlatform;
		if (platform == null) platform = "";
		byte[] raw = Util.stringToByteArray(platform, true);
		if (raw.length > 60) { byte[] cut = new byte[60]; System.arraycopy(raw, 0, cut, 0, 60); raw = cut; }
		int w = 0, h = 0;
		try { w = jimm.SplashCanvas.getAreaWidth(); h = jimm.SplashCanvas.getAreaHeight(); } catch (Exception ignore) {}
		long mem = Runtime.getRuntime().totalMemory() / 1024;
		// Хвостом — настройки «Медиа»: пары u16 ключ / u16 значение, 0 —
		// «как в профиле моста» (не шлём). Мост 0.47+ кладёт их поверх
		// профиля; старый мост хвост не читает.
		int[] media = mediaPairs();
		byte[] buf = new byte[1 + raw.length + 2 + 2 + 4 + media.length * 2];
		int m = 0;
		Util.putByte(buf, m, raw.length); m += 1;
		System.arraycopy(raw, 0, buf, m, raw.length); m += raw.length;
		Util.putWord(buf, m, w); m += 2;
		Util.putWord(buf, m, h); m += 2;
		Util.putDWord(buf, m, mem); m += 4;
		for (int i = 0; i < media.length; i++) { Util.putWord(buf, m, media[i]); m += 2; }
		conn.sendPacket(new SnacPacket(0x0001, 0x00F2, 0x00000000, new byte[0], buf));
	}

	// Ключи пар «Медиа» в 01/F2 — как у моста (server.MEDIA_KEYS).
	private static final int MEDIA_PHOTO_W = 1, MEDIA_PHOTO_H = 2, MEDIA_PHOTO_Q = 3,
			MEDIA_VIDEO_W = 4, MEDIA_VIDEO_H = 5, MEDIA_VIDEO_KBPS = 6, MEDIA_VIDEO_SEC = 7,
			MEDIA_VIDEO_ROTATE = 8, MEDIA_VOICE_KBPS10 = 9, MEDIA_VOICE_SEC = 10, MEDIA_PHOTO_KB = 11,
			MEDIA_VIDEO_KB = 12, MEDIA_ROSTER_LIMIT = 13, MEDIA_EXPRESS = 14,
			MEDIA_MAX = 15, MEDIA_TELEGRAM = 16, MEDIA_MAX_ROSTER_LIMIT = 17,
			MEDIA_EXPRESS_ROSTER_LIMIT = 18, MEDIA_CLIENT_VERSION = 19, MEDIA_VIDEO_MODE = 20;

	private static int[] mediaPairs()
	{
		int[] out = new int[40];
		int n = 0;
		// Версия клиента — первой парой: сведения о телефоне уходят раньше
		// способностей, а мосту версия нужна уже при сборке контакт-листа
		// (вложенные группы шлются только клиенту, который их понимает).
		n = pair(out, n, MEDIA_CLIENT_VERSION, TMM_VERSION_MAJOR * 100 + TMM_VERSION_MINOR);
		// 3 — выбор между встроенным плеером и браузером (0.79+).
		n = pair(out, n, MEDIA_VIDEO_MODE, 3);
		int[] size = jimm.Options.mediaSize(jimm.Options.OPTION_MEDIA_PHOTO_SIZE);
		if (size != null) { out[n++] = MEDIA_PHOTO_W; out[n++] = size[0]; out[n++] = MEDIA_PHOTO_H; out[n++] = size[1]; }
		n = pair(out, n, MEDIA_PHOTO_Q, jimm.Options.getInt(jimm.Options.OPTION_MEDIA_PHOTO_QUALITY));
		n = pair(out, n, MEDIA_PHOTO_KB, jimm.Options.getInt(jimm.Options.OPTION_MEDIA_PHOTO_KB));
		size = jimm.Options.mediaSize(jimm.Options.OPTION_MEDIA_VIDEO_SIZE);
		if (size != null) { out[n++] = MEDIA_VIDEO_W; out[n++] = size[0]; out[n++] = MEDIA_VIDEO_H; out[n++] = size[1]; }
		n = pair(out, n, MEDIA_VIDEO_KBPS, jimm.Options.mediaVideoKbps());
		n = pair(out, n, MEDIA_VIDEO_SEC, jimm.Options.getInt(jimm.Options.OPTION_MEDIA_VIDEO_SECONDS));
		n = pair(out, n, MEDIA_VIDEO_KB, jimm.Options.getInt(jimm.Options.OPTION_MEDIA_VIDEO_KB));
		n = pair(out, n, MEDIA_VIDEO_ROTATE, jimm.Options.getInt(jimm.Options.OPTION_VIDEO_ROTATE));
		n = pair(out, n, MEDIA_VOICE_KBPS10, jimm.Options.getInt(jimm.Options.OPTION_MEDIA_VOICE_KBPS10));
		n = pair(out, n, MEDIA_VOICE_SEC, jimm.Options.getInt(jimm.Options.OPTION_MEDIA_VOICE_SECONDS));
		// Сколько чатов класть в контакт-лист; 65535 — все (0 значило бы
		// «как в профиле»). Мост читает пару до того, как отдаст список.
		n = pair(out, n, MEDIA_ROSTER_LIMIT, jimm.Options.getInt(jimm.Options.OPTION_MEDIA_ROSTER_LIMIT));
		// Сети моста: 1 — включена, 2 — выключена; и сколько чатов каждой в списке.
		n = pair(out, n, MEDIA_EXPRESS, jimm.Options.getInt(jimm.Options.OPTION_EXPRESS));
		n = pair(out, n, MEDIA_MAX, jimm.Options.getBoolean(jimm.Options.OPTION_MAX_ON) ? 1 : 2);
		n = pair(out, n, MEDIA_TELEGRAM, jimm.Options.getBoolean(jimm.Options.OPTION_TELEGRAM_ON) ? 1 : 2);
		n = pair(out, n, MEDIA_MAX_ROSTER_LIMIT, jimm.Options.getInt(jimm.Options.OPTION_MAX_ROSTER_LIMIT));
		n = pair(out, n, MEDIA_EXPRESS_ROSTER_LIMIT, jimm.Options.getInt(jimm.Options.OPTION_EXPRESS_ROSTER_LIMIT));
		int[] cut = new int[n];
		System.arraycopy(out, 0, cut, 0, n);
		return cut;
	}

	private static int pair(int[] out, int n, int key, int value)
	{
		if (value <= 0) return n;
		out[n++] = key; out[n++] = value;
		return n;
	}

	// Настройки «Медиа» поменяли — мост должен узнать сразу, не при
	// следующем входе.
	static public void resendClientInfo()
	{
		try { if (isConnected() && c != null) sendClientInfo(c); }
		catch (Exception ignore) {}
	}

	// Кому сообщить, чем кончилось соединение со службой.
	public interface BartConnectListener
	{
		void onBartConnected();
		void onBartConnectFailed(JimmException e);
	}

	// Соединение со службой открывается в своём потоке: Connector.open на
	// GPRS занимает секунды, а то и десятки секунд, и раньше всё это время
	// стоял поток связи — не ходили ни сообщения, ни пинги. Готовое
	// соединение становится bartC и будит главный цикл.
	static public void connectBart(final String hostAndPort, final BartConnectListener l)
	{
		new Thread() {
			public void run()
			{
				disconnectBart(true);        // брошенный сокет никто больше не закроет
				Connection conn = new SOCKETConnection(JimmException.ICQ_BART);
				try
				{
					conn.connect(hostAndPort);
				}
				catch (JimmException e)
				{
					l.onBartConnectFailed(e);
					return;
				}
				catch (Exception e)
				{
					l.onBartConnectFailed(new JimmException(100, 52, true));
					return;
				}
				synchronized (Icq.class)
				{
					bartC = conn;
					noteBartUse();
				}
				l.onBartConnected();
				synchronized (wait) { wait.notifyAll(); }
			}
		}.start();
	}

	static public synchronized boolean bartUsable()
	{
		if (bartC == null) return false;
		if (bartC.getState()
				&& System.currentTimeMillis() - bartLastUse < BART_REUSE_MS)
			return true;
		disconnectBart(true);
		return false;
	}
	//#sijapp cond.end#

	static public void setVisibility(int value)
	{
		currentVisibility = value;
	}

	static public int getVisibility()
	{
		return currentVisibility;
	}

	// Checks whether the comm. subsystem is in STATE_NOT_CONNECTED
	static public synchronized boolean isNotConnected()
	{
		return !connected;
	}

	// Puts the comm. subsystem into STATE_NOT_CONNECTED
	static public synchronized void setNotConnected()
	{
		connected = false;
	}

	// Checks whether the comm. subsystem is in STATE_CONNECTED
	static public synchronized boolean isConnected()
	{
		return connected;
	}

	// Puts the comm. subsystem into STATE_CONNECTED
	static protected synchronized void setConnected()
	{
		SplashCanvas.setLastErrCode(null);
		Icq.reconnect_attempts = (Options.getBoolean(Options.OPTION_RECONNECT))	?
						Options.getInt(Options.OPTION_RECONNECT_NUMBER) : 0;
		connected = true;
	}

	// Resets the comm. subsystem
	static public synchronized void resetServerCon()
	{
		// Wake up thread in order to complete
		synchronized (Icq.wait)
		{
			Icq.wait.notify();
		}

		// Reset all variables
		connected = false;

		// Reset all timer tasks
		Jimm.jimm.cancelTimer();

		// Delete all actions
		if (actAction != null)
		{
			actAction.removeAllElements();
		}
		if (reqAction != null)
		{
			reqAction.removeAllElements();
		}

	}


	
	static public Object getWaitObj()
	{
		return wait;
	}

	// Connection to the ICQ server
	static Connection c;
	//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
	static Connection bartC;
	//  #sijapp cond.end#
	
	public static boolean isMyConnection(Connection conn)
	{
		return (conn == c);
	}

	// TeleMotoMax: sends a camera snapshot to the bridge over the main
	// connection, in parts of PHOTO_PART bytes: SNAC 10/02 with the target
	// uin, the part number and the chunk. The bridge answers 10/03.
	// Часть небольшая нарочно: отправка держит замок на потоке вывода, и
	// пока уходят 30 КБ по GPRS (это добрых полминуты), поток связи не может
	// ни подтвердить входящее, ни отправить сообщение — клиент выглядит
	// повисшим. 8 КБ уходят за пару секунд, между частями остальные успевают.
	public static final int PHOTO_PART = 8000;

	public static void sendPhoto(String uin, byte[] photo) throws JimmException
	{
		sendPhoto(uin, photo, null);
	}

	// Снимок 1200×1600 — это 150–250 КБ, по GPRS минуты; экран камеры
	// показывает, сколько частей уже ушло.
	public static void sendPhoto(String uin, byte[] photo, UploadProgress progress)
			throws JimmException
	{
		byte[] uinRaw = Util.stringToByteArray(uin);
		int total = (photo.length + PHOTO_PART - 1) / PHOTO_PART;
		if (total < 1) total = 1;
		for (int part = 1; part <= total; part++)
		{
			int from = (part - 1) * PHOTO_PART;
			int size = photo.length - from;
			if (size > PHOTO_PART) size = PHOTO_PART;
			byte[] buf = new byte[1 + uinRaw.length + 2 + 2 + 2 + size];
			int marker = 0;
			Util.putByte(buf, marker, uinRaw.length); marker += 1;
			System.arraycopy(uinRaw, 0, buf, marker, uinRaw.length); marker += uinRaw.length;
			Util.putWord(buf, marker, part); marker += 2;
			Util.putWord(buf, marker, total); marker += 2;
			Util.putWord(buf, marker, size); marker += 2;
			System.arraycopy(photo, from, buf, marker, size);
			sendPacket(new SnacPacket(0x0010, 0x0002, 0x00000000, new byte[0], buf));
			if (progress != null) progress.onPart(part, total);
			if (part < total) breathe();
		}
	}

	// TeleMotoMax: a voice message recorded on the phone, SNAC 10/04 — same
	// as a snapshot but with the length in seconds before the chunk.
	/** Кому сообщать, сколько частей загрузки уже ушло. */
	public interface UploadProgress
	{
		void onPart(int part, int total);
	}

	// Между частями — короткая пауза: отправка держит замок на потоке вывода,
	// и без передышки поток связи не смог бы вклиниться со своими пакетами
	// (подтверждениями, «печатает», сообщениями), а клиент выглядел бы
	// повисшим на всё время заливки.
	private static void breathe()
	{
		try { Thread.sleep(200); } catch (Exception ignore) {}
	}

	public static void sendVoice(String uin, byte[] voice, int seconds, String type)
			throws JimmException
	{
		sendVoice(uin, voice, seconds, type, null);
	}

	public static void sendVoice(String uin, byte[] voice, int seconds, String type,
			UploadProgress progress) throws JimmException
	{
		sendTimed(0x0004, uin, voice, seconds, type, progress);
	}

	// «Кружок» с камеры: та же раскладка, что у голосового, SNAC 10/05.
	public static void sendVideo(String uin, byte[] clip, int seconds, String type,
			UploadProgress progress) throws JimmException
	{
		sendTimed(0x0005, uin, clip, seconds, type, progress);
	}

	// Файл с телефона: части 10/08 — UIN, номер части, всего частей, общий
	// размер (4 байта), кусок; хвостом первой части — имя файла. Читается
	// из потока по частям: в памяти одна часть, а не весь файл.
	public static void sendFile(String uin, java.io.InputStream in, long size, String name,
			UploadProgress progress) throws JimmException, java.io.IOException
	{
		sendFile(uin, in, size, name, progress, 0);
	}

	// kind — как отправить на той стороне: 0 документом, 1 фотографией,
	// 2 видео. Байт хвостом первой части после имени; старый мост его не
	// читает и шлёт документом, как раньше.
	public static void sendFile(String uin, java.io.InputStream in, long size, String name,
			UploadProgress progress, int kind) throws JimmException, java.io.IOException
	{
		byte[] uinRaw = Util.stringToByteArray(uin);
		byte[] nameRaw = Util.stringToByteArray(name == null ? "" : name, true);
		if (nameRaw.length > 200) { byte[] cut = new byte[200]; System.arraycopy(nameRaw, 0, cut, 0, 200); nameRaw = cut; }
		int total = (int) ((size + PHOTO_PART - 1) / PHOTO_PART);
		if (total < 1) total = 1;
		byte[] chunk = new byte[PHOTO_PART];
		for (int part = 1; part <= total; part++)
		{
			int want = (int) Math.min((long) PHOTO_PART, size - (long) (part - 1) * PHOTO_PART);
			int got = 0;
			while (got < want)
			{
				int n = in.read(chunk, got, want - got);
				if (n < 0) throw new java.io.IOException("file shorter than declared");
				got += n;
			}
			int tail = (part == 1) ? 1 + nameRaw.length + 1 : 0;
			byte[] buf = new byte[1 + uinRaw.length + 2 + 2 + 4 + 2 + got + tail];
			int marker = 0;
			Util.putByte(buf, marker, uinRaw.length); marker += 1;
			System.arraycopy(uinRaw, 0, buf, marker, uinRaw.length); marker += uinRaw.length;
			Util.putWord(buf, marker, part); marker += 2;
			Util.putWord(buf, marker, total); marker += 2;
			Util.putDWord(buf, marker, size); marker += 4;
			Util.putWord(buf, marker, got); marker += 2;
			System.arraycopy(chunk, 0, buf, marker, got); marker += got;
			if (tail > 0)
			{
				Util.putByte(buf, marker, nameRaw.length); marker += 1;
				System.arraycopy(nameRaw, 0, buf, marker, nameRaw.length); marker += nameRaw.length;
				Util.putByte(buf, marker, kind);
			}
			sendPacket(new SnacPacket(0x0010, 0x0008, 0x00000000, new byte[0], buf));
			if (progress != null) progress.onPart(part, total);
			if (part < total) breathe();
		}
	}

	private static void sendTimed(int subtype, String uin, byte[] voice, int seconds, String type,
			UploadProgress progress) throws JimmException
	{
		byte[] uinRaw = Util.stringToByteArray(uin);
		// Тип записи («audio/amr») идёт хвостом первой части: мосту он
		// подсказывает, что ему прислали, а старый мост его просто не читает.
		byte[] typeRaw = Util.stringToByteArray(type == null ? "" : type);
		if (typeRaw.length > 60) typeRaw = new byte[0];
		int total = (voice.length + PHOTO_PART - 1) / PHOTO_PART;
		if (total < 1) total = 1;
		for (int part = 1; part <= total; part++)
		{
			int from = (part - 1) * PHOTO_PART;
			int size = voice.length - from;
			if (size > PHOTO_PART) size = PHOTO_PART;
			int tail = (part == 1) ? 1 + typeRaw.length : 0;
			byte[] buf = new byte[1 + uinRaw.length + 2 + 2 + 2 + 2 + size + tail];
			int marker = 0;
			Util.putByte(buf, marker, uinRaw.length); marker += 1;
			System.arraycopy(uinRaw, 0, buf, marker, uinRaw.length); marker += uinRaw.length;
			Util.putWord(buf, marker, part); marker += 2;
			Util.putWord(buf, marker, total); marker += 2;
			Util.putWord(buf, marker, seconds); marker += 2;
			Util.putWord(buf, marker, size); marker += 2;
			System.arraycopy(voice, from, buf, marker, size); marker += size;
			if (tail > 0)
			{
				Util.putByte(buf, marker, typeRaw.length); marker += 1;
				System.arraycopy(typeRaw, 0, buf, marker, typeRaw.length);
			}
			sendPacket(new SnacPacket(0x0010, subtype, 0x00000000, new byte[0], buf));
			if (progress != null) progress.onPart(part, total);
			if (part < total) breathe();
		}
	}

	public static void sendPacket(Packet packet) throws JimmException
	{
		if (c == null) return; // TODO: may be better to throw exception?
		c.sendPacket(packet);
	}
	
	public static void connect(String data) throws JimmException
	{
		if (c == null) return; // TODO: may be better to throw exception?
		c.connect(data);
	}

	// Main loop
	public void run()
	{
		//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
		boolean biPacketAvailable;
		//  #sijapp cond.end#

		// Get thread object
		Thread thread = Thread.currentThread();
		TimerTasks sessionKeepAlive = null;
		// Required variables
		Action newAction = null;

		try
		{
			synchronized (Icq.class)
			{
				// Поток, отменённый ещё до запуска, не должен создавать
				// сокет и таймер поверх следующего сеанса.
				if (Icq.thread != thread) return;

				// All phone builds connect directly to the bridge with a socket.
				c = new SOCKETConnection();
//#sijapp cond.if modules_PROXY is "true"#
				if (Options.getInt(Options.OPTION_CONN_TYPE) == Options.CONN_TYPE_PROXY) c = new SOCKSConnection();
//#sijapp cond.end#

				actAction = new Vector();
				actListener = new ActionListener();

				resetPingWatch();        // новый сеанс — счёт пингов с чистого листа
				cancelKeepAlive();
				sessionKeepAlive = new TimerTasks(TimerTasks.ICQ_KEEPALIVE, thread, c);
				keepAliveTimerTask = sessionKeepAlive;
				long keepAliveInterv = Integer.parseInt(Options
						.getString(Options.OPTION_CONN_ALIVE_INVTERV)) * 1000;
				Jimm.getTimerRef().schedule(sessionKeepAlive, keepAliveInterv,
						keepAliveInterv);
			}

			// Abort only in error state
			while (Icq.thread == thread)
			{
				// Get next action
				synchronized (this)
				{
					if (reqAction.size() > 0)
					{
						if ((actAction.size() == 1)
								&& ((Action) actAction.elementAt(0))
										.isExclusive())
						{
							newAction = null;
						} else
						{
							if (reqAction != null && reqAction.size() != 0)
								newAction = (Action) reqAction.elementAt(0);
							if (newAction != null && !newAction.isExecutable())
							{
								// Пока действие ждало очереди, состояние
								// изменилось (например, второй ConnectAction
								// после удавшегося входа). У Jimm такое
								// действие оставалось в голове очереди
								// навсегда и запирало всё, что за ним, —
								// фото, история, голосовые не начинались.
								reqAction.removeElementAt(0);
								newAction.onEvent(Action.ON_ERROR);
								newAction = null;
							}
							else if ((actAction.size() > 0) && newAction
									.isExclusive())
							{
								newAction = null;
							} else
							{
								if (reqAction != null && reqAction.size() != 0)
									reqAction.removeElementAt(0);
							}
						}
					} else
					{
						newAction = null;
					}
				}

				// Set dcPacketAvailable to true if the peerC is not null and
				// there is an packet waiting

				// Set biPacketAvailable to true if the bartC is not null and
				// there is an packet waiting
				//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
				// bartC читаем один раз: приёмник службы, увидев конец
				// потока, обнуляет его из своего потока — прямое
				// bartC.available() падало с NullPointerException, а это #141
				// и мёртвый главный цикл при живом сокете.
				Connection bi = bartC;
				biPacketAvailable = (bi != null) ? ((bi.available() > 0) ? true : false ) : false;
				//  #sijapp cond.end#

				// Wait if a new action does not exist. The check and the
				// wait share one lock: a packet that arrived in between
				// used to notify nobody, and the loop slept until the next
				// packet on the main connection — a photo from the service
				// sat in its queue while the screen said "loading".
				if (newAction == null)
				{
					try
					{
						synchronized (wait)
						{
							boolean quiet = (c.available() == 0);
				//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
							bi = bartC;
							if (quiet && bi != null && bi.available() > 0) quiet = false;
				//  #sijapp cond.end#
							if (quiet) wait.wait(/*Icq.STANDBY*/);
						}
					} catch (InterruptedException e)
					{
						// Do nothing
					}

				}
				// Initialize action
				else if (newAction != null)
				{
					try
					{
						newAction.init();
						if (Icq.thread != thread) break;
						actAction.addElement(newAction);
					} catch (JimmException e)
					{
						// Пока init() ждал (Connector.open на мёртвом GPRS
						// может висеть минуты), сеанс успели закрыть и
						// начать новый. Ошибка старой попытки не должна
						// рвать новую: она про соединение, которого уже нет.
						if (Icq.thread != thread)
						{
							jimm.ConnLog.note("старая попытка: " + e.getFullErrCode() + ", пропущено");
							break;
						}
						JimmException.handleException(e);
						if (e.isCritical())
							throw (e);
					}
				}

				if (Icq.thread != thread) break;
				//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
				bi = bartC;
				biPacketAvailable = (bi != null) ? ((bi.available() > 0) ? true : false ) : false;
				//  #sijapp cond.end#

				// Read next packet, if available
				Packet packet;
				boolean consumed;
				while (Icq.thread == thread && (
					(c.available() > 0)
				//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
					|| biPacketAvailable
				//  #sijapp cond.end#
				))
				{
					// Try to get packet
					packet = null;
					try
					{
						if (c.available() > 0)
						{
							packet = c.getPacket();
							noteServerData();     // канал жив
						}
						//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
						else if (biPacketAvailable) packet = bi.getPacket();
						//  #sijapp cond.end#
					} catch (JimmException e)
					{
						JimmException.handleException(e);
						if (e.isCritical())
							throw (e);
					}

					// Forward received packet to all active actions and to the
					// action listener
					consumed = false;
					for (int i = 0; i < actAction.size(); i++)
					{
						try
						{
							if (((Action) actAction.elementAt(i))
									.forward(packet))
							{
								consumed = true;
								break;
							}
						} catch (JimmException e)
						{
							JimmException.handleException(e);
							if (e.isCritical()) throw (e);
						}
					}
					if (!consumed)
					{
						try
						{
							actListener.forward(packet);
						} catch (JimmException e)
						{
							JimmException.handleException(e);
							if (e.isCritical()) throw (e);
						}
					}

					//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
					bi = bartC;
					biPacketAvailable = (bi != null) ? ((bi.available() > 0) ? true : false ) : false;
					//  #sijapp cond.end#
				}

				// Remove completed actions
				for (int i = 0; i < actAction.size(); i++)
				{
					if (((Action) actAction.elementAt(i)).isCompleted()
							|| ((Action) actAction.elementAt(i)).isError())
					{
						actAction.removeElementAt(i--);
					}
				}

			}
		}
		catch (Throwable e)
		{
			// Throwable, а не Exception: OutOfMemoryError главный цикл раньше
			// просто убивал — сокет оставался открытым, клиент «в сети», а
			// сообщений нет. Теперь это обрыв связи с переподключением.
			DebugLog.addText ("MainThread: Exception: " + e.toString());
			e.printStackTrace();

			if (Icq.thread == thread) {// Construct and handle exception
				// Как ошибка связи: закрыть сокет и переподключиться.
				// Некритичный вариант оставлял открытое соединение без
				// обработчика — «в сети», но ничего не приходит.
				jimm.ConnLog.note("сбой цикла связи: " + e.getClass().getName());
				JimmException f = new JimmException(141, 0, JimmException.ICQ_MAIN);
				JimmException.handleException(f);
			}
		}

		finally
		{
			// Ушедший поток убирает свою задачу, даже если уже есть новый
			// сеанс. Его таймер и соединение трогать нельзя.
			if (sessionKeepAlive != null) sessionKeepAlive.cancel();
			synchronized (Icq.class)
			{
				if (keepAliveTimerTask == sessionKeepAlive) keepAliveTimerTask = null;
				if (Icq.thread == thread)
				{
					if (!Options.getBoolean(Options.OPTION_RECONNECT) && c != null)
					{
						c.notifyToDisconnect();
						resetServerCon();
						MainThread.resetContactsOffline();
					}
					Icq.thread = null;
				}
			}
		}

	}

	public static boolean isNotCriticalConnectionError (int errcode) {
		switch (errcode) {
		    case 110:	// Login from another device
		    case 111:	// Bad password
		    case 112:	// Non-existant UIN
		    case 117:	// Empty UIN and/or password
		    case 119:	// "You need to allow network connection"
		    case 122:	// Specified server host and/or port is invalid
		    case 127:	// peer connection: specified server host and/or port is invalid
			return false;
		}
		return true;
	}


	public static int getCurrentStatus()
	{
		return isConnected() ? (int) Options
				.getLong(Options.OPTION_ONLINE_STATUS)
				: ContactList.STATUS_OFFLINE;
	}


	
	static public void setOnlineStatus(int status, boolean dcInfo) throws JimmException
	{
		ByteArrayOutputStream statBuffer = new ByteArrayOutputStream();
		ByteArrayOutputStream visBuffer = new ByteArrayOutputStream();
		
		int onlineStatus = Util.translateStatusSend(status);
		
		int visibilityItemId = Options.getInt(Options.OPTION_VISIBILITY_ID);
		byte bCode = 0;

		/* Main status */
		if (status != -1)
		{
			/* Visiblity */
			if (visibilityItemId != 0)
			{
				if (onlineStatus == Util.SET_STATUS_INVISIBLE)
					bCode = (status == ContactList.STATUS_INVIS_ALL) ? (byte) 2 : (byte) 3;
				else
					bCode = (byte) 4;
				Util.writeWord(visBuffer, 0, true);
				Util.writeWord(visBuffer, 0, true);
				Util.writeWord(visBuffer, visibilityItemId, true);
				Util.writeWord(visBuffer, 4, true);
				Util.writeWord(visBuffer, 5, true);
				Util.writeWord(visBuffer, 0xCA, true);
				Util.writeWord(visBuffer, 1, true);
				Util.writeByte(visBuffer, bCode);
			
				// Change privacy setting according to new status
				if ((getVisibility() != bCode) && (onlineStatus == Util.SET_STATUS_INVISIBLE))
				{
					setVisibility(bCode);
					SnacPacket reply2pre = new SnacPacket(
							SnacPacket.CLI_ROSTERUPDATE_FAMILY,
							SnacPacket.CLI_ROSTERUPDATE_COMMAND,
							SnacPacket.CLI_ROSTERUPDATE_COMMAND, new byte[0], visBuffer.toByteArray());
					sendPacket(reply2pre);
				}
			}
		
			Util.writeWord(statBuffer, 0x06, true); // TLV (0x06)
			Util.writeWord(statBuffer, 4, true); // TLV len
			Util.writeDWord(statBuffer, onlineStatus|0x10000000, true);
		}
		
		// DC Info
		if (dcInfo)
		{
			Util.writeWord(statBuffer, 0x0C, true);		// TLV (0x0C)
			Util.writeWord(statBuffer, 0x25, true);		// TLV len
			Util.writeDWord(statBuffer, 0xC0A80001, true);	// 192.168.0.1, cannot get own IP address
			Util.writeDWord(statBuffer, 0x0000ABCD, true);	// Port 43981
			Util.writeByte(statBuffer, 0x00);		// Firewall
			Util.writeWord(statBuffer, 0x08, true);		// Support protocol version 8
			Util.writeDWord(statBuffer, 0x00000000, true);
			Util.writeDWord(statBuffer, 0x00000050, true);
			Util.writeDWord(statBuffer, 0x00000003, true);
			Util.writeDWord(statBuffer, 0xFFFFFFFE, true);
			Util.writeDWord(statBuffer, 0x00010000, true);
			Util.writeDWord(statBuffer, 0xFFFFFFFE, true);
			Util.writeWord(statBuffer, 0x0000, true);
		}

		if (statBuffer.size() != 0)
		{
			SnacPacket packet = new SnacPacket(SnacPacket.CLI_SETSTATUS_FAMILY,
					SnacPacket.CLI_SETSTATUS_COMMAND, SnacPacket.CLI_SETSTATUS_COMMAND, new byte[0],
					statBuffer.toByteArray());
			sendPacket(packet);
		}
		
		// Change privacy setting according to new status
		if ((status != -1) && (getVisibility() != bCode) && (visibilityItemId != 0 && onlineStatus != Util.SET_STATUS_INVISIBLE))
		{
			setVisibility(bCode);
			SnacPacket reply2post = new SnacPacket(
					SnacPacket.CLI_ROSTERUPDATE_FAMILY,
					SnacPacket.CLI_ROSTERUPDATE_COMMAND,
					SnacPacket.CLI_ROSTERUPDATE_COMMAND, new byte[0], visBuffer.toByteArray());
			sendPacket(reply2post);
		}

	}

	static public void sendUserUnfoPacket() throws JimmException
	{
		ByteArrayOutputStream capsStream = new ByteArrayOutputStream();
		byte[] packet = null;
		
		try
		{
			byte[] ver = Util.stringToByteArray("###VERSION###");
			int verLen = ver.length;
			if (verLen > 10) verLen = 10;
			for (int i = 0; i < verLen; i++) CAP_VERSION[i+5] = ver[i];    
			
			capsStream.write(new byte[] {(byte)0x00, (byte)0x05, (byte)0x00, (byte)0x00});
			capsStream.write(CAP_AIM_SERVERRELAY);
			capsStream.write(CAP_AIM_ISICQ);
			capsStream.write(CAP_ICHAT);
			capsStream.write(CAP_UTF8);
			//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
			capsStream.write(CAP_AVATAR);
			//#sijapp cond.end#
			capsStream.write(CAP_VERSION);
			capsStream.write(CAP_TMM);

			//#sijapp cond.if target!="DEFAULT"#
			if (Options.getInt(Options.OPTION_TYPING_MODE) > 0) capsStream.write(CAP_MTN);
			//#sijapp cond.end#
			
			
			packet = capsStream.toByteArray();
			Util.putWord(packet, 2, packet.length-4);
		}
		catch (Exception e) {}
		
		sendPacket(new SnacPacket(SnacPacket.CLI_SETUSERINFO_FAMILY, SnacPacket.CLI_SETUSERINFO_COMMAND, 4, new byte[0], packet));

		byte[] buf = new byte[4];
		Util.putDWord(buf, 0, 0x00040000);
		sendPacket(new SnacPacket(SnacPacket.CLI_SETUSERINFO_FAMILY, SnacPacket.CLI_SETUSERINFO_COMMAND, 4, new byte[0], buf));
	}
	
	////////////////
	
	// Protocol capabilities required by messaging, avatars and typing.
	public static final byte[] CAP_ICHAT           = Util.explodeToBytes("09,46,00,00,4C,7F,11,D1,82,22,44,45,53,54,00,00", ',', 16);
	public static final byte[] CAP_AIM_ISICQ       = Util.explodeToBytes("09,46,13,44,4C,7F,11,D1,82,22,44,45,53,54,00,00", ',', 16);
	private static final byte[] CAP_AVATAR         = Util.explodeToBytes("09,46,13,4C,4C,7F,11,D1,82,22,44,45,53,54,00,00", ',', 16);
	public static final byte[] CAP_VERSION         = Util.explodeToBytes("*Jimm,20,00,00,00,00,00,00,00,00,00,00,00", ',', 16);
	public static final byte[] CAP_MTN             = Util.explodeToBytes("56,3f,c8,09,0b,6f,41,bd,9f,79,42,26,09,df,a2,f3", ',', 16);
	public static final byte[] CAP_AIM_SERVERRELAY = Util.explodeToBytes("09,46,13,49,4C,7F,11,D1,82,22,44,45,53,54,00,00", ',', 16);
	public static final byte[] CAP_UTF8            = Util.explodeToBytes("09,46,13,4E,4C,7F,11,D1,82,22,44,45,53,54,00,00", ',', 16);
	public static final byte[] CAP_UTF8_GUID       = Util.explodeToBytes("7b,30,39,34,36,31,33,34,45,2D,34,43,37,46,2D,31,31,44,31,2D,38,32,32,32,2D,34,34,34,35,35,33,35,34,30,30,30,30,7D", ',', 16);
	private static final byte[] CAP_OLD_HEAD = { (byte) 0x09, (byte) 0x46 };
	private static final byte[] CAP_OLD_TAIL = Util.explodeToBytes("4C,7F,11,D1,82,22,44,45,53,54,00,00", ',', 16);
	public static final int CAPF_NO_INTERNAL     = 0;      // No capability
	public static final int CAPF_AIM_SERVERRELAY = 1 << 0; // Client unterstands type-2 messages
	public static final int CAPF_UTF8_INTERNAL   = 1 << 1; // Client unterstands UTF-8 messages
	public static final int CAPF_TYPING          = 1 << 10;
	// TeleMotoMax: own capability so the bridge knows an extended client is
	// talking to it. "TMM:" then major and minor version, rest zeros.
	public static final int TMM_VERSION_MAJOR = 0;
	public static final int TMM_VERSION_MINOR = 4;
	public static final byte[] CAP_TMM = new byte[] {
		(byte) 'T', (byte) 'M', (byte) 'M', (byte) ':', (byte) TMM_VERSION_MAJOR, (byte) TMM_VERSION_MINOR,
		0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };

	public static void parseCapabilities(ContactItem item, byte[] capabilities)
	{
		int caps = CAPF_NO_INTERNAL;
		if (capabilities != null)
		{
			for (int offset = 0; offset + 16 <= capabilities.length; offset += 16)
			{
				if (Util.byteArrayEquals(capabilities, offset, CAP_AIM_SERVERRELAY, 0, 16)) caps |= CAPF_AIM_SERVERRELAY;
				else if (Util.byteArrayEquals(capabilities, offset, CAP_UTF8, 0, 16)) caps |= CAPF_UTF8_INTERNAL;
				else if (Util.byteArrayEquals(capabilities, offset, CAP_MTN, 0, 16)) caps |= CAPF_TYPING;
			}
		}
		item.setIntValue(ContactItem.CONTACTITEM_CAPABILITIES, caps);
	}

	// Expand TLV 0x19's two-byte capabilities, retaining complete TLV 0x0D GUIDs.
	public static byte[] mergeCapabilities(byte[] oldCaps, byte[] shortCaps)
	{
		int oldLength = oldCaps == null ? 0 : (oldCaps.length / 16) * 16;
		int count = shortCaps == null ? 0 : shortCaps.length / 2;
		byte[] merged = new byte[oldLength + count * 16];
		if (oldLength > 0) System.arraycopy(oldCaps, 0, merged, 0, oldLength);
		for (int i = 0; i < count; i++)
		{
			int offset = oldLength + i * 16;
			System.arraycopy(CAP_OLD_HEAD, 0, merged, offset, 2);
			System.arraycopy(shortCaps, i * 2, merged, offset + 2, 2);
			System.arraycopy(CAP_OLD_TAIL, 0, merged, offset + 4, 12);
		}
		return merged;
	}

	static public void sendCLI_ADDSTART() throws JimmException
	{
		sendPacket(new SnacPacket(SnacPacket.CLI_ADDSTART_FAMILY,
				SnacPacket.CLI_ADDSTART_COMMAND, SnacPacket.CLI_ADDSTART_COMMAND,
				new byte[0], new byte[0]));
	}

	static public void sendCLI_ADDEND() throws JimmException
	{
		sendPacket(new SnacPacket(SnacPacket.CLI_ADDEND_FAMILY,
				SnacPacket.CLI_ADDEND_COMMAND, SnacPacket.CLI_ADDEND_COMMAND, new byte[0],
				new byte[0]));
	}
	
	static public final int PROCESS_BUDDY_ADD = 10000;
	static public final int PROCESS_BUDDY_DELETE = 10001;
	
	static public void sendProcessBuddy(int mode, String name, int id, int groupId, int buddyType) throws JimmException
	{
		ByteArrayOutputStream buffer = new ByteArrayOutputStream();
		
		/* Name */
		Util.writeLenAndString(buffer, name, true);

		/* Group ID */
		Util.writeWord(buffer, groupId, true);

		/* ID */
		Util.writeWord(buffer, id, true);

		/* Type */
		Util.writeWord(buffer, buddyType, true);
		
		/* No additional data */
		Util.writeWord(buffer, 0, true);
		
		int command = -1;
		
		switch (mode)
		{
		case PROCESS_BUDDY_ADD:
			command = SnacPacket.CLI_ROSTERADD_COMMAND;
			break;
			
		case PROCESS_BUDDY_DELETE:
			command = SnacPacket.CLI_ROSTERDELETE_COMMAND;
			break;
		
		default:
			throw new JimmException(0, 0);
		}
		
		SnacPacket packet = new SnacPacket(0x0013, command, Util.getCounter(), new byte[0], buffer.toByteArray());
		
		sendPacket(packet);
	}

	public static boolean runActionAndProcessError(Action act) 
	{
		try
		{
			Icq.requestAction(act);
		} catch (JimmException e)
		{
			JimmException.handleException(e);
			return false;
		}
		
		SplashCanvas.addTimerTask("wait", act, false);
		
		return true;
	}
	
	public static void removeLocalContact(String uin)
	{
		byte[] buf = new byte[1 + uin.length()];
		Util.putByte(buf, 0, uin.length());
		System.arraycopy(uin.getBytes(), 0, buf, 1, uin.length());
		try
		{
			sendPacket(new SnacPacket(0x0003, 0x0005, 0, new byte[0], buf));
		} catch (JimmException e)
		{
			JimmException.handleException(e);
		}
	}

	// Adds a ContactItem to the server saved contact list
	static public synchronized void addToContactList(
			ContactItem cItem)
	{
		// Request contact item adding
		UpdateContactListAction act = new UpdateContactListAction(cItem,
				UpdateContactListAction.ACTION_ADD);

		try
		{
			requestAction(act);
		} catch (JimmException e)
		{
			JimmException.handleException(e);
			if (e.isCritical())
				return;
		}

		// Start timer
		SplashCanvas.addTimerTask("wait", act, false);
		// System.out.println("start addContact");
	}

	// Dels a ContactItem to the server saved contact list
	static public synchronized boolean delFromContactList(
			ContactItem cItem)
	{
		// Check whether contact item is temporary
		if (cItem.getBooleanValue(ContactItem.CONTACTITEM_IS_TEMP) && 
				!cItem.getBooleanValue(ContactItem.CONTACTITEM_IS_PHANTOM))
		{
			// Remove this temporary contact item
			removeLocalContact(cItem
					.getStringValue(ContactItem.CONTACTITEM_UIN));
			ContactList.removeContactItem(cItem);

			// Activate contact list
			ContactList.activateList();
		} 
		else
		{
			// Request contact item removal
			UpdateContactListAction act2 = new UpdateContactListAction(cItem,
					UpdateContactListAction.ACTION_DEL);
			try
			{
				Icq.requestAction(act2);
			} catch (JimmException e)
			{
				JimmException.handleException(e);
				if (e.isCritical())
					return false;
			}

			// Start timer
			SplashCanvas.addTimerTask("wait", act2, false);
		}
		return true;
	}

	//#sijapp cond.if target isnot "DEFAULT"#
	public synchronized static void beginTyping(String uin, boolean isTyping)
			throws JimmException
	{
		byte[] uinRaw = Util.stringToByteArray(uin);
		int tempBuffLen = Icq.MTN_PACKET_BEGIN.length + 1 + uinRaw.length + 2;
		int marker = 0;
		byte[] tempBuff = new byte[tempBuffLen];
		System.arraycopy(Icq.MTN_PACKET_BEGIN, 0, tempBuff, marker,
				Icq.MTN_PACKET_BEGIN.length);
		marker += Icq.MTN_PACKET_BEGIN.length;
		Util.putByte(tempBuff, marker, uinRaw.length);
		marker += 1;
		System.arraycopy(uinRaw, 0, tempBuff, marker, uinRaw.length);
		marker += uinRaw.length;
		Util.putWord(tempBuff, marker, ((isTyping) ? (0x0002) : (0x0000)));
		marker += 2;
		// Send packet
		SnacPacket snacPkt = new SnacPacket(0x0004, 0x0014, 0x00000000,
				new byte[0], tempBuff);
		sendPacket(snacPkt);
	}

	//#sijapp cond.end#
	
	public static String getFirstServerAddr()
	{
		String[] servers = Util.explode(Options.getString(Options.OPTION_SRV_HOST), ',');
		if (servers == null) return null;
		return (servers.length == 0) ? null : servers[0]; 
	}
	
	public static void rotateServersList()
	{
		String[] servers = Util.explode(Options.getString(Options.OPTION_SRV_HOST), ',');
		if ((servers == null) || (servers.length < 2)) return;
		String first = servers[0];
		for (int i = 1; i < servers.length; i++) servers[i-1] = servers[i];
		servers[servers.length-1] = first;
		Options.setString(Options.OPTION_SRV_HOST, Util.implode(servers, ','));
		DebugLog.addText("Icq.rotateServersList(): " + servers[0]);
	}
	
	
	public static final Hashtable interests;
	
	static
	{
		interests = new Hashtable();
		
		String str = 
			ResourceBundle.remove("interests1")+
			ResourceBundle.remove("interests2")+
			ResourceBundle.remove("interests3")+
			ResourceBundle.remove("interests4")+
			ResourceBundle.remove("interests5");
		
		String[] pairs = Util.explode(str, '|');
		
		if ((pairs.length%2) == 0)
			for (int i = 0; i < pairs.length; i += 2) interests.put(pairs[i], pairs[i+1]);
	}
}
