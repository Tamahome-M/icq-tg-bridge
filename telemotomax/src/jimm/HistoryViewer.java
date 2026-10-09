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

import java.util.Vector;

import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.Alert;
import javax.microedition.lcdui.AlertType;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Font;

import DrawControls.TextList;
import DrawControls.VirtualList;
import DrawControls.VirtualListCommands;
import jimm.comm.Icq;
import jimm.comm.RequestBartAction;
import jimm.comm.Util;
import jimm.util.ResourceBundle;

/**
 * Chat history fetched from the bridge, on its own screen. Unlike "!last",
 * which pours the messages into the chat where they stay in memory, this
 * screen is thrown away on "Back" together with all its text.
 *
 * The bridge sends one record per message: text length (2 bytes), UTF-8
 * text, a flag byte and, if the flag is set, a 16-byte photo token — so a
 * message with a picture can be opened with "Show photo" right here.
 * Bit 0x10 of the flag (bridge 0.72+) adds a 4-byte UIN of the discussion
 * started under the message: "Discussion" opens its history on top.
 */
public class HistoryViewer implements CommandListener, VirtualListCommands, JimmScreen,
		RequestBartAction.ErrorListener, RequestBartAction.RangeListener
{
	private static volatile HistoryViewer current;

	private final JimmScreen back;
	private final String uin;
	private final String name;
	/** Больше строк на экране держать незачем — это память телефона. */
	public static final int MAX_LINES = 200;

	static final Command cmdMore = new Command(ResourceBundle.getString("history_more"),
			Command.ITEM, 3);
	static final Command cmdThread = new Command(ResourceBundle.getString("history_thread"),
			Command.ITEM, 4);

	private TextList list;
	private Vector videoUrls = new Vector(); // only the hidden browser URL, never the full text
	private Vector tokens = new Vector();    // per message: byte[16] or null
	private byte[] kinds = new byte[MAX_LINES]; // one byte per message, without boxed Integers
	private Vector refs = new Vector();
	private Vector threads = new Vector();   // per message: String UIN обсуждения или null
	private int shown;                       // сколько сообщений уже загружено
	private boolean more;                    // осталось ли что подгружать
	private boolean paged;                   // мост ответил с пометкой «есть ещё»
	private boolean exhausted;               // последняя пачка пришла пустой
	private volatile boolean loading;

	private HistoryViewer(JimmScreen back, String uin, String name)
	{
		this.back = back;
		this.uin = uin;
		this.name = name;
	}

	// Opens the screen and asks the bridge for the last N messages (Options).
	static public void show(String uin, String name, JimmScreen back)
	{
		HistoryViewer viewer = new HistoryViewer(back, uin, name);
		current = viewer;
		viewer.build();
		viewer.request();
	}

	// Просит у моста следующую пачку: сколько сообщений и сколько уже
	// показано. Пятый байт «хеша» говорит мосту, что клиент ждёт ответ с
	// пометкой «есть ещё» — старый мост её не приписывает.
	private void request()
	{
		if (loading || list == null || tokens.size() >= MAX_LINES) return;
		loading = true;
		if (shown == 0) showStatus(ResourceBundle.getString("history_loading"));
		else list.setCaption(ResourceBundle.getString("history_loading"));
		list.repaint();
		byte[] token = new byte[16];
		int count = Options.getInt(Options.OPTION_HISTORY_COUNT);
		if (count < 1) count = 10;
		count = Math.min(count, MAX_LINES - tokens.size());
		Util.putWord(token, 0, count);
		Util.putWord(token, 2, shown);
		Util.putByte(token, 4, 1);
		try
		{
			Icq.requestAction(new RequestBartAction(uin, RequestBartAction.BART_HISTORY, token, this));
		}
		catch (JimmException e)
		{
			onBart(null);
		}
	}

	// Last message of a chat that has none yet: asked from the bridge and
	// put into the chat itself, token and all.
	static public void preloadLast(final String uin, final ChatTextList chat)
	{
		byte[] token = new byte[16];
		Util.putWord(token, 0, 1);
		RequestBartAction.Listener into = new RequestBartAction.Listener() {
			public void onBart(byte[] data)
			{
				if (data == null || data.length < 3) return;
				int len = Util.getWord(data, 0);
				if (2 + len + 1 > data.length) return;
				String text = Util.byteArrayToString(data, 2, len, true);
				int flag = Util.getByte(data, 2 + len);
				byte[] photo = null;
				int marker = 2 + len + 1;
				if ((flag & 1) != 0 && marker + 16 <= data.length)
				{
					photo = new byte[16];
					System.arraycopy(data, marker, photo, 0, 16);
					marker += 16;
				}
				// Обсуждение под сообщением — его UIN за токеном (мост 0.74+).
				String thread = null;
				if ((flag & 0x10) != 0 && marker + 4 <= data.length)
				{
					thread = String.valueOf(Util.getDWord(data, marker));
					marker += 4;
				}
				byte[] ref = null;
				if ((flag & 0x20) != 0 && marker + 8 <= data.length)
				{
					ref = new byte[8];
					System.arraycopy(data, marker, ref, 0, 8);
				}
				// Вид вложения — как в полной истории: бит 2 — видео,
				// бит 4 — голосовое, иначе фото. Раньше голосовое здесь
				// считалось фото, и в чате была кнопка «Показать фото».
				int kind = ((flag & 6) == 6) ? 4 : ((flag & 4) != 0 ? 3 : ((flag & 2) != 0 ? 2 : 1));
				ChatHistory.addHistoryLine(uin, text, photo, kind, thread, ref);
			}
		};
		try
		{
			Icq.requestAction(new RequestBartAction(uin, RequestBartAction.BART_HISTORY, token, into));
		}
		catch (JimmException ignore) {}
	}

	private void build()
	{
		list = new TextList(null);
		JimmUI.setColorScheme(list, false, -1, true);
		list.setCaption(name);
		list.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR);
		// Правая софт-клавиша с меню: в него попадают «Ещё», «Показать фото»
		// и «Прослушать» — без неё они некуда было бы нажать.
		list.addCommandEx(JimmUI.cmdMenu, VirtualList.MENU_TYPE_RIGHT_BAR);
		list.setCommandListener(this);
		list.setVLCommands(this);
		list.activate(Jimm.display);
	}

	private void showStatus(String text)
	{
		list.clear();
		JimmUI.addMessageText(list, text, list.getTextColor(), -1);
	}

	// Format only the incoming page; existing TextLines are retained as-is.
	private static void appendLine(TextList page, String line, int kind, int index)
	{
		boolean mine = kind >= 8;
		// Строка от моста — «[дд.мм чч:мм] Кто: текст». Заголовок с
		// именем и временем красим, как в чате (свои одним цветом,
		// чужие другим), а сам текст выводим тем же способом, что и
		// сообщения в переписке: обычным цветом и со смайлами.
		int cut = -1;
		int close = line.indexOf("] ");
		int newline = line.indexOf('\n');
		// Ссылка видео может стоять перед строкой с датой/автором.
		// Заголовок ищем только в первой строке, иначе URL попадал
		// в красный текст заголовка и обходил скрытие адреса.
		if (close > 0 && (newline < 0 || close < newline))
		{
			cut = line.indexOf(": ", close);
			if (newline >= 0 && cut >= newline) cut = -1;
		}
		if (cut > 0 && cut + 2 <= line.length())
		{
			page.addBigText(line.substring(0, cut + 1),
				ChatTextList.getInOutColor(!mine), Font.STYLE_BOLD, index);
			// Перевод строки обязателен: без него текст дописывается в
			// строку заголовка, и то, что в неё уже не влезает, уходит
			// за край экрана — от «текст для проверки» оставалось
			// «проверки». В чате перенос делается ровно так же.
			page.doCRLF(index);
			JimmUI.addMessageText(page, line.substring(cut + 2),
				page.getTextColor(), index);
		}
		else
		{
			JimmUI.addMessageText(page, line, page.getTextColor(), index);
		}
	}

	// Called from the comm thread with the history records or null. Parsing
	// and laying out the messages runs on a thread of its own, so the comm
	// thread that called us is not held up while the list is built.
	public void onBart(byte[] data)
	{
		onBart(data, 0, data == null ? 0 : data.length);
	}

	public void onBart(byte[] data, int offset, int length)
	{
		receive(data, offset, length, null);
	}

	public void onBartError(String message)
	{
		receive(null, 0, 0, message);
	}

	// Drop the worker's raw-buffer reference before formatting is committed.
	// A captured final byte[] in an anonymous thread would retain it longer.
	private final class PageJob extends Thread
	{
		byte[] data;
		final int offset, length;
		final String error;
		PageJob(byte[] data, int offset, int length, String error)
		{ this.data = data; this.offset = offset; this.length = length; this.error = error; }
		public void run()
		{
			try { render(this); }
			catch (Throwable t) { data = null; fail(t, length); }
		}
	}

	private void receive(byte[] data, int offset, int length, String error)
	{
		if (current != this || list == null) { loading = false; return; }
		new PageJob(data, offset, length, error).start();
	}

	private void fail(Throwable t, int size)
	{
		loading = false;
		String type = t.getClass().getName();
		int dot = type.lastIndexOf('.');
		if (dot >= 0) type = type.substring(dot + 1);
		String reason = ResourceBundle.getString("history_failed") + " " + type;
		if (size > 0) reason += " (" + size + " " + ResourceBundle.getString("bytes") + ")";
		synchronized (this)
		{
			if (current != this || list == null) return;
			showFailure(reason);
		}
	}

	private void showFailure(String error)
	{
		loading = false;
		if (shown == 0) showStatus(ResourceBundle.getString("history_failed")
				+ (error == null ? "" : ": " + error));
		list.setCaption(name + (shown > 0 ? " (" + shown + ")" : ""));
		checkMore();
		checkPhoto();
		list.repaint();
		if (error != null && list.isActive())
		{
			Alert alert = new Alert(ResourceBundle.getString("history_failed"), error, null, AlertType.ERROR);
			alert.setTimeout(Alert.FOREVER);
			Jimm.display.setCurrent(alert, Jimm.display.getCurrent());
		}
	}

	private void render(byte[] data)
	{
		render(new PageJob(data, 0, data == null ? 0 : data.length, null));
	}

	private void render(PageJob job)
	{
		byte[] data = job.data;
		job.data = null;
		TextList target = list;
		if (current != this || target == null) { loading = false; return; }
		if (data == null)
		{
			synchronized (this) { if (current == this && list == target) showFailure(job.error); }
			return;
		}
		int end = job.offset + job.length;
		if (job.offset < 0 || job.length < 0 || job.offset > data.length - job.length)
			throw new IllegalArgumentException("history range");
		int start = historyStart(data, job.offset, end);
		int received = recordCount(data, start, end);
		int count = Math.min(received, MAX_LINES - tokens.size());
		boolean pageMore = start > job.offset
				&& Util.getByte(data, start - 1) != 0;
		TextList page = new TextList(null);
		JimmUI.setColorScheme(page, false, -1, true);
		page.lock();
		Vector newTokens = new Vector(count), newThreads = new Vector(count);
		Vector newRefs = new Vector(count), newUrls = new Vector(count);
		byte[] newKinds = new byte[count];
		int marker = start, skipped = received - count, added = 0;
		while (marker < end)
		{
			if (current != this || list != target) { loading = false; return; }
			int len = Util.getWord(data, marker), textAt = marker + 2;
			marker = textAt + len;
			int flag = Util.getByte(data, marker++);
			int tokenAt = marker;
			if ((flag & 1) != 0) marker += 16;
			int threadAt = marker;
			if ((flag & 0x10) != 0) marker += 4;
			int refAt = marker;
			if ((flag & 0x20) != 0) marker += 8;
			// If an old bridge ignores the requested limit, retain the newest
			// records of that page, and still stay within 200 messages total.
			if (skipped-- > 0) continue;
			String text = Util.byteArrayToString(data, textAt, len, true);
			byte[] token = null, ref = null;
			if ((flag & 1) != 0) { token = new byte[16]; System.arraycopy(data, tokenAt, token, 0, 16); }
			if ((flag & 0x20) != 0) { ref = new byte[8]; System.arraycopy(data, refAt, ref, 0, 8); }
			newTokens.addElement(token);
			newRefs.addElement(ref);
			newThreads.addElement((flag & 0x10) == 0 ? null : String.valueOf(Util.getDWord(data, threadAt)));
			newUrls.addElement(VideoLink.url(text));
			int kind = ((flag & 6) == 6) ? 4 : ((flag & 4) != 0 ? 3 : ((flag & 2) != 0 ? 2 : 1));
			if ((flag & 8) != 0) kind += 8;
			newKinds[added] = (byte) kind;
			appendLine(page, text, kind, added++);
		}
		data = null;
		synchronized (this)
		{
			if (current != this || list != target) { loading = false; return; }
			boolean first = shown == 0;
			target.lock();
			try
			{
				int capacity = tokens.size() + count;
				tokens.ensureCapacity(capacity);
				threads.ensureCapacity(capacity);
				refs.ensureCapacity(capacity);
				videoUrls.ensureCapacity(capacity);
				if (first) target.clear();
				if (count > 0)
				{
					// Allocate the joining line-array before changing metadata.
					target.prependFrom(page, count);
					System.arraycopy(kinds, 0, kinds, count, tokens.size());
					System.arraycopy(newKinds, 0, kinds, 0, count);
					for (int i = count - 1; i >= 0; i--)
					{
						tokens.insertElementAt(newTokens.elementAt(i), 0);
						threads.insertElementAt(newThreads.elementAt(i), 0);
						refs.insertElementAt(newRefs.elementAt(i), 0);
						videoUrls.insertElementAt(newUrls.elementAt(i), 0);
					}
					shown += count;
				}
				else if (first) showStatus(ResourceBundle.getString("history_empty"));
				paged = start > job.offset;
				more = pageMore && received > 0;
				if (received == 0) exhausted = true;
				target.setCaption(name + (shown > 0 ? " (" + shown + ")" : ""));
				// Empty older replies leave the current selection and viewport intact.
				if (count > 0) target.setTopItem(first ? target.getSize() : 0);
				loading = false;
				checkMore();
				checkPhoto();
			}
			finally { target.unlock(); }
		}
	}

	private static int historyStart(byte[] data, int offset, int end)
	{
		if (offset == end) return offset;
		boolean marked = Util.getByte(data, offset) == 0xFF;
		if (marked && end - offset == 2) return offset + 2;
		if (end - offset == 1 && Util.getByte(data, offset) <= 1) return end;
		for (int i = 0; i < 3; i++)
		{
			int start = offset + (marked ? (i == 0 ? 2 : i == 1 ? 1 : 0) : i);
			if (start <= end && recordCount(data, start, end) > 0) return start;
		}
		throw new IllegalArgumentException("history records");
	}

	private static boolean fits(byte[] data, int start)
	{
		return recordCount(data, start, data.length) > 0;
	}

	// Validate the entire record range before any displayed history is changed.
	private static int recordCount(byte[] data, int start, int end)
	{
		int marker = start, records = 0;
		while (marker + 3 <= end)
		{
			int len = Util.getWord(data, marker);
			marker += 2;
			if (len == 0 || len > 4000 || marker + len + 1 > end) return -1;
			marker += len;
			int flag = Util.getByte(data, marker++);
			if ((flag & 0xC0) != 0) return -1;
			if ((flag & 1) != 0) marker += 16;
			if ((flag & 0x10) != 0) marker += 4;
			if ((flag & 0x20) != 0) marker += 8;
			if (marker > end) return -1;
			records++;
		}
		return marker == end ? records : -1;
	}

	// «Ещё» показываем, пока есть что просить. Мост с пометкой сам говорит,
	// осталось ли; мост постарше её не шлёт — тогда предлагаем, пока
	// очередная пачка не придёт пустой.
	private void checkMore()
	{
		list.removeCommandEx(cmdMore);
		boolean worth = paged ? more : !exhausted;
		if (worth && tokens.size() < MAX_LINES)
			list.addCommandEx(cmdMore, VirtualList.MENU_TYPE_RIGHT);
	}

	private byte[] currentToken()
	{
		int index = list.getCurrTextIndex();
		if (index < 0 || index >= tokens.size()) return null;
		return (byte[]) tokens.elementAt(index);
	}

	private String currentThread()
	{
		int index = list.getCurrTextIndex();
		if (index < 0 || index >= threads.size()) return null;
		return (String) threads.elementAt(index);
	}

	private String currentVideoUrl()
	{
		int index = list.getCurrTextIndex();
		return index < 0 || index >= videoUrls.size() ? null : (String) videoUrls.elementAt(index);
	}

	private int currentKind()
	{
		int index = list.getCurrTextIndex();
		if (index < 0 || index >= tokens.size()) return 0;
		return kinds[index] & 7;   // без пометки «моё»
	}

	private byte[] currentRef()
	{
		int index = list.getCurrTextIndex();
		return index < 0 || index >= refs.size() ? null : (byte[])refs.elementAt(index);
	}
	public static void refreshQuoteMenu()
	{
		if (current != null) NativeQuote.updateMenu(current.list, current.currentRef());
	}

	private void checkPhoto()
	{
		NativeQuote.updateMenu(list, currentRef());
		list.removeCommandEx(ChatTextList.cmdShowPhoto);
		list.removeCommandEx(ChatTextList.cmdPlayVideo);
		list.removeCommandEx(ChatTextList.cmdPlayVoice);
		list.removeCommandEx(cmdThread);
		if (currentThread() != null) list.addCommandEx(cmdThread, VirtualList.MENU_TYPE_RIGHT);
		if (currentVideoUrl() != null) list.addCommandEx(ChatTextList.cmdPlayVideo, VirtualList.MENU_TYPE_RIGHT);
		if (currentToken() != null)
		{
			int kind = currentKind();
			// У голосового и файла картинки нет — только своё действие.
			if (kind == 1 || kind == 2) list.addCommandEx(ChatTextList.cmdShowPhoto, VirtualList.MENU_TYPE_RIGHT);
			if (kind == 2 && currentVideoUrl() == null) list.addCommandEx(ChatTextList.cmdPlayVideo, VirtualList.MENU_TYPE_RIGHT);
			if (kind == 3) list.addCommandEx(ChatTextList.cmdPlayVoice, VirtualList.MENU_TYPE_RIGHT);
//#sijapp cond.if modules_CAMERA="true"#
			if (kind == 4) list.addCommandEx(ChatTextList.cmdGetFile, VirtualList.MENU_TYPE_RIGHT);
//#sijapp cond.end#
		}
	}

	public void vlCursorMoved(VirtualList sender)
	{
		checkPhoto();
	}

	// Выбор записи открывает то, что к ней приложено: снимок, ролик или
	// голосовое.
	public void vlItemClicked(VirtualList sender)
	{
		String videoUrl = currentVideoUrl();
		byte[] token = currentToken();
		if (videoUrl != null || (token != null && currentKind() == 2))
		{
			VideoMenu.show(uin, token, videoUrl, this);
			return;
		}
		if (token == null)
		{
			// Без вложения выбор записи открывает обсуждение под ней, если есть.
			String thread = currentThread();
			if (thread != null) HistoryViewer.show(thread, name, this);
			return;
		}
		int kind = currentKind();
//#sijapp cond.if modules_CAMERA="true"#
		if (kind == 4) { FileDownloader.show(uin, token, this); return; }
//#sijapp cond.end#
		if (kind == 3) MediaPlayer.showVoice(uin, token, this);
		else PhotoViewer.show(uin, token, this);
	}

	public void vlKeyPress(VirtualList sender, int keyCode, int type) {}

	public void commandAction(Command c, Displayable d)
	{
		if (c == NativeQuote.cmdSelect) { NativeQuote.select(uin, currentRef()); return; }
		if (c == NativeQuote.cmdPaste) { NativeQuote.paste(uin); return; }
//#sijapp cond.if modules_CAMERA="true"#
		if (c == ChatTextList.cmdGetFile)
		{
			byte[] token = currentToken();
			if (token != null) FileDownloader.show(uin, token, this);
			return;
		}
//#sijapp cond.end#
		if (c == ChatTextList.cmdShowPhoto)
		{
			byte[] token = currentToken();
			if (token != null) PhotoViewer.show(uin, token, this);
			return;
		}
		if (c == ChatTextList.cmdPlayVideo)
		{
			String videoUrl = currentVideoUrl();
			byte[] token = currentToken();
			VideoMenu.show(uin, token, videoUrl, this);
			return;
		}
		if (c == ChatTextList.cmdPlayVoice)
		{
			byte[] token = currentToken();
			if (token != null) MediaPlayer.showVoice(uin, token, this);
			return;
		}
		if (c == cmdMore)
		{
			request();
			return;
		}
		if (c == cmdThread)
		{
			String thread = currentThread();
			if (thread != null) HistoryViewer.show(thread, name, this);
			return;
		}
		synchronized (this)
		{
			if (current == this) current = null;
			loading = false;
			if (list != null) list.clear();
			list = null;
			videoUrls = null;
			tokens = null;
			kinds = null;
			threads = null;
			refs = null;
		}
		if (back != null) back.activate();
		else JimmUI.backToLastScreen();
	}

	public void activate()
	{
		if (list != null)
		{
			current = this;                // вернулись из вложенной истории
			if (!loading) list.setCaption(name + (shown > 0 ? " (" + shown + ")" : ""));
			list.activate(Jimm.display);
		}
	}

	public boolean isScreenActive()
	{
		return list != null && list.isActive();
	}
}
