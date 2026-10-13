package jimm;

/** One startup deadline shared by message sounds and vibration; no timer. */
public final class MessageAlerts
{
	private static volatile long quietUntil;

	public static synchronized void start()
	{
		if (quietUntil == 0) quietUntil = System.currentTimeMillis() + 60000L;
	}

	public static boolean allowed()
	{
		long deadline = quietUntil;
		if (deadline <= 0) return true;
		if (System.currentTimeMillis() < deadline) return false;
		quietUntil = -1; // Expired permanently: resume/reconnect never restart it.
		return true;
	}
}
