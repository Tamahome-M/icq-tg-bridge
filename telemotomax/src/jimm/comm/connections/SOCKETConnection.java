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
import java.util.Vector;

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
	public synchronized void connect(String hostAndPort)
			throws JimmException
	{
		try
		{
			state = false;
			//#sijapp cond.if target!="DEFAULT"#
			sc = (SocketConnection) Connector.open("socket://"
					+ hostAndPort, Connector.READ_WRITE);
			//#sijapp cond.else#
			//#				sc = (StreamConnection) Connector.open("socket://" + hostAndPort, Connector.READ_WRITE);
			//#sijapp cond.end#
			is = sc.openInputStream();
			os = sc.openOutputStream();

			setInputCloseFlag(false);
			rcvThread = new Thread(this);
			rcvThread.start();
			// Set starting point for seq numbers (not bigger then 0x8000)
			flapSEQ = getSeqValue();
			nextIcqSequence = 2;
			state = true;
		} catch (ConnectionNotFoundException e)
		{
			if (!getInputCloseFlag()) throw (new JimmException(121, 0));
		} catch (IllegalArgumentException e)
		{
			throw (new JimmException(122, 0));
		} catch (IOException e)
		{
			throw (new JimmException(120, 0));
		} catch (SecurityException e)
		{
			throw (new JimmException(119, 0));
		}
		finally
		{
			if (!state) closeStreams();
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
				state = false;
				notifyToDisconnect();
				if (!getInputCloseFlag()) throw new JimmException(120, 3, this.typeNetwork);
			}

		}

	}

	//  #sijapp cond.if target!="DEFAULT" & modules_FILES="true"#

	// Return the port this connection is running on
	public int getLocalPort()
	{
		try
		{
			return (this.sc.getLocalPort());
		} catch (IOException e)
		{
			return (0);
		}
	}

	// Return the ip this connection is running on
	public byte[] getLocalIP()
	{
		try
		{
			return (Util.ipToByteArray(this.sc.getLocalAddress()));
		} catch (IOException e)
		{
			return (new byte[4]);
		}
	}

	//#sijapp cond.end#

	// Main loop
	public void run()
	{
		// Required variables
		byte[] flapHeader = new byte[6];
		byte[] rcvdPacket;
		int bRead = 0, bReadSum;

		// Reset packet buffer
		synchronized (this)
		{
			rcvdPackets = new Vector();
		}

		// Try
		try
		{
			// Check abort condition
			while (!getInputCloseFlag())
			{
				// Read flap header
				bReadSum = 0;
				if (Options.getInt(Options.OPTION_CONN_PROP) == 1)
				{
					while (is.available() == 0)
						Thread.sleep(250);
					if (is == null)
						break;
				}
				do
				{
					bRead = is.read(flapHeader, bReadSum, flapHeader.length
							- bReadSum);
					if (bRead == -1)
						break;
					bReadSum += bRead;
				} while (bReadSum < flapHeader.length);
				if (bRead == -1)
					break;

				// Verify flap header
				if (Util.getByte(flapHeader, 0) != 0x2A)
				{
					throw (new JimmException(124, 0));
				}

				// TeleMotoMax: тело читается сразу в кадр, за заголовком —
				// раньше сначала в отдельный массив, потом копия в кадр:
				// для части ролика или голосового это лишние 60 КБ в куче.
				int flapLen = Util.getWord(flapHeader, 4);
				rcvdPacket = new byte[flapHeader.length + flapLen];
				System.arraycopy(flapHeader, 0, rcvdPacket, 0, flapHeader.length);

				// Read flap data
				bReadSum = 0;
				while (bReadSum < flapLen)
				{
					bRead = is.read(rcvdPacket, flapHeader.length + bReadSum, flapLen - bReadSum);
					if (bRead == -1)
						break;
					bReadSum += bRead;
				}
				if (bRead == -1)
					break;

				// Count the data
//#sijapp cond.if modules_TRAFFIC is "true" #
				Traffic.addInTraffic(bReadSum + 57);
				MainThread.updateContactListCaption();
//#sijapp cond.end#

				// Lock object and add rcvd packet to vector
				synchronized (rcvdPackets)
				{
					rcvdPackets.addElement(rcvdPacket);
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
			JimmException.handleException(e);
		}
		// Catch IO exception
		catch (IOException e)
		{
			// Construct and handle exception (only if input close flag has not been set)
			if (!getInputCloseFlag() && Icq.isMyConnection(this) && (this.typeNetwork == JimmException.ICQ_MAIN))
			{
				JimmException f = new JimmException(120, 1, this.typeNetwork);
				JimmException.handleException(f);
			}
			// Reset input close flag
		}
		// TeleMotoMax: OutOfMemoryError на большом кадре раньше убивал приёмник
		// молча — сокет открыт, клиент «в сети», а читать некому.
		catch (Throwable t)
		{
			if (!getInputCloseFlag() && Icq.isMyConnection(this) && (this.typeNetwork == JimmException.ICQ_MAIN))
			{
				JimmException f = new JimmException(120, 5, this.typeNetwork);
				JimmException.handleException(f);
			}
		}
		finally
		{
			state = false;
			closeStreams();
			if (Icq.isMyConnection(this) && (this.typeNetwork == JimmException.ICQ_MAIN))
				Icq.setNotConnected();
		}
		
		// Sometimes Nokia emulator stops working and bRead returns -1 
		if (bRead == -1 && !getInputCloseFlag())
		{
			JimmException f = new JimmException(120, 4, this.typeNetwork);
			JimmException.handleException(f);
		}
	}
	
	private void closeStreams()
	{
		try { is.close(); } catch (Exception e) {} 
		is = null;

		try { os.close(); } catch (Exception e) {}
		os = null;

		try { sc.close(); } catch (Exception e) {}
		sc = null;
		
	}
	
	public void forceDisconnect()
	{
		setInputCloseFlag(true);
		closeStreams();
	}

}
