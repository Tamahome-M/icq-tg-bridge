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

import java.util.Enumeration;
import javax.microedition.io.Connector;
import javax.microedition.io.file.FileConnection;
import javax.microedition.io.file.FileSystemRegistry;

/**
 * Временный файл там, куда телефон даёт писать (JSR-75). Проверять корень
 * через canWrite() на ещё не созданном файле нельзя: V8 отвечает «нет»,
 * хотя писать можно, — плеер и запись кружка из-за этого годами говорили
 * «no writable root» при живом доступе к файлам. Единственная честная
 * проверка — создать файл: сначала в подкаталоге tmm/ (как загрузчик
 * файлов), потом в самом корне.
 */
final class TempFiles
{
	/** Последняя ошибка при поиске места — для экрана «Видео недоступно». */
	static String lastError = "";

	private TempFiles() {}

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
		try
		{
			Enumeration roots = FileSystemRegistry.listRoots();
			while (roots.hasMoreElements())
			{
				String root = (String) roots.nextElement();
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
						if (dirs[i].endsWith("tmm/"))
						{
							FileConnection d = (FileConnection) Connector.open(dirs[i], Connector.READ_WRITE);
							try { if (!d.exists()) d.mkdir(); } finally { d.close(); }
						}
						FileConnection fc = (FileConnection) Connector.open(url, Connector.READ_WRITE);
						try
						{
							if (fc.exists()) fc.delete();
							fc.create();
						}
						finally { fc.close(); }
						return url;
					}
					catch (Exception e)
					{
						String n = e.getClass().getName();
						int dot = n.lastIndexOf('.');
						lastError = (dot >= 0 ? n.substring(dot + 1) : n)
								+ (e.getMessage() != null ? ": " + e.getMessage() : "");
					}
				}
			}
			if (lastError.length() == 0) lastError = "no roots";
		}
		catch (Exception e) { lastError = String.valueOf(e); }
		// Создать заранее не вышло нигде — спросим по-старому, canWrite():
		// на V3 такая проверка работала годами, а создаёт файл уже тот,
		// кто в него пишет. (На V8 canWrite() врёт — потому она второй.)
		String probed = probeByCanWrite(name);
		if (probed != null) lastError = "";
		return probed;
	}

	private static String probeByCanWrite(String name)
	{
		try
		{
			Enumeration roots = FileSystemRegistry.listRoots();
			while (roots.hasMoreElements())
			{
				String root = (String) roots.nextElement();
				while (root.length() > 0 && root.charAt(0) == '/') root = root.substring(1);
				if (root.length() > 0 && !root.endsWith("/")) root += "/";
				String url = "file:///" + root + name;
				try
				{
					FileConnection fc = (FileConnection) Connector.open(url, Connector.READ_WRITE);
					boolean ok = fc.canWrite();
					fc.close();
					if (ok) return url;
				}
				catch (Exception e)
				{
					if (lastError.length() == 0) lastError = String.valueOf(e);
				}
			}
		}
		catch (Exception e) { if (lastError.length() == 0) lastError = String.valueOf(e); }
		return null;
	}
}
