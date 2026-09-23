/*******************************************************************************
 TeleMotoMax - Jimm fork for icq-tg-bridge
 Copyright (C) 2003-08  Jimm Project (RequestBuddyIconAction this is based on)

 This program is free software; you can redistribute it and/or
 modify it under the terms of the GNU General Public License
 as published by the Free Software Foundation; either version 2
 of the License, or (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.
 *******************************************************************************/

package jimm.comm;

import java.util.Date;
import jimm.DebugLog;
import jimm.JimmException;
import jimm.comm.connections.SOCKETConnection;

/**
 * Fetches something from the bridge over the BART service (family 0x10,
 * the second connection the buddy icons use): a picture attached to a
 * message (type 0x0080, "hash" = the bridge's token) or a chat's history
 * as text (type 0x0081, "hash" = the number of messages). The reply is
 * parsed exactly like the icon reply, so the bridge answers with the very
 * same layout; what the bytes mean is up to the listener.
 */
public class RequestBartAction extends Action implements Icq.BartConnectListener
{
	public static final int BART_PHOTO = 0x0080;
	public static final int BART_HISTORY = 0x0081;
	public static final int BART_VIDEO = 0x0082;
	public static final int BART_VOICE = 0x0083;
	public static final int BART_CHATS = 0x0084;     // весь список чатов моста
	public static final int BART_OPEN = 0x0085;      // вернуть чат на телефон
	public static final int BART_FILE = 0x0086;      // документ по токену, в первой части — имя

	/** Who gets the bytes the service replied with (null on failure). */
	public interface Listener
	{
		void onBart(byte[] data);
	}

	/** A listener that also wants to know how many parts have arrived. */
	public interface ProgressListener extends Listener
	{
		void onBartProgress(int part, int total);
	}

	/**
	 * Слушатель, который забирает части сразу, по одной: ролик или
	 * голосовое так уходят прямо во временный файл, и в куче лежит одна
	 * часть, а не весь клип целиком (до 240 КБ — почти всё, что есть у V3).
	 * Вернул false — часть не принята, дальше собираем в памяти как обычно.
	 * После последней части приходит onBart(null-или-пусто) через onBartDone.
	 */
	public interface PartSink extends ProgressListener
	{
		boolean onBartPart(byte[] buf, int off, int len, int part, int total);
		void onBartDone(boolean ok);
	}

	public static final int STATE_ERROR = -1;
	public static final int STATE_INIT_DONE = 0;
	public static final int STATE_CONNECTION_ESTB = 1;
	public static final int STATE_CONNECTING = 6;         // Connector.open в своём потоке
	public static final int STATE_CLI_COOKIE_SENT = 2;
	public static final int STATE_CLI_REQ_SENT = 4;
	public static final int STATE_ACTION_DONE = 5;
	public static final int STATE_MAX = 5;

	public int TIMEOUT = 60 * 1000;
	public static final int VIDEO_TIMEOUT = 240 * 1000;   // the clip is transcoded first

	private String srvHost;
	private String srvPort;
	private String uin;
	private int bartType;
	private byte[] token;
	private byte[] clicookie;
	private Listener listener;
	private int state;
	private Date lastActivity = new Date();
	private boolean active;
	// Replies that come in parts (the clip): collected here until the last one.
	// The buffer is allocated once, by the size of the first part, so the
	// phone does not hold the clip twice while the parts are being joined.
	private byte[] parts;
	private int filled;
	private boolean notified;         // слушателю уже сказали, чем кончилось
	private boolean streaming;        // части уходят слушателю по одной
	private int extraFlags;           // свои биты во флагах приметы (0x40 — ссылку на файл)

	public void setFlags(int flags)
	{
		extraFlags = flags;
	}

	public RequestBartAction(String uin, int bartType, byte[] token, Listener listener)
	{
		super(false, true);
		this.uin = uin;
		this.bartType = bartType;
		this.token = token;
		this.listener = listener;
		// Ролик и голосовое мост сначала перекодирует, потом отдаёт частями —
		// до первой части может пройти больше минуты на GPRS.
		if (bartType == BART_VIDEO || bartType == BART_VOICE || bartType == BART_FILE) TIMEOUT = VIDEO_TIMEOUT;
	}

	protected void init() throws JimmException
	{
		if (Icq.bartUsable())
		{
			this.sendRequest();
			this.lastActivity = new Date();
			return;
		}
		try
		{
			byte[] rbuf = new byte[2];
			Util.putWord(rbuf, 0, 0x0010);
			Packet reqp = new SnacPacket(SnacPacket.CLI_SERVICEREQUEST_FAMILY, SnacPacket.CLI_SERVICEREQUEST_COMMAND, 0x00010004, new byte[0], rbuf);
			Icq.c.sendPacket(reqp);
			this.state = STATE_INIT_DONE;
		}
		catch (JimmException je)
		{
			this.state = STATE_ERROR;
			throw (new JimmException(100, 50, true));
		}
		this.lastActivity = new Date();
	}

	private void sendRequest() throws JimmException
	{
		byte[] uinRaw = Util.stringToByteArray(this.uin);
		int uinLength = uinRaw.length;
		byte[] buf = new byte[1 + uinLength + 1 + 2 + 1 + 1 + 16];
		Util.putByte(buf, 0, uinLength);
		System.arraycopy(uinRaw, 0, buf, 1, uinLength);
		Util.putByte(buf, 1 + uinLength, 0x01);
		Util.putWord(buf, 2 + uinLength, bartType);
		// Флаги приметы: у Jimm всегда 0x01. Для ролика TeleMotoMax добавляет
		// выбор поворота: 0x20 — всегда боком, 0x10 — никогда, ничего — авто
		// (мост сам смотрит на исходник). Старый мост лишние биты не читает.
		int flags = 0x01 | extraFlags;
		// «Боком»: ролик — по своей настройке, снимок — по своей; флаги те же.
		if (bartType == BART_VIDEO || bartType == BART_PHOTO)
		{
			int mode = jimm.Options.getInt(bartType == BART_VIDEO
					? jimm.Options.OPTION_VIDEO_ROTATE : jimm.Options.OPTION_PHOTO_ROTATE);
			if (mode == 1) flags |= 0x20;
			else if (mode == 2) flags |= 0x10;
		}
		Util.putByte(buf, 4 + uinLength, flags);
		Util.putByte(buf, 5 + uinLength, 0x10);
		System.arraycopy(token, 0, buf, 6 + uinLength, 16);
		SnacPacket request = new SnacPacket(0x0010, 0x0006, 0x0006, new byte[0], buf);
		try
		{
			Icq.bartC.sendPacket(request);
			Icq.noteBartUse();
		}
		catch (JimmException je)
		{
			this.state = STATE_ERROR;
			Icq.disconnectBart(true);
			throw (new JimmException(je.getErrCode(), 53, true));
		}
		this.state = STATE_CLI_REQ_SENT;
	}

	protected boolean forward(Packet packet) throws JimmException
	{
		this.active = true;
		try
		{
			boolean consumed = false;
			switch (this.state)
			{
			case STATE_INIT_DONE:
				if (packet instanceof SnacPacket)
				{
					SnacPacket snacPacket = (SnacPacket) packet;
					if ((snacPacket.getFamily() == SnacPacket.SRV_REDIRECT_FAMILY)
							&& (snacPacket.getCommand() == SnacPacket.SRV_REDIRECT_COMMAND))
					{
						byte[] buf = snacPacket.getDataRef();   // только читаем
						int marker = 0;
						for (int i = 0; i < 3; i++)
						{
							int tlvType = Util.getWord(buf, marker);
							byte[] tlvData = Util.getTlv(buf, marker);
							switch (tlvType)
							{
							case 0x0005:
								this.srvHost = Util.byteArrayToString(tlvData);
								this.srvPort = "5190";
								break;
							case 0x0006:
								this.clicookie = tlvData;
								break;
							}
							marker += 2 + 2 + tlvData.length;
						}
					}
					if (this.clicookie == null || this.clicookie.length == 0)
					{
						this.state = STATE_ERROR;
						throw (new JimmException(117, 0, false));
					}
					// Соединение открывается в своём потоке — поток связи
					// не ждёт; ответ придёт в onBartConnected/Failed.
					this.state = STATE_CONNECTING;
					Icq.connectBart(this.srvHost + ":" + this.srvPort, this);
					consumed = true;
				}
				break;

			case STATE_CONNECTION_ESTB:
				if (packet instanceof ConnectPacket)
				{
					ConnectPacket connectPacket = (ConnectPacket) packet;
					if (connectPacket.getType() == ConnectPacket.SRV_CLI_HELLO)
					{
						ConnectPacket reply = new ConnectPacket(this.clicookie);
						Icq.bartC.sendPacket(reply);
					}
					this.state = STATE_CLI_COOKIE_SENT;
					consumed = true;
				}
				break;

			case STATE_CLI_COOKIE_SENT:
				if (packet instanceof SnacPacket)
				{
					SnacPacket reply = new SnacPacket(SnacPacket.CLI_READY_FAMILY, SnacPacket.CLI_READY_COMMAND, 0x00000000, new byte[0], ConnectAction.CLI_READY_DATA);
					Icq.bartC.sendPacket(reply);
					this.sendRequest();
					this.state = STATE_CLI_REQ_SENT;
					consumed = true;
				}
				break;

			case STATE_CLI_REQ_SENT:
				if (packet instanceof SnacPacket)
				{
					SnacPacket snacPacket = (SnacPacket) packet;
					if ((snacPacket.getFamily() == SnacPacket.SRV_REPLYAVATAR_FAMILY)
							&& (snacPacket.getCommand() == SnacPacket.SRV_REPLYAVATAR_COMMAND))
					{
						byte[] buf = snacPacket.getDataRef();   // только читаем
						int marker = 0;
						int uinLength = Util.getByte(buf, marker);
						marker += 1 + uinLength;
						// Ответ службы адресован примете: типу и «хешу» —
						// у нас это токен. Пока идёт одна загрузка, может
						// начаться другая (история и снимок, например), и
						// без этой проверки первое же действие в очереди
						// съедало бы чужой ответ, а его хозяин ждал бы
						// вечно. Чужое не берём — пусть достанется своему.
						Icq.noteBartUse();
						int replyType = Util.getWord(buf, marker);
						int hashLen = Util.getByte(buf, marker + 3);
						if (replyType != this.bartType
								|| hashLen != 16
								|| !Util.byteArrayEquals(buf, marker + 4, this.token, 0, 16))
						{
							this.active = false;
							return false;
						}
						// Flags of the two item blocks carry "part N of M" for
						// replies that do not fit one packet; 1 of 1 otherwise.
						int part = Util.getByte(buf, marker + 2);
						int total = Util.getByte(buf, marker + 2 + 1 + 1 + 16 + 1 + 2);
						marker += 2 + 1 + 1 + 16 + 1 + 2 + 1 + 1 + 16;
						int dataLength = Util.getWord(buf, marker);
						marker += 2;
						if (total > 1 && listener instanceof PartSink
								&& (streaming || parts == null)
								&& ((PartSink) listener).onBartPart(buf, marker, dataLength, part, total))
						{
							streaming = true;
							buf = null;
							this.lastActivity = new Date();
							if (part < total)
							{
								this.active = false;
								return true;           // wait for the rest
							}
							notified = true;
							((PartSink) listener).onBartDone(true);
						}
						else if (total > 1)
						{
							if (parts == null)
							{
								// Части, кроме последней, одного размера —
								// значит по первой известен весь объём.
								parts = new byte[dataLength * total];
								filled = 0;
							}
							if (filled + dataLength > parts.length)
							{
								byte[] bigger = new byte[filled + dataLength];
								System.arraycopy(parts, 0, bigger, 0, filled);
								parts = bigger;
							}
							System.arraycopy(buf, marker, parts, filled, dataLength);
							filled += dataLength;
							buf = null;
							if (listener instanceof ProgressListener)
								((ProgressListener) listener).onBartProgress(part, total);
							if (part < total)
							{
								this.lastActivity = new Date();
								this.active = false;
								return true;           // wait for the rest
							}
							byte[] all = parts;
							if (filled != all.length)
							{
								// Последняя часть короче — отдаём ровно то,
								// что пришло.
								all = new byte[filled];
								System.arraycopy(parts, 0, all, 0, filled);
							}
							parts = null;
							notified = true;
							listener.onBart(all);
						}
						else
						{
							byte[] data = new byte[dataLength];
							System.arraycopy(buf, marker, data, 0, dataLength);
							buf = null;
							notified = true;
							listener.onBart(data);
						}
						this.state = STATE_ACTION_DONE;
						consumed = true;
					}
					else if ((snacPacket.getFamily() == SnacPacket.SRV_REPLYAVATAR_FAMILY)
							&& (snacPacket.getCommand() == 0x0001))
					{
						// Error from the service: the bridge has nothing to give.
						listener.onBart(null);
						this.state = STATE_ACTION_DONE;
						consumed = true;
					}
				}
				break;
			}
			if (consumed) this.lastActivity = new Date();
			this.active = false;
			return (consumed);
		}
		catch (JimmException e)
		{
			this.lastActivity = new Date();
			this.active = false;
			this.state = STATE_ERROR;
			throw (e);
		}
	}

	public boolean isCompleted()
	{
		return (this.state == STATE_ACTION_DONE);
	}

	// Соединение со службой готово (из потока Icq.connectBart).
	public void onBartConnected()
	{
		if (this.state != STATE_CONNECTING)
		{
			// Пока соединялись, запрос сочли пропавшим — сокет не нужен.
			Icq.disconnectBart(true);
			return;
		}
		this.lastActivity = new Date();
		this.state = STATE_CONNECTION_ESTB;
	}

	// В ошибке — настоящая причина (#120 — ввод-вывод, #121 — сеть не
	// даёт соединение), а не безликое #100.
	public void onBartConnectFailed(JimmException e)
	{
		this.state = STATE_ERROR;
		Icq.disconnectBart(true);
		int ext = (e.getErrCode() == 100) ? 52 : 51;
		JimmException.handleException(new JimmException(e.getErrCode(), ext, true));
	}

	public boolean isError()
	{
		if ((this.state != STATE_ERROR) && !this.active
				&& (this.lastActivity.getTime() + this.TIMEOUT < System.currentTimeMillis()))
		{
			this.state = STATE_ERROR;
		}
		// Действие с ошибкой просто убирают из очереди, и экран, который ждёт
		// ответа, остался бы с «Загрузка...» навсегда. Поэтому о неудаче
		// говорим сами — один раз — и отпускаем собранные части.
		if (this.state == STATE_ERROR && !this.notified)
		{
			this.notified = true;
			this.parts = null;
			// Jimm рассчитывает на onEvent(ON_ERROR), но главный цикл его
			// не вызывает — соединение, в котором запрос пропал, закрываем
			// здесь, иначе следующий запрос уйдёт в тот же мёртвый сокет.
			Icq.disconnectBart(true);
			if (streaming) ((PartSink) listener).onBartDone(false);
			else if (listener != null) listener.onBart(null);
		}
		return (this.state == STATE_ERROR);
	}

	public int getProgress()
	{
		return (state > 0) ? 100 * state / STATE_MAX : 0;
	}

	public void onEvent(int eventType)
	{
		switch (eventType)
		{
		case ON_COMPLETE:
			break;
		case ON_CANCEL:
		case ON_ERROR:
			DebugLog.addText("RequestBartAction ON_ERROR");
			parts = null;
			if (!notified)
			{
				notified = true;
				if (streaming) ((PartSink) listener).onBartDone(false);
				else listener.onBart(null);
			}
			Icq.disconnectBart(true);
			break;
		}
	}
}
