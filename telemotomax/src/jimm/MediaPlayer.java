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
import java.io.OutputStream;
import java.util.Enumeration;
import java.util.Vector;

import javax.microedition.io.Connector;
import javax.microedition.lcdui.Canvas;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;
import javax.microedition.lcdui.Graphics;
import javax.microedition.media.Manager;
import javax.microedition.media.Player;
import javax.microedition.media.PlayerListener;
import javax.microedition.media.control.VideoControl;

import jimm.comm.Icq;
import jimm.comm.RequestBartAction;
import jimm.util.ResourceBundle;

/**
 * Plays media attached to a message: the first seconds of a video (BART type
 * 0x0082) or a voice message (0x0083). The bridge sends it already transcoded
 * to what the phone takes — 3GP with H.263/MPEG-4 for video, 3GP with AMR for
 * voice. Video playback is not supported by the V3 at all (its MMAPI knows
 * only audio/3gpp), voice is; the same screen serves both.
 *
 * Playing from a temp file (JSR-75) is tried first and memory second, and
 * both the file and the player are dropped when the screen is closed.
 */
public class MediaPlayer extends Canvas implements CommandListener, JimmScreen,
		RequestBartAction.PartSink, PlayerListener
{
	// Потоковый приём: части клипа складываются в очередь, писатель в своём
	// потоке дописывает их во временный файл (ввод-вывод не в потоке связи),
	// после последней — запускает плеер. В куче при этом одна-две части, а
	// не весь клип. Нет записываемого корня — части не принимаем, и
	// RequestBartAction собирает клип в памяти, как раньше.
	private Vector partQueue;
	private Thread writer;
	private OutputStream partOut;
	private boolean partFailed;
	private boolean partsDone;
	private boolean partsOk;

	public synchronized boolean onBartPart(byte[] buf, int off, int len, int part, int total)
	{
		if (current != this || partFailed) return false;
		Jimm.wakeBacklight();
		if (partQueue == null)
		{
			String url = tempFileUrl(bartType == RequestBartAction.BART_VOICE ? ".amr" : ".3gp");
			if (url == null) return false;
			filePath = url;
			partQueue = new Vector();
			writer = new Thread() { public void run() { writeParts(); } };
			writer.start();
		}
		byte[] copy = new byte[len];
		System.arraycopy(buf, off, copy, 0, len);
		partQueue.addElement(copy);
		clipSize += len;
		notifyAll();
		// Части идут прямо в файл, минуя onBartProgress, — счётчик на
		// экране обновляем сами, иначе за всю загрузку не меняется ничего.
		waited = 0;
		receiving = true;
		if (part == 1) { firstPart = len; keepHead(buf, off, len); }
		status = waitingText() + " " + part + "/" + total + ", "
				+ loaded(clipSize, firstPart, part, total);
		repaint();
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
		final String path = filePath;
		try
		{
			TempFiles.api().recreate(path);
			partOut = TempFiles.out(path);
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
				partOut.write(chunk);
			}
			status = ResourceBundle.getString("media_saving");
			repaint();
			partOut.flush();
			partOut.close(); partOut = null;
			long written = TempFiles.size(path);
			if (written == 0) throw new Exception("empty temp file");
		}
		catch (Exception e)
		{
			err = e;
			partFailed = true;
		}
		try { if (partOut != null) partOut.close(); } catch (Exception ignore) {}
		partOut = null;
		if (current != this) { deleteFile(path); return; }
		if (err != null || !partsOk)
		{
			deleteTemp();
			if (err != null) fail(err, null); else { status = failedText(); repaint(); }
			return;
		}
		status = ResourceBundle.getString("media_opening");
		repaint();
		try
		{
			start(Manager.createPlayer(path));
			status = null;
			repaint();
		}
		catch (Exception e)
		{
			// Плеер не взял файл — пробуем из памяти, как при однопакетном
			// ответе: на V8 из памяти играет не всё, но клип уже у нас.
			Exception streamErr = null;
			byte[] clip = readFile(path, memoryLimit());
			if (clip != null) streamErr = playFromStream(clip);
			deleteTemp();
			if (clip == null || streamErr != null)
			{
				fail(e, streamErr);
				return;
			}
			status = null;
			repaint();
		}
	}

	// Сколько можно прочитать в память, если плеер не взял файл. Настройка
	// «Ролик в памяти, КБ» (Медиа) — сколько сказали, столько и берём.
	// Ноль — считать самим, но честно: куча динамическая, freeMemory()
	// показывает свободное место в нынешней куче (она ещё может подрасти) и
	// скачет от сборки мусора, поэтому сначала зовём gc, берём половину и не
	// больше двух мегабайт. У V8 куча около мегабайта, у V3 меньше.
	private static int memoryLimit()
	{
		int kb = 0;
		try { kb = Options.getInt(Options.OPTION_MEDIA_MEM_KB); } catch (Exception ignore) {}
		if (kb > 0) return kb * 1024;
		try { System.gc(); } catch (Throwable ignore) {}
		long limit = Runtime.getRuntime().freeMemory() / 2;
		if (limit > 2 * 1024 * 1024) limit = 2 * 1024 * 1024;
		return (int) limit;
	}

	/** Файл целиком, если он не больше предела; иначе null. */
	private static byte[] readFile(String url, int limit)
	{
		java.io.InputStream in = null;
		try
		{
			long size = TempFiles.size(url);
			if (size <= 0 || size > limit) return null;      // в кучу не ляжет
			byte[] buf = new byte[(int) size];
			in = TempFiles.in(url);
			int got = 0;
			while (got < buf.length)
			{
				int n = in.read(buf, got, buf.length - got);
				if (n < 0) break;
				got += n;
			}
			return got == buf.length ? buf : null;
		}
		catch (Exception e) { return null; }
		finally
		{
			try { if (in != null) in.close(); } catch (Exception ignore) {}
		}
	}

	private static void deleteFile(String url)
	{
		TempFiles.remove(url);
	}

	private static MediaPlayer current;

	private final JimmScreen back;
	private final int bartType;
	private final String mime;
	private String status;
	private String[] details;          // why it did not play, shown under the status
	private Player player;
	private String filePath;           // temp file URL, or null if played from memory
	private int clipSize;
	private int waited;              // секунд ждём первую часть (мост качает)
	private boolean settled;         // ответ пришёл (или всё сломалось): отсчёт стоп
	private boolean receiving;       // части пошли: отсчёт ожидания больше не нужен
	private byte[] head;             // начало клипа: по нему виден кодек
	private int firstPart;           // размер первой части: по нему виден весь объём
	private byte[] token;            // примета вложения: нужна, чтобы просить следующий кусок
	private String uin;
	private int segment;             // какой кусок ролика смотрим (0 — первый)
	private static final Command cmdNext = new Command(ResourceBundle.getString("video_next"), Command.ITEM, 2);
	private boolean paused;
	private boolean finished;
	private boolean ticking;

	private MediaPlayer(JimmScreen back, int bartType, String mime)
	{
		this.back = back;
		this.bartType = bartType;
		this.mime = mime;
		setFullScreenMode(true);
		addCommand(JimmUI.cmdBack);
		setCommandListener(this);
	}

	static public void show(String uin, byte[] token, JimmScreen back)
	{
		// Пока телефон ничего не грузит: мост качает ролик из Telegram или
		// MAX и перекодирует его — об этом и пишем, «Загрузка видео»
		// начнётся, когда пойдут части.
		open(uin, token, back, RequestBartAction.BART_VIDEO, "video/3gpp",
				ResourceBundle.getString("media_preparing"));
	}

	static public void showVoice(String uin, byte[] token, JimmScreen back)
	{
		open(uin, token, back, RequestBartAction.BART_VOICE, "audio/3gpp",
				ResourceBundle.getString("media_preparing_voice"));
	}

	static private void open(String uin, byte[] token, JimmScreen back,
			int bartType, String mime, String waiting)
	{
		open(uin, token, back, bartType, mime, waiting, 0);
	}

	// segment — какой кусок ролика просить: мост режет длинный ролик по
	// «Видео: длина» из настроек, а «Дальше» просит следующий кусок.
	static private void open(String uin, byte[] token, JimmScreen back,
			int bartType, String mime, String waiting, int segment)
	{
		MediaPlayer viewer = new MediaPlayer(back, bartType, mime);
		viewer.uin = uin;
		viewer.token = token;
		viewer.segment = segment;
		if (bartType == RequestBartAction.BART_VIDEO) viewer.addCommand(cmdNext);
		viewer.status = waiting + (segment > 0 ? " (" + (segment + 1) + ")" : "");
		current = viewer;
		Jimm.display.setCurrent(viewer);
		viewer.tickWaiting();
		try
		{
			byte[] ask = token;
			if (segment > 0)
			{
				// Номер куска — лишним байтом за приметой: старый мост такой
				// приметы не найдёт и честно ответит ошибкой.
				ask = new byte[token.length + 1];
				System.arraycopy(token, 0, ask, 0, token.length);
				ask[token.length] = (byte) segment;
			}
			Icq.requestAction(new RequestBartAction(uin, bartType, ask, viewer));
		}
		catch (JimmException e)
		{
			viewer.onBart(null);
		}
	}

	public void onBartProgress(int part, int total)
	{
		if (current != this) return;
		receiving = true;
		waited = 0;
		status = waitingText() + " " + part + "/" + total;
		repaint();
	}

	// Подсветка на время просмотра: гасить её телефон начинает по своему
	// сроку, а нажимать клавиши во время ролика некому. Держим, подновляя
	// раз в несколько секунд, пока экран наш и плеер жив.
	private void keepLit()
	{
		new Thread() {
			public void run()
			{
				while (current == MediaPlayer.this && player != null)
				{
					Jimm.wakeBacklight(true);
					try { Thread.sleep(4000); } catch (Exception ignore) {}
				}
			}
		}.start();
	}

	// Пока не пришла первая часть, мост качает вложение и перекодирует его
	// — на медленной сети это минуты. Без отсчёта экран выглядит повисшим,
	// поэтому показываем, сколько ждём; с первой частью счётчик частей
	// заменяет отсчёт.
	private void tickWaiting()
	{
		new Thread() {
			public void run()
			{
				String waiting = status;
				while (current == MediaPlayer.this && partQueue == null && player == null
						&& !settled && !receiving)
				{
					try { Thread.sleep(1000); } catch (Exception ignore) {}
					if (current != MediaPlayer.this || partQueue != null || player != null
							|| settled || receiving) return;
					waited++;
					status = waiting + " " + waited + " с";
					repaint();
				}
			}
		}.start();
	}

	// Called from the comm thread with the whole clip (or null).
	public void onBart(byte[] data)
	{
		if (current != this) return;
		settled = true;
		if (data == null)
		{
			// На последнем куске мост отвечает ошибкой: ролик кончился.
			status = segment > 0 ? ResourceBundle.getString("video_end") : failedText();
			repaint();
			return;
		}
		status = null;
		repaint();
		// Setting up the player (writing the temp file, createPlayer, start)
		// blocks; it must not run on the comm thread that called us, or the
		// whole connection freezes. Do it on a thread of its own.
		final byte[] clip = data;
		keepHead(clip, 0, clip.length);
		new Thread() {
			public void run()
			{
				if (current != MediaPlayer.this) return;
				clipSize = clip.length;
				Exception fileErr = playFromFile(clip);
				if (fileErr == null) return;
				Exception streamErr = playFromStream(clip);
				if (streamErr == null) return;
				fail(fileErr, streamErr);
			}
		}.start();
	}

	private Exception playFromFile(byte[] data)
	{
		String url = tempFileUrl(bartType == RequestBartAction.BART_VOICE ? ".amr" : ".3gp");
		if (url == null) return new Exception(TempFiles.lastError);
		OutputStream os = null;
		try
		{
			os = TempFiles.out(url);
			os.write(data);
			os.flush();
			os.close(); os = null;
			filePath = url;
			// Данные уже во временном файле — держать их ещё и в куче незачем:
			// плеер читает с «диска», а памяти на V3 немного.
			data = null;
			start(Manager.createPlayer(url));
			return null;
		}
		catch (Exception e)
		{
			try { if (os != null) os.close(); } catch (Exception ignore) {}
			deleteTemp();
			return e;
		}
	}

	// Из памяти телефон открывает поток по названному типу — и разборчив:
	// один и тот же 3GP он может взять как «video/3gpp», но отвергнуть как
	// «video/mp4», и наоборот. Перебираем несколько названий, прежде чем
	// сказать, что не вышло.
	private Exception playFromStream(byte[] data)
	{
		String[] types = (bartType == RequestBartAction.BART_VOICE)
				? new String[] { mime, "audio/amr", "audio/3gpp" }
				: new String[] { mime, "video/mp4", "video/3gpp2", "video/mpeg4" };
		Exception last = null;
		for (int i = 0; i < types.length; i++)
		{
			if (types[i] == null || (i > 0 && types[i].equals(types[0]))) continue;
			try
			{
				start(Manager.createPlayer(new ByteArrayInputStream(data), types[i]));
				playedAs = types[i];
				return null;
			}
			catch (Exception e) { last = e; }
		}
		return last;
	}

	private String playedAs;

	// The player tells us when the voice message has played to the end, so the
	// screen can offer to play it again instead of just going quiet.
	public void playerUpdate(Player p, String event, Object data)
	{
		if (current != this || p != player) return;
		if (PlayerListener.END_OF_MEDIA.equals(event))
		{
			finished = true;
			paused = false;
			repaint();
		}
	}

	// Redraws the running time about twice a second while the voice plays.
	private void tick()
	{
		if (ticking) return;
		ticking = true;
		new Thread() {
			public void run()
			{
				while (current == MediaPlayer.this && player != null)
				{
					repaint();
					try { Thread.sleep(500); } catch (Exception ignore) {}
				}
				ticking = false;
			}
		}.start();
	}

	// Pause and resume; at the end of the voice message "fire" plays it again.
	private void toggle()
	{
		Player p = player;
		if (p == null) return;
		try
		{
			if (finished)
			{
				p.setMediaTime(0);
				p.start();
				finished = false;
				paused = false;
			}
			else if (paused)
			{
				p.start();
				paused = false;
			}
			else
			{
				p.stop();
				paused = true;
			}
		}
		catch (Exception ignore) {}
		repaint();
	}

	private void rewind()
	{
		Player p = player;
		if (p == null) return;
		try
		{
			p.setMediaTime(0);
			if (paused || finished) p.start();
			paused = false;
			finished = false;
		}
		catch (Exception ignore) {}
		repaint();
	}

	// Media time in seconds, or -1 if the player does not tell.
	private int mediaSeconds(boolean total)
	{
		Player p = player;
		if (p == null) return -1;
		try
		{
			long micros = total ? p.getDuration() : p.getMediaTime();
			if (micros < 0) return -1;
			return (int) (micros / 1000000L);
		}
		catch (Exception e) { return -1; }
	}

	private static String time(int seconds)
	{
		if (seconds < 0) return "--:--";
		return seconds / 60 + ":" + (seconds % 60 < 10 ? "0" : "") + (seconds % 60);
	}

	private void start(Player p) throws Exception
	{
		try
		{
			startInternal(p);
		}
		catch (Exception e)
		{
			// Не завёлся — закрыть сразу, а не держать до выхода с экрана:
			// вторая попытка (из памяти) создаёт ещё один плеер.
			try { p.close(); } catch (Exception ig) {}
			if (player == p) player = null;
			throw e;
		}
	}

	private void startInternal(Player p) throws Exception
	{
		player = p;
		player.realize();
		VideoControl vc = (bartType == RequestBartAction.BART_VOICE)
				? null : (VideoControl) player.getControl("VideoControl");
		if (vc != null)
		{
			vc.initDisplayMode(VideoControl.USE_DIRECT_VIDEO, this);
			int w = vc.getSourceWidth(), h = vc.getSourceHeight();
			if (w <= 0 || h <= 0) { w = getWidth(); h = getHeight(); }
			int dw = getWidth(), dh = h * dw / w;
			if (dh > getHeight()) { dh = getHeight(); dw = w * dh / h; }
			vc.setDisplaySize(dw, dh);
			vc.setDisplayLocation((getWidth() - dw) / 2, (getHeight() - dh) / 2);
			vc.setVisible(true);
		}
		player.prefetch();
		if (bartType == RequestBartAction.BART_VOICE)
		{
			try { player.addPlayerListener(this); } catch (Exception ignore) {}
		}
		player.start();
		// Пока идёт ролик, по клавишам не нажимают — подсветка гаснет на
		// середине. Держим её включённой, пока плеер играет; при выходе с
		// экрана возвращаем телефону обычный режим.
		keepLit();
		if (bartType == RequestBartAction.BART_VOICE) tick();
	}

	// A writable temp file URL, or null if no root is available.
	// Место под временный файл — честным созданием (TempFiles): canWrite()
	// на несуществующем файле V8 отвечает «нет» при живом доступе к файлам,
	// и плеер говорил «no writable root», а из памяти MP4 он не играет.
	private static String tempFileUrl(String ext)
	{
		return TempFiles.writableUrl("tmm_media" + ext, true);
	}

	private void deleteTemp()
	{
		String path = filePath;
		filePath = null;
		// Пока писатель дописывает части, файл удалит он сам, когда выйдет.
		if (writer != null && writer.isAlive()) return;
		deleteFile(path);
	}

	// Short name of an exception: "javax.microedition.media.MediaException"
	// does not fit the screen, "MediaException" does.
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

	/**
	 * «48/120 КБ» — сколько принято из скольких. Точного объёма мост не
	 * присылает, но все части, кроме последней, одного размера, значит по
	 * первой он известен; на последней части объём уже точный.
	 */
	/** Первые байты клипа — по ним на экране ошибки виден кодек. */
	private void keepHead(byte[] buf, int off, int len)
	{
		if (head != null || len <= 0) return;
		int n = len < 256 ? len : 256;
		head = new byte[n];
		System.arraycopy(buf, off, head, 0, n);
	}

	/** «3gp/s263» — марка файла и кодек кадра, как их назвал сам файл. */
	private String headInfo()
	{
		if (head == null) return "";
		String s = new String(head, 0, head.length);
		String brand = "";
		int f = s.indexOf("ftyp");
		if (f >= 0 && f + 8 <= s.length()) brand = s.substring(f + 4, f + 8).trim();
		String codec = "";
		String[] known = { "s263", "mp4v", "avc1", "h263", "samr", "mp4a" };
		for (int i = 0; i < known.length; i++)
			if (s.indexOf(known[i]) >= 0)
				codec += (codec.length() > 0 ? "+" : "") + known[i];
		if (brand.length() == 0 && codec.length() == 0) return "";
		return brand + (codec.length() > 0 ? "/" + codec : "");
	}

	static String loaded(long got, int firstPart, int part, int total)
	{
		long whole = (part >= total || firstPart <= 0) ? got : (long) firstPart * total;
		if (whole < got) whole = got;
		return (got / 1024) + "/" + (whole / 1024) + " КБ";
	}

	private String waitingText()
	{
		return ResourceBundle.getString(
				bartType == RequestBartAction.BART_VOICE ? "voice_loading2" : "video_loading");
	}

	private String failedText()
	{
		return ResourceBundle.getString(
				bartType == RequestBartAction.BART_VOICE ? "voice_failed2" : "video_failed");
	}

	private void fail(Exception fileErr, Exception streamErr)
	{
		settled = true;                // отсчёт ожидания больше не затирает экран
		status = failedText();
		// Весь список, как его отдаёт телефон: раньше он был отфильтрован по
		// «video» и «3gp», и на V3 оставалась одна строка «audio/3gpp» —
		// выглядело так, будто телефон не умеет ничего другого.
		String types = "";
		try
		{
			String[] list = Manager.getSupportedContentTypes(null);
			for (int i = 0; i < list.length && types.length() < 120; i++)
				types += (types.length() > 0 ? ", " : "") + list[i];
			if (types.length() == 0) types = "пусто";
		}
		catch (Exception e) { types = shortName(e); }
		details = new String[] {
			(clipSize / 1024) + " КБ, файлы: " + TempFiles.apiName(),
			"тип: " + mime + (headInfo().length() > 0 ? ", в файле: " + headInfo() : ""),
			"файл: " + shortName(fileErr),
			"память: " + shortName(streamErr),
			"плеер: " + types,
		};
		repaint();
	}

	protected void paint(Graphics g)
	{
		g.setColor(0x000000);
		g.fillRect(0, 0, getWidth(), getHeight());
		if (status == null && player != null && bartType == RequestBartAction.BART_VOICE)
		{
			paintVoice(g);
			return;
		}
		if (status != null)
		{
			Font font = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
			g.setColor(0xFFFFFF);
			g.setFont(font);
			int step = font.getHeight();
			// Подробности ошибки переносятся по ширине: «no writable root:
			// …» на V3 обрезалось краем экрана, и причина оставалась за кадром.
			java.util.Vector rows = new java.util.Vector();
			if (details != null)
				for (int i = 0; i < details.length; i++) wrap(details[i], font, getWidth() - 4, rows);
			int lines = 1 + rows.size();
			int y = (getHeight() - lines * step) / 2 + step;
			if (y < step) y = step;
			g.drawString(status, getWidth() / 2, y, Graphics.HCENTER | Graphics.BASELINE);
			g.setColor(0xC0C0C0);
			for (int i = 0; i < rows.size(); i++)
			{
				y += step;
				g.drawString((String) rows.elementAt(i), 2, y, Graphics.LEFT | Graphics.BASELINE);
			}
		}
	}

	/** Режет строку на куски не шире width — по пробелам, а длинное слово по буквам. */
	private static void wrap(String text, Font font, int width, java.util.Vector out)
	{
		while (text.length() > 0)
		{
			if (font.stringWidth(text) <= width) { out.addElement(text); return; }
			int n = text.length();
			while (n > 1 && font.stringWidth(text.substring(0, n)) > width) n--;
			int sp = text.lastIndexOf(' ', n);
			if (sp > 0) n = sp;
			out.addElement(text.substring(0, n).trim());
			text = text.substring(n).trim();
		}
	}

	// A voice message has nothing to show, so the screen shows what it is
	// doing: elapsed time, a progress bar and which key does what.
	private void paintVoice(Graphics g)
	{
		Font font = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_MEDIUM);
		Font small = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
		int at = mediaSeconds(false), total = mediaSeconds(true);
		if (finished && total >= 0) at = total;
		int middle = getHeight() / 2;

		g.setFont(small);
		g.setColor(0x808080);
		String what = ResourceBundle.getString(
				finished ? "voice_done" : (paused ? "voice_paused" : "voice_playing"));
		g.drawString(what, getWidth() / 2, middle - font.getHeight() - small.getHeight() - 8,
				Graphics.HCENTER | Graphics.BASELINE);

		g.setFont(font);
		g.setColor(0xFFFFFF);
		String clock = time(at) + (total > 0 ? " / " + time(total) : "");
		g.drawString(clock, getWidth() / 2, middle - 6, Graphics.HCENTER | Graphics.BASELINE);

		// Полоса заполняется, только если плеер знает длительность.
		int barWidth = getWidth() - 20, barY = middle + 6, barHeight = 6;
		g.setColor(0x404040);
		g.drawRect(10, barY, barWidth, barHeight);
		if (total > 0 && at >= 0)
		{
			int filled = at >= total ? barWidth - 1 : (barWidth - 1) * at / total;
			g.setColor(0x33AA33);
			g.fillRect(11, barY + 1, filled, barHeight - 1);
		}

		g.setFont(small);
		g.setColor(0xC0C0C0);
		g.drawString(ResourceBundle.getString(finished ? "voice_keys_again" : "voice_keys"),
				getWidth() / 2, barY + barHeight + small.getHeight() + 6,
				Graphics.HCENTER | Graphics.BASELINE);
		g.drawString((clipSize / 1024) + " КБ", getWidth() / 2,
				barY + barHeight + 2 * small.getHeight() + 8,
				Graphics.HCENTER | Graphics.BASELINE);
	}

	private void stop()
	{
		if (player != null)
		{
			try { player.stop(); } catch (Exception ignore) {}
			try { player.close(); } catch (Exception ignore) {}
			player = null;
		}
		deleteTemp();
	}

	protected void keyPressed(int keyCode)
	{
		DrawControls.VirtualList.touch();
		// У голосового экран живой: «выбор» (или «5») — пауза и продолжение,
		// в конце — ещё раз; «4» (или влево) — с начала; «0» — закрыть.
		if (bartType == RequestBartAction.BART_VOICE && player != null)
		{
			int action = 0;
			try { action = getGameAction(keyCode); } catch (Exception ignore) {}
			if (action == FIRE || keyCode == KEY_NUM5) { toggle(); return; }
			if (action == LEFT || keyCode == KEY_NUM4) { rewind(); return; }
			if (keyCode == KEY_NUM0) { close(); return; }
			return;
		}
		// Как и фото: закрывают «выбор», «5», «0» и «Назад», остальные
		// клавиши только будят подсветку.
		int action = 0;
		try { action = getGameAction(keyCode); } catch (Exception ignore) {}
		if (action == FIRE || keyCode == KEY_NUM5 || keyCode == KEY_NUM0) close();
		else if (keyCode == KEY_NUM3 && bartType == RequestBartAction.BART_VIDEO) next();
	}

	public void commandAction(Command c, Displayable d)
	{
		if (c == cmdNext) { next(); return; }
		close();
	}

	// Следующий кусок ролика: тот же экран, тот же токен, номер куска на
	// единицу больше. Мост режет по «Видео: длина» из настроек «Медиа»:
	// целиком длинный ролик по GPRS ехал бы десятки минут.
	private void next()
	{
		if (token == null || bartType != RequestBartAction.BART_VIDEO) return;
		String uin = this.uin, mime = this.mime;
		byte[] tok = this.token;
		int nextSegment = this.segment + 1;
		JimmScreen where = this.back;
		close();
		open(uin, tok, where, RequestBartAction.BART_VIDEO, mime,
				ResourceBundle.getString("media_preparing"), nextSegment);
	}

	private void close()
	{
		if (current == this) current = null;
		synchronized (this) { notifyAll(); }   // разбудить писателя, чтобы вышел
		stop();                            // free the player and the temp file first
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
