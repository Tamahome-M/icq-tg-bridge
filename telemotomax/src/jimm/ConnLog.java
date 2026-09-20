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

import jimm.comm.Util;

/**
 * Короткая память о связи: последние события — обрыв, решение
 * (повтор, ожидание сети, ошибка), попытка, успех — с временем. Показывается
 * в «О программе», чтобы по «телефон лежит отключённый» было видно, что
 * именно произошло, а не гадать. Восемь строк, старые вытесняются.
 */
public final class ConnLog
{
	private static final int SIZE = 8;
	private static final String[] lines = new String[SIZE];
	private static int next;

	public static synchronized void note(String what)
	{
		lines[next] = Util.getDateString(true) + " " + what;
		next = (next + 1) % SIZE;
	}

	/** Строки от старой к новой, пустые пропущены. */
	public static synchronized String text()
	{
		StringBuffer sb = new StringBuffer();
		for (int i = 0; i < SIZE; i++)
		{
			String s = lines[(next + i) % SIZE];
			if (s == null) continue;
			if (sb.length() != 0) sb.append('\n');
			sb.append(s);
		}
		return sb.toString();
	}
}
