/*******************************************************************************
 Jimm - Mobile Messaging - J2ME ICQ clone
 Copyright (C) 2005-08  Jimm Project

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
 File: src/jimm/RunnableImpl.java
 Version: ###VERSION###  Date: ###DATE###
 Author(s): Artyomov Denis
 *******************************************************************************/

package jimm;

import java.util.Vector;
import javax.microedition.lcdui.*;

import DrawControls.VirtualList;
import jimm.comm.Message;
import jimm.comm.Util;
import jimm.ContactItem;

public class MainThread implements Runnable
{
	private static Vector mainThreadTasks = new Vector(16);
	private static MainThread _this;
	private static boolean queueScheduled;
	private static Thread uiThread;
	private static final int MAX_QUEUED_EVENTS = 64;
	private static final int MAX_QUEUED_BYTES = 16 * 1024;
	private static int queuedBytes;
	private static final Integer[] taskNumbers = new Integer[32];
	private static long clockMinute = -1;

	final static private int TYPE_ADD_MSG             = 1;
	final static private int TYPE_USER_OFFLINE        = 4;
	final static private int TYPE_UPDATE_CONTACT_LIST = 5;
	final static private int TYPE_SHOW_USER_INFO      = 6;
	final static private int TYPE_UPDATE_CL_CAPTION   = 7;
	final static private int TYPE_USER_IS_TYPING      = 9;
	final static private int TYPE_RESET_CONTACTS      = 10;
	final static private int TYPE_SHOW_TIME           = 11;
	final static private int TYPE_ADD_CONTACT         = 12;
	final static private int TYPE_MESS_DELIVERED      = 15;
	final static private int TYPE_BACK_TO_LAST_SCR    = 19;
	final static private int TYPE_ACTIVATE_CL         = 20;
	final static private int TYPE_ACTIVATE_MM         = 21;
	final static private int TYPE_RESET_LOGIN_TIMER   = 22;
	final static private int TYPE_MESSAGE_REF = 25;
	final static private int TYPE_NATIVE_QUOTE_RESULT = 26;
	final static private int TYPE_PRESENCE_ONLINE = 27;
	final static private int TYPE_PRESENCE_OFFLINE = 28;
	final static private int TYPE_MESS_READ = 29;
	final static private int TYPE_RUN = 30;
	final static private int TYPE_ACTIVATE_SCREEN = 31;

//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
	final static public int TYPE_UPDATE_BUDDYICON    = 24;
//  #sijapp cond.end#


	MainThread()
	{
		_this = this;
	}
	
	private static void addMainThreadTask(int taskId, Object[] data)
	{
		int bytes = payloadBytes(data);
		for (;;)
		{
			boolean schedule, accepted = false;
			synchronized (mainThreadTasks)
			{
				// Clock/caption updates describe the latest state, not a history.
				boolean duplicate = false;
				if (taskId == TYPE_SHOW_TIME || taskId == TYPE_UPDATE_CL_CAPTION)
					for (int i = 0; i + 1 < mainThreadTasks.size(); i += 2)
						if (((Integer)mainThreadTasks.elementAt(i)).intValue() == taskId) duplicate = true;
				if (duplicate) accepted = true;
				else if (!queueFull(bytes))
				{
					int before = mainThreadTasks.size();
					try
					{
						if (taskNumbers[taskId] == null) taskNumbers[taskId] = new Integer(taskId);
						mainThreadTasks.ensureCapacity(before + 2);
						mainThreadTasks.addElement(taskNumbers[taskId]);
						mainThreadTasks.addElement(data);
						queuedBytes += bytes;
						accepted = true;
					}
					catch (Error failure)
					{
						while (mainThreadTasks.size() > before) mainThreadTasks.removeElementAt(before);
						throw failure;
					}
				}
				// A clock tick is replaceable. Never park its timer behind a full
				// UI queue while the flip is closed; the next tick retries.
				else if (taskId == TYPE_SHOW_TIME) accepted = true;
				else if (Thread.currentThread() == uiThread) throw new OutOfMemoryError();
				schedule = !queueScheduled;
				if (schedule) queueScheduled = true;
			}
			if (schedule) scheduleQueue();
			if (accepted) return;
			// Retry scheduling even when a full queue followed callSerially OOM.
			// Network producers wait; the UI never waits for itself.
			synchronized (mainThreadTasks)
			{
				if (queueFull(bytes))
					try { mainThreadTasks.wait(250); } catch (InterruptedException ignore) {}
			}
		}
	}

	private static boolean queueFull(int bytes)
	{
		return mainThreadTasks.size() >= MAX_QUEUED_EVENTS * 2
				|| (bytes > 0 && !mainThreadTasks.isEmpty() && queuedBytes + bytes > MAX_QUEUED_BYTES);
	}

	private static int payloadBytes(Object[] data)
	{
		int bytes = 0;
		if (data != null) for (int i = 0; i < data.length; i++)
		{
			Object item = data[i];
			if (item instanceof byte[]) bytes += ((byte[])item).length;
			else
			{
				String text = item instanceof Message ? ((Message)item).getText() : item instanceof String ? (String)item : null;
				if (text != null) bytes += text.length() * 2;
				if (item instanceof Message)
				{
					String name = ((Message)item).getSenderName();
					if (name != null) bytes += name.length() * 2;
				}
			}
		}
		return bytes;
	}

	private static void scheduleQueue()
	{
		try
		{
			FlipWatch.expectUI();
			Jimm.display.callSerially(_this);
		}
		catch (Throwable failure)
		{
			synchronized (mainThreadTasks) { queueScheduled = false; }
			FlipWatch.queueFailed();
			// Leave accepted events intact; the next clock/network event retries.
		}
	}

	
	/* Method run contains operations which have to be synchronized
	 with main events queue (in main thread)
	 If you want your code run in main thread, make new constant 
	 beginning of TYPE_ and write your source to switch block of 
	 RunnableImpl.run method.
	 To run you source call RunnableImpl.callSerially()
	 Note RunnableImpl.callSerially NEVER blocks calling thread */
	
	public void run()
	{
		FlipWatch.serialAlive();
		uiThread = Thread.currentThread();
		try { SplashCanvas.applyAutoLock(); }
		catch (OutOfMemoryError failure) { System.gc(); }
		catch (Throwable failure) { failure.printStackTrace(); }
		// Small batches keep key events responsive; no burst-sized snapshot.
		for (int i = 0; i < 16; i++)
		{
			int mode;
			Object[] taskData;
			synchronized (mainThreadTasks)
			{
				if (mainThreadTasks.size() < 2) break;
				mode = ((Integer)mainThreadTasks.elementAt(0)).intValue();
				taskData = (Object[])mainThreadTasks.elementAt(1);
				queuedBytes = Math.max(0, queuedBytes - payloadBytes(taskData));
				mainThreadTasks.removeElementAt(1);
				mainThreadTasks.removeElementAt(0);
				mainThreadTasks.notifyAll();
			}
			try
			{
				execureTask(mode, taskData);
			}
			catch (OutOfMemoryError e) { System.gc(); }
			catch (Throwable e)
			{
				e.printStackTrace();
			}
		}
		boolean more;
		synchronized (mainThreadTasks)
		{
			more = !mainThreadTasks.isEmpty();
			queueScheduled = more;
			mainThreadTasks.notifyAll();
		}
		if (more) scheduleQueue();
	}
	
	private static void execureTask(int type, Object[] data) throws JimmException
	{
		// Connection completion, warnings and queued Back events must keep
		// the locked screen until its PIN is entered.
		if ((type == TYPE_BACK_TO_LAST_SCR || type == TYPE_ACTIVATE_CL || type == TYPE_ACTIVATE_MM || type == TYPE_ACTIVATE_SCREEN)
				&& SplashCanvas.pinLocked())
		{
			SplashCanvas.showLockedAlert(type == TYPE_BACK_TO_LAST_SCR || type == TYPE_ACTIVATE_SCREEN ? null : (Alert) data[0]);
			return;
		}
		switch (type)
		{
		case TYPE_PRESENCE_ONLINE:
		case TYPE_PRESENCE_OFFLINE:
			jimm.comm.PresenceUpdate.apply((byte[])data[0], type == TYPE_PRESENCE_ONLINE);
			break;
//#sijapp cond.if target isnot "DEFAULT"#
		case TYPE_USER_IS_TYPING:
			ContactList.BeginTyping((String) data[0], getBoolean(data, 1));
			break;
//#sijapp cond.end#

		case TYPE_ADD_MSG:
			boolean isChecked = ContactList.addMessage((Message) data[0]);
//#sijapp cond.if target isnot "DEFAULT"#
			if (isChecked && !ContactList.readingChat(((Message) data[0]).getSndrUin())
					&& ContactList.lastAlertAllowed) {
				int duration = Options.vibrationMillis(SplashCanvas.locked());
				if (duration > 0) Jimm.display.vibrate(duration);
			}
//#sijapp cond.end#			
			break;

		case TYPE_USER_OFFLINE:
			ContactList.update((String) data[0], ContactList.STATUS_OFFLINE);
			break;

		case TYPE_SHOW_USER_INFO:
			JimmUI.showUserInfo((String[]) data[0]);
			break;

		case TYPE_UPDATE_CL_CAPTION:
			//#sijapp cond.if modules_TRAFFIC="true"#
			ContactList.updateTitle(Traffic.getSessionTraffic());
			//#sijapp cond.else#
			//#			ContactList.updateTitle(0);
			//#sijapp cond.end#
			break;

		case TYPE_UPDATE_CONTACT_LIST:
			ContactList.update((String) data[0], getInt(data, 1),
					(byte[]) data[2], (byte[]) data[3], getInt(data, 4),
					getInt(data, 5), getInt(data, 6), getInt(data, 7), getInt(data, 8), getInt(data, 9), getInt(data, 10), getInt(data, 11)
							//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
							,(byte[]) data[12]
							//  #sijapp cond.end#
			);

			break;

		//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
		case TYPE_UPDATE_BUDDYICON:
			try
			{
				ContactList.update((String)data[0], (Image)data[1], (byte[])data[2]);
				JimmUI.updateActiveUserInfo((String)data[0]);
			}
			finally { PhotoViewer.avatarCommitted(); }
			break;
		//  #sijapp cond.end#

		case TYPE_RESET_CONTACTS:
			ContactList.setStatusesOffline();
			break;
			
		case TYPE_SHOW_TIME:
			long minute = System.currentTimeMillis() / 60000;
			if (minute != clockMinute)
			{
				clockMinute = minute;
				VirtualList.setBottomText(Util.getDateString(true));
			}
			Threads.checkReconnect();
			break;
		case TYPE_RUN:
			((Runnable)data[0]).run();
			break;
		case TYPE_ACTIVATE_SCREEN:
			if (data[0] != null) ((JimmScreen)data[0]).activate();
			else JimmUI.backToLastScreen();
			break;
			
		case TYPE_ADD_CONTACT:
			ContactItem citem = (ContactItem)data[0];
			ContactList.addContactItem(citem);
			ChatHistory.updateChatIfExists(citem);
			break;
			
			
		case TYPE_MESSAGE_REF:
			ChatHistory.setMessageRef((String)data[0], getInt(data, 1), (byte[])data[2]);
			break;
		case TYPE_NATIVE_QUOTE_RESULT:
			((NativeQuote)data[0]).showResult((String)data[1]);
			break;
		case TYPE_MESS_DELIVERED:
			ChatHistory.messageIsDelivered((String)data[0], getInt(data, 1));
			break;
		case TYPE_MESS_READ:
			ChatHistory.messageIsRead((String)data[0], getInt(data, 1));
			break;
			
		case TYPE_BACK_TO_LAST_SCR:
			JimmUI.backToLastScreen();
			break;
			
		case TYPE_ACTIVATE_CL:
			Alert alert = (Alert)data[0];
			if (alert == null) ContactList.activateList();
			else ContactList.activateList(alert);
			break;
			
		case TYPE_ACTIVATE_MM:
			MainMenu.activate((Alert)data[0]);
			break;
			
		case TYPE_RESET_LOGIN_TIMER:
			ContactList.resetLoginTimer();
			break;
		}
	}

	static public void addMainThreadTask(int type, Object obj1)
	{
		addMainThreadTask(type, new Object[] { obj1 });
	}

	static public void addMainThreadTask(int type)
	{
		addMainThreadTask(type, null);
	}

	static public void addMainThreadTask(int type, Object obj1, Object obj2)
	{
		addMainThreadTask(type, new Object[] { obj1, obj2 });
	}

	///////////////////////////////////////////////////////////////////////////

	static public void updateContactListCaption()
	{
		if (ContactList.getVisibleContactListRef().isActive())
			addMainThreadTask(TYPE_UPDATE_CL_CAPTION);
	}

	static public void addMessageSerially(Object message)
	{
		addMainThreadTask(TYPE_ADD_MSG, message);
//#sijapp cond.if target is "MIDP2"#
		if (Options.getBoolean(Options.OPTION_BRING_UP)) Jimm.setMinimized(false);
//#sijapp cond.end #
	}

	static public void updateContactList(String uin, int status,
			byte[] internalIP, byte[] externalIP, int dcPort, int dcType,
			int icqProt, int authCookie, int signon, int online, int idle, int regdate
//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
			, byte[] biHash
//#sijapp cond.end#
	)
	{
		Object[] arguments;
//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
		arguments = new Object[13];
//#sijapp cond.else#
		arguments = new Object[12];
//#sijapp cond.end#

		arguments[0] = uin;
		setInt(arguments, 1, status);
		arguments[2] = internalIP;
		arguments[3] = externalIP;
		setInt(arguments, 4, dcPort);
		setInt(arguments, 5, dcType);
		setInt(arguments, 6, icqProt);
		setInt(arguments, 7, authCookie);
		setInt(arguments, 8, signon);
		setInt(arguments, 9, online);
		setInt(arguments, 10, idle);
		setInt(arguments, 11, regdate);
		//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
		arguments[12] = biHash;
		//#sijapp cond.end#

		addMainThreadTask(TYPE_UPDATE_CONTACT_LIST, arguments);
	}

	static public void updatePresence(byte[] packet, boolean online)
	{
		// Retain the immutable SNAC body, rather than copying its TLVs and
		// allocating thirteen arguments/eight boxed integers for each buddy.
		addMainThreadTask(online ? TYPE_PRESENCE_ONLINE : TYPE_PRESENCE_OFFLINE, packet);
	}

	//#sijapp cond.if target!="DEFAULT" & modules_AVATARS="true"#
	static public void updateBuddyIcon(String uin, Image image, byte[] biHashOfDone)
	{
		Object[] arguments = new Object[3];

		arguments[0] = uin;
		arguments[1] = image;
		arguments[2] = biHashOfDone;

		addMainThreadTask(TYPE_UPDATE_BUDDYICON, arguments);
	}
	//#sijapp cond.end#

	//#sijapp cond.if target isnot "DEFAULT"#
	static public void BeginTyping(String uin, boolean type)
	{
		Object[] args = new Object[2];
		args[0] = uin;
		setBoolean(args, 1, type);
		addMainThreadTask(TYPE_USER_IS_TYPING, args);
	}

	//#sijapp cond.end#

	static public void resetContactsOffline()
	{
		addMainThreadTask(TYPE_RESET_CONTACTS);
	}
	
	static public void showTime()
	{
		// The timer keeps running even if Motorola stops UI callbacks.
		JimmUI.checkAutoLock();
		addMainThreadTask(TYPE_SHOW_TIME);
	}

	public static void runSerially(Runnable work) { addMainThreadTask(TYPE_RUN, work); }
	public static void activateScreenMT(JimmScreen screen) { addMainThreadTask(TYPE_ACTIVATE_SCREEN, (Object)screen); }
	
	static public void addContact(ContactItem cItem)
	{
		addMainThreadTask(TYPE_ADD_CONTACT, cItem);
	}
	
	
	public static void setMessageRef(String uin, int messageId, byte[] ref)
	{
		addMainThreadTask(TYPE_MESSAGE_REF, new Object[] {uin, new Integer(messageId), ref});
	}
	public static void nativeQuoteResult(NativeQuote action, String error)
	{
		addMainThreadTask(TYPE_NATIVE_QUOTE_RESULT, new Object[] {action, error});
	}

	static public void messageIsDelevered(String uin, int messId)
	{
		addMainThreadTask(TYPE_MESS_DELIVERED, uin, new Integer(messId));
	}

	static public void messageIsRead(String uin, int messId)
	{
		addMainThreadTask(TYPE_MESS_READ, uin, new Integer(messId));
	}
	
	
	static public void backToLastScreenMT()
	{
		addMainThreadTask(TYPE_BACK_TO_LAST_SCR);
	}
	
	static public void activateContactListMT(Alert alert)
	{
		addMainThreadTask(TYPE_ACTIVATE_CL, alert);
	}
	
	static public void activateMainMenu(Alert alert)
	{
		addMainThreadTask(TYPE_ACTIVATE_MM, alert);
	}
	
	static public void resetLoginTimer()
	{
		addMainThreadTask(TYPE_RESET_LOGIN_TIMER);
	}
	
	static public void showUserInfo(String[] strData)
	{
		addMainThreadTask(TYPE_SHOW_USER_INFO, (Object)strData);
	}
	
	static public void userOffline(String uin)
	{
		addMainThreadTask(TYPE_USER_OFFLINE, uin);
	}

	///////////////////////////////////////////////////////////////////////////
	///////////////////////////////////////////////////////////////////////////
	///////////////////////////////////////////////////////////////////////////

	static public void setBoolean(Object[] data, int index, boolean value)
	{
		data[index] = new Boolean(value);
	}

	static public boolean getBoolean(Object[] data, int index)
	{
		return (data[index] == null) ? false : ((Boolean) data[index])
				.booleanValue();
	}

	static public void setLong(Object[] data, int index, long value)
	{
		data[index] = new Long(value);
	}

	static public long getLong(Object[] data, int index)
	{
		return (data[index] == null) ? 0 : ((Long) data[index]).longValue();
	}

	static public void setInt(Object[] data, int index, int value)
	{
		data[index] = new Integer(value);
	}

	static public int getInt(Object[] data, int index)
	{
		return (data[index] == null) ? 0 : ((Integer) data[index]).intValue();
	}

}
