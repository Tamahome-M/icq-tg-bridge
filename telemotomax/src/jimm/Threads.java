/*******************************************************************************
 Jimm - Mobile Messaging - J2ME ICQ clone
 Copyright (C) 2008  Jimm Project

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
 File: src/jimm/Threads.java
 Version: ###VERSION###  Date: ###DATE###
 Author(s): Artyomov Denis
 *******************************************************************************/

package jimm;

import jimm.comm.Icq;

public class Threads implements Runnable
{
	final static public int TYPE_RECONNECT     = 2;
	
	private int type; 
	private long delay = 5000;

	// Переподключение уже назначено: два обрыва подряд (сторож пингов и
	// приёмник сокета) давали два потока, два ConnectAction и два входа —
	// мост закрывал первый как «подключился заново», а второй ConnectAction
	// застревал в очереди.
	private static boolean reconnectPending;
	private static long retryAt;
	private static boolean retryStartupDns;
	private static int reconnectGeneration;
	private int generation;

	// Пауза между попытками, когда быстрые попытки кончились, а сети нет.
	final static public long SLOW_RECONNECT_MS = 60 * 1000;
	
	public Threads(int type)
	{
		this.type = type;
		synchronized (Threads.class) { generation = reconnectGeneration; }
	}

	// Invalidate a sleeping scheduler and any deferred retry, without spawning
	// another worker while the old one is still returning from connect().
	public static synchronized void cancelReconnect()
	{
		++reconnectGeneration;
		retryAt = 0;
	}

	private boolean current()
	{
		synchronized (Threads.class) { return generation == reconnectGeneration; }
	}
	
	public void run()
	{
		switch (type)
		{
		case TYPE_RECONNECT:
			boolean again = false;
			try
			{
				if (current() && !Icq.isDisconnected())
				{
					try {Thread.sleep(delay);} catch (Exception e) {}
					synchronized (Icq.class)
					{
					// За время паузы могли отключиться руками — тогда не лезем.
					if (!current() || Icq.isDisconnected() || Icq.isConnected() || Icq.isConnecting())
					{
						ConnLog.note(Icq.isConnected() ? "попытка отменена: уже в сети" :
								(Icq.isConnecting() ? "попытка отменена: уже подключаемся" :
								"попытка отменена: отключено руками"));
						break;
					}
					ConnLog.note("попытка входа");
					ContactList.beforeConnect();
					Icq.connect(true);
					}
				}
			}
			catch (Throwable t)
			{
				// Сама попытка упала (нет памяти, не создался поток) —
				// раньше цепочка на этом молча обрывалась. Повторим позже.
				ConnLog.note("попытка не началась: " + t.getClass().getName());
				again = true;
			}
			finally
			{
				synchronized (Threads.class) { reconnectPending = false; }
			}
			if (again) reconnect(SLOW_RECONNECT_MS, generation);
			break;
		}
	}
	
	
	static public void reconnect()
	{
		reconnect(5000);
	}

	static public void reconnect(long delayMs)
	{
		final int currentGeneration;
		synchronized (Threads.class) { currentGeneration = reconnectGeneration; }
		reconnect(delayMs, currentGeneration);
	}

	private static void reconnect(long delayMs, int expectedGeneration)
	{
		boolean startupDns = jimm.comm.connections.StartupDns.needsNextAddress();
		boolean automatic = Options.getBoolean(Options.OPTION_RECONNECT);
		synchronized (Threads.class)
		{
			if (expectedGeneration != reconnectGeneration) return;
			if (reconnectPending)
			{
				// The new login can fail before the previous scheduler returns
				// from Icq.connect(). Keep its authorized retry for the clock.
				if (startupDns || automatic)
				{
					retryAt = System.currentTimeMillis() + delayMs;
					retryStartupDns = startupDns;
				}
				return;
			}
			reconnectPending = true;
			retryAt = 0;
			retryStartupDns = startupDns;
		}
		try
		{
			Threads ri = new Threads(TYPE_RECONNECT);
			ri.generation = expectedGeneration;
			ri.delay = delayMs;
			new Thread(ri).start();
		}
		catch (Throwable failure)
		{
			synchronized (Threads.class)
			{
				reconnectPending = false;
				if (expectedGeneration == reconnectGeneration && retryAt == 0)
					retryAt = System.currentTimeMillis() + SLOW_RECONNECT_MS;
			}
		}
	}

	// Reuse the existing UI clock: scheduling another timer/thread when
	// native thread allocation failed would fail for the same reason.
	static public void checkReconnect()
	{
		boolean startupDns;
		int currentGeneration;
		synchronized (Threads.class)
		{
			if (reconnectPending || retryAt == 0 || System.currentTimeMillis() < retryAt) return;
			retryAt = 0;
			startupDns = retryStartupDns;
			currentGeneration = reconnectGeneration;
		}
		boolean allowed = startupDns ? jimm.comm.connections.StartupDns.needsNextAddress()
				: Options.getBoolean(Options.OPTION_RECONNECT);
		if (allowed && !Icq.isDisconnected() && !Icq.isConnected() && !Icq.isConnecting()) reconnect(0, currentGeneration);
	}
	
		
	

}
