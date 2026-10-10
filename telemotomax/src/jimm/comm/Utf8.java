package jimm.comm;

/** UTF-8 without streams, length prefixes or temporary byte copies.
 * Accepts the modified UTF-8 used by older Jimm clients on input as well.
 */
final class Utf8
{
	static String decode(byte[] data, int offset, int length)
	{
		int end = offset + length, chars = 0;
		// Validate before allocating, then reserve exactly the UTF-16 size.
		for (int i = offset; i < end;)
		{
			int first = data[i++] & 255;
			if (first < 128) { chars++; continue; }
			int remaining, code;
			if (first >= 0xC0 && first < 0xE0)
			{
				remaining = 1;
				code = first & 31;
			}
			else if (first >= 0xE0 && first < 0xF0)
			{
				remaining = 2;
				code = first & 15;
			}
			else if (first >= 0xF0 && first <= 0xF4)
			{
				remaining = 3;
				code = first & 7;
			}
			else return null;
			if (remaining > end - i) return null;
			for (int j = 0; j < remaining; j++)
			{
				int next = data[i++] & 255;
				if ((next & 0xC0) != 0x80) return null;
				code = (code << 6) | (next & 63);
			}
			if (remaining == 1 && code < 128 && !(first == 0xC0 && code == 0)) return null;
			if (remaining == 2 && code < 0x800) return null;
			if (remaining == 3 && (code < 0x10000 || code > 0x10FFFF)) return null;
			chars += remaining == 3 ? 2 : 1;
		}
		if (chars == 0) return "";
		char[] result = new char[chars];
		int out = 0;
		for (int i = offset; i < end;)
		{
			int first = data[i++] & 255, code;
			if (first < 128) code = first;
			else if (first < 0xE0)
				code = ((first & 31) << 6) | (data[i++] & 63);
			else if (first < 0xF0)
			{
				code = ((first & 15) << 12) | ((data[i++] & 63) << 6);
				code |= data[i++] & 63;
			}
			else
			{
				code = ((first & 7) << 18) | ((data[i++] & 63) << 12);
				code |= (data[i++] & 63) << 6;
				code |= data[i++] & 63;
				code -= 0x10000;
				result[out++] = (char)(0xD800 | (code >> 10));
				code = 0xDC00 | (code & 0x3FF);
			}
			result[out++] = (char)code;
		}
		return new String(result);
	}

	static byte[] encode(String value)
	{
		int size = 0, length = value.length();
		for (int i = 0; i < length; i++)
		{
			int code = value.charAt(i);
			if (code < 128) size++;
			else if (code < 0x800) size += 2;
			else if (code >= 0xD800 && code <= 0xDFFF)
			{
				if (code < 0xDC00 && i + 1 < length
						&& value.charAt(i + 1) >= 0xDC00 && value.charAt(i + 1) <= 0xDFFF)
				{
					size += 4;
					i++;
				}
				else size++; // Unpaired UTF-16 surrogate: replacement '?'.
			}
			else size += 3;
		}
		byte[] result = new byte[size];
		int out = 0;
		for (int i = 0; i < length; i++)
		{
			int code = value.charAt(i);
			if (code >= 0xD800 && code <= 0xDFFF)
			{
				if (code < 0xDC00 && i + 1 < length
						&& value.charAt(i + 1) >= 0xDC00 && value.charAt(i + 1) <= 0xDFFF)
					code = 0x10000 + ((code - 0xD800) << 10) + value.charAt(++i) - 0xDC00;
				else code = '?';
			}
			if (code < 128) result[out++] = (byte)code;
			else if (code < 0x800)
			{
				result[out++] = (byte)(0xC0 | (code >> 6));
				result[out++] = (byte)(0x80 | (code & 63));
			}
			else
			{
				if (code > 0xFFFF)
				{
					result[out++] = (byte)(0xF0 | (code >> 18));
					result[out++] = (byte)(0x80 | ((code >> 12) & 63));
				}
				else result[out++] = (byte)(0xE0 | (code >> 12));
				result[out++] = (byte)(0x80 | ((code >> 6) & 63));
				result[out++] = (byte)(0x80 | (code & 63));
			}
		}
		return result;
	}
}
