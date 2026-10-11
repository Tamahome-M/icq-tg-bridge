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
import java.io.OutputStream;
import java.io.IOException;
import java.util.Vector;

import javax.microedition.lcdui.Canvas;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;
import javax.microedition.lcdui.Graphics;
import javax.microedition.media.Manager;
import javax.microedition.media.Player;
import javax.microedition.media.PlayerListener;
import javax.microedition.media.control.RecordControl;

import jimm.comm.Icq;
import jimm.util.ResourceBundle;

/**
 * Records a voice message with the phone's microphone and sends it to the
 * chat through the bridge. "Fire" (or "5") starts the recording and stops
 * it; the recording is then sent in parts over the main connection (SNAC
 * 10/04), and the bridge answers 10/03 — sent or not.
 *
 * The phone records in its own format, usually AMR; turning that into what
 * Telegram and MAX call a voice message is the bridge's job.
 */
public class VoiceRecorder extends Canvas implements CommandListener, JimmScreen,
		PlayerListener
{
	public static final int MAX_SECONDS = 60;
	public static final int MAX_BYTES = 512 * 1024;
	/** Столько ждём от моста ответа «ушло или нет». */
	public static final int ANSWER_WAIT = 45 * 1000;

	private static volatile VoiceRecorder current;

	private final JimmScreen back;
	private final String uin;
	private Player player;
	private RecordControl record;
	private RecordingBuffer sink;
	private long startedAt;
	private String status;
	private String hint;
	private String[] details;
	private volatile boolean recording;
	private boolean opening, stopRequested;
	private volatile boolean sending;
	private Icq.Upload transfer;
	private java.util.TimerTask answerTask, returnTask;
	private boolean done;
	private int sentPart;
	private int sentTotal;
	private int lastSize;               // сколько уже записано, байт
	private String stopReason = "";     // почему запись прекратилась сама

	private VoiceRecorder(String uin, JimmScreen back)
	{
		this.uin = uin;
		this.back = back;
		setFullScreenMode(true);
		addCommand(JimmUI.cmdBack);
		setCommandListener(this);
	}

	static public void show(String uin, JimmScreen back)
	{
		VoiceRecorder rec = new VoiceRecorder(uin, back);
		current = rec;
		Jimm.display.setCurrent(rec);
		rec.status = ResourceBundle.getString("record_voice");
		rec.repaint();
	}

	// Opening the microphone blocks, so it happens off the UI thread.
	private void start()
	{
		synchronized (this)
		{
			if (current != this || recording || sending || done) return;
			recording = opening = true; stopRequested = false;
			startedAt = 0; lastSize = 0; details = null; stopReason = "";
		}
		status = ResourceBundle.getString("voice_recording");
		repaint();
		try { new Thread() {
			public void run()
			{
				Player local = null;
				boolean owned = false;
				try
				{
					local = openMicrophone();
					synchronized (VoiceRecorder.this)
					{
						if (current != VoiceRecorder.this || !recording) return;
						player = local; owned = true;
					}
					RecordControl control = (RecordControl)local.getControl("RecordControl");
					if (control == null) throw new Exception("no RecordControl");
					RecordingBuffer buffer = new RecordingBuffer((int)Math.min(MAX_BYTES,
							Math.max(0, (Runtime.getRuntime().freeMemory() - 48 * 1024) / 2)));
					control.setRecordStream(buffer);
					try { local.addPlayerListener(VoiceRecorder.this); } catch (Exception ignore) {}
					synchronized (VoiceRecorder.this)
					{
						if (current != VoiceRecorder.this || !recording) return;
						record = control; sink = buffer;
					}
					local.start(); control.startRecord();
					synchronized (VoiceRecorder.this)
					{
						if (current != VoiceRecorder.this || !recording) return;
						startedAt = System.currentTimeMillis(); opening = false;
					}
					if (stopRequested) stopAndSend();
					// Reuse the microphone worker instead of a second polling thread.
					while (recording && current == VoiceRecorder.this)
					{
						int secs = seconds(); lastSize = buffer.size();
						status = ResourceBundle.getString("voice_recording") + " " + time(secs);
						repaint();
						if (secs >= MAX_SECONDS || buffer.full()) { stopAndSend(); return; }
						try { Thread.sleep(500); } catch (Exception ignore) {}
					}
				}
				catch (Throwable failure) { abort(failure); }
				finally
				{
					if (!owned && local != null) { try { local.close(); } catch (Throwable ignore) {} }
				}
			}
		}.start(); }
		catch (Throwable failure) { abort(failure); }
	}

	private void abort(Throwable failure)
	{
		stopRecorder();
		synchronized (this) { recording = opening = sending = false; }
		if (transfer != null) transfer.cancel();
		if (current == this) failed(failure);
	}

	/** Bounded chunks: no growing whole-recording array and no final copy. */
	private static final class RecordingBuffer extends OutputStream
	{
		private static final int CHUNK = 2048;
		private final Vector chunks = new Vector();
		private final int limit;
		private int count;
		private boolean sealed, overflow;
		RecordingBuffer(int limit) throws IOException
		{ if (limit < CHUNK) throw new IOException("low memory"); this.limit = limit; }
		public synchronized int size() { return count; }
		public synchronized boolean full() { return overflow || count >= limit; }
		private final byte[] single = new byte[1];
		public synchronized void write(int value) throws IOException
		{ single[0] = (byte)value; write(single, 0, 1); }
		public synchronized void write(byte[] bytes, int offset, int length) throws IOException
		{
			if (sealed) throw new IOException("recording closed");
			if (offset < 0 || length < 0 || offset > bytes.length - length) throw new IndexOutOfBoundsException();
			int remaining = Math.min(length, limit - count);
			while (remaining > 0)
			{
				int part = count / CHUNK, position = count % CHUNK;
				if (part == chunks.size()) chunks.addElement(new byte[Math.min(CHUNK, limit - count)]);
				byte[] chunk = (byte[])chunks.elementAt(part);
				int take = Math.min(remaining, chunk.length - position);
				System.arraycopy(bytes, offset, chunk, position, take);
				count += take; offset += take; remaining -= take; length -= take;
			}
			if (length > 0) { overflow = true; throw new IOException("recording limit"); }
		}
		public synchronized InputStream input()
		{
			sealed = true;
			return new InputStream() {
				private int at;
				private final byte[] single = new byte[1];
				public int read() throws IOException
				{ return read(single, 0, 1) < 0 ? -1 : single[0] & 255; }
				public int read(byte[] bytes, int offset, int length) throws IOException
				{
					if (offset < 0 || length < 0 || offset > bytes.length - length) throw new IndexOutOfBoundsException();
					if (length == 0) return 0;
					if (at == count) return -1;
					int taken = 0;
					while (length > 0 && at < count)
					{
						int part = at / CHUNK, position = at % CHUNK;
						byte[] chunk = (byte[])chunks.elementAt(part);
						int take = Math.min(length, Math.min(chunk.length - position, count - at));
						System.arraycopy(chunk, position, bytes, offset, take);
						at += take; offset += take; length -= take; taken += take;
						if (at % CHUNK == 0 || at == count) chunks.setElementAt(null, part);
					}
					return taken;
				}
				public void close() { chunks.removeAllElements(); }
			};
		}
	}

	// AMR is what the bridge expects and what the phone records anyway, but
	// asking for it by name costs nothing and saves guessing later; if the
	// phone does not take the locator, the plain one is tried next.
	private static final String[] LOCATORS = {
		"capture://audio?encoding=audio/amr",
		"capture://audio?encoding=amr",
		"capture://audio",
	};

	private Player openMicrophone() throws Exception
	{
		Exception last = null;
		for (int i = 0; i < LOCATORS.length; i++)
		{
			Player p = null;
			try
			{
				p = Manager.createPlayer(LOCATORS[i]);
				p.realize();
				return p;
			}
			catch (Throwable e)
			{
				// Создался, но не открылся — закрыть, иначе каждая попытка
				// с очередным адресом оставляла плеер висеть.
				if (p != null) { try { p.close(); } catch (Exception ig) {} }
				if (e instanceof Error) throw (Error)e;
				last = (Exception)e;
			}
		}
		throw last != null ? last : new Exception("no microphone");
	}

	// Телефон может прекратить запись сам — по своему потолку размера или
	// по ошибке. Молча терять записанное нельзя: заканчиваем и отправляем,
	// а причину показываем на экране.
	public void playerUpdate(Player p, String event, Object data)
	{
		if (current != this || !recording) return;
		// Имена событий записи берём строками: в MIDP-заголовках сборки есть
		// не все константы JSR-135, а телефон шлёт именно эти имена.
		if ("recordStopped".equals(event) || "recordError".equals(event)
				|| "sizeLimitReached".equals(event)
				|| PlayerListener.END_OF_MEDIA.equals(event)
				|| PlayerListener.ERROR.equals(event))
		{
			stopReason = event;
			stopAndSend();
		}
	}

	private static String time(int secs)
	{
		if (secs < 0) secs = 0;
		return secs / 60 + ":" + (secs % 60 < 10 ? "0" : "") + (secs % 60);
	}

	private int seconds()
	{
		if (startedAt == 0) return 0;
		return (int) ((System.currentTimeMillis() - startedAt) / 1000);
	}

	private void stopAndSend()
	{
		synchronized (this)
		{
			if (!recording || sending || current != this) return;
			if (opening) { stopRequested = true; return; }
			recording = false; sending = true;
		}
		final int secs = Math.max(1, seconds());
		try
		{
			transfer = new Icq.Upload(uin) {
				public boolean isActive() { return current == VoiceRecorder.this && sending && super.isActive(); }
				public void onPart(int part, int total)
				{
					Jimm.wakeBacklight(); sentPart = part; sentTotal = total; repaint();
				}
			};
			status = ResourceBundle.getString("voice_recorded") + time(secs);
			hint = null; repaint();
			new Thread() {
				public void run()
				{
					RecordingBuffer buffer;
					RecordControl control;
					Player microphone;
					synchronized (VoiceRecorder.this) { buffer = sink; control = record; microphone = player; }
					InputStream input = null;
					try
					{
						if (current != VoiceRecorder.this || !sending || buffer == null || control == null) return;
						try { control.commit(); }
						catch (Exception error) { if (buffer.size() == 0) throw error; }
						String type = "";
						try { if (microphone != null) type = String.valueOf(microphone.getContentType()); } catch (Exception ignore) {}
						lastSize = buffer.size(); input = buffer.input();
						stopRecorder();
						if (lastSize == 0) throw new IOException("empty recording");
						status = ResourceBundle.getString("camera_sending"); repaint();
						Icq.sendVoiceStream(uin, input, lastSize, secs, type, transfer);
						if (current != VoiceRecorder.this || !sending) return;
						status = ResourceBundle.getString("voice_waiting"); waitForBridge(); repaint();
					}
					catch (Throwable failure) { abort(failure); }
					finally { if (input != null) try { input.close(); } catch (Exception ignore) {} }
				}
			}.start();
		}
		catch (Throwable failure) { abort(failure); }
	}

	// Ответ моста (10/03) может и не прийти — например, связь оборвалась на
	// последней части. Ждать вечно нельзя: экран должен сказать, чем кончилось.
	private void waitForBridge()
	{
		if (current != this || !sending) return;
		if (answerTask != null) answerTask.cancel();
		answerTask = new java.util.TimerTask() { public void run() {
			try {
				if (current != VoiceRecorder.this || !sending) return;
				sending = false;
				if (transfer != null) transfer.cancel();
				status = ResourceBundle.getString("camera_not_sent");
				stopReason = ResourceBundle.getString("voice_no_answer");
				repaint();
			} catch (Throwable ignore) {}
		} };
		Jimm.getTimerRef().schedule(answerTask, ANSWER_WAIT);
	}

	// The bridge said whether the voice message reached the chat.
	static public void voiceSent(String uin, boolean ok, long request)
	{
		final VoiceRecorder rec = current;
		if (rec == null || !rec.sending || rec.transfer == null || !rec.transfer.matches(uin, request)) return;
		if (rec.answerTask != null) rec.answerTask.cancel();
		rec.transfer.cancel();
		rec.sending = false;
		if (ok)
		{
			rec.done = true;
			rec.status = ResourceBundle.getString("voice_sent");
			rec.hint = null;
			rec.repaint();
			rec.returnTask = new java.util.TimerTask() { public void run() {
				try { MainThread.runSerially(new Runnable() { public void run() { if (current == rec && rec.done) rec.close(); } }); } catch (Throwable ignore) {}
			} };
			Jimm.getTimerRef().schedule(rec.returnTask, 1200);
			return;
		}
		rec.status = ResourceBundle.getString("camera_not_sent");
		rec.repaint();
	}

	private void failed(Throwable e)
	{
		String name = "?";
		if (e != null)
		{
			name = e.getClass().getName();
			int dot = name.lastIndexOf('.');
			if (dot >= 0) name = name.substring(dot + 1);
			String msg = e.getMessage();
			if (msg != null && msg.length() > 0)
			{
				if (msg.length() > 30) msg = msg.substring(0, 30);
				name += ": " + msg;
			}
		}
		status = ResourceBundle.getString("voice_failed2") + " " + name;
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
		try { supports = String.valueOf(System.getProperty("supports.audio.capture")); }
		catch (Exception ex) { supports = "?"; }
		details = new String[] { "звук: " + supports, "capture: " + types };
		repaint();
	}

	// Экран говорит ровно то, что происходит: ждём нажатия, пишем, заливаем
	// (с частями), отправлено или нет — раньше на нём висела одна строка, и
	// понять, ушло ли голосовое, было нельзя.
	protected void paint(Graphics g)
	{
		g.setColor(0x000000);
		g.fillRect(0, 0, getWidth(), getHeight());
		Font big = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_BOLD, Font.SIZE_MEDIUM);
		Font small = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
		int middle = getHeight() / 2;

		// Красный кружок, пока идёт запись: видно без чтения текста.
		if (recording)
		{
			g.setColor(0xCC2222);
			int r = small.getHeight();
			g.fillArc(getWidth() / 2 - r / 2, middle - big.getHeight() - r - 4, r, r, 0, 360);
		}

		g.setFont(big);
		g.setColor(0xFFFFFF);
		if (status != null)
			g.drawString(status, getWidth() / 2, middle, Graphics.HCENTER | Graphics.BASELINE);

		g.setFont(small);
		int y = middle + small.getHeight() + 4;
		g.setColor(0xC0C0C0);
		String second = second();
		if (second != null)
			g.drawString(second, getWidth() / 2, y, Graphics.HCENTER | Graphics.BASELINE);
		y += small.getHeight() + 2;

		if (!sending && !done)
		{
			String keys = (hint != null) ? hint : ResourceBundle.getString(
					recording ? "voice_stop" : "voice_start");
			g.drawString(keys, getWidth() / 2, y, Graphics.HCENTER | Graphics.BASELINE);
		}
		if (details != null)
		{
			for (int i = 0; i < details.length; i++)
			{
				y += small.getHeight();
				g.drawString(details[i], 2, y, Graphics.LEFT | Graphics.BASELINE);
			}
		}
	}

	// Вторая строка: размер записи, ход заливки, причина самостановки.
	private String second()
	{
		if (sending && sentTotal > 1)
			return ResourceBundle.getString("voice_part") + " " + sentPart + "/" + sentTotal;
		if (lastSize > 0) return (lastSize / 1024) + " КБ"
				+ (stopReason.length() > 0 ? ", " + stopReason : "");
		return stopReason.length() > 0 ? stopReason : null;
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

	private void stopRecorder()
	{
		Player old;
		synchronized (this) { old = player; player = null; record = null; sink = null; }
		if (old != null)
		{
			try { old.stop(); } catch (Throwable ignore) {}
			try { old.close(); } catch (Throwable ignore) {}
		}
	}

	public void commandAction(Command c, Displayable d)
	{
		close();
	}

	private void close()
	{
		boolean owned = current == this;
		if (owned) current = null;
		if (transfer != null) transfer.cancel();
		if (answerTask != null) answerTask.cancel();
		if (returnTask != null) returnTask.cancel();
		synchronized (this) { recording = sending = false; }
		stopRecorder();
		if (owned) MainThread.activateScreenMT(back);
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
