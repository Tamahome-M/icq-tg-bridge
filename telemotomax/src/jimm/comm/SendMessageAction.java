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
 File: src/jimm/comm/SendMessageAction.java
 Version: ###VERSION###  Date: ###DATE###
 Author(s): Manuel Linsmayer, Spassky Alexander, Andreas Rossbacher
 *******************************************************************************/

package jimm.comm;

import java.io.ByteArrayOutputStream;

import jimm.ContactList;
import jimm.ContactItem;
import jimm.JimmException;
import jimm.Options;

public class SendMessageAction extends Action
{
	// Plain message
	private PlainMessage plainMsg;


	private int SEQ1 = 0xffff;
	
	private int messId = -1;
	
	public int getMessId()
	{
		return messId;
	}

	// Constructor
	public SendMessageAction(Message msg)
	{
		super(false, true);
		
		messId = (int)System.currentTimeMillis();
		
		//#sijapp cond.if target!="DEFAULT"#
		if (msg instanceof PlainMessage)
		{
			this.plainMsg = (PlainMessage) msg;
		}
		//#sijapp cond.else#
		//#		if (msg instanceof PlainMessage)
		//#		{
		//#			this.plainMsg = (PlainMessage) msg;
		//#		}
		//#sijapp cond.end#
	}

	// Init action
	protected void init() throws JimmException
	{
		// Forward init request depending on message type
		SEQ1--;
		initPlainMsg();
	}

	// Init action for plain messages
	private void initPlainMsg() throws JimmException
	{

		// Get receiver object
		ContactItem rcvr;

        rcvr = this.plainMsg.getRcvr();

		// What message format/encoding should we use?
		int type = 1;
		boolean utf8;
		utf8 = (rcvr.getIntValue (ContactItem.CONTACTITEM_STATUS) == 
			ContactList.STATUS_OFFLINE) ? false : 
			rcvr.hasCapability(Icq.CAPF_UTF8_INTERNAL);
		

		if ((this.plainMsg != null)
			&& ((this.plainMsg.getMessageType() >= Message.MESSAGE_TYPE_AWAY) 
			&& (this.plainMsg.getMessageType() <= Message.MESSAGE_TYPE_FFC)))
		{
			type = 2;
		}
		
		if (Options.getBoolean(Options.OPTION_DELIV_MES_INFO)
			&& rcvr.hasCapability(Icq.CAPF_AIM_SERVERRELAY)
			&& (rcvr.getIntValue(ContactItem.CONTACTITEM_CLIENT) != Icq.CLI_STICQ)
			&& (rcvr.getIntValue(ContactItem.CONTACTITEM_CLIENT) != Icq.CLI_TRILLIAN)
			&& (rcvr.getIntValue(ContactItem.CONTACTITEM_STATUS) != ContactList.STATUS_OFFLINE))
		{
			type = 2;
		}

		//////////////////////
		// Message format 1 //
		//////////////////////
		
		if (type == 1)
		{
			byte[] textRaw = 
				utf8 ? 
				Util.stringToUcs2beByteArray(Util.restoreCrLf(this.plainMsg.getText())) 
				: Util.stringToByteArray(Util.restoreCrLf(this.plainMsg.getText()));
				
			String uin = rcvr.getStringValue(ContactItem.CONTACTITEM_UIN);
			
			ByteArrayOutputStream buffer = new ByteArrayOutputStream();
			ByteArrayOutputStream tlvBuffer = new ByteArrayOutputStream();
			
			// msg-id cookie 
			Util.writeDWord(buffer, messId, true);
			Util.writeDWord(buffer, type, true);
			
			// message channel
			Util.writeWord(buffer, type, true);
			
			// UIN
			Util.writeByte(buffer, uin.length());
			Util.writeByteArray(buffer, uin.getBytes());
			
			// ---------- message data TLV ------------- 
			tlvBuffer.reset();
			
			// Capabilities
			Util.writeWord(tlvBuffer, 0x0501, true);
			if (utf8)
			{
				Util.writeWord(tlvBuffer, 0x0002, true);
				Util.writeWord(tlvBuffer, 0x0106, true);
			} else
			{
				Util.writeWord(tlvBuffer, 0x0001, true);
				Util.writeByte(tlvBuffer, 0x01);
			}
			
			// Type: message
			Util.writeWord(tlvBuffer, 0x0101, true);
			
			// Mess data len
			Util.writeWord(tlvBuffer, 4+textRaw.length, true);
			
			// MESSAGE.ENCODING
			Util.writeDWord(tlvBuffer, utf8 ? 0x00020000 : 0x00000000, true);
			Util.writeByteArray(tlvBuffer, textRaw);
			Util.writeTLV(buffer, 0x0002, tlvBuffer.toByteArray(), true);
			
			// ---------- Store offline TLV ------------- 
			Util.writeTLV(buffer, 0x0006, null, true);
			
			// ---------- req. serv delivery TLV ----------
			if (Options.getBoolean(Options.OPTION_DELIV_MES_INFO)) Util.writeTLV(buffer, 0x0003, null, true);
			
			// ----------- Send packet --------------
			SnacPacket snacPkt = new SnacPacket(SnacPacket.CLI_SENDMSG_FAMILY,
					SnacPacket.CLI_SENDMSG_COMMAND, 0, new byte[0], buffer.toByteArray());
			Icq.sendPacket(snacPkt);
		}

		//////////////////////
		// Message format 2 //
		//////////////////////

		else if (type == 2)
		{
			// System.out.println("Send TYPE 2");
			// Get UIN
			byte[] uinRaw = Util.stringToByteArray(rcvr
					.getStringValue(ContactItem.CONTACTITEM_UIN));

			// Get text
			byte[] textRaw;

			// Get filename if file transfer
			byte[] filenameRaw;

			textRaw = Util.stringToByteArray( Util.restoreCrLf(this.plainMsg.getText()) );
			filenameRaw = new byte[0];                

			// Set length
			// file request: 192 + UIN len + file description (no null) +
			// file name (null included)
			// normal msg: 163 + UIN len + message length;

			int p_sz = 0;

			p_sz = 163 + uinRaw.length + textRaw.length;                

			//int tlv5len = 148;
			//int tlv11len = 108;

			// Build the packet
			byte[] buf = new byte[p_sz];
			int marker = 0;
			Util.putDWord(buf, marker, messId); // CLI_SENDMSG.TIME
			marker += 4;
			Util.putDWord(buf, marker, type); // CLI_SENDMSG.ID
			marker += 4;
			Util.putWord(buf, marker, 0x0002); // CLI_SENDMSG.FORMAT
			marker += 2;
			Util.putByte(buf, marker, uinRaw.length); // CLI_SENDMSG.UIN
			System.arraycopy(uinRaw, 0, buf, marker + 1, uinRaw.length);
			marker += 1 + uinRaw.length;

			//-----------------TYPE2 Specific Data-------------------
			Util.putWord(buf, marker, 0x0005);
			marker += 2;

			// Length of TLV5 differs betweeen normal message and file requst
			Util.putWord(buf, marker, 144 + textRaw.length, true);
			marker += 2;

			Util.putWord(buf, marker, 0x0000);
			marker += 2;

			Util.putDWord(buf, marker, messId);
			marker += 4;

			Util.putDWord(buf, marker, 0x00000000);
			marker += 4;

			System.arraycopy(Icq.CAP_AIM_SERVERRELAY, 0, buf, marker, 16);
			// SUB_MSG_TYPE2.CAPABILITY
			marker += 16;

			// Set TLV 0x0a to 0x0001
			Util.putDWord(buf, marker, 0x000a0002);
			marker += 4;
			Util.putWord(buf, marker, 0x0001);
			marker += 2;

			// Set emtpy TLV 0x0f
			Util.putDWord(buf, marker, 0x000f0000);
			marker += 4;

			// Set TLV 0x2711
			Util.putWord(buf, marker, 0x2711);
			marker += 2;

			// Length of TLV2711 differs betweeen normal message and file requst
			Util.putWord(buf, marker, 104 + textRaw.length, true);                
			marker += 2;
			// Put 0x1b00 (unknown)
			Util.putWord(buf, marker, 0x1B00);
			marker += 2;

			// Put ICQ protocol version in LE
			Util.putWord(buf, marker, 0x0800);
			marker += 2;

			// Put capablilty (16 zero bytes)
			Util.putDWord(buf, marker, 0x00000000);
			marker += 4;
			Util.putDWord(buf, marker, 0x00000000);
			marker += 4;
			Util.putDWord(buf, marker, 0x00000000);
			marker += 4;
			Util.putDWord(buf, marker, 0x00000000);
			marker += 4;

			// Put some unknown stuff
			Util.putWord(buf, marker, 0x0000);
			marker += 2;
			Util.putByte(buf, marker, 0x03);
			marker += 1;

			// Set the DC_TYPE to "normal" if we send a file transfer request
			Util.putDWord(buf, marker, 0x00000000);
			marker += 4;
			// Put cookie, unkown 0x0e00 and cookie again
			Util.putWord(buf, marker, SEQ1, false);
			marker += 2;
			Util.putWord(buf, marker, 0x0e, false);
			marker += 2;
			Util.putWord(buf, marker, SEQ1, false);
			marker += 2;

			// Put 12 unknown zero bytes
			Util.putDWord(buf, marker, 0x00000000);
			marker += 4;
			Util.putDWord(buf, marker, 0x00000000);
			marker += 4;
			Util.putDWord(buf, marker, 0x00000000);
			marker += 4;

			// Put message type 0x0001 if normal message else 0x001a for file request
			Util.putWord(buf, marker, this.plainMsg.getMessageType(),false);                
			marker += 2;

			// Put contact status
			Util.putWord(buf, marker, Util.translateStatusSend((int) Options
					.getLong(Options.OPTION_ONLINE_STATUS)), false);
			marker += 2;

			// Put priority
			Util.putWord(buf, marker, 0x01, false);
			marker += 2;
			// Put message
			// Put message length
			Util.putWord(buf, marker, textRaw.length + 1, false);
			marker += 2;

			// Put message
			System.arraycopy(textRaw, 0, buf, marker, textRaw.length); // TLV.MESSAGE
			marker += textRaw.length;
			Util.putByte(buf, marker, 0x00);
			marker++;
			// Put foreground, background color and guidlength
			Util.putDWord(buf, marker, 0x00000000);
			marker += 4;
			Util.putDWord(buf, marker, 0x00FFFFFF);
			marker += 4;
			Util.putDWord(buf, marker, 0x26000000);
			marker += 4;
			System.arraycopy(Icq.CAP_UTF8_GUID, 0, buf, marker, 38);
			// SUB_MSG_TYPE2.CAPABILITY
			marker += 38;                

			// Put TLV 0x03
			Util.putWord(buf, marker, 0x0003, true); // CLI_SENDMSG.UNKNOWN
			marker += 2;
			Util.putWord(buf, marker, 0x0000);
			marker += 2;
			// Send packet
			SnacPacket snacPkt = new SnacPacket(SnacPacket.CLI_SENDMSG_FAMILY,
					SnacPacket.CLI_SENDMSG_COMMAND, 0, new byte[0], buf);
			Icq.sendPacket(snacPkt);
			// System.out.println("SendMessageAction: Sent the packet");
		}

		SEQ1--;

	}

	// Forwards received packet, returns true if packet was consumed
	protected boolean forward(Packet packet) throws JimmException
	{
		return (false);
	}

	// Returns true if the action is completed
	public boolean isCompleted()
	{
		return (true);
	}

	// Returns true if an error has occured
	public boolean isError()
	{
		return (false);
	}

}
