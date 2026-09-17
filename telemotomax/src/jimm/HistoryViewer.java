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
 */
public class HistoryViewer implements CommandListener, VirtualListCommands, JimmScreen,
		RequestBartAction.Listener
{
	private static HistoryViewer current;

	private final JimmScreen back;
	private final String uin;
	private final String name;
	/** Больше строк на экране держать незачем — это память телефона. */
	public static final int MAX_LINES = 200;

	static final Command cmdMore = new Command(ResourceBundle.getString("history_more"),
			Command.ITEM, 3);

	private TextList list;
	private Vector texts = new Vector();     // per message: String
	private Vector tokens = new Vector();    // per message: byte[16] or null
	private Vector kinds = new Vector();     // per message: Integer kind (1 photo, 2 video)
	private int shown;                       // сколько сообщений уже загружено
	private boolean more;                    // осталось ли что подгружать
	private boolean paged;                   // мост ответил с пометкой «есть ещё»
	private boolean exhausted;               // последняя пачка пришла пустой
	private boolean loading;

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
		if (loading) return;
		loading = true;
		if (texts.size() == 0) addLine(ResourceBundle.getString("history_loading"), null);
		else list.setCaption(ResourceBundle.getString("history_loading"));
		list.repaint();
		byte[] token = new byte[16];
		int count = Options.getInt(Options.OPTION_HISTORY_COUNT);
		if (count < 1) count = 10;
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
				if ((flag & 1) != 0 && 2 + len + 1 + 16 <= data.length)
				{
					photo = new byte[16];
					System.arraycopy(data, 2 + len + 1, photo, 0, 16);
				}
				ChatHistory.addHistoryLine(uin, text, photo, (flag & 2) != 0 ? 2 : 1);
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

	private void addLine(String text, byte[] token)
	{
		addLine(text, token, 1);
	}

	private void addLine(String text, byte[] token, int kind)
	{
		texts.addElement(text);
		tokens.addElement(token);
		kinds.addElement(new Integer(kind));
	}

	// Список перерисовывается целиком: подгруженная пачка встаёт перед уже
	// показанным, а TextList умеет только дописывать в конец.
	private void fill()
	{
		list.clear();
		for (int i = 0; i < texts.size(); i++)
		{
			String line = (String) texts.elementAt(i);
			boolean mine = ((Integer) kinds.elementAt(i)).intValue() >= 8;
			// Строка от моста — «[дд.мм чч:мм] Кто: текст». Заголовок с
			// именем и временем красим, как в чате (свои одним цветом,
			// чужие другим), а сам текст выводим тем же способом, что и
			// сообщения в переписке: обычным цветом и со смайлами.
			int cut = -1;
			int close = line.indexOf("] ");
			if (close > 0) cut = line.indexOf(": ", close);
			if (cut > 0 && cut + 2 <= line.length())
			{
				list.addBigText(line.substring(0, cut + 1),
						ChatTextList.getInOutColor(!mine), Font.STYLE_BOLD, i);
				// Перевод строки обязателен: без него текст дописывается в
				// строку заголовка, и то, что в неё уже не влезает, уходит
				// за край экрана — от «текст для проверки» оставалось
				// «проверки». В чате перенос делается ровно так же.
				list.doCRLF(i);
				JimmUI.addMessageText(list, line.substring(cut + 2),
						list.getTextColor(), i);
			}
			else
			{
				JimmUI.addMessageText(list, line, list.getTextColor(), i);
			}
		}
	}

	// Called from the comm thread with the history records or null. Parsing
	// and laying out the messages runs on a thread of its own, so the comm
	// thread that called us is not held up while the list is built.
	public void onBart(final byte[] data)
	{
		if (current != this) return;
		new Thread() {
			public void run() { render(data); }
		}.start();
	}

	private void render(byte[] data)
	{
		if (current != this) return;
		boolean first = shown == 0;
		boolean failed = data == null;
		Vector newTexts = new Vector();
		Vector newTokens = new Vector();
		Vector newKinds = new Vector();
		if (data != null)
		{
			// Мосты разных возрастов отвечают по-разному: со страницами
			// впереди идёт примета 0xFF и байт «есть ещё», с мостом
			// постарше — сразу записи, а был и промежуточный, с одним
			// байтом без приметы. Перепутать их нельзя: со сдвигом на
			// байт разбор даёт пустые строки вместо текста. Поэтому
			// пробуем все три начала и берём то, при котором записи легли
			// ровно до конца ответа.
			// Порядок проверки — от самого вероятного: с приметой впереди
			// это наверняка ответ со страницами.
			int[] order = (data.length > 0 && Util.getByte(data, 0) == 0xFF)
					? new int[] { 2, 1, 0 } : new int[] { 0, 1, 2 };
			int start = 0;
			for (int i = 0; i < order.length; i++)
			{
				if (order[i] > data.length) continue;
				if (fits(data, order[i]))
				{
					start = order[i];
					break;
				}
			}
			paged = start > 0;
			more = (start == 2) ? Util.getByte(data, 1) != 0
					: ((start == 1) ? Util.getByte(data, 0) != 0 : false);
			int marker = start;
			while (marker + 3 <= data.length)
			{
				int len = Util.getWord(data, marker);
				marker += 2;
				if (marker + len + 1 > data.length) break;
				String text = Util.byteArrayToString(data, marker, len, true);
				marker += len;
				int flag = Util.getByte(data, marker);
				marker += 1;
				byte[] token = null;
				if ((flag & 1) != 0 && marker + 16 <= data.length)
				{
					token = new byte[16];
					System.arraycopy(data, marker, token, 0, 16);
					marker += 16;
				}
				newTexts.addElement(text);
				newTokens.addElement(token);
				int kind = (flag & 4) != 0 ? 3 : ((flag & 2) != 0 ? 2 : 1);
				if ((flag & 8) != 0) kind += 8;
				newKinds.addElement(new Integer(kind));
			}
		}
		data = null;

		list.lock();
		if (first)
		{
			texts.removeAllElements();
			tokens.removeAllElements();
			kinds.removeAllElements();
		}
		// Подгруженное старее уже показанного, поэтому встаёт перед ним.
		for (int i = newTexts.size() - 1; i >= 0; i--)
		{
			texts.insertElementAt(newTexts.elementAt(i), 0);
			tokens.insertElementAt(newTokens.elementAt(i), 0);
			kinds.insertElementAt(newKinds.elementAt(i), 0);
		}
		shown += newTexts.size();
		if (newTexts.size() == 0) exhausted = true;
		if (texts.size() == 0)
		{
			texts.addElement(ResourceBundle.getString(
					failed ? "history_failed" : "history_empty"));
			tokens.addElement(null);
			kinds.addElement(new Integer(1));
		}
		else if (failed)
		{
			list.setCaption(ResourceBundle.getString("history_failed"));
		}
		fill();
		list.unlock();
		list.setCaption(name + (shown > 0 ? " (" + shown + ")" : ""));
		// Первую пачку смотрят с конца (свежее), подгруженную — с начала,
		// с того места, где она кончается и начинается уже прочитанное.
		list.setTopItem(first ? list.getSize() : 0);
		loading = false;
		checkMore();
		checkPhoto();
		list.repaint();
	}

	// Ложатся ли записи ровно до конца ответа, если начать с этого байта.
	// Заодно отбрасываем начала, дающие пустые или нелепо длинные строки:
	// именно так выглядит разбор со сдвигом.
	private static boolean fits(byte[] data, int start)
	{
		int marker = start;
		int records = 0;
		while (marker + 3 <= data.length)
		{
			int len = Util.getWord(data, marker);
			marker += 2;
			if (len == 0 || len > 4000) return false;
			if (marker + len + 1 > data.length) return false;
			marker += len;
			int flag = Util.getByte(data, marker);
			marker += 1;
			if ((flag & 0xF0) != 0) return false;        // старшие биты не наши
			if ((flag & 1) != 0)
			{
				if (marker + 16 > data.length) return false;
				marker += 16;
			}
			records++;
		}
		return records > 0 && marker == data.length;
	}

	// «Ещё» показываем, пока есть что просить. Мост с пометкой сам говорит,
	// осталось ли; мост постарше её не шлёт — тогда предлагаем, пока
	// очередная пачка не придёт пустой.
	private void checkMore()
	{
		list.removeCommandEx(cmdMore);
		boolean worth = paged ? more : !exhausted;
		if (worth && texts.size() < MAX_LINES)
			list.addCommandEx(cmdMore, VirtualList.MENU_TYPE_RIGHT);
	}

	private byte[] currentToken()
	{
		int index = list.getCurrTextIndex();
		if (index < 0 || index >= tokens.size()) return null;
		return (byte[]) tokens.elementAt(index);
	}

	private int currentKind()
	{
		int index = list.getCurrTextIndex();
		if (index < 0 || index >= kinds.size()) return 0;
		return ((Integer) kinds.elementAt(index)).intValue() & 7;   // без пометки «моё»
	}

	private void checkPhoto()
	{
		list.removeCommandEx(ChatTextList.cmdShowPhoto);
		list.removeCommandEx(ChatTextList.cmdPlayVideo);
		list.removeCommandEx(ChatTextList.cmdPlayVoice);
		if (currentToken() != null)
		{
			int kind = currentKind();
			// У голосового картинки нет — только «Прослушать», как в чате.
			if (kind != 3) list.addCommandEx(ChatTextList.cmdShowPhoto, VirtualList.MENU_TYPE_RIGHT);
			if (kind == 2) list.addCommandEx(ChatTextList.cmdPlayVideo, VirtualList.MENU_TYPE_RIGHT);
			if (kind == 3) list.addCommandEx(ChatTextList.cmdPlayVoice, VirtualList.MENU_TYPE_RIGHT);
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
		byte[] token = currentToken();
		if (token == null) return;
		int kind = currentKind();
		if (kind == 3) MediaPlayer.showVoice(uin, token, this);
		else PhotoViewer.show(uin, token, this);
	}

	public void vlKeyPress(VirtualList sender, int keyCode, int type) {}

	public void commandAction(Command c, Displayable d)
	{
		if (c == ChatTextList.cmdShowPhoto)
		{
			byte[] token = currentToken();
			if (token != null) PhotoViewer.show(uin, token, this);
			return;
		}
		if (c == ChatTextList.cmdPlayVideo)
		{
			byte[] token = currentToken();
			if (token != null) MediaPlayer.show(uin, token, this);
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
		if (current == this) current = null;
		list = null;                       // the text goes with the screen
		texts = null;
		tokens = null;
		kinds = null;
		if (back != null) back.activate();
		else JimmUI.backToLastScreen();
	}

	public void activate()
	{
		if (list != null) list.activate(Jimm.display);
	}

	public boolean isScreenActive()
	{
		return list != null && list.isActive();
	}
}
