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
public class VoiceRecorder extends Canvas implements CommandListener, JimmScreen
{
	public static final int MAX_SECONDS = 60;

	private static VoiceRecorder current;

	private final JimmScreen back;
	private final String uin;
	private Player player;
	private RecordControl record;
	private ByteArrayOutputStream sink;
	private long startedAt;
	private String status;
	private String[] details;
	private boolean recording;
	private boolean sending;

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
					rc.setRecordSizeLimit(512 * 1024);
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
			try
			{
				Player p = Manager.createPlayer(LOCATORS[i]);
				p.realize();
				return p;
			}
			catch (Exception e) { last = e; }
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
					status = ResourceBundle.getString("voice_recording") + " " + secs + " с";
					repaint();
					if (secs >= MAX_SECONDS) { stopAndSend(); return; }
					try { Thread.sleep(1000); } catch (Exception ignore) {}
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
		status = ResourceBundle.getString("voice_recorded") + secs + " с";
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
				try
				{
					Icq.sendVoice(uin, data, secs, type);
					status = ResourceBundle.getString("camera_sending")
							+ " " + (data.length / 1024) + " КБ";
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

	// The bridge said whether the voice message reached the chat.
	static public void voiceSent(String uin, boolean ok)
	{
		VoiceRecorder rec = current;
		if (rec == null || !rec.uin.equals(uin)) return;
		rec.sending = false;
		if (ok)
		{
			rec.close();
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

	protected void paint(Graphics g)
	{
		g.setColor(0x000000);
		g.fillRect(0, 0, getWidth(), getHeight());
		Font font = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
		g.setFont(font);
		int step = font.getHeight();
		int lines = 2 + (details == null ? 0 : details.length);
		int y = (getHeight() - lines * step) / 2 + step;
		g.setColor(0xFFFFFF);
		if (status != null) g.drawString(status, getWidth() / 2, y, Graphics.HCENTER | Graphics.BASELINE);
		y += step;
		g.setColor(0xC0C0C0);
		String hint = recording ? ResourceBundle.getString("voice_stop") : ResourceBundle.getString("voice_start");
		if (!sending) g.drawString(hint, getWidth() / 2, y, Graphics.HCENTER | Graphics.BASELINE);
		if (details != null)
		{
			for (int i = 0; i < details.length; i++)
			{
				y += step;
				g.drawString(details[i], 2, y, Graphics.LEFT | Graphics.BASELINE);
			}
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
