package jimm;

import DrawControls.VirtualList;

/** Physical cover state. No MIDP visibility or timing heuristic is used. */
public abstract class FlipState
{
	private static FlipState reader;
	private static boolean attempted;
	private static volatile int state = -1;
	private static long closedAt;

	protected abstract int readState();

	/** Called by the existing UI clock, even while the cover is closed. */
	public static synchronized boolean poll()
	{
		if (!attempted)
		{
			attempted = true;
			try
			{
				// Keep the vendor dependency out of the ordinary MIDlet's verifier.
				reader = (FlipState)Class.forName("jimm.VodafoneFlipState").newInstance();
			}
			catch (Throwable unavailable)
			{
				ConnLog.note("Крышка: API недоступен (" + unavailable.getClass().getName() + ")");
			}
		}
		if (reader == null) return false;
		int next;
		try
		{
			next = reader.readState();
			if (next != 0 && next != 1) throw new IllegalStateException();
		}
		catch (Throwable unavailable)
		{
			boolean changed = state != -1;
			state = -1;
			closedAt = 0;
			reader = null;
			VirtualList.touch();
			ConnLog.note("Крышка: API недоступен (" + unavailable.getClass().getName() + ")");
			return changed;
		}
		if (next == state) return false;
		closedAt = next == 1 ? System.currentTimeMillis() : 0;
		state = next;
		ConnLog.note(next == 1 ? "Крышка: закрыта" : "Крышка: открыта");
		return true;
	}

	public static boolean supported() { return state >= 0; }
	public static boolean closed() { return state == 1; }
	public static boolean notificationLocked() { return closed() || SplashCanvas.locked(); }

	public static synchronized boolean lockDue()
	{
		if (state != 1) return false;
		int minutes = Options.autoLockMinutes();
		return minutes > 0
				&& System.currentTimeMillis() - closedAt >= minutes * 60000L;
	}
}
