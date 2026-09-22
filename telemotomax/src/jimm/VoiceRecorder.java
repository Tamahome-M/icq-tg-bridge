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

	private static VoiceRecorder current;

	private final JimmScreen back;
	private final String uin;
	private Player player;
	private RecordControl record;
	private ByteArrayOutputStream sink;
	private long startedAt;
	private String status;
	private String hint;
	private String[] details;
	private boolean recording;
	private boolean sending;
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
		if (recording || sending) return;
		recording = true;
		status = ResourceBundle.getString("voice_recording");
		repaint();
		new Thread() {
			public void run()
			{
				try
				{
					Player p = openMicrophone();
					RecordControl rc = (RecordControl) p.getControl("RecordControl");
					if (rc == null) throw new Exception("no RecordControl");
					sink = new ByteArrayOutputStream();
					rc.setRecordStream(sink);
					// Потолок размера не ставим: телефон вправе урезать его до
					// своего (на V3 это обрывало запись на ~10 секундах), а
					// длину мы и так держим сами — по времени и по размеру.
					try { p.addPlayerListener(VoiceRecorder.this); } catch (Exception ignore) {}
					p.start();
					rc.startRecord();
					player = p;
					record = rc;
					startedAt = System.currentTimeMillis();
					repaintLater();
				}
				catch (Exception e)
				{
					recording = false;
					failed(e);
				}
			}
		}.start();
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
			catch (Exception e)
			{
				// Создался, но не открылся — закрыть, иначе каждая попытка
				// с очередным адресом оставляла плеер висеть.
				if (p != null) { try { p.close(); } catch (Exception ig) {} }
				last = e;
			}
		}
		throw last != null ? last : new Exception("no microphone");
	}

	// Redraws the running time once a second while recording.
	private void repaintLater()
	{
		new Thread() {
			public void run()
			{
				while (recording && current == VoiceRecorder.this)
				{
					int secs = seconds();
					lastSize = (sink == null) ? 0 : sink.size();
					status = ResourceBundle.getString("voice_recording") + " " + time(secs);
					repaint();
					if (secs >= MAX_SECONDS || lastSize >= MAX_BYTES) { stopAndSend(); return; }
					try { Thread.sleep(500); } catch (Exception ignore) {}
				}
			}
		}.start();
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
		if (!recording || sending) return;
		recording = false;
		sending = true;
		final int secs = Math.max(1, seconds());
		status = ResourceBundle.getString("voice_recorded") + time(secs);
		hint = null;
		repaint();
		new Thread() {
			public void run()
			{
				byte[] data = null;
				Exception err = null;
				try
				{
					record.commit();
					data = sink.toByteArray();
				}
				catch (Exception e) { err = e; }
				// Тип записи спрашиваем, пока плеер ещё жив.
				String type = "";
				try { if (player != null) type = String.valueOf(player.getContentType()); }
				catch (Exception ignore) {}
				stopRecorder();
				if (data == null || data.length == 0)
				{
					sending = false;
					failed(err);
					return;
				}
				lastSize = data.length;
				status = ResourceBundle.getString("camera_sending");
				repaint();
				try
				{
					// Заливка идёт частями и не быстро — показываем, сколько ушло.
					Icq.sendVoice(uin, data, secs, type, new Icq.UploadProgress() {
						public void onPart(int part, int total)
						{
							Jimm.wakeBacklight();
							sentPart = part;
							sentTotal = total;
							repaint();
						}
					});
					status = ResourceBundle.getString("voice_waiting");
					waitForBridge();
				}
				catch (Exception e)
				{
					sending = false;
					failed(e);
					return;
				}
				repaint();
			}
		}.start();
	}

	// Ответ моста (10/03) может и не прийти — например, связь оборвалась на
	// последней части. Ждать вечно нельзя: экран должен сказать, чем кончилось.
	private void waitForBridge()
	{
		new Thread() {
			public void run()
			{
				try { Thread.sleep(ANSWER_WAIT); } catch (Exception ignore) {}
				if (current != VoiceRecorder.this || !sending) return;
				sending = false;
				status = ResourceBundle.getString("camera_not_sent");
				stopReason = ResourceBundle.getString("voice_no_answer");
				repaint();
			}
		}.start();
	}

	// The bridge said whether the voice message reached the chat.
	static public void voiceSent(String uin, boolean ok)
	{
		final VoiceRecorder rec = current;
		if (rec == null || !rec.uin.equals(uin)) return;
		rec.sending = false;
		if (ok)
		{
			rec.done = true;
			rec.status = ResourceBundle.getString("voice_sent");
			rec.hint = null;
			rec.repaint();
			new Thread() {
				public void run()
				{
					try { Thread.sleep(1200); } catch (Exception ignore) {}
					rec.close();
				}
			}.start();
			return;
		}
		rec.status = ResourceBundle.getString("camera_not_sent");
		rec.repaint();
	}

	private void failed(Exception e)
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
		record = null;
		sink = null;
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
		stopRecorder();
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
