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

package jimm.comm;

/**
 * Шифрование канала с мостом: ChaCha20-Poly1305 (RFC 8439), схема та же,
 * что в bridge/oscar/crypto.py — там она и описана. Здесь только
 * арифметика: 32-битные слова для ChaCha20 (int) и 26-битные конечности
 * на long для Poly1305 — ARM7 с KVM такое переваривает быстро, а памяти
 * нужно несколько сотен байт.
 *
 * Один объект — одно направление: свой ключ и счётчик кадров.
 */
public final class Crypto
{
	public static final int TAG_LEN = 16;
	public static final int ENCRYPTED = 0x80;      // бит канала FLAP

	private final int[] key = new int[8];
	private long counter;

	// Рабочие буферы, чтобы не плодить мусор на каждом кадре.
	private final int[] state = new int[16];
	private final int[] work = new int[16];
	private final byte[] block = new byte[64];

	public Crypto(byte[] key32)
	{
		for (int i = 0; i < 8; i++) key[i] = le32(key32, i * 4);
	}

	// K32 из фразы: MD5(фраза‖1) ‖ MD5(фраза‖2). MD5 у Jimm уже есть.
	public static byte[] masterKey(String secret)
	{
		byte[] raw = Util.stringToByteArray(secret, true);
		byte[] k32 = new byte[32];
		byte[] buf = new byte[raw.length + 1];
		System.arraycopy(raw, 0, buf, 0, raw.length);
		buf[raw.length] = 1;
		System.arraycopy(Util.calculateMD5(buf), 0, k32, 0, 16);
		buf[raw.length] = 2;
		System.arraycopy(Util.calculateMD5(buf), 0, k32, 16, 16);
		return k32;
	}

	// Ключ направления: первые 32 байта потока ChaCha20(K32, 0, метка‖snonce).
	public static Crypto forDirection(byte[] k32, byte[] label4, byte[] snonce8)
	{
		byte[] nonce = new byte[12];
		System.arraycopy(label4, 0, nonce, 0, 4);
		System.arraycopy(snonce8, 0, nonce, 4, 8);
		Crypto master = new Crypto(k32);
		byte[] out = new byte[64];
		master.blockInto(0, nonce, out);
		byte[] dirKey = new byte[32];
		System.arraycopy(out, 0, dirKey, 0, 32);
		return new Crypto(dirKey);
	}

	public static final byte[] LABEL_C2S = { 'c', '2', 's', 0 };
	public static final byte[] LABEL_S2C = { 's', '2', 'c', 0 };

	// --- кадры ---------------------------------------------------------

	// Шифртекст ‖ тег. Номер кадра — следующий по счётчику.
	public byte[] seal(byte[] plain, int off, int len)
	{
		byte[] nonce = nextNonce();
		byte[] out = new byte[len + TAG_LEN];
		xor(1, nonce, plain, off, len, out, 0);
		byte[] otk = new byte[32];
		blockInto(0, nonce, block);
		System.arraycopy(block, 0, otk, 0, 32);
		poly1305(otk, out, 0, len, out, len);
		return out;
	}

	// null — тег не сошёлся: чужой ключ или порча.
	public byte[] open(byte[] sealed, int off, int len)
	{
		if (len < TAG_LEN) return null;
		byte[] nonce = nextNonce();
		int ctLen = len - TAG_LEN;
		byte[] otk = new byte[32];
		blockInto(0, nonce, block);
		System.arraycopy(block, 0, otk, 0, 32);
		byte[] tag = new byte[TAG_LEN];
		poly1305(otk, sealed, off, ctLen, tag, 0);
		int diff = 0;
		for (int i = 0; i < TAG_LEN; i++) diff |= tag[i] ^ sealed[off + ctLen + i];
		if (diff != 0) return null;
		byte[] plain = new byte[ctLen];
		xor(1, nonce, sealed, off, ctLen, plain, 0);
		return plain;
	}

	private byte[] nextNonce()
	{
		byte[] nonce = new byte[12];
		long c = counter++;
		for (int i = 0; i < 8; i++) nonce[11 - i] = (byte) (c >>> (8 * i));
		return nonce;
	}

	// --- ChaCha20 ------------------------------------------------------

	private void blockInto(int ctr, byte[] nonce, byte[] out)
	{
		int[] s = state;
		s[0] = 0x61707865; s[1] = 0x3320646E; s[2] = 0x79622D32; s[3] = 0x6B206574;
		for (int i = 0; i < 8; i++) s[4 + i] = key[i];
		s[12] = ctr;
		s[13] = le32(nonce, 0); s[14] = le32(nonce, 4); s[15] = le32(nonce, 8);
		int[] w = work;
		System.arraycopy(s, 0, w, 0, 16);
		for (int i = 0; i < 10; i++)
		{
			qr(w, 0, 4, 8, 12); qr(w, 1, 5, 9, 13); qr(w, 2, 6, 10, 14); qr(w, 3, 7, 11, 15);
			qr(w, 0, 5, 10, 15); qr(w, 1, 6, 11, 12); qr(w, 2, 7, 8, 13); qr(w, 3, 4, 9, 14);
		}
		for (int i = 0; i < 16; i++)
		{
			int v = w[i] + s[i];
			out[i * 4] = (byte) v;
			out[i * 4 + 1] = (byte) (v >>> 8);
			out[i * 4 + 2] = (byte) (v >>> 16);
			out[i * 4 + 3] = (byte) (v >>> 24);
		}
	}

	private static void qr(int[] w, int a, int b, int c, int d)
	{
		w[a] += w[b]; w[d] ^= w[a]; w[d] = (w[d] << 16) | (w[d] >>> 16);
		w[c] += w[d]; w[b] ^= w[c]; w[b] = (w[b] << 12) | (w[b] >>> 20);
		w[a] += w[b]; w[d] ^= w[a]; w[d] = (w[d] << 8) | (w[d] >>> 24);
		w[c] += w[d]; w[b] ^= w[c]; w[b] = (w[b] << 7) | (w[b] >>> 25);
	}

	private void xor(int ctr, byte[] nonce, byte[] in, int inOff, int len, byte[] out, int outOff)
	{
		for (int done = 0; done < len; done += 64, ctr++)
		{
			blockInto(ctr, nonce, block);
			int n = Math.min(64, len - done);
			for (int i = 0; i < n; i++)
				out[outOff + done + i] = (byte) (in[inOff + done + i] ^ block[i]);
		}
	}

	private static int le32(byte[] b, int off)
	{
		return (b[off] & 0xFF) | ((b[off + 1] & 0xFF) << 8)
				| ((b[off + 2] & 0xFF) << 16) | ((b[off + 3] & 0xFF) << 24);
	}

	// --- Poly1305 (RFC 8439, конечности по 26 бит) ----------------------

	// Тег по данным AEAD: pad16(ct) ‖ le64(0) ‖ le64(len ct); AAD пустые.
	private static void poly1305(byte[] otk, byte[] ct, int off, int len, byte[] tag, int tagOff)
	{
		long r0 = le32(otk, 0) & 0x3FFFFFFL;
		long r1 = (le32u(otk, 3) >>> 2) & 0x3FFFF03L;
		long r2 = (le32u(otk, 6) >>> 4) & 0x3FFC0FFL;
		long r3 = (le32u(otk, 9) >>> 6) & 0x3F03FFFL;
		long r4 = (le32u(otk, 12) >>> 8) & 0x00FFFFFL;
		long s1 = r1 * 5, s2 = r2 * 5, s3 = r3 * 5, s4 = r4 * 5;
		long h0 = 0, h1 = 0, h2 = 0, h3 = 0, h4 = 0;

		// Сообщение: шифртекст, дополненный нулями до 16, затем длины.
		int padded = (len + 15) & ~15;
		int total = padded + 16;
		byte[] m = new byte[16];
		for (int pos = 0; pos < total; pos += 16)
		{
			for (int i = 0; i < 16; i++)
			{
				int p = pos + i;
				byte v;
				if (p < len) v = ct[off + p];
				else if (p < padded) v = 0;
				else if (p < padded + 8) v = 0;                         // len(aad) = 0
				else v = (byte) ((long) len >>> (8 * (p - padded - 8)));  // le64(len ct)
				m[i] = v;
			}
			h0 += le32u(m, 0) & 0x3FFFFFFL;
			h1 += (le32u(m, 3) >>> 2) & 0x3FFFFFFL;
			h2 += (le32u(m, 6) >>> 4) & 0x3FFFFFFL;
			h3 += (le32u(m, 9) >>> 6) & 0x3FFFFFFL;
			h4 += (le32u(m, 12) >>> 8) | (1L << 24);

			long d0 = h0 * r0 + h1 * s4 + h2 * s3 + h3 * s2 + h4 * s1;
			long d1 = h0 * r1 + h1 * r0 + h2 * s4 + h3 * s3 + h4 * s2;
			long d2 = h0 * r2 + h1 * r1 + h2 * r0 + h3 * s4 + h4 * s3;
			long d3 = h0 * r3 + h1 * r2 + h2 * r1 + h3 * r0 + h4 * s4;
			long d4 = h0 * r4 + h1 * r3 + h2 * r2 + h3 * r1 + h4 * r0;

			long c = d0 >>> 26; h0 = d0 & 0x3FFFFFFL; d1 += c;
			c = d1 >>> 26; h1 = d1 & 0x3FFFFFFL; d2 += c;
			c = d2 >>> 26; h2 = d2 & 0x3FFFFFFL; d3 += c;
			c = d3 >>> 26; h3 = d3 & 0x3FFFFFFL; d4 += c;
			c = d4 >>> 26; h4 = d4 & 0x3FFFFFFL; h0 += c * 5;
			c = h0 >>> 26; h0 &= 0x3FFFFFFL; h1 += c;
		}

		// Полная нормализация и вычитание p при необходимости.
		long c = h1 >>> 26; h1 &= 0x3FFFFFFL; h2 += c;
		c = h2 >>> 26; h2 &= 0x3FFFFFFL; h3 += c;
		c = h3 >>> 26; h3 &= 0x3FFFFFFL; h4 += c;
		c = h4 >>> 26; h4 &= 0x3FFFFFFL; h0 += c * 5;
		c = h0 >>> 26; h0 &= 0x3FFFFFFL; h1 += c;

		long g0 = h0 + 5; c = g0 >>> 26; g0 &= 0x3FFFFFFL;
		long g1 = h1 + c; c = g1 >>> 26; g1 &= 0x3FFFFFFL;
		long g2 = h2 + c; c = g2 >>> 26; g2 &= 0x3FFFFFFL;
		long g3 = h3 + c; c = g3 >>> 26; g3 &= 0x3FFFFFFL;
		long g4 = h4 + c - (1L << 26);
		if ((g4 >>> 63) == 0)          // g4 >= 0: h >= p, берём h - p
		{
			h0 = g0; h1 = g1; h2 = g2; h3 = g3; h4 = g4 & 0x3FFFFFFL;
		}

		long f0 = (h0 | (h1 << 26)) & 0xFFFFFFFFL;
		long f1 = ((h1 >>> 6) | (h2 << 20)) & 0xFFFFFFFFL;
		long f2 = ((h2 >>> 12) | (h3 << 14)) & 0xFFFFFFFFL;
		long f3 = ((h3 >>> 18) | (h4 << 8)) & 0xFFFFFFFFL;

		f0 += le32u(otk, 16); f1 += le32u(otk, 20) + (f0 >>> 32); f0 &= 0xFFFFFFFFL;
		f2 += le32u(otk, 24) + (f1 >>> 32); f1 &= 0xFFFFFFFFL;
		f3 += le32u(otk, 28) + (f2 >>> 32); f2 &= 0xFFFFFFFFL; f3 &= 0xFFFFFFFFL;
		putLe32(tag, tagOff, f0); putLe32(tag, tagOff + 4, f1);
		putLe32(tag, tagOff + 8, f2); putLe32(tag, tagOff + 12, f3);
	}

	private static long le32u(byte[] b, int off)
	{
		return le32(b, off) & 0xFFFFFFFFL;
	}

	private static void putLe32(byte[] b, int off, long v)
	{
		b[off] = (byte) v; b[off + 1] = (byte) (v >>> 8);
		b[off + 2] = (byte) (v >>> 16); b[off + 3] = (byte) (v >>> 24);
	}

	// --- кадры FLAP ----------------------------------------------------

	// Готовый кадр (заголовок 6 байт + тело) → тот же кадр с шифрованным
	// телом: бит 0x80 в канале, новая длина.
	public byte[] sealFlap(byte[] flap)
	{
		int len = flap.length - 6;
		byte[] body = seal(flap, 6, len);
		byte[] out = new byte[6 + body.length];
		System.arraycopy(flap, 0, out, 0, 6);
		out[1] = (byte) (out[1] | ENCRYPTED);
		out[4] = (byte) (body.length >>> 8);
		out[5] = (byte) body.length;
		System.arraycopy(body, 0, out, 6, body.length);
		return out;
	}
}
