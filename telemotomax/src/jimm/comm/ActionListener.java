/*******************************************************************************
 Jimm - Mobile Messaging - J2ME ICQ clone
 Copyright (C) 2003-08  Jimm Project

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
 File: src/jimm/comm/ActionListener.java
 Version: ###VERSION###  Date: ###DATE###
 Author(s): Manuel Linsmayer, Andreas Rossbacher, Spassky Alexander, Igor Palkin
 *******************************************************************************/

package jimm.comm;


import java.io.ByteArrayInputStream;

import jimm.ContactList;
import jimm.ContactItem;
import jimm.DebugLog;
import jimm.Jimm;
import jimm.JimmUI;
import jimm.MainThread;
import jimm.JimmException;
import jimm.Options;
import jimm.SplashCanvas;



public class ActionListener
{
	/** ************************************************************************* */

	// Forwards received packet
	protected void forward(Packet packet) throws JimmException
	{
		// Watch out for channel 4 (Disconnect) packets
		if (packet instanceof DisconnectPacket)
		{
			DisconnectPacket disconnectPacket = (DisconnectPacket) packet;

			// Throw exception
			if (disconnectPacket.getError() == 0x0001)
			{ // Multiple logins
				throw (new JimmException(110, 0));
			} else
			{ // Unknown error
				throw (new JimmException(100, 0));
			}

		}

		/** *********************************************************************** */

		// Watch out for requested offline messages
		if (packet instanceof FromIcqSrvPacket) {
			FromIcqSrvPacket fromIcqSrvPacket = (FromIcqSrvPacket) packet;
			if (fromIcqSrvPacket.getFamily() == 0x0015) {
				int subCommand = fromIcqSrvPacket.getSubcommand();
				switch (subCommand) {
					// Watch out for SRV_OFFLINEMSG
					case FromIcqSrvPacket.SRV_OFFLINEMSG_SUBCMD:
						// Get raw data
						byte[] buf = fromIcqSrvPacket.getDataRef();

						// Check length
						if (buf.length > 13) {
							// Extract UIN
							long uinRaw = Util.getDWord(buf, 0, false);

							String uin = String.valueOf(uinRaw);

							// Extract date of dispatch
							long date = Util.createLongTime(
									Util.getWord(buf, 4, false),
									Util.getByte(buf, 6),
									Util.getByte(buf, 7),
									Util.getByte(buf, 8),
									Util.getByte(buf, 9),
									0);

							// Get type
							int type = Util.getWord(buf, 10, false);

							// Get text length
							int textLen = Util.getWord(buf, 12, false);

							// Get text
							String text = Util.removeCr(Util.byteArrayToString(buf, 14, textLen, Util.isDataUTF8(buf, 14, textLen)));

							// Normal message
							if (type == 0x0001) {
								// Check length
								if (buf.length != 14 + textLen) {
									throw (new JimmException(116, 1));
								}

								// Forward message to contact list
								PlainMessage message = new PlainMessage(uin, Options.getString(Options.OPTION_UIN), Util.gmtTimeToLocalTime(date), text, true);
								MainThread.addMessageSerially(message);
							} // URL message
							else if (type == 0x0004) {
								if (buf.length != 14 + textLen) {
									throw (new JimmException(116, 1));
								}

								// Search for delimiter
								int delim = text.indexOf(0xFE);

								// Split message, if delimiter could be found
								String urlText;
								String url;
								if (delim != -1) {
									urlText = text.substring(0, delim);
									url = text.substring(delim + 1);
								} else {
									urlText = text;
									url = "";
								}

								// Forward message message to contact list
								UrlMessage message = new UrlMessage(uin, Options.getString(Options.OPTION_UIN), Util.gmtTimeToLocalTime(date), url, urlText);
								MainThread.addMessageSerially(message);
							}
						}
						break;

					// Watch out for SRV_DONEOFFLINEMSGS
					case FromIcqSrvPacket.SRV_DONEOFFLINEMSGS_SUBCMD:
						// Send a CLI_TOICQSRV/CLI_ACKOFFLINEMSGS packet
						ToIcqSrvPacket reply = new ToIcqSrvPacket(0x00000000, Options.getString(Options.OPTION_UIN), ToIcqSrvPacket.CLI_ACKOFFLINEMSGS_SUBCMD, new byte[0], new byte[0]);
						Icq.c.sendPacket(reply);
						break;
				}
			}
		}

		// Watch out for channel 2 (SNAC) packets
		else if (packet instanceof SnacPacket)
		{
			SnacPacket snacPacket = (SnacPacket) packet;

			// TeleMotoMax: the bridge answers a camera snapshot with 10/03 —
			// the uin and one byte: 0 sent, anything else failed.
			if ((snacPacket.getFamily() == 0x0010) && (snacPacket.getCommand() == 0x0003))
			{
				byte[] p = snacPacket.getDataRef();
				int len = Util.getByte(p, 0);
				String uin = Util.byteArrayToString(p, 1, len);
				boolean ok = (p.length > 1 + len) && (Util.getByte(p, 1 + len) == 0);
				jimm.VoiceRecorder.voiceSent(uin, ok);
//#sijapp cond.if modules_CAMERA="true"#
				jimm.CameraShot.photoSent(uin, ok);
				jimm.VideoRecorder.videoSent(uin, ok);
				jimm.FileSender.fileSent(uin, ok);
//#sijapp cond.end#
				return;
			}

			// Typing notify
			//#sijapp cond.if target isnot "DEFAULT"#
			if ((snacPacket.getFamily() == 0x0004)
					&& (snacPacket.getCommand() == 0x0014)
					&& Options.getInt(Options.OPTION_TYPING_MODE) > 0)
			{
				byte[] p = snacPacket.getDataRef();
				int uin_len = Util.getByte(p, 10);
				String uin = Util.byteArrayToString(p, 11, uin_len);
				int flag = Util.getWord(p, 11 + uin_len);
				DebugLog.addText("Typing notify: " + flag);

				if (flag == 0x0002)
					//Begin typing
					MainThread.BeginTyping(uin, true);
				else
					//End typing
					MainThread.BeginTyping(uin, false);
			}
			//#sijapp cond.end#

			// Error after requesting offline messages?
			if ((snacPacket.getFamily() == 0x0015) && (snacPacket.getCommand() == 0x0001))
			{
				// Get data
				byte[] buf = snacPacket.getDataRef();

				// Read the error code from the packet
				int errCode = Util.getWord(buf, 0);

				DebugLog.addText("Error after requesting offline messages, error code: " + errCode);
			}

			// Watch out for SRV_USERONLINE packets
			else if ((snacPacket.getFamily() == SnacPacket.SRV_USERONLINE_FAMILY)
					&& (snacPacket.getCommand() == SnacPacket.SRV_USERONLINE_COMMAND))
			{
				MainThread.updatePresence(snacPacket.getDataRef(), true);
			}

			/** ********************************************************************* */

			// Watch out for SRV_USEROFFLINE packets
			if ((snacPacket.getFamily() == SnacPacket.SRV_USEROFFLINE_FAMILY)
					&& (snacPacket.getCommand() == SnacPacket.SRV_USEROFFLINE_COMMAND))
			{
				MainThread.updatePresence(snacPacket.getDataRef(), false);
			}

			/** ********************************************************************* */

			if (snacPacket.getFamily() == 4 && snacPacket.getCommand() == 0x15)
			{
				byte[] data = snacPacket.getDataRef();
				if (data.length >= 17)
				{
					int len = Util.getByte(data, 8);
					if (data.length == 9 + len + 8)
					{
						byte[] ref = new byte[8];
						System.arraycopy(data, 9 + len, ref, 0, 8);
						MainThread.setMessageRef(Util.byteArrayToString(data, 9, len), (int)Util.getDWord(data, 0), ref);
					}
				}
			}
			// Watch out for CLI_ACKMSG_COMMAND packets
			else if ((snacPacket.getFamily() == SnacPacket.CLI_ACKMSG_FAMILY)
					&& (snacPacket.getCommand() == SnacPacket.CLI_ACKMSG_COMMAND))
			{
				// Get raw data
				byte[] buf = snacPacket.getDataRef();
				
				int msgId1 = (int)Util.getDWord(buf, 0);
				int msgId2 = (int)Util.getDWord(buf, 4);
				
				// Get length of the uin 
				int uinLen = Util.getByte(buf, 10);
				String uin = Util.byteArrayToString(buf, 11, uinLen);

				// Get message type
				int msgType = Util.getWord(buf, 58 + uinLen, false); // TODO: fix java.lang.ArrayIndexOutOfBoundsException

				if (((msgType == Message.MESSAGE_TYPE_NORM) || (msgType == 26)) // 26 is sended from ICQ6
					&& (msgId2 == 0x0002) 
					&& Options.getBoolean(Options.OPTION_DELIV_MES_INFO))
				{
					MainThread.messageIsDelevered(uin, msgId1);
					return;
				}
				
			}
		
			/** ********************************************************************* */

			// Watch out for SRV_RECVMSG
			else if ((snacPacket.getFamily() == SnacPacket.SRV_RECVMSG_FAMILY)
					&& (snacPacket.getCommand() == SnacPacket.SRV_RECVMSG_COMMAND))
			{

				// Get raw data, initialize marker
				byte[] buf = snacPacket.getDataRef();
				int marker = 0;

				// Check length
				if (buf.length < 11)
				{
					throw (new JimmException(150, 0, false));
				}

				// Get message format
				marker += 8;
				int format = Util.getWord(buf, marker);
				marker += 2;

				// Get UIN length
				int uinLen = Util.getByte(buf, marker);
				marker += 1;

				// Check length
				if (buf.length < marker + uinLen + 4)
				{
					throw (new JimmException(150, 1, false));
				}

				// Get UIN
				String uin = Util.byteArrayToString(buf, marker, uinLen);
				marker += uinLen;

				// Skip WARNING
				marker += 2;

				// Skip TLVS
				int tlvCount = Util.getWord(buf, marker);
				marker += 2;
				for (int i = 0; i < tlvCount; i++)
				{
					int length = Util.getTlvLength(buf, marker, buf.length);
					if (length < 0)
					{
						throw (new JimmException(150, 2, false));
					}
					marker += 4 + length;
				}

				// Get message data and initialize marker
				byte[] msgBuf = buf;
				int msgStart, msgEnd;
				int tlvType;
				do
				{
					int length = Util.getTlvLength(buf, marker, buf.length);
					if (length < 0)
					{
						throw (new JimmException(150, 3, false));
					}
					tlvType = Util.getWord(buf, marker);
					msgStart = marker + 4;
					msgEnd = msgStart + length;
					marker = msgEnd;
				} while ((tlvType != 0x0002) && (tlvType != 0x0005));
				int msgMarker = msgStart;

				// TeleMotoMax: the bridge may append TLV 0x9001 after the
				// body — kind (1 byte) and a 16-byte token of an attached
				// picture. Plain Jimm never looks past the body, so it is
				// harmless for it.
				byte[] messageRef = null;
				byte[] attachToken = null;
				int attachKind = 0;
				int extMarker = marker;
				while (extMarker + 4 <= buf.length)
				{
					int extType = Util.getWord(buf, extMarker);
					int extLength = Util.getTlvLength(buf, extMarker, buf.length);
					if (extLength < 0) break;
					if (extType == 0x9002 && extLength == 8)
					{
						messageRef = new byte[8];
						System.arraycopy(buf, extMarker + 4, messageRef, 0, 8);
					}
					// kind 1 = photo, 2 = video preview, 3 = voice message, 4 = file
					if ((extType == 0x9001) && (extLength == 17)
							&& (buf[extMarker + 4] >= 1) && (buf[extMarker + 4] <= 4))
					{
						attachToken = new byte[16];
						System.arraycopy(buf, extMarker + 5, attachToken, 0, 16);
						attachKind = buf[extMarker + 4];
					}
					extMarker += 4 + extLength;
				}

				//////////////////////
				// Message format 1 //
				//////////////////////
				if (format == 0x0001)
				{

					// Variables for all possible TLVs
					// byte[] capabilities = null;
					int messageStart = -1, messageLength = 0;

					// Read all TLVs
					while (msgMarker < msgEnd)
					{

						// Get next TLV
						int length = Util.getTlvLength(msgBuf, msgMarker, msgEnd);
						if (length < 0)
						{
							throw (new JimmException(151, 0, false));
						}

						// Get type of next TLV
						tlvType = Util.getWord(msgBuf, msgMarker);

						// Update markers
						int valueStart = msgMarker + 4;
						msgMarker = valueStart + length;

						// Save value
						switch (tlvType)
						{
						case 0x0501:
							// capabilities
							// capabilities = tlvValue;
							break;
						case 0x0101:
							// message
							messageStart = valueStart;
							messageLength = length;
							break;
						default:
							throw (new JimmException(151, 1, false));
						}

					}

					// Process packet if at least the message TLV was present
					if (messageStart >= 0)
					{

						// Check length of message
						if (messageLength < 4)
						{
							throw (new JimmException(151, 2, false));
						}

						// Get message text
						String text;
						if (Util.getWord(buf, messageStart) == 0x0002)
						{
							text = Util.removeCr(Util.ucs2beByteArrayToString(
									buf, messageStart + 4, messageLength - 4));
						} else
						{
							text = Util.removeCr(Util.byteArrayToString(
									buf, messageStart + 4, messageLength - 4));
						}

						// Construct object which encapsulates the received
						// plain message

						PlainMessage plainMsg = new PlainMessage(uin, Options
								.getString(Options.OPTION_UIN), Util
								.createCurrentDate(false), text, false);
						plainMsg.setAttach(attachToken, attachKind);
						plainMsg.setMessageRef(messageRef);
						MainThread.addMessageSerially(plainMsg);
					}

				}
				//////////////////////
				// Message format 2 //
				//////////////////////
				else if (format == 0x0002)
				{
					// TLV(A): Acktype 0x0000 - normal message
					//                 0x0001 - file request / abort request
					//                 0x0002 - file ack

					// Check length
					if (msgEnd - msgStart < 10)
					{
						throw (new JimmException(152, 0, false));
					}

					// Get and validate SUB_MSG_TYPE2.COMMAND
					int command = Util.getWord(msgBuf, msgMarker);
					if (command != 0x0000)
						return; // Only normal messages are
					// supported yet
					msgMarker += 2;

					// Skip SUB_MSG_TYPE2.TIME and SUB_MSG_TYPE2.ID
					msgMarker += 4 + 4;

					// Check length
					if (msgEnd - msgMarker < 16)
					{
						throw (new JimmException(152, 1, false));
					}

					// Skip SUB_MSG_TYPE2.CAPABILITY
					msgMarker += 16;

					// Get message data and initialize marker
					byte[] msg2Buf = buf;
					int msg2Start, msg2End;

					do
					{
						int length = Util.getTlvLength(msgBuf, msgMarker, msgEnd);
						if (length < 0)
						{
							throw (new JimmException(152, 2, false));
						}
						tlvType = Util.getWord(msgBuf, msgMarker);
						msg2Start = msgMarker + 4;
						msg2End = msg2Start + length;
						msgMarker = msg2End;
					} while (tlvType != 0x2711);

					int msg2Marker = msg2Start;

					// Check length
					if (msg2End - msg2Start < 2 + 2 + 16 + 3 + 4 + 2 + 2 + 2 + 12
							+ 2 + 2 + 2 + 2)
					{
						throw (new JimmException(152, 3, false));
					}

					// Skip values up to (and including) SUB_MSG_TYPE2.UNKNOWN
					// (before MSGTYPE)
					msg2Marker += 2 + 2 + 16 + 3 + 4 + 2 + 2 + 2 + 12;

					// Get and validate message type
					int msgType = Util.getWord(msg2Buf, msg2Marker, false);
					msg2Marker += 2;
					if (!((msgType == Message.MESSAGE_TYPE_NORM) || (msgType == Message.MESSAGE_TYPE_URL)
							|| (msgType == Message.MESSAGE_TYPE_EXTENDED)))
						return;

					msg2Marker += 2;

					// Skip PRIORITY
					msg2Marker += 2;

					// Get length of text
					int textLen = Util.getWord(msg2Buf, msg2Marker, false);
					msg2Marker += 2;

					// Check length
					if (textLen > msg2End - msg2Marker - 8)
					{
						throw (new JimmException(152, 4, false));
					}

					// Decode from the original packet; do not copy the body,
					// its nested TLV and then the text into three new arrays.
					int rawTextStart = msg2Marker;
					msg2Marker += textLen;
					// Plain message or URL message
					// TeleMotoMax: > 0, а не > 1 — у Jimm сообщение из одного
					// символа без завершающего нуля молча пропадало.
					if (((msgType == 0x0001) || (msgType == 0x0004))
							&& (textLen > 0))
					{

						// Skip FOREGROUND and BACKGROUND
						if ((msgType == 0x0001) || (msgType == 0x0004))
						{
							msg2Marker += 4 + 4;
						}

						// Check encoding (by checking GUID)
						boolean isUtf8 = false;
						if (msg2End - msg2Marker >= 4)
						{
							int guidLen = (int) Util.getDWord(msg2Buf,
									msg2Marker, false);
							if (guidLen < 0 || guidLen > msg2End - msg2Marker - 4)
							{
								throw new JimmException(152, 4, false);
							}
							isUtf8 = guidLen == Icq.CAP_UTF8_GUID.length
								&& Util.byteArrayEquals(msg2Buf, msg2Marker + 4, Icq.CAP_UTF8_GUID, 0, guidLen);
							msg2Marker += 4 + guidLen;
						}

						// Decode text and create Message object
						Message message;
						if (msgType == 0x0001)
						{

							// Decode text
							String text = Util.removeCr(Util.byteArrayToString(
									buf, rawTextStart, textLen, isUtf8));

							// Instantiate message object
							message = new PlainMessage(uin, Options
									.getString(Options.OPTION_UIN), Util
									.createCurrentDate(false), text, false);

						} else
						{

							// Search for delimited
							int delim = -1;
							for (int i = 0; i < textLen; i++)
							{
								if (buf[rawTextStart + i] == (byte)0xFE)
								{
									delim = i;
									break;
								}
							}

							// Decode text; split text first, if delimiter could
							// be found
							String urlText, url;
							if (delim != -1)
							{
								urlText = Util.removeCr(Util.byteArrayToString(
										buf, rawTextStart, delim, isUtf8));
								url = Util.removeCr(Util.byteArrayToString(
										buf, rawTextStart + delim + 1, textLen
												- delim - 1, isUtf8));
							} else
							{
								urlText = Util.removeCr(Util.byteArrayToString(
										buf, rawTextStart, textLen, isUtf8));
								url = "";
							}

							// Instantiate UrlMessage object
							message = new UrlMessage(uin, Options
									.getString(Options.OPTION_UIN), Util
									.createCurrentDate(false), url, urlText);
						}

						// Forward message object to contact list
						message.setAttach(attachToken, attachKind);
						message.setMessageRef(messageRef);
						MainThread.addMessageSerially(message);

						// Acknowledge message
						byte[] ackBuf = new byte[10 + 1 + uinLen + 2 + 51 + 3];
						int ackMarker = 0;
						System.arraycopy(buf, 0, ackBuf, ackMarker, 10);
						ackMarker += 10;
						Util.putByte(ackBuf, ackMarker, uinLen);
						ackMarker += 1;
						byte[] uinRaw = Util.stringToByteArray(uin);
						System.arraycopy(uinRaw, 0, ackBuf, ackMarker,
								uinRaw.length);
						ackMarker += uinRaw.length;
						Util.putWord(ackBuf, ackMarker, 0x0003);
						ackMarker += 2;
						System.arraycopy(msg2Buf, msg2Start, ackBuf, ackMarker, 51);
						ackMarker += 51;
						Util.putWord(ackBuf, ackMarker, 0x0001, false);
						ackMarker += 2;
						Util.putByte(ackBuf, ackMarker, 0x00);
						ackMarker += 1;
						SnacPacket ackPacket = new SnacPacket(
								SnacPacket.CLI_ACKMSG_FAMILY,
								SnacPacket.CLI_ACKMSG_COMMAND, 0, new byte[0],
								ackBuf);
						Icq.sendPacket(ackPacket);

					}
					// Extended message
					else if (msgType == 0x001A)
					{

						// Check length
						if (msg2End - msg2Marker < 2 + 18 + 4)
						{
							throw (new JimmException(152, 5, false));
						}

						// Save current marker position
						int extDataStart = msg2Marker;

						// Skip EXTMSG.LEN and EXTMSG.UNKNOWN
						msg2Marker += 2 + 18;

						// Get length of plugin string
						int pluginLen = (int) Util.getDWord(msg2Buf,
								msg2Marker, false);
						msg2Marker += 4;

						// Check length
						if (pluginLen < 0 || pluginLen > msg2End - msg2Marker - 23)
						{
							throw (new JimmException(152, 6, false));
						}

						// Get plugin string
						String plugin = Util.byteArrayToString(msg2Buf,
								msg2Marker, pluginLen);
						msg2Marker += pluginLen;

						// Skip EXTMSG.UNKNOWN and EXTMSG.LEN
						msg2Marker += 15 + 4;

						// Get length of text
						textLen = (int) Util.getDWord(msg2Buf, msg2Marker,
								false);
						msg2Marker += 4;

						// Check length
						if (textLen < 0 || textLen > msg2End - msg2Marker)
						{
							throw (new JimmException(152, 7, false));
						}

						// Get text
						String text = Util.removeCr(Util.byteArrayToString(
								msg2Buf, msg2Marker, textLen));
						msg2Marker += textLen;

						if (plugin.equals("Send Web Page Address (URL)"))
						{

							// Search for delimiter
							int delim = text.indexOf(0xFE);

							// Split message, if delimiter could be found
							String urlText;
							String url;
							if (delim != -1)
							{
								urlText = text.substring(0, delim);
								url = text.substring(delim + 1);
							} else
							{
								urlText = text;
								url = "";
							}

							// Forward message message to contact list
							UrlMessage message = new UrlMessage(uin, Options
									.getString(Options.OPTION_UIN), Util
									.createCurrentDate(false), url, urlText);
							message.setMessageRef(messageRef);
							MainThread.addMessageSerially(message);

							// Acknowledge message
							byte[] ackBuf = new byte[10 + 1 + uinLen + 2 + 51
									+ 3 + 20 + 4 + (int) pluginLen + 19 + 4
									+ textLen];
							int ackMarker = 0;
							System.arraycopy(buf, 0, ackBuf, ackMarker, 10);
							ackMarker += 10;
							Util.putByte(ackBuf, ackMarker, uinLen);
							ackMarker += 1;
							byte[] uinRaw = Util.stringToByteArray(uin);
							System.arraycopy(uinRaw, 0, ackBuf, ackMarker,
									uinRaw.length);
							ackMarker += uinRaw.length;
							Util.putWord(ackBuf, ackMarker, 0x0003);
							ackMarker += 2;
							System.arraycopy(msgBuf, msgStart, ackBuf, ackMarker, 51);
							ackMarker += 51;
							Util.putWord(ackBuf, ackMarker, 0x0001, false);
							ackMarker += 2;
							Util.putByte(ackBuf, ackMarker, 0x00);
							ackMarker += 1;
							System.arraycopy(msg2Buf, extDataStart, ackBuf,
									ackMarker, 20 + 4 + (int) pluginLen + 19
											+ 4 + textLen);
							SnacPacket ackPacket = new SnacPacket(
									SnacPacket.CLI_ACKMSG_FAMILY,
									SnacPacket.CLI_ACKMSG_COMMAND, 0,
									new byte[0], ackBuf);
							Icq.sendPacket(ackPacket);

						}
						// Other messages
						else
						{
							// Discard
						}

					}

				}
				//////////////////////
				// Message format 4 //
				//////////////////////
				else if (format == 0x0004)
				{

					// Check length
					if (msgEnd - msgStart < 8)
					{
						throw (new JimmException(153, 0, false));
					}

					// Skip SUB_MSG_TYPE4.UIN
					msgMarker += 4;

					// Get SUB_MSG_TYPE4.MSGTYPE
					int msgType = Util.getWord(msgBuf, msgMarker, false);
					msgMarker += 2;

					// Only plain messages and URL messagesa are supported
					if ((msgType != 0x0001) && (msgType != 0x0004))
						return;

					// Get length of text
					int textLen = Util.getWord(msgBuf, msgMarker, false);
					msgMarker += 2;

					// Check length (exact match required)
					if (msgEnd - msgStart != 8 + textLen)
					{
						throw (new JimmException(153, 1, false));
					}

					// Get text
					String text = Util.removeCr(Util.byteArrayToString(msgBuf,
							msgMarker, textLen));
					msgMarker += textLen;

					// Plain message
					if (msgType == 0x0001)
					{
						// Forward message to contact list
						PlainMessage plainMsg = new PlainMessage(uin, Options
								.getString(Options.OPTION_UIN), Util
								.createCurrentDate(false), text, false);
						MainThread.addMessageSerially(plainMsg);
					}
					// URL message
					else if (msgType == 0x0004)
					{

						// Search for delimiter
						int delim = text.indexOf(0xFE);

						// Split message, if delimiter could be found
						String urlText;
						String url;
						if (delim != -1)
						{
							urlText = text.substring(0, delim);
							url = text.substring(delim + 1);
						} else
						{
							urlText = text;
							url = "";
						}

						// Forward message message to contact list
						UrlMessage urlMsg = new UrlMessage(uin, Options
								.getString(Options.OPTION_UIN), Util
								.createCurrentDate(false), url, urlText);
						MainThread.addMessageSerially(urlMsg);
					}

				}

			}

			//	  Watch out for SRV_ADDEDYOU
			else if ((snacPacket.getFamily() == SnacPacket.SRV_ADDEDYOU_FAMILY)
					&& (snacPacket.getCommand() == SnacPacket.SRV_ADDEDYOU_COMMAND))
			{
				// Get data
				byte[] buf = snacPacket.getDataRef();

				// Get UIN of the contact changing status
				int uinLen = Util.getByte(buf, 0);
				String uin = Util.byteArrayToString(buf, 1, uinLen);

				// Create a new system notice
				SystemNotice notice = new SystemNotice(
						SystemNotice.SYS_NOTICE_YOUWEREADDED, uin, false, null);

				// Handle the new system notice
				MainThread.addMessageSerially(notice);
			}

			//	  Watch out for SRV_AUTHREQ
			else if ((snacPacket.getFamily() == SnacPacket.SRV_AUTHREQ_FAMILY)
					&& (snacPacket.getCommand() == SnacPacket.SRV_AUTHREQ_COMMAND))
			{
				int authMarker = 0;

				// Get data
				byte[] buf = snacPacket.getDataRef();

				// Get UIN of the contact changing status
				int length = Util.getByte(buf, 0);
				authMarker += 1;
				String uin = Util.byteArrayToString(buf, authMarker, length);
				authMarker += length;

				// Get reason
				length = Util.getWord(buf, authMarker);
				authMarker += 2;
				String reason = Util.byteArrayToString(buf, authMarker, length,
						Util.isDataUTF8(buf, authMarker, length));

				// Create a new system notice
				SystemNotice notice = new SystemNotice(
						SystemNotice.SYS_NOTICE_AUTHREQ, uin, false, reason);

				// Handle the new system notice
				MainThread.addMessageSerially(notice);
			}

			//	  Watch out for SRV_AUTHREPLY
			else if ((snacPacket.getFamily() == SnacPacket.SRV_AUTHREPLY_FAMILY)
					&& (snacPacket.getCommand() == SnacPacket.SRV_AUTHREPLY_COMMAND))
			{

				int authMarker = 0;
				// Get data
				byte[] buf = snacPacket.getDataRef();

				// Get UIN of the contact changing status
				int length = Util.getByte(buf, 0);
				authMarker += 1;
				String uin = Util.byteArrayToString(buf, authMarker, length);
				authMarker += length;

				// Get granted boolean
				boolean granted = false;
				if (Util.getByte(buf, authMarker) == 0x01)
				{
					granted = true;
				}
				authMarker += 1;

				// Get reason only of not granted
				SystemNotice notice;
				if (!granted)
				{
					length = Util.getWord(buf, authMarker);
					String reason = Util.byteArrayToString(buf, authMarker,
							length + 2);
					// Create a new system notice
					if (length == 0)
						notice = new SystemNotice(
								SystemNotice.SYS_NOTICE_AUTHREPLY, uin,
								granted, null);
					else
						notice = new SystemNotice(
								SystemNotice.SYS_NOTICE_AUTHREPLY, uin,
								granted, reason);
				} else
				{
					// Create a new system notice
					//System.out.println("Auth granted");
					notice = new SystemNotice(
							SystemNotice.SYS_NOTICE_AUTHREPLY, uin, granted, "");
				}

				// Handle the new system notice
				MainThread.addMessageSerially(notice);
			}
			
			else if ((snacPacket.getFamily() == SnacPacket.SRV_MSG_ACK_FAMILY)
					&& (snacPacket.getCommand() == SnacPacket.SRV_MSG_ACK_COMMAND))
			{
				ByteArrayInputStream stream = new ByteArrayInputStream(snacPacket.getDataRef());
				int messId1 = Util.getDWord(stream, true);
				int messId2 = Util.getDWord(stream, true);
				Util.getWord(stream, true);
				if ((messId2 == 0x0001) && Options.getBoolean(Options.OPTION_DELIV_MES_INFO))
				{
					String uin = Util.getLenAndString(stream, 1);
					MainThread.messageIsDelevered(uin, messId1);
				}
			}

		}
	}

}
