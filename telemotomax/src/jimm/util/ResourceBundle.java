/*******************************************************************************
 Jimm - Mobile Messaging - J2ME ICQ clone
 Copyright (C) 2003-07  Jimm Project

 This program is free software; you can redistribute it and/or
 modify it under the terms of the GNU General Public License
 as published by the Free Software Foundation; either version 2
 of the License, or (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program; if not, write to the Free Software
 Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
 ********************************************************************************
 File: src/jimm/util/ResourceBundle.java
 Version: ###VERSION###  Date: ###DATE###
 Author(s): Manuel Linsmayer, Artyomov Denis
 *******************************************************************************/

package jimm.util;

import java.util.Hashtable;
import java.io.InputStream;
import java.io.DataInputStream;

public class ResourceBundle {
	// List of available language packs
	public static String[] langAvailable;

	static {
		InputStream istream = null;
		try {
			istream = ResourceBundle.class.getResourceAsStream(
					"/langlist.lng");
			DataInputStream dos = new DataInputStream(istream);
			int size = dos.readShort();
			langAvailable = new String[size];
			for (int i = 0; i < size; i++)
				langAvailable[i] = dos.readUTF();
		} catch (Exception e) {
			langAvailable = new String[] {"RU"};
		}
		finally { if (istream != null) try { istream.close(); } catch (Exception ignore) {} }
	}

	// Current language
	private static String currUiLanguage = ResourceBundle.langAvailable[0];

	// Get user interface language/localization for current session
	public static String getCurrUiLanguage() {
		return ResourceBundle.currUiLanguage;
	}

	// Set user interface language/localization for current session
	public static synchronized void setCurrUiLanguage(String currUiLanguage) {
		if (ResourceBundle.currUiLanguage.equals(currUiLanguage))
			return;
		for (int i = 0; i < ResourceBundle.langAvailable.length; i++) {
			if (ResourceBundle.langAvailable[i].equals(currUiLanguage)) {
				ResourceBundle.currUiLanguage = currUiLanguage;
				loadLang();
				return;
			}
		}
	}

	static private void loadLang() {
		InputStream istream = null;
		String[] compact = new String[0];
		Hashtable named = null;

		try {
			istream = ResourceBundle.class.getResourceAsStream(
					"/" + ResourceBundle.currUiLanguage + ".lng");
			DataInputStream dos = new DataInputStream(istream);
			int size = dos.readUnsignedShort();
			compact = new String[size];
			for (int j = 0; j < size; j++)
			{
				String key = dos.readUTF(), value = dos.readUTF();
				int index = compactIndex(key);
				if (index >= 0)
				{
					if (index >= compact.length)
					{
						String[] grown = new String[index + 64];
						System.arraycopy(compact, 0, grown, 0, compact.length);
						compact = grown;
					}
					compact[index] = value;
				}
				else
				{
					if (named == null) named = new Hashtable();
					named.put(key, value);
				}
			}
		} catch (Exception e) {
		}
		finally { if (istream != null) try { istream.close(); } catch (Exception ignore) {} }
		compactResources = compact;
		resources = named;
	}

	// LangsTask encodes numeric IDs with this alphabet, least significant
	// digit first. Named error/lang keys and longer keys retain Hashtable lookup.
	private static int compactIndex(String key)
	{
		if (key == null || key.length() < 1 || key.length() > 2) return -1;
		int index = 0, factor = 1;
		for (int i = 0; i < key.length(); i++)
		{
			char ch = key.charAt(i);
			int digit = ch == '_' ? 0 : ch >= '0' && ch <= '9' ? ch - '0' + 1
					: ch >= 'a' && ch <= 'z' ? ch - 'a' + 11
					: ch >= 'A' && ch <= 'Z' ? ch - 'A' + 37 : -1;
			if (digit < 0 || (i > 0 && digit == 0)) return -1;
			index += digit * factor;
			factor *= 63;
		}
		return index;
	}

	// Get string from active language pack
	public static synchronized String getString(String key) {
		if (compactResources == null)
			loadLang();
		if (key == null) return null; 
		int index = compactIndex(key);
		String value = index >= 0 ? (index < compactResources.length ? compactResources[index] : null)
				: resources == null ? null : (String) resources.get(key);
		if (value != null) {
			return (value);
		} else {
			return (key);
		}
	}

	// Resource hashtable
	static private Hashtable resources = null;
	static private String[] compactResources;

	final static public int FLAG_ELLIPSIS = 1 << 0;

	public static synchronized String getString(String key, int flags) {
		String result = getString(key);

		if ((flags & FLAG_ELLIPSIS) != 0)
			result = result + "...";

		return result;
	}
	
	public static synchronized String remove(String key)
	{
		String result = getString(key);
		int index = compactIndex(key);
		if (index >= 0)
		{
			if (index < compactResources.length) compactResources[index] = null;
		}
		else if (resources != null && key != null) resources.remove(key);
		return result;
	}

}
