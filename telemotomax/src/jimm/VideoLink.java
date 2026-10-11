package jimm;

import jimm.comm.Util;

/** A labelled video link carried in message text, without displaying its URL. */
public final class VideoLink
{
	public static final String LABEL = "[видео]";
	private static final String PREFIX = LABEL + "(";

	public static int start(String text)
	{
		if (text == null) return -1;
		int start = text.indexOf(PREFIX);
		while (start >= 0)
		{
			int from = start + PREFIX.length();
			int end = text.indexOf(')', from);
			if (end > from && end - from <= 2048)
			{
				boolean valid = text.startsWith("http://", from) || text.startsWith("https://", from);
				for (int i = from; valid && i < end; i++)
				{
					char ch = text.charAt(i);
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
		return start < 0 ? null : text.substring(start + PREFIX.length(), text.indexOf(')', start + PREFIX.length()));
	}

	/** The browser URL belongs in VideoMenu, ordinary caption links stay visible. */
	public static String visibleText(String text)
	{
		int start = start(text);
		return start < 0 ? text : text.substring(0, start) + LABEL + text.substring(text.indexOf(')', start + PREFIX.length()) + 1);
	}

	/** Check caption links in the original ranges without copying the caption. */
	public static boolean hasVisibleURL(String text)
	{
		int start = start(text);
		if (start < 0) return Util.hasURL(text);
		return Util.hasURL(text, 0, start)
				|| Util.hasURL(text, text.indexOf(')', start + PREFIX.length()) + 1, text.length());
	}

	public static void open(String url)
	{
		try { Jimm.jimm.platformRequest(url); }
		catch (Exception e) { ConnLog.note("не удалось открыть видео в браузере"); }
	}
}
