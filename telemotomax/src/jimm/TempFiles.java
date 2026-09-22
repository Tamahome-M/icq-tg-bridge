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
		lastError = "";
		try
		{
			Enumeration roots = FileSystemRegistry.listRoots();
			while (roots.hasMoreElements())
			{
				String root = (String) roots.nextElement();
				while (root.length() > 0 && root.charAt(0) == '/') root = root.substring(1);
				if (root.length() > 0 && !root.endsWith("/")) root += "/";
				String[] dirs = { "file:///" + root + "tmm/", "file:///" + root };
				for (int i = 0; i < dirs.length; i++)
				{
					String url = dirs[i] + name;
					try
					{
						if (i == 0)
						{
							FileConnection d = (FileConnection) Connector.open(dirs[0], Connector.READ_WRITE);
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
		return null;
	}
}
