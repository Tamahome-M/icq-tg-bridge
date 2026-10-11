/*******************************************************************************
 Library of additional graphical screens for J2ME applications
 Copyright (C) 2003-08  Jimm Project

 This library is free software; you can redistribute it and/or
 modify it under the terms of the GNU Lesser General Public
 License as published by the Free Software Foundation; either
 version 2.1 of the License, or (at your option) any later version.

 This library is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 Lesser General Public License for more details.

 You should have received a copy of the GNU Lesser General Public
 License along with this library; if not, write to the Free Software
 Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
********************************************************************************
 File: src/jimm/comm/connections/SOCKETConnection.java
 Version: ###VERSION###  Date: ###DATE###
 Author(s): Andreas Rossbacher
*******************************************************************************/

package jimm.comm.connections;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

//#sijapp cond.if target!="DEFAULT"#
	import javax.microedition.io.SocketConnection;
//#sijapp cond.else#
//#	import javax.microedition.io.StreamConnection;
//#sijapp cond.end#

import javax.microedition.io.ConnectionNotFoundException;
import javax.microedition.io.Connector;


import jimm.JimmException;
import jimm.Options;
import jimm.MainThread;
import jimm.comm.Icq;
import jimm.comm.SnacPacket;
import jimm.comm.Packet;
import jimm.comm.ToIcqSrvPacket;
import jimm.comm.Util;

//#sijapp cond.if modules_TRAFFIC is "true" #
	import jimm.Traffic;
//#sijapp cond.end#

// SOCKETConnection
public class SOCKETConnection extends Connection implements Runnable
{

	// Connection variables
	//  #sijapp cond.if target!="DEFAULT"#
	private SocketConnection sc;

	//#sijapp cond.else#
	//#    	private StreamConnection sc;
	//#sijapp cond.end#
	private InputStream is;

	private OutputStream os;
	private static final class CryptoDeadline extends java.util.TimerTask
	{
		private volatile javax.microedition.io.Connection socket;
		volatile boolean expired;
		CryptoDeadline(javax.microedition.io.Connection value) { socket = value; }
		public void run()
		{
			javax.microedition.io.Connection pending = socket;
			if (pending == null) return;
			expired = true;
			try { pending.close(); } catch (Throwable ignore) {}
		}
		public boolean cancel()
		{
			socket = null;   // a cancelled TimerTask can remain queued until its deadline
			return super.cancel();
		}
	}

	// ICQ sequence number counter
	private int nextIcqSequence;

	public SOCKETConnection ()
	{
		this.typeNetwork = JimmException.ICQ_MAIN;
	}

	public SOCKETConnection (int type)
	{
		this.typeNetwork = type;
	}

	// Opens a connection to the specified host and starts the receiver thread
	private int connectGeneration;

	public void connect(String hostAndPort) throws JimmException
	{
		final int generation;
		synchronized (this)
		{
			if (typeNetwork == JimmException.ICQ_MAIN && !Icq.isConnectionOwner(this)) throw new JimmException(140, 0, false);
			generation = ++connectGeneration;
			state = false;
			rcvThread = null;
			setInputCloseFlag(false);
		}
		SocketConnection socket = null;
		InputStream input = null;
		OutputStream output = null;
		boolean admitted = false;
		try
		{
			// Connector.open/crypto can block for minutes. Cancellation must
			// acquire neither this monitor nor a lock held during network I/O.
			socket = (SocketConnection)Connector.open("socket://" + hostAndPort, Connector.READ_WRITE);
			synchronized (this)
			{
				if (generation != connectGeneration || getInputCloseFlag()) throw new IOException();
				sc = socket; // publish early so Cancel can interrupt the handshake
			}
			input = socket.openInputStream();
			output = socket.openOutputStream();
			if (Options.getBoolean(Options.OPTION_ENCRYPTION))
			{
				CryptoDeadline deadline = new CryptoDeadline(socket);
				jimm.Jimm.getTimerRef().schedule(deadline, 45000);
				try
				{
					SecureTransport secure = SecureTransport.open(input, output, Options.getString(Options.OPTION_ENCRYPTION_PSK));
					input = secure.input;
					output = secure.output;
				}
				catch (IOException e)
				{
					if (deadline.expired) throw new JimmException(118, 0, this.typeNetwork);
					throw e;
				}
				finally { deadline.cancel(); }
			}
			synchronized (this)
			{
				if (generation != connectGeneration || getInputCloseFlag()) throw new IOException();
				is = input; os = output;
				clearPackets();
				flapSEQ = getSeqValue(); nextIcqSequence = 2;
				rcvThread = new Thread(this);
				state = true;
				rcvThread.start();
				admitted = true;
			}
		}
		catch (ConnectionNotFoundException e) { throw new JimmException(121, 0, this.typeNetwork); }
		catch (IllegalArgumentException e) { throw new JimmException(122, 0, this.typeNetwork); }
		catch (IOException e)
		{
			if (e instanceof SecureTransport.Failure) throw new JimmException(((SecureTransport.Failure)e).code, 0, this.typeNetwork);
			throw new JimmException(120, 0, this.typeNetwork);
		}
		catch (SecurityException e) { throw new JimmException(119, 0, this.typeNetwork); }
		finally
		{
			if (!admitted)
			{
				try { if (input != null) input.close(); } catch (Throwable ignore) {}
				try { if (output != null) output.close(); } catch (Throwable ignore) {}
				try { if (socket != null) socket.close(); } catch (Throwable ignore) {}
				synchronized (this)
				{
					if (generation == connectGeneration) { state = false; is = null; os = null; sc = null; }
				}
			}
		}
	}

	// Sends the specified packet
	public void sendPacket(Packet packet) throws JimmException
	{
		// Throw exception if output stream is not ready. The stream is read
		// once: closeStreams() may null it from another thread in between.
		OutputStream out = os;
		if (out == null) throw new JimmException(123, 0, this.typeNetwork);

		// Request lock on output stream
		synchronized (out)
		{

			// Set sequence numbers
			packet.setSequence(getFlapSequence());
			if (packet instanceof ToIcqSrvPacket)
			{
				((ToIcqSrvPacket) packet).setIcqSequence(nextIcqSequence++);
			}

			// Send packet and count the bytes
			try
			{
				byte[] outpack = packet.toByteArray();
				out.write(outpack);
				out.flush();
//#sijapp cond.if modules_TRAFFIC is "true" #
				Traffic.addOutTraffic(outpack.length + 51); // 51 is the overhead for each packet
				MainThread.updateContactListCaption();
//#sijapp cond.end#
			} catch (IOException e)
			{
				boolean closing = getInputCloseFlag();
				state = false;
				notifyToDisconnect();
				if (!closing) throw new JimmException(120, 3, this.typeNetwork);
			}

		}

	}


	// Дочитывает ровно len байт; false — поток кончился.
	private boolean readFully(InputStream source, byte[] buf, int off, int len) throws IOException
	{
		int got = 0;
		while (got < len)
		{
			int n = source.read(buf, off + got, len - got);
			if (n == -1) return false;
			if (n == 0) { int one = source.read(); if (one == -1) return false; buf[off + got++] = (byte)one; }
			else got += n;
		}
		return true;
	}
	// Main loop
	public void run()
	{
		Thread receiver = Thread.currentThread();
		// Own these streams even if the same Connection is reused for BOS.
		InputStream source;
		OutputStream destination;
		javax.microedition.io.Connection socket;
		synchronized (this)
		{
			if (receiver != rcvThread) return;
			source = is;
			destination = os;
			socket = sc;
		}
		// Required variables
		byte[] flapHeader = new byte[6];
		byte[] rcvdPacket;
		int bRead = 0, bReadSum;


		// Try
		try
		{
			// Check abort condition
			while (receiver == rcvThread && !getInputCloseFlag())
			{
				// Check cancellation in the optional available()-polling mode too.
				if (Options.getInt(Options.OPTION_CONN_PROP) == 1)
				{
					while (receiver == rcvThread && !getInputCloseFlag() && source.available() == 0)
						Thread.sleep(250);
					if (receiver != rcvThread || getInputCloseFlag()) break;
				}
				if (!readFully(source, flapHeader, 0, flapHeader.length)) { bRead = -1; break; }

				// Verify flap header
				if (Util.getByte(flapHeader, 0) != 0x2A)
				{
					throw (new JimmException(124, 0));
				}

				// TeleMotoMax: тело SNAC читается сразу в свой массив, без кадра
				// целиком: раньше кадр читался в один массив, а Packet.parse
				// копировал тело во второй — на части списка чатов или истории
				// это лишние 10–24 КБ в куче на каждый пакет.
				int flapLen = Util.getWord(flapHeader, 4);
				if (!waitForPacketSpace(flapLen + 6) || receiver != rcvThread) break;
				int channel = Util.getByte(flapHeader, 1);
				Object ready;
				if (channel == 2 && flapLen >= 10)
				{
					byte[] head = new byte[10];
					if (!readFully(source, head, 0, 10)) { bRead = -1; break; }
					int family = Util.getWord(head, 0), command = Util.getWord(head, 2), flags = Util.getWord(head, 4);
					long reference = Util.getDWord(head, 6);
					if ((family == SnacPacket.CLI_TOICQSRV_FAMILY && command == SnacPacket.CLI_TOICQSRV_COMMAND)
							|| (family == SnacPacket.SRV_FROMICQSRV_FAMILY && command == SnacPacket.SRV_FROMICQSRV_COMMAND))
					{
						// Семейство 0x15 разбирает свой класс, ему нужен весь кадр.
						rcvdPacket = new byte[6 + flapLen];
						System.arraycopy(flapHeader, 0, rcvdPacket, 0, 6);
						System.arraycopy(head, 0, rcvdPacket, 6, 10);
						if (!readFully(source, rcvdPacket, 16, flapLen - 10)) { bRead = -1; break; }
						ready = rcvdPacket;
					}
					else
					{
						byte[] extData = new byte[0];
						int bodyLen = flapLen - 10;
						if ((flags & 0x8000) != 0)
						{
							byte[] lenBuf = new byte[2];
							if (bodyLen < 2) throw new JimmException(133, 1);
							if (!readFully(source, lenBuf, 0, 2)) { bRead = -1; break; }
							int extLen = Util.getWord(lenBuf, 0);
							if (bodyLen < 2 + extLen) throw new JimmException(133, 2);
							extData = new byte[extLen];
							if (!readFully(source, extData, 0, extLen)) { bRead = -1; break; }
							bodyLen -= 2 + extLen;
						}
						byte[] data = new byte[bodyLen];
						if (!readFully(source, data, 0, bodyLen)) { bRead = -1; break; }
						ready = new SnacPacket(Util.getWord(flapHeader, 2), family, command, flags, reference, extData, data);
					}
				}
				else
				{
					rcvdPacket = new byte[flapHeader.length + flapLen];
					System.arraycopy(flapHeader, 0, rcvdPacket, 0, flapHeader.length);
					if (!readFully(source, rcvdPacket, flapHeader.length, flapLen)) { bRead = -1; break; }
					ready = rcvdPacket;
				}
				bReadSum = flapLen;
				// Count the data
//#sijapp cond.if modules_TRAFFIC is "true" #
				Traffic.addInTraffic(bReadSum + 57);
				MainThread.updateContactListCaption();
//#sijapp cond.end#

				// Reusing this Connection cannot put an old frame in the new queue.
				synchronized (this)
				{
					if (receiver != rcvThread) break;
					queuePacket(ready);
				}

				// Notify main loop
				synchronized (Icq.getWaitObj())
				{
					Icq.getWaitObj().notify();
				}
			}

		}
		// Catch communication exception
		catch (NullPointerException e) { } /* Do nothing */

		// Catch InterruptedException
		catch (InterruptedException e) { } /* Do nothing */

		// Catch JimmException
		catch (JimmException e)
		{
			if (receiver == rcvThread && !getInputCloseFlag()) JimmException.handleException(e);
		}
		// Catch IO exception
		catch (IOException e)
		{
			// Construct and handle exception (only if input close flag has not been set)
			if (receiver == rcvThread && !getInputCloseFlag() && Icq.isMyConnection(this) && (this.typeNetwork == JimmException.ICQ_MAIN))
			{
				jimm.ConnLog.note("ошибка чтения сокета");
				JimmException f = e instanceof SecureTransport.Failure
						? new JimmException(((SecureTransport.Failure)e).code, 0, this.typeNetwork)
						: new JimmException(120, 1, this.typeNetwork);
				JimmException.handleException(f);
			}
			// Reset input close flag
		}
		// TeleMotoMax: OutOfMemoryError на большом кадре раньше убивал приёмник
		// молча — сокет открыт, клиент «в сети», а читать некому.
		catch (Throwable t)
		{
			if (receiver == rcvThread && !getInputCloseFlag() && Icq.isMyConnection(this) && (this.typeNetwork == JimmException.ICQ_MAIN))
			{
				JimmException f = new JimmException(120, 5, this.typeNetwork);
				JimmException.handleException(f);
			}
		}
		finally
		{
			try { if (source != null) source.close(); } catch (Exception ignore) {}
			try { if (destination != null) destination.close(); } catch (Exception ignore) {}
			try { if (socket != null) socket.close(); } catch (Exception ignore) {}
			synchronized (this)
			{
				if (receiver == rcvThread)
				{
					state = false;
					is = null; os = null; sc = null;
				}
			}
			// Never take the Icq lock while holding the connection lock.
			synchronized (Icq.class)
			{
				if (receiver == rcvThread && Icq.isMyConnection(this)
						&& (this.typeNetwork == JimmException.ICQ_MAIN))
					Icq.setNotConnected();
			}
		}
		
		// Sometimes Nokia emulator stops working and bRead returns -1 
		if (receiver == rcvThread && bRead == -1 && !getInputCloseFlag() && Icq.isMyConnection(this))
		{
			if (this.typeNetwork == JimmException.ICQ_MAIN) jimm.ConnLog.note("сервер закрыл соединение");
			JimmException f = new JimmException(120, 4, this.typeNetwork);
			JimmException.handleException(f);
		}
	}
	
	private void closeStreams()
	{
		InputStream input;
		OutputStream output;
		SocketConnection socket;
		synchronized (this)
		{
			++connectGeneration;
			input = is; output = os; socket = sc;
			is = null; os = null; sc = null; state = false;
		}
		try { if (input != null) input.close(); } catch (Throwable ignore) {}
		try { if (output != null) output.close(); } catch (Throwable ignore) {}
		try { if (socket != null) socket.close(); } catch (Throwable ignore) {}
	}

	public void forceDisconnect()
	{
		notifyToDisconnect();
		closeStreams();
	}

}
