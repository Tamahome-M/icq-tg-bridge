/* TeleMotoMax: experimental flip inference, journal only. */
package jimm;

public final class FlipWatch
{
	private static final int UNKNOWN = 0, OPEN = 1, CLOSED = 2,
			BACKGROUND = 3, TIMER_GAP = 4, QUEUE_ERROR = 5;
	private static int state;
	private static long lastTick, waitingSince;
	private static boolean expected;
	private static boolean reportPending;
	private static String pendingReason;
	private static long pendingSilence;
	private static final long SILENCE = 30000, MAX_TICK_GAP = 25000;

	// The existing ten-second timer must actually keep running. A long
	// pause of the whole VM is insufficient evidence of a closed flip.
	public static void tick(long now)
	{
		synchronized (FlipWatch.class)
		{
			if (state != BACKGROUND)
			{
				if (lastTick == 0) waitingSince = expected ? now : 0;
				else if (now < lastTick || now - lastTick > MAX_TICK_GAP)
				{
					change(TIMER_GAP, "задержка таймера", Math.max(0, now - lastTick));
					waitingSince = expected ? now : 0;
				}
				lastTick = now;
				if (expected && state != CLOSED && now - waitingSince >= SILENCE)
					change(CLOSED, null, now - waitingSince);
			}
		}
		report();
	}

	public static void expectUI() { expectUI(System.currentTimeMillis()); }
	static synchronized void expectUI(long now)
	{
		if (state == BACKGROUND) return;
		if (!expected) waitingSince = now;
		expected = true;
	}

	public static void serialAlive() { ui(System.currentTimeMillis(), "очередь интерфейса", true); }
	public static void uiAlive(String reason) { ui(System.currentTimeMillis(), reason, false); }
	static synchronized void ui(long now, String reason, boolean serial)
	{
		if (state == BACKGROUND) return;
		long silence = state == CLOSED ? Math.max(0, now - waitingSince) : 0;
		if (serial) expected = false;
		waitingSince = expected ? now : 0;
		change(OPEN, reason, silence);
	}

	public static synchronized void queueFailed()
	{
		if (state == BACKGROUND) return;
		expected = false;
		waitingSince = 0;
		change(QUEUE_ERROR, "ошибка очереди интерфейса", 0);
	}

	public static synchronized void background()
	{
		expected = false;
		lastTick = waitingSince = 0;
		change(BACKGROUND, "приложение в фоне", 0);
	}

	public static synchronized void resume()
	{
		if (state == OPEN) return;
		expected = false;
		lastTick = waitingSince = 0;
		change(UNKNOWN, "возврат; ждём интерфейс", 0);
	}

	private static void change(int next, String reason, long silence)
	{
		if (state == next) return;
		state = next;
		// Callbacks also run during cold startup, under native UI locks.
		// Only record evidence here; no journal, settings or display calls.
		pendingReason = reason;
		pendingSilence = silence;
		reportPending = true;
	}

	// The existing timer starts after initialization. Coalesce transitions
	// between its ticks and never hold our monitor while writing the journal.
	static void report()
	{
		int next;
		String reason;
		long silence;
		synchronized (FlipWatch.class)
		{
			if (!reportPending) return;
			next = state;
			reason = pendingReason;
			silence = pendingSilence;
			pendingReason = null;
			reportPending = false;
		}
		// Optional logging must not interrupt the timer even after an OOM.
		try
		{
			String message;
			if (next == CLOSED)
				message = "флип? закрыт: интерфейс молчит " + (silence / 1000) + " с; таймер жив";
			else
			{
				message = (next == OPEN ? "флип? открыт: " : "флип? неизвестно: ") + reason;
				if (silence > 0) message += " (" + (silence / 1000) + " с)";
			}
			ConnLog.note(message);
		}
		catch (Throwable ignore) {}
	}
}
