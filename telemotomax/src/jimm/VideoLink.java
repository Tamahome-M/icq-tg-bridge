package jimm;

/** A labelled video link carried in message text, without displaying its URL. */
public final class VideoLink
{
	public static final String LABEL = "[видео]";
	private static final String PREFIX = LABEL + "(";

	public static boolean browserMode()
	{
		//#sijapp cond.if modules_VIDEO_BROWSER="true"#
		return true;
		//#sijapp cond.else#
		//# return false;
		//#sijapp cond.end#
	}

	public static int start(String text)
	{
		if (!browserMode() || text == null) return -1;
		int start = text.indexOf(PREFIX);
		while (start >= 0)
		{
			int from = start + PREFIX.length();
			int end = text.indexOf(')', from);
			if (end > from && end - from <= 2048)
			{
				String url = text.substring(from, end);
				boolean valid = url.startsWith("http://") || url.startsWith("https://");
				for (int i = 0; valid && i < url.length(); i++)
				{
					char ch = url.charAt(i);
					if (ch <= ' ' || ch == '<' || ch == '>' || ch == '"') valid = false;
				}
				if (valid) return start;
			}
			start = text.indexOf(PREFIX, start + PREFIX.length());
		}
		return -1;
	}

	public static int end(String text)
	{
		int start = start(text);
		return start < 0 ? -1 : text.indexOf(')', start + PREFIX.length()) + 1;
	}

	public static String url(String text)
	{
		int start = start(text);
		return start < 0 ? null : text.substring(start + PREFIX.length(), end(text) - 1);
	}

	public static void open(String url)
	{
		try { Jimm.jimm.platformRequest(url); }
		catch (Exception e) { ConnLog.note("не удалось открыть видео в браузере"); }
	}
}
