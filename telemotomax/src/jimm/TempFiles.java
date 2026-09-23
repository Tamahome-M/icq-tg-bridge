/*******************************************************************************
 TeleMotoMax - Jimm fork for icq-tg-bridge

 This program is free software; you can redistribute it and/or
 modify it under the terms of the GNU General Public License
 as published by the Free Software Foundation; either version 2
 of the License, or (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.
 *******************************************************************************/

package jimm;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Enumeration;
import java.util.Vector;
import javax.microedition.io.Connection;
import javax.microedition.io.Connector;

/**
 * Временный файл там, куда телефон даёт писать.
 *
 * Файловых API у этих телефонов два, и они несовместимы: на V8 (MOTOMAGX)
 * это JSR-75 (`javax.microedition.io.file`), а на V3 (P2K) его нет вовсе —
 * там фирменный `com.motorola.io`. Выбор делается тем же способом, что в
 * обозревателе файлов Jimm: есть ли класс JSR-75. Работа с каждым API
 * лежит в своём классе, чтобы отсутствующий на телефоне не загружался.
 *
 * Проверять корень через canWrite() на ещё не созданном файле нельзя: V8
 * отвечает «нет», хотя писать можно, — плеер из-за этого говорил «no
 * writable root» при живом доступе к файлам. Честная проверка — создать
 * файл; canWrite() остаётся запасной (на V3 она работала годами).
 */
final class TempFiles
{
	/** Последняя ошибка при поиске места — для экрана «Видео недоступно». */
	static String lastError = "";

	private static Files api;

	private TempFiles() {}

	/** То немногое из файлового API, что нужно плееру и записи. */
	interface Files
	{
		String[] roots() throws IOException;
		void mkdir(String url) throws IOException;
		void recreate(String url) throws IOException;   // заново: был — удалить
		void remove(String url) throws IOException;
		boolean canWrite(String url) throws IOException;
		OutputStream out(String url) throws IOException;
		InputStream in(String url) throws IOException;
		long size(String url) throws IOException;
	}

	static Files api()
	{
		if (api == null)
		{
			try
			{
				Class.forName("javax.microedition.io.file.FileConnection");
				api = new JsrFiles();
			}
			catch (Throwable t) { api = new MotoFiles(); }
		}
		return api;
	}

	/** Какой API выбран — строкой для журнала и экрана ошибки. */
	static String apiName()
	{
		return (api() instanceof MotoFiles) ? "com.motorola.io" : "JSR-75";
	}

	/** Адрес созданного пустого файла с таким именем, или null. */
	static String writableUrl(String name)
	{
		return writableUrl(name, false);
	}

	/**
	 * rootFirst — сначала пробовать сам корень, потом tmm/: плееру проще
	 * короткий путь (так он играл на V3), а загрузчику файлов приятнее
	 * складывать скачанное в tmm/.
	 */
	static String writableUrl(String name, boolean rootFirst)
	{
		lastError = "";
		Files files = api();
		String[] roots;
		try { roots = files.roots(); }
		catch (Throwable t) { lastError = apiName() + ", корни: " + shortName(t); return null; }
		if (roots == null || roots.length == 0)
		{
			lastError = apiName() + ": корней нет";
			return null;
		}
		// Отчёт собираем сразу: по одной строке «no writable root» на экране
		// не понять, каких корней телефон не дал и на чём именно отказал.
		StringBuffer seen = new StringBuffer(apiName() + ", корни:");
		for (int r = 0; r < roots.length; r++) seen.append(' ').append(roots[r]);
		String created = "", allowed = "";
		for (int r = 0; r < roots.length; r++)
		{
			String root = roots[r];
			while (root.length() > 0 && root.charAt(0) == '/') root = root.substring(1);
			if (root.length() > 0 && !root.endsWith("/")) root += "/";
			String[] dirs = rootFirst
					? new String[] { "file:///" + root, "file:///" + root + "tmm/" }
					: new String[] { "file:///" + root + "tmm/", "file:///" + root };
			for (int i = 0; i < dirs.length; i++)
			{
				String url = dirs[i] + name;
				try
				{
					if (dirs[i].endsWith("tmm/")) files.mkdir(dirs[i]);
					files.recreate(url);
					return url;
				}
				catch (Throwable t)
				{
					if (created.length() == 0) created = shortName(t);
				}
			}
		}
		// Создать заранее не вышло нигде — спросим по-старому, canWrite():
		// создаёт файл уже тот, кто в него пишет. (На V8 canWrite() врёт —
		// потому она второй.)
		for (int r = 0; r < roots.length; r++)
		{
			String root = roots[r];
			while (root.length() > 0 && root.charAt(0) == '/') root = root.substring(1);
			if (root.length() > 0 && !root.endsWith("/")) root += "/";
			String url = "file:///" + root + name;
			try
			{
				if (files.canWrite(url)) { lastError = ""; return url; }
				if (allowed.length() == 0) allowed = "нет";
			}
			catch (Throwable t) { if (allowed.length() == 0) allowed = shortName(t); }
		}
		lastError = seen + "; создать: " + (created.length() > 0 ? created : "?")
				+ "; canWrite: " + (allowed.length() > 0 ? allowed : "?");
		return null;
	}

	static OutputStream out(String url) throws IOException { return api().out(url); }

	static InputStream in(String url) throws IOException { return api().in(url); }

	static long size(String url)
	{
		try { return api().size(url); }
		catch (Throwable t) { return -1; }
	}

	static void remove(String url)
	{
		if (url == null) return;
		try { api().remove(url); }
		catch (Throwable ignore) {}
	}

	static String shortName(Throwable t)
	{
		if (t == null) return "?";
		String n = t.getClass().getName();
		int dot = n.lastIndexOf('.');
		return (dot >= 0 ? n.substring(dot + 1) : n)
				+ (t.getMessage() != null ? ": " + t.getMessage() : "");
	}

	/** Поток, закрывающий заодно и соединение: порознь их держать незачем. */
	static final class ConnOut extends OutputStream
	{
		private final Connection conn;
		private final OutputStream os;

		ConnOut(Connection conn, OutputStream os) { this.conn = conn; this.os = os; }

		public void write(int b) throws IOException { os.write(b); }
		public void write(byte[] b) throws IOException { os.write(b); }
		public void write(byte[] b, int off, int len) throws IOException { os.write(b, off, len); }
		public void flush() throws IOException { os.flush(); }

		public void close() throws IOException
		{
			try { os.close(); } finally { conn.close(); }
		}
	}

	static final class ConnIn extends InputStream
	{
		private final Connection conn;
		private final InputStream is;

		ConnIn(Connection conn, InputStream is) { this.conn = conn; this.is = is; }

		public int read() throws IOException { return is.read(); }
		public int read(byte[] b, int off, int len) throws IOException { return is.read(b, off, len); }
		public int available() throws IOException { return is.available(); }

		public void close() throws IOException
		{
			try { is.close(); } finally { conn.close(); }
		}
	}
}

/** Файлы по JSR-75 — V8 (MOTOMAGX) и вообще всё, где он есть. */
final class JsrFiles implements TempFiles.Files
{
	private javax.microedition.io.file.FileConnection open(String url, int mode) throws IOException
	{
		return (javax.microedition.io.file.FileConnection) Connector.open(url, mode);
	}

	public String[] roots() throws IOException
	{
		Vector v = new Vector();
		Enumeration e = javax.microedition.io.file.FileSystemRegistry.listRoots();
		while (e.hasMoreElements()) v.addElement(e.nextElement());
		String[] out = new String[v.size()];
		v.copyInto(out);
		return out;
	}

	public void mkdir(String url) throws IOException
	{
		javax.microedition.io.file.FileConnection d = open(url, Connector.READ_WRITE);
		try { if (!d.exists()) d.mkdir(); } finally { d.close(); }
	}

	public void recreate(String url) throws IOException
	{
		javax.microedition.io.file.FileConnection fc = open(url, Connector.READ_WRITE);
		try { if (fc.exists()) fc.delete(); fc.create(); } finally { fc.close(); }
	}

	public void remove(String url) throws IOException
	{
		javax.microedition.io.file.FileConnection fc = open(url, Connector.READ_WRITE);
		try { if (fc.exists()) fc.delete(); } finally { fc.close(); }
	}

	public boolean canWrite(String url) throws IOException
	{
		javax.microedition.io.file.FileConnection fc = open(url, Connector.READ_WRITE);
		try { return fc.canWrite(); } finally { fc.close(); }
	}

	public OutputStream out(String url) throws IOException
	{
		javax.microedition.io.file.FileConnection fc = open(url, Connector.READ_WRITE);
		try
		{
			if (!fc.exists()) fc.create();
			return new TempFiles.ConnOut(fc, fc.openOutputStream());
		}
		catch (IOException e) { try { fc.close(); } catch (Exception ignore) {} throw e; }
	}

	public InputStream in(String url) throws IOException
	{
		javax.microedition.io.file.FileConnection fc = open(url, Connector.READ);
		try { return new TempFiles.ConnIn(fc, fc.openInputStream()); }
		catch (IOException e) { try { fc.close(); } catch (Exception ignore) {} throw e; }
	}

	public long size(String url) throws IOException
	{
		javax.microedition.io.file.FileConnection fc = open(url, Connector.READ);
		try { return fc.fileSize(); } finally { fc.close(); }
	}
}

/** Файлы по фирменному API Motorola — V3 (P2K), где JSR-75 нет. */
final class MotoFiles implements TempFiles.Files
{
	private com.motorola.io.FileConnection open(String url) throws IOException
	{
		return (com.motorola.io.FileConnection) Connector.open(url);
	}

	public String[] roots() throws IOException
	{
		return com.motorola.io.FileSystemRegistry.listRoots();
	}

	public void mkdir(String url) throws IOException
	{
		com.motorola.io.FileConnection d = open(url);
		try { if (!d.exists()) d.mkdir(); } finally { d.close(); }
	}

	public void recreate(String url) throws IOException
	{
		com.motorola.io.FileConnection fc = open(url);
		try { if (fc.exists()) fc.delete(); fc.create(); } finally { fc.close(); }
	}

	public void remove(String url) throws IOException
	{
		com.motorola.io.FileConnection fc = open(url);
		try { if (fc.exists()) fc.delete(); } finally { fc.close(); }
	}

	public boolean canWrite(String url) throws IOException
	{
		com.motorola.io.FileConnection fc = open(url);
		try { return fc.canWrite(); } finally { fc.close(); }
	}

	public OutputStream out(String url) throws IOException
	{
		com.motorola.io.FileConnection fc = open(url);
		try
		{
			if (!fc.exists()) fc.create();
			return new TempFiles.ConnOut(fc, fc.openOutputStream());
		}
		catch (IOException e) { try { fc.close(); } catch (Exception ignore) {} throw e; }
	}

	public InputStream in(String url) throws IOException
	{
		com.motorola.io.FileConnection fc = open(url);
		try { return new TempFiles.ConnIn(fc, fc.openInputStream()); }
		catch (IOException e) { try { fc.close(); } catch (Exception ignore) {} throw e; }
	}

	public long size(String url) throws IOException
	{
		com.motorola.io.FileConnection fc = open(url);
		try { return fc.fileSize(); } finally { fc.close(); }
	}
}
