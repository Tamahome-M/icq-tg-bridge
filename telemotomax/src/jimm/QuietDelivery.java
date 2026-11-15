//#sijapp cond.if modules_MOTOMAGX="true"#
package jimm;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import javax.microedition.lcdui.Choice;
import javax.microedition.lcdui.ChoiceGroup;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Form;
import javax.microedition.lcdui.StringItem;
import javax.microedition.rms.RecordStore;
import jimm.comm.Icq;
import jimm.comm.SnacPacket;
import jimm.comm.Util;
import jimm.comm.connections.Connection;
import jimm.util.ResourceBundle;

/** Local quiet-delivery choices; the bridge receives only a session snapshot. */
public final class QuietDelivery implements CommandListener, JimmScreen
{
	private static final String STORE = "tmm-quiet";
	private static final int MAX_CHATS = 256;
	private static String loadedScope;
	private static volatile String sessionScope;
	private static Connection sessionConnection;
	private static int recordId;
	private static int[] chats = new int[0];

	private final String scope;
	private final int uin;
	private final JimmScreen back;
	private final Form form;
	private final ChoiceGroup mode;
	private final StringItem status;
	private final Command save = new Command(ResourceBundle.getString("save"), Command.OK, 1);
	private final Command retry = new Command(ResourceBundle.getString("quiet_retry"), Command.SCREEN, 2);
	private boolean closed, loaded;

	// Length prefixes make the exact identity unambiguous, including host lists.
	private static String scope(String host, String port, String owner)
	{
		return host.length() + ":" + host + port.length() + ":" + port + owner.length() + ":" + owner;
	}

	private static String configuredScope()
	{
		return scope(Options.getString(Options.OPTION_SRV_HOST),
				Options.getString(Options.OPTION_SRV_PORT), Options.getString(Options.OPTION_UIN));
	}

	private static synchronized void load(String wanted) throws Exception
	{
		if (wanted.equals(loadedScope)) return;
		RecordStore store = RecordStore.openRecordStore(STORE, true);
		try
		{
			int found = 0;
			int[] values = new int[0];
			// This store never deletes individual records, so IDs stay contiguous.
			for (int id = 1; id <= store.getNumRecords(); id++)
			{
				byte[] data = store.getRecord(id);
				if (data.length > 8192) throw new IOException();
				DataInputStream in = new DataInputStream(new ByteArrayInputStream(data));
				if (in.readUnsignedByte() != 1) throw new IOException();
				String savedScope = in.readUTF();
				if (!wanted.equals(savedScope)) continue;
				int count = in.readUnsignedShort();
				if (count > MAX_CHATS || in.available() != count * 4) throw new IOException();
				values = new int[count];
				for (int i = 0; i < count; i++)
				{
					values[i] = in.readInt();
					if (values[i] <= 0) throw new IOException();
					for (int j = 0; j < i; j++) if (values[j] == values[i]) throw new IOException();
				}
				found = id;
				break;
			}
			chats = values; recordId = found; loadedScope = wanted;
		}
		finally { try { store.closeRecordStore(); } catch (Exception ignore) {} }
	}

	private static int index(int uin)
	{
		for (int i = 0; i < chats.length; i++) if (chats[i] == uin) return i;
		return -1;
	}

	private static synchronized void persist(String wanted, int uin, boolean quiet) throws Exception
	{
		load(wanted);
		int old = index(uin);
		if ((old >= 0) == quiet) return;
		if (quiet && chats.length == MAX_CHATS) throw new IOException(ResourceBundle.getString("quiet_limit"));
		int[] next = new int[chats.length + (quiet ? 1 : -1)];
		if (quiet)
		{
			System.arraycopy(chats, 0, next, 0, chats.length);
			next[chats.length] = uin;
		}
		else
		{
			System.arraycopy(chats, 0, next, 0, old);
			System.arraycopy(chats, old + 1, next, old, chats.length - old - 1);
		}
		ByteArrayOutputStream bytes = new ByteArrayOutputStream();
		DataOutputStream out = new DataOutputStream(bytes);
		out.writeByte(1); out.writeUTF(wanted); out.writeShort(next.length);
		for (int i = 0; i < next.length; i++) out.writeInt(next[i]);
		byte[] data = bytes.toByteArray();
		RecordStore store = RecordStore.openRecordStore(STORE, true);
		try
		{
			if (recordId == 0) recordId = store.addRecord(data, 0, data.length);
			else store.setRecord(recordId, data, 0, data.length);
			chats = next;
		}
		finally { try { store.closeRecordStore(); } catch (Exception ignore) {} }
	}

	private static synchronized SnacPacket packet(String wanted) throws Exception
	{
		load(wanted);
		byte[] data = new byte[2 + chats.length * 4];
		Util.putWord(data, 0, chats.length);
		for (int i = 0; i < chats.length; i++) Util.putDWord(data, 2 + i * 4, chats[i]);
		return new SnacPacket(0x0001, 0x00F3, Util.getCounter(), new byte[0], data);
	}

	/** Before READY/offline delivery, including an explicitly empty list. */
	public static void sync(Connection connection, String host, String port, String owner) throws JimmException
	{
		String wanted = scope(host, port, owner);
		SnacPacket snapshot;
		try { snapshot = packet(wanted); }
		catch (Exception failure) { throw new JimmException(120, 87, true); }
		connection.sendPacket(snapshot);
		// A slow old socket may finish after a replacement login has synced.
		// Match disconnect's Icq -> QuietDelivery lock order when publishing.
		synchronized (Icq.class)
		{
			if (!Icq.isCurrentConnection(Thread.currentThread(), connection)) return;
			synchronized (QuietDelivery.class)
			{
				sessionScope = wanted;
				sessionConnection = connection;
			}
		}
	}

	public static synchronized void disconnected()
	{
		sessionConnection = null;
		sessionScope = null;
	}

	private QuietDelivery(String uin, String name, JimmScreen back)
	{
		this.uin = Integer.parseInt(uin);
		if (this.uin <= 0) throw new IllegalArgumentException();
		String active = sessionScope;
		this.scope = Icq.isConnected() && active != null ? active : configuredScope();
		this.back = back;
		form = new Form(ResourceBundle.getString("quiet_delivery"));
		mode = new ChoiceGroup(name, Choice.POPUP, new String[] {
			ResourceBundle.getString("quiet_normal"), ResourceBundle.getString("quiet_silent") }, null);
		status = new StringItem(null, "");
		form.append(status);
		form.addCommand(JimmUI.cmdBack);
		form.setCommandListener(this);
		read();
	}

	public static void show(String uin, String name, JimmScreen back)
	{
		QuietDelivery screen = new QuietDelivery(uin, name, back);
		MainThread.activateScreenMT(screen);
	}

	private void read()
	{
		try
		{
			synchronized (QuietDelivery.class)
			{
				load(scope);
				mode.setSelectedIndex(index(uin) >= 0 ? 1 : 0, true);
			}
			if (!loaded) form.append(mode);
			loaded = true;
			status.setText(ResourceBundle.getString("quiet_hint"));
			form.removeCommand(retry); form.addCommand(save);
		}
		catch (Exception failure)
		{
			status.setText(ResourceBundle.getString("quiet_storage_error"));
			form.addCommand(retry);
		}
	}

	public void commandAction(Command command, Displayable displayable)
	{
		if (closed || displayable != form) return;
		if (command == JimmUI.cmdBack)
		{
			closed = true;
			MainThread.activateScreenMT(back);
		}
		else if (command == retry) read();
		else if (command == save && loaded)
		{
			try { persist(scope, uin, mode.getSelectedIndex() == 1); }
			catch (Exception failure)
			{
				String reason = failure.getMessage();
				status.setText(reason == null ? ResourceBundle.getString("quiet_storage_error") : reason);
				return;
			}
			boolean sent = false;
			if (Icq.isConnected())
			{
				try
				{
					Connection target;
					SnacPacket snapshot;
					synchronized (QuietDelivery.class)
					{
						target = scope.equals(sessionScope) ? sessionConnection : null;
						snapshot = target == null ? null : packet(scope);
					}
					// Never redirect an old form's update into a newly logged-in account.
					if (target != null) { target.sendPacket(snapshot); sent = true; }
				}
				catch (Exception failure) { /* Keep the local choice for reconnect. */ }
			}
			status.setText(ResourceBundle.getString(sent ? "quiet_saved" : "quiet_saved_offline"));
		}
	}

	public void activate() { if (!closed) Jimm.display.setCurrent(form); }
	public boolean isScreenActive() { return !closed && form.isShown(); }
}
//#sijapp cond.end#
