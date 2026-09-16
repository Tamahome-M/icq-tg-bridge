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
public class RequestBartAction extends Action
{
	public static final int BART_PHOTO = 0x0080;
	public static final int BART_HISTORY = 0x0081;
	public static final int BART_VIDEO = 0x0082;
	public static final int BART_VOICE = 0x0083;

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

	public static final int STATE_ERROR = -1;
	public static final int STATE_INIT_DONE = 0;
	public static final int STATE_CONNECTION_ESTB = 1;
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
	private java.io.ByteArrayOutputStream parts;

	public RequestBartAction(String uin, int bartType, byte[] token, Listener listener)
	{
		super(false, true);
		this.uin = uin;
		this.bartType = bartType;
		this.token = token;
		this.listener = listener;
		if (bartType == BART_VIDEO) TIMEOUT = VIDEO_TIMEOUT;
	}

	protected void init() throws JimmException
	{
		if (Icq.bartC != null && Icq.bartC.getState())
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
		Util.putByte(buf, 4 + uinLength, 0x01);
		Util.putByte(buf, 5 + uinLength, 0x10);
		System.arraycopy(token, 0, buf, 6 + uinLength, 16);
		SnacPacket request = new SnacPacket(0x0010, 0x0006, 0x0006, new byte[0], buf);
		try
		{
			Icq.bartC.sendPacket(request);
		}
		catch (JimmException je)
		{
			this.state = STATE_ERROR;
			throw (new JimmException(100, 53, true));
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
						byte[] buf = snacPacket.getData();
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
					try
					{
						Icq.bartC = new SOCKETConnection(JimmException.ICQ_BART);
						Icq.bartC.connect(this.srvHost + ":" + this.srvPort);
					}
					catch (JimmException e)
					{
						this.state = STATE_ERROR;
						throw (new JimmException(100, 51, true));
					}
					catch (Exception e)
					{
						this.state = STATE_ERROR;
						throw (new JimmException(100, 52, true));
					}
					this.state = STATE_CONNECTION_ESTB;
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
						byte[] buf = snacPacket.getData();
						int marker = 0;
						int uinLength = Util.getByte(buf, marker);
						marker += 1 + uinLength;
						// Flags of the two item blocks carry "part N of M" for
						// replies that do not fit one packet; 1 of 1 otherwise.
						int part = Util.getByte(buf, marker + 2);
						int total = Util.getByte(buf, marker + 2 + 1 + 1 + 16 + 1 + 2);
						marker += 2 + 1 + 1 + 16 + 1 + 2 + 1 + 1 + 16;
						int dataLength = Util.getWord(buf, marker);
						marker += 2;
						if (total > 1)
						{
							if (parts == null) parts = new java.io.ByteArrayOutputStream();
							parts.write(buf, marker, dataLength);
							buf = null;
							if (listener instanceof ProgressListener)
								((ProgressListener) listener).onBartProgress(part, total);
							if (part < total)
							{
								this.lastActivity = new Date();
								this.active = false;
								return true;           // wait for the rest
							}
							byte[] all = parts.toByteArray();
							parts = null;
							listener.onBart(all);
						}
						else
						{
							byte[] data = new byte[dataLength];
							System.arraycopy(buf, marker, data, 0, dataLength);
							buf = null;
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

	public boolean isError()
	{
		if ((this.state != STATE_ERROR) && !this.active
				&& (this.lastActivity.getTime() + this.TIMEOUT < System.currentTimeMillis()))
		{
			this.state = STATE_ERROR;
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
			listener.onBart(null);
			Icq.disconnectBart(true);
			break;
		}
	}
}
