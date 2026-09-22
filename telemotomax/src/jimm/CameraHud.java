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

import javax.microedition.lcdui.Font;
import javax.microedition.lcdui.Graphics;

//#sijapp cond.if modules_CAMERA="true"#
/**
 * Общие подсказки поверх видоискателя у экранов камеры (фото и кружок),
 * чтобы с первого взгляда было видно, что это за экран, что сейчас
 * происходит и какая клавиша что делает: полоса сверху — режим слева и
 * состояние справа (размер снимка, таймер записи, ход отправки), полоса
 * снизу — клавиши, красная мигающая точка — идёт запись.
 */
final class CameraHud
{
	static final Font FONT = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_BOLD, Font.SIZE_SMALL);
	static final Font SMALL = Font.getFont(Font.FACE_PROPORTIONAL, Font.STYLE_PLAIN, Font.SIZE_SMALL);
	static final int BAND = 0x000000, TEXT = 0xFFFFFF, DIM = 0xC0C0C0, REC = 0xFF3030, WARN = 0xFFD040;

	private CameraHud() {}

	/** Полоса сверху: слева режим (жирным), справа — состояние своим цветом. */
	static void top(Graphics g, int width, String left, String right, int rightColor)
	{
		int h = FONT.getHeight() + 6;
		g.setColor(BAND);
		g.fillRect(0, 0, width, h);
		g.setFont(FONT);
		g.setColor(TEXT);
		if (left != null) g.drawString(left, 4, 3, Graphics.LEFT | Graphics.TOP);
		if (right != null)
		{
			g.setColor(rightColor);
			g.drawString(right, width - 4, 3, Graphics.RIGHT | Graphics.TOP);
		}
	}

	/** Полоса снизу: подсказки клавиш, одна или две строки. */
	static void bottom(Graphics g, int width, int height, String line1, String line2)
	{
		int step = SMALL.getHeight();
		int h = (line2 == null ? 1 : 2) * step + 6;
		g.setColor(BAND);
		g.fillRect(0, height - h, width, h);
		g.setFont(SMALL);
		g.setColor(DIM);
		int y = height - h + 3;
		g.drawString(line1, width / 2, y, Graphics.HCENTER | Graphics.TOP);
		if (line2 != null) g.drawString(line2, width / 2, y + step, Graphics.HCENTER | Graphics.TOP);
	}

	/** Красная точка записи; мигает — полсекунды видна, полсекунды нет. */
	static void recDot(Graphics g, int x, int y, int size)
	{
		if ((System.currentTimeMillis() / 500) % 2 == 0) return;
		g.setColor(REC);
		g.fillArc(x, y, size, size, 0, 360);
	}

	/** Сообщение посередине на тёмной плашке: «открываю камеру», ошибка. */
	static void box(Graphics g, int width, int height, String text, String[] details)
	{
		int step = SMALL.getHeight();
		int lines = 1 + (details == null ? 0 : details.length);
		int h = lines * step + 8;
		int y0 = (height - h) / 2;
		g.setColor(BAND);
		g.fillRect(0, y0, width, h);
		g.setFont(FONT);
		g.setColor(TEXT);
		g.drawString(text, width / 2, y0 + 4, Graphics.HCENTER | Graphics.TOP);
		if (details != null)
		{
			g.setFont(SMALL);
			g.setColor(DIM);
			int y = y0 + 4 + step;
			for (int i = 0; i < details.length; i++, y += step)
				g.drawString(details[i], 2, y, Graphics.LEFT | Graphics.TOP);
		}
	}

	/** Длинный отчёт (проба камеры): с самого верха, мелким, сколько влезет. */
	static void list(Graphics g, int width, int height, String title, String[] lines)
	{
		g.setColor(BAND);
		g.fillRect(0, 0, width, height);
		g.setFont(FONT);
		g.setColor(TEXT);
		g.drawString(title, 2, 2, Graphics.LEFT | Graphics.TOP);
		g.setFont(SMALL);
		g.setColor(DIM);
		int step = SMALL.getHeight();
		int y = 4 + FONT.getHeight();
		for (int i = 0; i < lines.length && y + step <= height; i++, y += step)
		{
			String s = lines[i];
			// Не влезает — режем: экран узкий, а строки пробы длинные.
			while (s.length() > 1 && SMALL.stringWidth(s) > width - 4) s = s.substring(0, s.length() - 1);
			g.drawString(s, 2, y, Graphics.LEFT | Graphics.TOP);
		}
	}

	/** «0:07» — секунды как минуты:секунды. */
	static String mmss(int secs)
	{
		return (secs / 60) + ":" + (secs % 60 < 10 ? "0" : "") + (secs % 60);
	}
}
//#sijapp cond.end#
