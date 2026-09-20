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
	final static public int TYPE_REQ_LAST_VESR = 1;
	final static public int TYPE_RECONNECT     = 2;
	
	private int type; 
	private long delay = 5000;

	// Переподключение уже назначено: два обрыва подряд (сторож пингов и
	// приёмник сокета) давали два потока, два ConnectAction и два входа —
	// мост закрывал первый как «подключился заново», а второй ConnectAction
	// застревал в очереди.
	private static boolean reconnectPending;

	// Пауза между попытками, когда быстрые попытки кончились, а сети нет.
	final static public long SLOW_RECONNECT_MS = 60 * 1000;
	
	public Threads(int type)
	{
		this.type = type;
	}
	
	public void run()
	{
		switch (type)
		{
		case TYPE_REQ_LAST_VESR:
			JimmUI.internalReqLastVersThread();
			break;
			
		case TYPE_RECONNECT:
			boolean again = false;
			try
			{
				if (!Icq.isDisconnected())
				{
					try {Thread.sleep(delay);} catch (Exception e) {}
					// За время паузы могли отключиться руками — тогда не лезем.
					if (Icq.isDisconnected() || Icq.isConnected())
					{
						ConnLog.note(Icq.isConnected() ? "попытка отменена: уже в сети" : "попытка отменена: отключено руками");
						break;
					}
					ConnLog.note("попытка входа");
					ContactList.beforeConnect();
					Icq.connect(true);
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
			if (again) reconnect(SLOW_RECONNECT_MS);
			break;
		}
	}
	
	static public void requestLastJimmVers()
	{
		Threads ri = new Threads(TYPE_REQ_LAST_VESR);
		new Thread(ri).start();
	}
	
	static public void reconnect()
	{
		reconnect(5000);
	}

	static public void reconnect(long delayMs)
	{
		synchronized (Threads.class)
		{
			if (reconnectPending) return;
			reconnectPending = true;
		}
		Threads ri = new Threads(TYPE_RECONNECT);
		ri.delay = delayMs;
		new Thread(ri).start();
	}
	
		
	

}
