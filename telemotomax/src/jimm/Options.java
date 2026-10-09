/*******************************************************************************
 Jimm - Mobile Messaging - J2ME ICQ clone
 Copyright (C) 2003-08  Jimm Project

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
 *******************************************************************************
 File: src/jimm/Options.java
 Version: ###VERSION###  Date: ###DATE###
 Author(s): Manuel Linsmayer, Andreas Rossbacher, Artyomov Denis, Igor Palkin
 ******************************************************************************/

/*******************************************************************************
 Current record store format:

 Record #1: VERSION               (UTF8)
 Record #2: OPTION KEY            (BYTE)
 OPTION VALUE          (Type depends on key)
 OPTION KEY            (BYTE)
 OPTION VALUE          (Type depends on key)
 OPTION KEY            (BYTE)
 OPTION VALUE          (Type depends on key)
 ...

 Option key            Option value
 0 -  63 (00XXXXXX)  UTF8
 64 - 127 (01XXXXXX)  INTEGER
 128 - 191 (10XXXXXX)  BOOLEAN
 192 - 224 (110XXXXX)  LONG
 225 - 255 (111XXXXX)  SHORT, BYTE-ARRAY (scrambled String)
 ******************************************************************************/

package jimm;

import jimm.comm.Action;
import jimm.comm.SearchAction;
import jimm.comm.UpdateContactListAction;
import jimm.comm.Util;
import jimm.comm.Icq;
import jimm.util.ResourceBundle;

//#sijapp cond.if target="MIDP2"|target="MOTOROLA"|target="RIM"#
import javax.microedition.io.file.*;
import javax.microedition.io.*;
//#sijapp cond.elseif target="SIEMENS2"#
//#import com.siemens.mp.io.file.FileConnection;
//#import com.siemens.mp.io.file.FileSystemRegistry;
//#import javax.microedition.io.Connector;
//#sijapp cond.end#

import java.io.*;
import java.util.*;
import DrawControls.*;

import javax.microedition.lcdui.*;
import javax.microedition.rms.RecordStore;
import javax.microedition.rms.RecordStoreException;

import DrawControls.VirtualList;
import DrawControls.device.Device;


public class Options
{
	/* Not stored in RMS */
	public static final int OPTION_UIN      = 254;    
	public static final int OPTION_PASSWORD = 255;
	
	/* String */
	static final int        OPTION_UIN1               = 0;
	public static final int OPTION_SRV_HOST           = 1;
	public static final int OPTION_SRV_PORT           = 2;
	public static final int OPTION_UI_LANGUAGE        = 3;
	public static final int OPTION_CAMERA_SIZE        = 31;   // TeleMotoMax: размер снимка «WxH», пусто — как решит телефон
	public static final int OPTION_MEDIA_PHOTO_SIZE   = 32;   // TeleMotoMax, «Медиа»: фото от моста «WxH», пусто — как в профиле
	public static final int OPTION_MEDIA_VIDEO_SIZE   = 33;
	public static final int OPTION_ENCRYPTION_PSK     = 35;
	public static final int OPTION_ENCRYPTION         = 176;
	public static final int OPTION_MESS_NOTIF_FILE    = 4;
	public static final int OPTION_MESS_UNLOCKED_FILE = 36;
	public static final int OPTION_LOCK_PIN = 37;
	public static final int LOCK_PIN_MAX = 8;
	// Numeric RMS slots are full; use unused long slots for the new profile.
	public static final int OPTION_MESS_UNLOCKED_MODE = 193;
	public static final int OPTION_MESS_UNLOCKED_VOL  = 194;
	public static final int OPTION_VIBRA_UNLOCKED_MS = 195;
	public static final int OPTION_VIBRA_LOCKED_MS = 196;
	public static final int[] VIBRATION_DURATIONS = {200, 500, 1000, 1500, 2000};
	public static final int OPTION_CURRENCY           = 6;
	public static final int OPTION_PRX_SERV           = 8;
	public static final int OPTION_PRX_PORT           = 9;
	public static final int OPTION_AUTORETRY_COUNT    = 10;
	public static final int OPTION_PRX_NAME           = 11;
	public static final int OPTION_PRX_PASS           = 12;
	public static final int OPTION_CONN_ALIVE_INVTERV = 13;
	static final int        OPTION_UIN2               = 14;
	static final int        OPTION_UIN3               = 15;
	public static final int OPTION_TYPING_FILE        = 16;
	public static final int OPTION_ANTI_SPAM_QUESTION = 19;
	public static final int OPTION_ANTI_SPAM_ANS      = 20;
	public static final int OPTION_BG_IMAGE_URL       = 21;
	
	/* Passwords */
	static final int OPTION_PASSWORD1 = 228;
	static final int OPTION_PASSWORD2 = 229;
	static final int OPTION_PASSWORD3 = 230;
	
	/* int */
	public static final int OPTION_CONN_PROP          = 64;
	public static final int OPTION_CL_SORT_BY         = 65;
	public static final int OPTION_MESS_NOTIF_MODE    = 66;
	public static final int OPTION_MESS_NOTIF_VOL     = 67;
	public static final int OPTION_COST_PER_PACKET    = 70;
	public static final int OPTION_COST_PER_DAY       = 71;
	public static final int OPTION_COST_PACKET_LENGTH = 72;
	public static final int OPTION_COLOR_SCHEME       = 73;
	public static final int OPTION_LIGHT_TIMEOUT      = 74;
	public static final int OPTION_VIBRATOR           = 75;
	public static final int OPTION_PRX_TYPE           = 76;
	public static final int OPTION_EXT_CLKEY0         = 77; 
	public static final int OPTION_EXT_CLKEYSTAR      = 78;
	public static final int OPTION_EXT_CLKEY4         = 79;
	public static final int OPTION_EXT_CLKEY6         = 80; 
	public static final int OPTION_EXT_CLKEYCALL      = 81; 
	public static final int OPTION_EXT_CLKEYPOUND     = 82;
//#sijapp cond.if modules_PROXY is "true"#
	public static final int OPTION_CONN_TYPE          = 83;
//#sijapp cond.end#
	public static final int OPTION_VISIBILITY_ID      = 85;
	public static final int OPTION_POPUP_WIN2         = 84; // This option is FREE
	static final int        OPTION_CURR_ACCOUNT       = 86;
	public static final int OPTION_GMT_OFFSET         = 87;
	public static final int OPTION_TYPING_MODE        = 88;
	public static final int OPTION_TYPING_VOL         = 89;
	public static final int OPTION_LOCAL_OFFSET       = 90;
	public static final int OPTION_RECONNECT_NUMBER   = 91;
	public static final int OPTION_DAYLIGHT_SAVING    = 93;
//	public static final int OPTION_CAMERA_LOCATOR     = 95;
	public static final int OPTION_CAMERA_ENCODING    = 98;
	public static final int OPTION_CAMERA_RES         = 99;
	public static final int OPTION_CAPTION_OFFSET     = 100;
	public static final int OPTION_BG_IMAGE           = 101;
	public static final int OPTION_IMG_SCALE          = 104;
	public static final int OPTION_BG_IMAGE_MODE      = 105;
	
	public static final int OPTION_EXT_CLKEY1         = 106;
	public static final int OPTION_EXT_CLKEY2         = 107;
	public static final int OPTION_EXT_CLKEY3         = 108;
	public static final int OPTION_EXT_CLKEY5         = 109;
	public static final int OPTION_EXT_CLKEY7         = 110;
	public static final int OPTION_EXT_CLKEY8         = 111;
	public static final int OPTION_EXT_CLKEY9         = 112;
	
	/* boolean */
	public static final int OPTION_KEEP_CONN_ALIVE   = 128; 
	public static final int OPTION_DISPLAY_DATE      = 129;
	public static final int OPTION_CL_HIDE_OFFLINE   = 130;
	public static final int OPTION_CP1251_HACK       = 133;
	public static final int OPTION_CHAT_SMALL_FONT   = 135;
	public static final int OPTION_USE_GROUPS       = 136;
	public static final int OPTION_HISTORY           = 137;
	public static final int OPTION_AUTO_CONNECT      = 138;
	public static final int OPTION_SHADOW_CON        = 139;
	public static final int OPTION_LIGHT_MANUAL      = 140;
	public static final int OPTION_USE_SMILES        = 141;
	public static final int OPTION_SHOW_LAST_MESS    = 142;
	public static final int OPTION_MD5_LOGIN         = 144;
	public static final int OPTION_FULL_SCREEN       = 145;
	static final int        OPTION_LANG_CHANGED      = 148;
	public static final int OPTION_RECONNECT         = 149;
	public static final int OPTION_SILENT_MODE       = 150;
	public static final int OPTION_BRING_UP          = 151;
	public static final int OPTION_CREEPING_LINE     = 152;
	public static final int OPTION_SHOW_MESS_ICON    = 153;
	public static final int OPTION_SHOW_NICK         = 154;
	public static final int OPTION_SHOW_MESS_DATE    = 155;
	public static final int OPTION_SHOW_MESS_CLRF    = 156;
	public static final int OPTION_MESS_COLORED_TEXT = 157;
	public static final int OPTION_ASK_FOR_WEB_FT    = 160;
	public static final int OPTION_DELIV_MES_INFO    = 162;
	public static final int OPTION_MIRROR_MENU       = 163;
	public static final int OPTION_SHOW_DELETED_CONT = 164;
	public static final int OPTION_SMALL_FONT        = 165;
	public static final int OPTION_ANTI_SPAM         = 166;
	public static final int OPTION_FULL_TEXTBOX      = 167;
	public static final int OPTION_CL_HIDE_EMPTY     = 168;
	public static final int OPTION_INIT_CAPS	     = 169;
	// TeleMotoMax: how many messages "History from server" asks for
	public static final int OPTION_HISTORY_COUNT    = 113;   // 64..127 — числовые ключи
	public static final int OPTION_CHAT_MESSAGES    = 114;   // сколько сообщений держит чат
	public static final int OPTION_VIDEO_ROTATE     = 115;   // ролик боком: 0 авто, 1 всегда, 2 никогда
	// «Медиа»: что мост отдаёт телефону; 0 — как в профиле моста.
	public static final int OPTION_MEDIA_PHOTO_QUALITY  = 116;   // качество JPEG снимка
	public static final int OPTION_MEDIA_PHOTO_KB       = 117;   // снимок не больше, КБ
	public static final int OPTION_MEDIA_VIDEO_KBPS     = 118;   // битрейт ролика
	public static final int OPTION_MEDIA_VIDEO_SECONDS  = 119;   // длина ролика
	public static final int OPTION_MEDIA_VOICE_KBPS10   = 120;   // битрейт голосового ×10 (122 — 12.2)
	public static final int OPTION_MEDIA_VOICE_SECONDS  = 121;   // длина голосового
	public static final int OPTION_PHOTO_ROTATE         = 122;   // фото боком: 0 авто, 1 всегда, 2 никогда
	public static final int OPTION_MEDIA_MEM_KB         = 123;
	public static final int OPTION_MEDIA_ROSTER_LIMIT   = 124;   // «Медиа»: чатов в контакт-листе, 65535 — все, 0 — как в профиле
	public static final int OPTION_MEDIA_VIDEO_KB       = 125;   // «Медиа»: предел размера ролика, КБ
	public static final int OPTION_EXPRESS              = 126;   // сеть eXpress на мосту — 1 включена, 2 выключена
	// Тип настройки задан диапазоном номера (см. save()): 64–127 — число,
	// 128–191 — флажок. Числовых номеров осталось два — они под ограничения.
	public static final int OPTION_TELEGRAM_ON          = 131;   // сеть Telegram на мосту включена (флажок)
	public static final int OPTION_MAX_ON               = 132;   // сеть MAX на мосту включена (флажок)
	public static final int OPTION_MAX_ROSTER_LIMIT     = 94;    // чатов MAX в списке: 65535 — все, 0 — как в мосте
	public static final int OPTION_EXPRESS_ROSTER_LIMIT = 127;   // чатов eXpress в списке: 65535 — все, 0 — как в мосте

//#sijapp cond.if modules_CAMERA="true"#
	static final String[] MEDIA_VIDEO_SIZES = { "176x144", "144x176", "240x180", "320x240", "240x320", "480x640", "640x480" };
	static final int[] MEDIA_VIDEO_KBPS = { 32, 48, 64, 96, 128, 192, 256, 384 };
//#sijapp cond.else#
	static final String[] MEDIA_VIDEO_SIZES = { "128x96", "176x144" };
	static final int[] MEDIA_VIDEO_KBPS = { 16, 24, 32, 48, 64, 96, 120 };
//#sijapp cond.end#

	/** «WxH» из настройки «Медиа» как {w, h}; пусто или негодно — null. */
	public static int[] mediaSize(int key)
	{
		String s = Options.getString(key);
		if (s == null) return null;
		if (key == OPTION_MEDIA_VIDEO_SIZE)
		{
			boolean supported = false;
			for (int i = 0; i < MEDIA_VIDEO_SIZES.length; i++)
				if (MEDIA_VIDEO_SIZES[i].equals(s)) supported = true;
			if (!supported)
			{
				// Старое значение RMS не должно обходить новый список размеров.
				Options.setString(key, "");
				return null;
			}
		}
		int x = s.indexOf('x');
		if (x <= 0) return null;
		try { return new int[] { Integer.parseInt(s.substring(0, x)), Integer.parseInt(s.substring(x + 1)) }; }
		catch (Exception e) { return null; }
	}

	public static int mediaVideoKbps()
	{
		int current = Options.getInt(OPTION_MEDIA_VIDEO_KBPS);
//#sijapp cond.if modules_CAMERA="true"#
//#sijapp cond.else#
		if (current > 0)
		{
			int closest = MEDIA_VIDEO_KBPS[0];
			for (int i = 1; i < MEDIA_VIDEO_KBPS.length; i++)
				if (Math.abs(MEDIA_VIDEO_KBPS[i] - current) < Math.abs(closest - current))
					closest = MEDIA_VIDEO_KBPS[i];
			// Например, 128 из прежней V3-сборки становится 120.
			Options.setInt(OPTION_MEDIA_VIDEO_KBPS, closest);
			current = closest;
		}
//#sijapp cond.end#
		return current;
	}
	// TeleMotoMax: раз выключили цветной текст сообщений у тех, кто обновился
	// со старой сборки (в новых установках он и так выключен).
	public static final int OPTION_PLAIN_TEXT_DONE  = 170;   // 128..191 — флаги
	
	/* long */
	public static final int OPTION_ONLINE_STATUS = 192; 
	
	/* Filetransfer modes */
	
	/* Hotkey Actions */
	public static final int HOTKEY_NONE        = 0;
	public static final int HOTKEY_INFO        = 2;
	public static final int HOTKEY_NEWMSG      = 3;
	public static final int HOTKEY_ONOFF       = 4;
	public static final int HOTKEY_OPTIONS     = 5;
	public static final int HOTKEY_MENU        = 6;
	public static final int HOTKEY_LOCK        = 7;
	public static final int HOTKEY_HISTORY     = 8;
	public static final int HOTKEY_MINIMIZE    = 9;
	public static final int HOTKEY_CLI_INFO    = 10;
	public static final int HOTKEY_FULLSCR     = 11;
	public static final int HOTKEY_SOUNDOFF	   = 12;
	public static final int HOTKEY_USER_GROUPS = 13;
	public static final int HOTKEY_INC_LIGHT   = 15;
	public static final int HOTKEY_DEC_LIGHT   = 16;
	public static final int HOTKEY_LIGHT_ONOFF = 17;
	public static final int HOTKEY_GOTO_TOP    = 18;
	public static final int HOTKEY_GOTO_BOTTOM = 19;
	public static final int HOTKEY_PAGE_UP     = 20;
	public static final int HOTKEY_PAGE_DOWN   = 21;
	public static final int HOTKEY_NEXT_CHAT   = 22;
	public static final int HOTKEY_PREV_CHAT   = 23;
	public static final int HOTKEY_UP          = 24;
	public static final int HOTKEY_DOWN        = 25;
	public static final int HOTKEY_SELECT      = 26;
	
	/* Constants for connection type */
//#sijapp cond.if modules_PROXY is "true"#
	public static final int CONN_TYPE_SOCKET = 0;
	public static final int CONN_TYPE_PROXY  = 2;
//#sijapp cond.end#
	
	/* Constants for method getSchemeColor to retrieving color from color scheme */
	public static final int CLRSCHHEME_BACK       = 1; // retrieving background color
	public static final int CLRSCHHEME_TEXT       = 2; // retrieving text color
	public static final int CLRSCHHEME_OUTGOING   = 3; // retrieving highlight color
	public static final int CLRSCHHEME_CURS       = 4; // retrieving cursor background color
	public static final int CLRSCHHEME_CAP        = 5; // retrieving caption background color
	public static final int CLRSCHHEME_INCOMING   = 6; // retrieving highlight color
	public static final int CLRSCHHEME_CAP_TEXT   = 7; // retrieving caption text color
	public static final int CLRSCHHEME_CURS_FRAME = 8; // retrieving cursor flame color

	public static final int BG_IMAGE_NONE = 0;
	public static final int BG_IMAGE_INT  = 1;
	public static final int BG_IMAGE_EXT  = 2;

	// Image placing modes
	public static final int BG_IMAGE_CENTER  = 0;
	public static final int BG_IMAGE_STRETCH = 1;
	public static final int BG_IMAGE_PAVE    = 2;
	

	/* Color schemes values */
	final static private int[] colors =
	{//	back      text      out text  cursor    caption   in text   cap text  curs.brd.
		0xFFFFFF, 0x000000, 0x0000FF, 0xE8E8FF, 0xF0F0F0, 0xFF0000, 0x000000, 0x6060A0, // Black on White
		0x000000, 0xFFFFFF, 0x00FFFF, 0x0000C0, 0x505050, 0xFF0000, 0xFFFFFF, 0x0000FF, // White on Black
		0x000080, 0xFFFFFF, 0x00FFFF, 0x0000D0, 0x0000B0, 0xFF0000, 0xFFFFFF, 0x0000FF, // White on Blue
		0xFFA0C0, 0x000000, 0x4000C0, 0xFFE0D0, 0xFFE0D0, 0xC00040, 0x000000, 0xA02020, // Pink
		0xE0FFE0, 0x000000, 0x008000, 0xC0FFC0, 0xB0FFB0, 0xFF0000, 0x000000, 0x00A000, // Green
		0xF9F3EF, 0xD60000, 0x3A6793, 0xE3BFA1, 0xC37D3F, 0xDB8941, 0xFFFFF0, 0xD26464, // Sand
		0x000000, 0x00D000, 0xD0D0D0, 0x005000, 0x007000, 0x00FF00, 0x80FF80, 0x008000, // Hacker
		0xD5FDFD, 0x000000, 0x009090, 0xB0FFFF, 0x80FFFF, 0x0000FF, 0x000000, 0x00A0A0, // Aqua
		0x8CB29C, 0x002250, 0x101080, 0xDBE1E7, 0x648C64, 0x801010, 0x8CFB6B, 0x5CCB3B, // Green Night
		0xFFFFFF, 0x000000, 0x0000FF, 0xE8E8FF, 0xC00000, 0xFF0000, 0xFFFFFF, 0x9080C0, // A'la opera mini
		
	    0xCCCCCC, 0x000000, 0x336699, 0xC0C0C0, 0xA5AECC, 0x336633, 0x000000, 0x666666, // Ergonomic
	    0xBAB190, 0x000000, 0x930a0a, 0xCCCC99, 0xCC9966, 0x336633, 0xFFFFFF, 0x666666, // Bronze golem
	    0xFFFFFF, 0x175A85, 0x336699, 0xCCEBFF, 0x175A85, 0x336633, 0xFFFFFF, 0x97b7c7, // Snowy frost
	    0x292e31, 0xcaa452, 0xc8c8c8, 0x616560, 0x636771, 0x448844, 0xFFFFFF, 0x31333b, // WA Bento
	    0x000000, 0xFF0000, 0xFFF314, 0xFF5500, 0x000000, 0x448844, 0xFFFFFF, 0xFF0000, // Quake	
	    0x003300, 0xDA6600, 0xFF0000, 0xFF5500, 0x003300, 0x448844, 0xFFFFFF, 0xFF0000, // Green2	
	    0xCCCCCC, 0x000000, 0x000000, 0x425173, 0xCCCCCC, 0x336600, 0xFFFFFF, 0x425173, // Silver	
	    
	    0x2d2d00, 0xffc549, 0x00FFFF, 0x86006e, 0x00560a, 0x00ff1b, 0x30ff47, 0xff00d2, // Neon
	};
	

	//#sijapp cond.if modules_DEBUGLOG is "true" #
	private static boolean checkKeys = false;
	//#sijapp cond.end #

	static int accountKeys[] =
	{ Options.OPTION_UIN1, Options.OPTION_PASSWORD1, Options.OPTION_UIN2,
			Options.OPTION_PASSWORD2, Options.OPTION_UIN3,
			Options.OPTION_PASSWORD3, };

	/**************************************************************************/

	final public static String emptyString = new String();

	// Hashtable containing all option key-value pairs
	static private Hashtable options;

	// Options form
	static OptionsForm optionsForm;

	public Options()
	{
		// Try to load option values from record store and construct options form
		try
		{
			options = new Hashtable();

			//#sijapp cond.if modules_DEBUGLOG is "true"#
			checkKeys = true;
			setDefaults();
			checkKeys = false;
			//#sijapp cond.else#
			//#			Options.setDefaults();
			//#sijapp cond.end #

			load();

			if (getBoolean(OPTION_LANG_CHANGED))
			{
				setBoolean(OPTION_LANG_CHANGED, false);
			}
		}
		// Use default values if loading option values from record store failed
		catch (Exception e)
		{
			setDefaults();
		}

		ResourceBundle.setCurrUiLanguage(getString(Options.OPTION_UI_LANGUAGE));
		

	}

	/* Set default values
	 This is done before loading because older saves may not contain all new values */
	static private void setDefaults()
	{
		setString(Options.OPTION_UIN1, emptyString);
		setString(Options.OPTION_PASSWORD1, emptyString);
		setString (Options.OPTION_SRV_HOST, "login.icq.com,login.oscar.aol.com,ibucp-vip-d.blue.aol.com");
//#sijapp cond.if modules_CAMERA="true"#
		// V8 (проверено 2026-09-22): 960×1280 — целый кадр, 291 КБ; больше Java не даёт.
		setString (Options.OPTION_CAMERA_SIZE, "960x1280");
//#sijapp cond.else#
		setString (Options.OPTION_CAMERA_SIZE, "");
//#sijapp cond.end#
		setString (Options.OPTION_MEDIA_PHOTO_SIZE, "");
		setString (Options.OPTION_MEDIA_VIDEO_SIZE, "");
		
		setString(Options.OPTION_SRV_PORT, "5190");
		setString(Options.OPTION_ENCRYPTION_PSK, "");
		setString(OPTION_LOCK_PIN, emptyString);
		setBoolean(Options.OPTION_ENCRYPTION, false);
		setBoolean(Options.OPTION_KEEP_CONN_ALIVE, true);
		setBoolean(Options.OPTION_RECONNECT, true);
		setInt(Options.OPTION_RECONNECT_NUMBER, 10);
		setString(Options.OPTION_CONN_ALIVE_INVTERV, "120");
		setInt(Options.OPTION_CONN_PROP, 0);
//#sijapp cond.if modules_PROXY is "true"#
		setInt(Options.OPTION_CONN_TYPE, 0);
//#sijapp cond.end#
		//#sijapp cond.if target isnot "MOTOROLA"#
		setBoolean(Options.OPTION_SHADOW_CON, false);
		//#sijapp cond.end#
		setBoolean(Options.OPTION_MD5_LOGIN, true);
		setBoolean(Options.OPTION_AUTO_CONNECT, false);
		setString(Options.OPTION_UI_LANGUAGE, ResourceBundle.langAvailable[0]);
		setBoolean(Options.OPTION_DISPLAY_DATE, false);
		setInt(Options.OPTION_CL_SORT_BY, 0);
		setBoolean(Options.OPTION_CL_HIDE_OFFLINE, false);
		setBoolean(Options.OPTION_CL_HIDE_EMPTY, false);
		//#sijapp cond.if target="MIDP2" | target="SIEMENS2" | target="RIM"#
		setInt(Options.OPTION_MESS_NOTIF_MODE, 2);
		setString(Options.OPTION_MESS_NOTIF_FILE, "message.wav");
		setInt(Options.OPTION_MESS_NOTIF_VOL, 50);
		setInt(Options.OPTION_TYPING_VOL, 50);
		setString(Options.OPTION_TYPING_FILE, "typing.wav");
		//#sijapp cond.elseif target is "MOTOROLA"#
		setInt    (Options.OPTION_MESS_NOTIF_MODE,    2);
		setString (Options.OPTION_MESS_NOTIF_FILE,    "message.mp3");
		setInt    (Options.OPTION_MESS_NOTIF_VOL,     50);
		setInt	  (Options.OPTION_TYPING_VOL,	 	  50);
		setString (Options.OPTION_TYPING_FILE,		  "typing.mp3");
		setBoolean(Options.OPTION_LIGHT_MANUAL,       true);
		//#sijapp cond.end#
		
//#sijapp cond.if target!="DEFAULT"#
		setString(OPTION_MESS_UNLOCKED_FILE, "msg_low.mp3");
		setLong(OPTION_MESS_UNLOCKED_MODE, 2);
		setLong(OPTION_MESS_UNLOCKED_VOL, 50);
		setInt(Options.OPTION_TYPING_MODE, 2);
//#sijapp cond.end#		

		//#sijapp cond.if target="MIDP2"#
		setBoolean(Options.OPTION_LIGHT_MANUAL,       false);
		//#sijapp cond.end#

		//#sijapp cond.if target="MOTOROLA" | target="MIDP2"#
		setInt    (Options.OPTION_LIGHT_TIMEOUT,      5);
		//#sijapp cond.end #
		setInt    (Options.OPTION_HISTORY_COUNT,     10);
		setInt    (Options.OPTION_CHAT_MESSAGES,     15);
		setInt    (Options.OPTION_VIDEO_ROTATE,      0);
		setInt    (Options.OPTION_MEDIA_PHOTO_QUALITY, 0);
		setInt    (Options.OPTION_MEDIA_PHOTO_KB,      0);
		setInt    (Options.OPTION_MEDIA_VIDEO_KBPS,    0);
		setInt    (Options.OPTION_MEDIA_VIDEO_SECONDS, 0);
		setInt    (Options.OPTION_MEDIA_VOICE_KBPS10,  0);
		setInt    (Options.OPTION_MEDIA_VOICE_SECONDS, 0);
		setInt    (Options.OPTION_PHOTO_ROTATE,        0);
		setInt    (Options.OPTION_MEDIA_MEM_KB,        0);
		setInt    (Options.OPTION_MEDIA_VIDEO_KB,      0);
		setInt    (Options.OPTION_MEDIA_ROSTER_LIMIT,  0);
		setInt    (Options.OPTION_EXPRESS,             1);
		setBoolean(Options.OPTION_TELEGRAM_ON,         true);
		setBoolean(Options.OPTION_MAX_ON,              true);
		setInt    (Options.OPTION_MAX_ROSTER_LIMIT,    0);
		setInt    (Options.OPTION_EXPRESS_ROSTER_LIMIT, 0);

		setBoolean(Options.OPTION_CP1251_HACK, ResourceBundle.langAvailable[0]
				.equals("RU") || ResourceBundle.langAvailable[0].equals("BE") );
		setBoolean(Options.OPTION_INIT_CAPS, true);
		//#sijapp cond.if target isnot "DEFAULT"#
		setInt(Options.OPTION_VIBRATOR, 0);
		setLong(OPTION_VIBRA_UNLOCKED_MS, 500);
		setLong(OPTION_VIBRA_LOCKED_MS, 500);
		//#sijapp cond.end#		
		//#sijapp cond.if modules_TRAFFIC is "true" #
		setInt(Options.OPTION_COST_PER_PACKET, 0);
		setInt(Options.OPTION_COST_PER_DAY, 0);
		setInt(Options.OPTION_COST_PACKET_LENGTH, 1024);
		setString(Options.OPTION_CURRENCY, "$");
		//#sijapp cond.end #
		setLong(Options.OPTION_ONLINE_STATUS, ContactList.STATUS_ONLINE);
		setBoolean(Options.OPTION_CHAT_SMALL_FONT, true);
		setBoolean(Options.OPTION_USE_GROUPS, false);
		setBoolean(Options.OPTION_HISTORY, false);
		setInt(Options.OPTION_COLOR_SCHEME, 0);
		setBoolean(Options.OPTION_USE_SMILES, true);
		setBoolean(Options.OPTION_SHOW_LAST_MESS, false);
		//#sijapp cond.if modules_PROXY is "true" #
		setInt(Options.OPTION_PRX_TYPE, 0);
		setString(Options.OPTION_PRX_SERV, emptyString);
		setString(Options.OPTION_PRX_PORT, "1080");
		setString(Options.OPTION_AUTORETRY_COUNT, "1");
		setString(Options.OPTION_PRX_NAME, emptyString);
		setString(Options.OPTION_PRX_PASS, emptyString);
		//#sijapp cond.end #
		setInt(Options.OPTION_VISIBILITY_ID, 0);

//#sijapp cond.if target="MOTOROLA"#
		setInt(Options.OPTION_EXT_CLKEYSTAR, HOTKEY_LIGHT_ONOFF);
//#sijapp cond.else#
		setInt(Options.OPTION_EXT_CLKEYSTAR, HOTKEY_FULLSCR);
//#sijapp cond.end #
		
		setInt(Options.OPTION_EXT_CLKEY0, HOTKEY_INFO);
		setInt(Options.OPTION_EXT_CLKEY1, HOTKEY_GOTO_TOP);
		setInt(Options.OPTION_EXT_CLKEY2, HOTKEY_UP);
		setInt(Options.OPTION_EXT_CLKEY3, HOTKEY_PAGE_UP);
		setInt(Options.OPTION_EXT_CLKEY4, 0);
		setInt(Options.OPTION_EXT_CLKEY5, HOTKEY_SELECT);
		setInt(Options.OPTION_EXT_CLKEY6, 0);
		setInt(Options.OPTION_EXT_CLKEY7, HOTKEY_GOTO_BOTTOM);
		setInt(Options.OPTION_EXT_CLKEY8, HOTKEY_DOWN);
		setInt(Options.OPTION_EXT_CLKEY9, HOTKEY_PAGE_DOWN);
		setInt(Options.OPTION_EXT_CLKEYCALL, HOTKEY_NEWMSG);
		setInt(Options.OPTION_EXT_CLKEYPOUND, HOTKEY_LOCK);

//#sijapp cond.if target isnot "DEFAULT" #
		setBoolean(Options.OPTION_SILENT_MODE, false);
//#sijapp cond.end #
		
		setString(Options.OPTION_UIN2, emptyString);
		setString(Options.OPTION_PASSWORD2, emptyString);
		setString(Options.OPTION_UIN3, emptyString);
		setString(Options.OPTION_PASSWORD3, emptyString);
		setInt(Options.OPTION_CURR_ACCOUNT, 0);

		setBoolean(Options.OPTION_FULL_SCREEN, false);

		//#sijapp cond.if target="MIDP2"#
		setBoolean(Options.OPTION_BRING_UP, true);
		//#sijapp cond.end#

		/* Offset (in hours) between GMT time and local zone time 
		 GMT_time + GMT_offset + DayLightSaving = Local_time */
		setInt(Options.OPTION_GMT_OFFSET, 0);

		/* Offset (in hours) between GMT time and phone clock 
		 Phone_clock + Local_offset - DayLightSaving = GMT_time */
		setInt(Options.OPTION_LOCAL_OFFSET, 0);

		/* DayLightSaving (int) */
		setInt(Options.OPTION_DAYLIGHT_SAVING, 0);

		setBoolean(OPTION_LANG_CHANGED, false);
		setBoolean(OPTION_CREEPING_LINE, false);
		setBoolean(OPTION_SHOW_MESS_ICON, true);
		setBoolean(OPTION_SHOW_NICK, false);
		setBoolean(OPTION_SHOW_MESS_DATE, true);
		setBoolean(OPTION_SHOW_MESS_CLRF, false);
		// Текст сообщения обычным цветом: цветными остаются ник и время,
		// а красный текст читать на V3 тяжело. Пометку «уже переключили»
		// здесь ставить нельзя: значения по умолчанию раскладываются перед
		// чтением настроек, и с ней разовое переключение у тех, кто
		// обновился со старой сборки, не срабатывало ни разу.
		setBoolean(OPTION_MESS_COLORED_TEXT, false);
		setBoolean(OPTION_PLAIN_TEXT_DONE, false);
		setBoolean(OPTION_ASK_FOR_WEB_FT, true);

//#sijapp cond.if modules_CAMERA="true"#
//		setInt(OPTION_CAMERA_LOCATOR, 0);
		setInt(OPTION_CAMERA_RES, 0);
		setInt(OPTION_CAMERA_ENCODING, 0);
//#sijapp cond.end#

//#sijapp cond.if target isnot "DEFAULT"#
		selectSoundType("message.", OPTION_MESS_NOTIF_FILE);
		selectSoundType("msg_low.", OPTION_MESS_UNLOCKED_FILE);
		selectSoundType("typing.", OPTION_TYPING_FILE);
//#sijapp cond.end#		
		
		
		
		setBoolean(OPTION_DELIV_MES_INFO, true);
		setBoolean(OPTION_MIRROR_MENU, false);
		setBoolean(OPTION_SHOW_DELETED_CONT, false);
		
		setBoolean(OPTION_SMALL_FONT, false);
		
//#sijapp cond.if modules_ANTISPAM="true"#		
		setBoolean(OPTION_ANTI_SPAM, false);
		setString(OPTION_ANTI_SPAM_QUESTION, "12-11");
		setString(OPTION_ANTI_SPAM_ANS, "1");
//#sijapp cond.end#		
		setBoolean(OPTION_FULL_TEXTBOX, false);
		
		setInt(OPTION_CAPTION_OFFSET, (Jimm.getPhoneVendor() == Device.PHONE_NOKIA) ? 8 : 0);

//#sijapp cond.if target!="DEFAULT"#
		setString(OPTION_BG_IMAGE_URL,  emptyString);
		setInt   (OPTION_BG_IMAGE,      0);
		setInt   (OPTION_BG_IMAGE_MODE, BG_IMAGE_PAVE);
//#sijapp cond.end#
		
//#sijapp cond.if target="MIDP2" | target="SIEMENS2"#
		setInt   (OPTION_IMG_SCALE,     100);
//#sijapp cond.end#
	}


	/* Delete all record stores */
	static public void reset_rms() throws RecordStoreException
	{
	    String[] stores = RecordStore.listRecordStores();
	    for (int i = 0;i < stores.length;i++)
	    {
		RecordStore.deleteRecordStore(stores[i]);
	    }
	}
	
	private static final String RMS_NAME = "opt"+"ions";
	
	/* Load option values from record store */
	static public void load() throws IOException
	{
		DataInputStream dis = Util.getRmsInputStream(RMS_NAME, null);
		
		if (dis == null) setDefaults();
		else
		{
			int optionKey;
			byte[] optionValue;
			boolean unlockedSeen = false;
			while (dis.available() > 0)
			{
				optionKey = dis.readUnsignedByte();
				if (optionKey == OPTION_MESS_UNLOCKED_FILE || optionKey == OPTION_MESS_UNLOCKED_MODE
						|| optionKey == OPTION_MESS_UNLOCKED_VOL) unlockedSeen = true;
				if (optionKey < 64) /* 0-63 = String */
					setString(optionKey, dis.readUTF());
				else if (optionKey < 128) /* 64-127 = int */
					setInt(optionKey, dis.readInt());
				else if (optionKey < 192) /* 128-191 = boolean */
					setBoolean(optionKey, dis.readBoolean());
				else if (optionKey < 224) /* 192-223 = long */
					setLong(optionKey, dis.readLong());
				else /* 226-255 = Scrambled String */
				{
					optionValue = new byte[dis.readUnsignedShort()];
					dis.readFully(optionValue);
					optionValue = Util.decipherPassword(optionValue);
					setString(optionKey, Util.byteArrayToString(optionValue, 0,
							optionValue.length, true));
				}
			}
			// Retired preferences; never reuse these RMS IDs.
			int[] retired = {5, 7, 17, 18, 34, 68, 69, 92, 96, 97, 102, 103, 158, 159, 161
//#sijapp cond.if modules_PROXY isnot "true"#
				, 83
//#sijapp cond.end#
			};
			for (int i = 0; i < retired.length; i++) options.remove(key(retired[i]));
			// Keep the former mode/volume for both profiles on first upgrade,
			// including disabled sound. The unlocked file starts with the quiet MP3.
			boolean saveNeeded = !unlockedSeen;
			if (!unlockedSeen)
			{
				setLong(OPTION_MESS_UNLOCKED_MODE, getInt(OPTION_MESS_NOTIF_MODE));
				setLong(OPTION_MESS_UNLOCKED_VOL, getInt(OPTION_MESS_NOTIF_VOL));
				setString(OPTION_MESS_UNLOCKED_FILE, "msg_low.mp3");
			}
//#sijapp cond.if modules_PROXY is "true"#
			// Preserve SOCKS (2); retired HTTP (1) becomes a socket connection.
			if (getInt(OPTION_CONN_TYPE) != CONN_TYPE_PROXY) setInt(OPTION_CONN_TYPE, CONN_TYPE_SOCKET);
//#sijapp cond.end#
			// Retired status-request hotkeys become unassigned, without shifting other actions.
			for (int i = 77; i <= 112; i++)
			{
				if ((i <= 82 || i >= 106) && getInt(i) == 14) setInt(i, HOTKEY_NONE);
			}
			// Обновившимся со старой сборки один раз выключаем цветной текст
			// сообщения: ник и время остаются цветными, а сам текст — обычным.
			// В настройках, сохранённых прежней сборкой, этой пометки нет —
			// по ней и видно, что переключение ещё не делали. Кому так не
			// нравится, вернёт галочку в настройках — больше мы её не трогаем.
			if (!getBoolean(OPTION_PLAIN_TEXT_DONE))
			{
				setBoolean(OPTION_MESS_COLORED_TEXT, false);
				setBoolean(OPTION_PLAIN_TEXT_DONE, true);
				saveNeeded = true;
			}
			if (saveNeeded) safeSave();
		}
	}

	/* Save option values to record store */
	static public void save() throws IOException
	{
		/* Save all option key-value pairs */
		ByteArrayOutputStream baos = new ByteArrayOutputStream();
		DataOutputStream dos = new DataOutputStream(baos);
		Enumeration optionKeys = options.keys();
		int optionKey;
		byte[] optionValue;
		while (optionKeys.hasMoreElements())
		{
			optionKey = ((Integer) optionKeys.nextElement()).intValue();
			dos.writeByte(optionKey);
			if (optionKey < 64) /* 0-63 = String */
				dos.writeUTF(getString(optionKey));
			else if (optionKey < 128) /* 64-127 = int */
				dos.writeInt(getInt(optionKey));
			else if (optionKey < 192) /* 128-191 = boolean */
				dos.writeBoolean(getBoolean(optionKey));
			else if (optionKey < 224) /* 192-223 = long */
				dos.writeLong(getLong(optionKey));
			else /* 226-255 = Scrambled String */
			{
				optionValue = Util.stringToByteArray(getString(optionKey), true);
				optionValue = Util.decipherPassword(optionValue);
				dos.writeShort(optionValue.length);
				dos.write(optionValue);
			}
		}
		
		Util.saveStreamToRms(baos.toByteArray(), RMS_NAME, null);
	}

	static public void safeSave()
	{
		try
		{
			save();
		} catch (Exception e)
		{
			JimmException.handleException(new JimmException(172, 0, true));
		}
	}

	/* Option retrieval methods (no type checking!) */
	// TeleMotoMax: ключи настроек — готовые объекты. Раньше каждое чтение
	// настройки создавало Integer: в кадре контакт-листа таких чтений
	// десятки, и весь этот мусор потом собирал сборщик — заметными паузами.
	private static final Integer[] keyCache = new Integer[256];

	private static Integer key(int k)
	{
		if (k < 0 || k >= keyCache.length) return new Integer(k);
		Integer v = keyCache[k];
		if (v == null) keyCache[k] = v = new Integer(k);
		return v;
	}

	static public synchronized String getString(int key)
	{
		switch (key)
		{
		case OPTION_UIN:
		case OPTION_PASSWORD:
			int index = getInt(Options.OPTION_CURR_ACCOUNT) * 2;
			return getString(accountKeys[key == OPTION_UIN ? index : index + 1]);
		}
		return ((String) options.get(key(key)));
	}

	public static boolean validLockPin(String value)
	{
		if (value == null) return false;
		if (value.length() == 0) return true;
		if (value.length() < 4 || value.length() > LOCK_PIN_MAX) return false;
		for (int i = 0; i < value.length(); i++)
			if (value.charAt(i) < '0' || value.charAt(i) > '9') return false;
		return true;
	}

	public static int vibrationMillis(boolean locked)
	{
		long value = getLong(locked ? OPTION_VIBRA_LOCKED_MS : OPTION_VIBRA_UNLOCKED_MS);
		for (int i = 0; i < VIBRATION_DURATIONS.length; i++)
			if (value == VIBRATION_DURATIONS[i]) return (int) value;
		return 500;
	}

	static public synchronized int getInt(int key)
	{
		return (((Integer) options.get(key(key))).intValue());
	}

	static public synchronized boolean getBoolean(int key)
	{
		return (((Boolean) options.get(key(key))).booleanValue());
	}

	static public synchronized long getLong(int key)
	{
		return (((Long) options.get(key(key))).longValue());
	}

	/* Option setting methods (no type checking!) */
	static public synchronized void setString(int key, String value)
	{
		//#sijapp cond.if modules_DEBUGLOG is "true" #
		if (checkKeys && options.containsKey(key(key)))
			System.out.println("Identical keys: " + key);
		//#sijapp cond.end#

		options.put(key(key), value);
	}

	static public synchronized void setInt(int key, int value)
	{
		//#sijapp cond.if modules_DEBUGLOG is "true" #
		if (checkKeys && options.containsKey(key(key)))
			System.out.println("Identical keys: " + key);
		//#sijapp cond.end#

		options.put(key(key), new Integer(value));
	}

	static public synchronized void setBoolean(int key, boolean value)
	{
		//#sijapp cond.if modules_DEBUGLOG is "true" #
		if (checkKeys && options.containsKey(key(key)))
			System.out.println("Identical keys: " + key);
		//#sijapp cond.end#

		options.put(key(key), new Boolean(value));
	}

	static public synchronized void setLong(int key, long value)
	{
		//#sijapp cond.if modules_DEBUGLOG is "true" #
		if (checkKeys && options.containsKey(key(key)))
			System.out.println("Identical keys: " + key);
		//#sijapp cond.end#

		options.put(key(key), new Long(value));
	}

	/**************************************************************************/


	/* Retrieves color value from color scheme */
	static public int getSchemeColor(int type, int theme)
	{
		if (theme == -1) theme = getInt(OPTION_COLOR_SCHEME);
		if ((theme + 1) * 8 > colors.length)
		{
		    setInt(OPTION_COLOR_SCHEME, 0);
		    theme = 0;
		}
		return (colors[theme * 8 + type - 1]);
	}

	static public void editOptions()
	{
		// Construct option form
		if (optionsForm == null)
			optionsForm = new OptionsForm();
		optionsForm.activateForm();
	}

	/** Меню списка контактов — из главного меню, а не из глубины настроек. */
	static public void editContactList()
	{
		if (optionsForm == null)
			optionsForm = new OptionsForm();
		optionsForm.activateContactList();
	}



	//#sijapp cond.if target isnot "DEFAULT"#
	private static void selectSoundType(String name, int option)
	{
		boolean ok;

		/* Test existsing option */
		ok = Util.testSoundFile(getString(option));
		if (ok)
			return;

		/* Test other extensions */
		String[] exts = Util.explode("wav|mp3|amr|mid|midi|mmf", '|');
		String testFile;
		for (int i = 0; i < exts.length; i++)
		{
			testFile = name + exts[i];
			ok = Util.testSoundFile(testFile);
			if (ok)
			{
				setString(option, testFile);
				break;
			}
		}
	}
	//#sijapp cond.end#	
	
//#sijapp cond.if target!="DEFAULT"#
	
	private static void setBgImage(Image img, int placeMode)
	{
		if (placeMode == BG_IMAGE_STRETCH)
			img = ImageList.resizeImage(img, VirtualList.getCanvasWidth(), 
					VirtualList.getCanvasHeight(), false);
		VirtualList.setBackImage(img, placeMode==BG_IMAGE_PAVE);
	}
	
	public static void setBackgroundImage(int mode, String value, final int placeMode)
	{
		switch (mode) {
			case Options.BG_IMAGE_INT :
				try
				{
					setBgImage(Image.createImage("/back.png"), placeMode);
				} 
				catch (IOException e) {} // Do nothing
				break;
				
			case Options.BG_IMAGE_NONE:
				VirtualList.setBackImage(null, false);
				break;
		}
	}
//#sijapp cond.end#
	

	

}

/**************************************************************************/
/**************************************************************************/

/* Form for editing option values */

class OptionsForm implements CommandListener, ItemStateListener, VirtualListCommands, JimmScreen
{



	private boolean lastGroupsUsed, lastHideOffline, lastHideEmpty;

	private int lastSortMethod;

	private int currentHour;
	
	private int currOptMode;
	private int currOptType;

	private String lastUILang;

	/* Options menu */
	private TextList optionsMenu;

	/* Options form */
	private Form optionsForm;

	private static final int RMS_ASK_RESULT_YES = 30000;
	private static final int RMS_ASK_RESULT_NO  = 30001;
	
	private static final int TYPE_TOP_OPTIONS = 10000;
	private static final int TYPE_MCL_OPTIONS = 10001;

	// Constants for menu actios
	private static final int OPTIONS_ACCOUNT     = 0;
	private static final int OPTIONS_NETWORK     = 1;
	private static final int OPTIONS_PROXY       = 2;
	private static final int OPTIONS_INTERFACE   = 3;
	private static final int OPTIONS_BG_IMAGE    = 4;
	private static final int OPTIONS_CAMERA      = 5;
	private static final int OPTIONS_MEDIA       = 30;   // TeleMotoMax: что мост отдаёт телефону
	// Сети моста — каждая своим пунктом: включена ли и сколько её чатов в списке.
	private static final int OPTIONS_NET_TELEGRAM = 31;
	private static final int OPTIONS_NET_MAX      = 32;
	private static final int OPTIONS_NET_EXPRESS  = 33;
	private static final int OPTIONS_HOTKEYS     = 6;
	private static final int OPTIONS_SIGNALING   = 7;
	private static final int OPTIONS_TRAFFIC     = 8;
	private static final int OPTIONS_TIMEZONE    = 9;
	private static final int OPTIONS_COLOR_THEME = 10;
	private static final int OPTIONS_MANAGE_CL   = 13;
	private static final int OPTIONS_RESET_RMS   = 14;
	private static final int OPTIONS_ANTISPAM    = 15;
	private static final int OPTIONS_TEMPLATES   = 19;

	// Constants for contact list menu
	private static final int OPTIONS_ADD_USER      = 100;
	private static final int OPTIONS_SEARCH_USER   = 101;
	private static final int OPTIONS_ADD_GROUP     = 102;
	private static final int OPTIONS_RENAME_GROUP  = 103;
	private static final int OPTIONS_DELETE_GROUP  = 104;
	private static final int OPTIONS_PRIVATE_LISTS = 105;
	private static final int OPTIONS_ALL_CHATS     = 106;

	
	// Options
	private TextField txtUIN;
	private TextField[] uinTextField;
	private TextField[] passwordTextField;
	private TextField srvHostTextField;
	private TextField srvPortTextField;
	private ChoiceGroup encryptionChoiceGroup;
	private TextField encryptionPskTextField;
	private ChoiceGroup keepConnAliveChoiceGroup;
	private TextField connAliveIntervTextField;
	private ChoiceGroup connPropChoiceGroup;
//#sijapp cond.if modules_PROXY is "true"#
	private ChoiceGroup connTypeChoiceGroup;
//#sijapp cond.end#
	private ChoiceGroup autoConnectChoiceGroup;
	private TextField reconnectNumberTextField;
	private ChoiceGroup uiLanguageChoiceGroup;
	private TextField lockPinTextField;
	private ChoiceGroup videoRotateChoice;     // TeleMotoMax, раздел «Медиа»
	private ChoiceGroup photoRotateChoice;
	private ChoiceGroup mediaPhotoSize, mediaPhotoQuality, mediaPhotoKb, mediaVideoKb;
	private ChoiceGroup mediaVideoSize, mediaVideoKbps, mediaVideoSeconds;
	private ChoiceGroup mediaVoiceKbps, mediaVoiceSeconds;
	private TextField mediaMemKb;
	// Значения списков «Медиа»; первый пункт каждого — «как в профиле моста».
	private static final String[] MEDIA_PHOTO_SIZES = { "176x176", "176x220", "240x320", "320x240", "480x640", "640x480" };
	private static final String[] MEDIA_VIDEO_SIZES = Options.MEDIA_VIDEO_SIZES;
	private static final int[] MEDIA_VIDEO_KBPS = Options.MEDIA_VIDEO_KBPS;
	private static final int[] MEDIA_QUALITIES = { 40, 50, 60, 70, 80, 90, 95 };
	private static final int[] MEDIA_PHOTO_KBS = { 20, 40, 60, 100, 150, 250 };
	private static final int[] MEDIA_VIDEO_SECS = { 5, 10, 15, 20, 30, 60, 120, 180, 300 };
	// Предел размера ролика: клип целиком лежит в куче телефона, и не одной
	// копией — на V3 32 КБ кончались OutOfMemoryError.
	private static final int[] MEDIA_VIDEO_KBS = { 16, 24, 32, 48, 64, 128, 256, 512 };
	private static final int[] MEDIA_VOICE_KBPS10 = { 48, 52, 59, 67, 74, 80, 102, 122 };   // режимы AMR-NB ×10
	private static final int[] MEDIA_VOICE_SECS = { 30, 60, 120, 300, 600 };
	// Чатов в контакт-листе — числовое поле: пусто — как в профиле моста
	// (0, не шлётся), 0 — все чаты (мосту уходит 65535: ноль в паре занят
	// под «как в профиле»), иначе само число.
	private static final int MEDIA_ROSTER_ALL = 65535;
	private ChoiceGroup choiceInterfaceMisc;
	private ChoiceGroup clSortByChoiceGroup;
	private ChoiceGroup chrgChat;
	private ChoiceGroup chrgMessFormat;
	private ChoiceGroup vibratorChoiceGroup;
	private ChoiceGroup unlockedVibrationDuration, lockedVibrationDuration;
	private ChoiceGroup chsBringUp;
	private ChoiceGroup chsFSMode;
	private ChoiceGroup choiceCurAccount;

	// Форма сети моста: включена ли и сколько её чатов класть в список.
	private ChoiceGroup netEnabled;
	private TextField netRosterLimit;
	private ChoiceGroup chsTimeZone;
	private ChoiceGroup chsCurrTime;
	private ChoiceGroup chsDayLight;
//#sijapp cond.if modules_CAMERA="true"#
	//	private ChoiceGroup clCamDevGroup;
	private ChoiceGroup camRes;
	private ChoiceGroup camEnc;
//#sijapp cond.end#

//#sijapp cond.if target isnot "DEFAULT"#
	private ChoiceGroup messageNotificationSoundChoice;
	private Gauge messageNotificationSoundVolume;
	private ChoiceGroup unlockedNotificationSoundChoice;
	private ChoiceGroup typingNotificationSoundChoice;
	private Gauge unlockedNotificationSoundVolume;
	private Gauge typingNotificationSoundVolume;
	private ChoiceGroup backImgGroup;
	private ChoiceGroup backImgModeGroup;
//#sijapp cond.end#
	
//#sijapp cond.if target="MIDP2" | target="SIEMENS2"#
	private ChoiceGroup imagesScale;
//#sijapp cond.end#	

//#sijapp cond.if modules_TRAFFIC is "true" #
	private TextField costPerPacketTextField;
	private TextField costPerDayTextField;
	private TextField costPacketLengthTextField;
	private TextField currencyTextField;
//#sijapp cond.end#
	
	private ChoiceGroup choiceContactList;
//#sijapp cond.if target="MOTOROLA" | target="MIDP2" #
	private TextField lightTimeout;
	private TextField historyCount;     // TeleMotoMax
	private TextField chatMessages;     // TeleMotoMax
//#sijapp cond.if modules_CAMERA="true"#
	private String[] cameraSizes;           // TeleMotoMax: размеры снимка в разделе «Камера»
//#sijapp cond.end#
	private ChoiceGroup lightManual;
//#sijapp cond.end#
	private TextField txtCapOffset;
	
//#sijapp cond.if modules_PROXY is "true"#
	private ChoiceGroup srvProxyType;
	private TextField srvProxyHostTextField;
	private TextField srvProxyPortTextField;
	private TextField srvProxyLoginTextField;
	private TextField srvProxyPassTextField;
	private TextField connAutoRetryTextField;
//#sijapp cond.end#
	
//#sijapp cond.if modules_ANTISPAM="true"#	
	private ChoiceGroup chsUseAntispam;
	private TextField txtfAntispamQ;
	private TextField txtfAntispamA;
//#sijapp cond.end#
	
	private TextList keysMenu;
	private TextList actionMenu;
	private TextList tlColorScheme;
	private TextList tlRmsAsk;
	private TextList groupSelector;


	private static OptionsForm _this;

	// Constructor
	public OptionsForm() throws NullPointerException
	{
		_this = this;

		// Initialize hotkeys
		keysMenu = new TextList(ResourceBundle.getString("ext_listhotkeys"));
		keysMenu.setCyclingCursor(true);
		
		keysMenu.setCommandListener(this);
		keysMenu.setCyclingCursor(true);
		actionMenu = new TextList(ResourceBundle.getString("ext_actionhotkeys"));
		actionMenu.setCommandListener(this);

		/*************************************************************************/

		optionsMenu = new TextList(ResourceBundle.getString("options_lng"));
		optionsMenu.setMode(VirtualList.CURSOR_MODE_DISABLED);
		
		JimmUI.setColorScheme(optionsMenu, false, -1, true);

		optionsMenu.addCommandEx(JimmUI.cmdSelect, VirtualList.MENU_TYPE_RIGHT_BAR);
		optionsMenu.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR); 
		optionsMenu.setCommandListener(this);
		optionsMenu.setCyclingCursor(true);

		// Initialize options form
		optionsForm = new Form(ResourceBundle.getString("options_lng"));
		optionsForm.setCommandListener(this);
		optionsForm.setItemStateListener(this);
		
		
		fillHotkeysActions(true);

		//System.out.println("OPTIONS_GMT_OFFSET="+Options.getInt(Options.OPTIONS_GMT_OFFSET));
		//System.out.println("OPTIONS_LOCAL_OFFSET="+Options.getInt(Options.OPTIONS_LOCAL_OFFSET));
	}

	// Initialize the kist for the Options menu
	private void initOptionsList(int type)
	{
		if (type != currOptType) currOptMode = 0;
		currOptType = type;
		
		
		optionsMenu.clear();
		JimmUI.setColorScheme(optionsMenu, false, -1, true);
		
		switch (type)
		{
		case TYPE_TOP_OPTIONS:
			JimmUI.addTextListItem(optionsMenu, "options_account", MainMenu.menuIcons.elementAt(11), OPTIONS_ACCOUNT, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "options_network", MainMenu.menuIcons.elementAt(12), OPTIONS_NETWORK, true, -1, Font.STYLE_PLAIN);
//#sijapp cond.if modules_PROXY is "true"#
			if (Options.getInt(Options.OPTION_CONN_TYPE) == Options.CONN_TYPE_PROXY)
				JimmUI.addTextListItem(optionsMenu, "proxy", MainMenu.menuIcons.elementAt(13), OPTIONS_PROXY, true, -1, Font.STYLE_PLAIN); 
//#sijapp cond.end#
			JimmUI.addTextListItem(optionsMenu, "options_interface", MainMenu.menuIcons.elementAt(14), OPTIONS_INTERFACE, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "color_scheme", MainMenu.menuIcons.elementAt(15), OPTIONS_COLOR_THEME, true, -1, Font.STYLE_PLAIN);
			
//#sijapp cond.if target!="DEFAULT"#			
			JimmUI.addTextListItem(optionsMenu, "background_image", MainMenu.menuIcons.elementAt(34), OPTIONS_BG_IMAGE, true, -1, Font.STYLE_PLAIN);
//#sijapp cond.end#			
//#sijapp cond.if modules_CAMERA="true"#
			if (System.getProperty("video.snapshot.encodings") != null)
				JimmUI.addTextListItem(optionsMenu, "options_camera", MainMenu.menuIcons.elementAt(17), OPTIONS_CAMERA, true, -1, Font.STYLE_PLAIN);
//#sijapp cond.end#
			JimmUI.addTextListItem(optionsMenu, "options_media", MainMenu.menuIcons.elementAt(17), OPTIONS_MEDIA, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "options_net_telegram", MainMenu.menuIcons.elementAt(11), OPTIONS_NET_TELEGRAM, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "options_net_max", MainMenu.menuIcons.elementAt(11), OPTIONS_NET_MAX, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "options_net_express", MainMenu.menuIcons.elementAt(11), OPTIONS_NET_EXPRESS, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "options_hotkeys", MainMenu.menuIcons.elementAt(18), OPTIONS_HOTKEYS, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "options_signaling", MainMenu.menuIcons.elementAt(19), OPTIONS_SIGNALING, true, -1, Font.STYLE_PLAIN);
//#sijapp cond.if modules_TRAFFIC is "true"#
			JimmUI.addTextListItem(optionsMenu, "traffic_lng", MainMenu.menuIcons.elementAt(21), OPTIONS_TRAFFIC, true, -1, Font.STYLE_PLAIN); 
//#sijapp cond.end#
			JimmUI.addTextListItem(optionsMenu, "time_zone", MainMenu.menuIcons.elementAt(22), OPTIONS_TIMEZONE, true, -1, Font.STYLE_PLAIN);
			
//#sijapp cond.if modules_ANTISPAM="true"#			
			JimmUI.addTextListItem(optionsMenu, "antispam", MainMenu.menuIcons.elementAt(25), OPTIONS_ANTISPAM, true, -1, Font.STYLE_PLAIN);
//#sijapp cond.end#
			
			JimmUI.addTextListItem(optionsMenu, "templates", MainMenu.menuIcons.elementAt(35), OPTIONS_TEMPLATES, true, -1, Font.STYLE_PLAIN); 
			
			JimmUI.addTextListItem(optionsMenu, "reset_rms_caption", MainMenu.menuIcons.elementAt(26), OPTIONS_RESET_RMS, true, -1, Font.STYLE_PLAIN);
			break;
			
		case TYPE_MCL_OPTIONS:
			JimmUI.addTextListItem(optionsMenu, "all_chats", MainMenu.menuIcons.elementAt(2), OPTIONS_ALL_CHATS, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "add_user", MainMenu.menuIcons.elementAt(27), OPTIONS_ADD_USER, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "add_group", MainMenu.menuIcons.elementAt(28), OPTIONS_ADD_GROUP, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "search_user", MainMenu.menuIcons.elementAt(29), OPTIONS_SEARCH_USER, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "del_group", MainMenu.menuIcons.elementAt(30), OPTIONS_DELETE_GROUP, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "rename_group", MainMenu.menuIcons.elementAt(31), OPTIONS_RENAME_GROUP, true, -1, Font.STYLE_PLAIN);
			JimmUI.addTextListItem(optionsMenu, "priv_lists", MainMenu.menuIcons.elementAt(32), OPTIONS_PRIVATE_LISTS, true, -1, Font.STYLE_PLAIN);
			break;
		}

		optionsMenu.selectTextByIndex(currOptMode);
		optionsMenu.activate(Jimm.display);
	}
	
	public void vlKeyPress(VirtualList sender, int keyCode, int type) {}
	public void vlItemClicked(VirtualList sender) {}
	
	public void vlCursorMoved(VirtualList sender) 
	{
		if (tlColorScheme == sender)
		{
			int index = tlColorScheme.getCurrTextIndex();
			JimmUI.setColorScheme(tlColorScheme, false, index, true);
		}
	}
	
	private void InitResetRmsUI()
	{
		tlRmsAsk = new TextList(ResourceBundle.getString("reset_rms_caption"));
		JimmUI.setColorScheme(tlRmsAsk, true, -1, true);

		tlRmsAsk.addBigText(ResourceBundle.getString("reset_rms_ask"), tlRmsAsk.getTextColor(), Font.STYLE_PLAIN, -1);
		tlRmsAsk.doCRLF(-1);
		tlRmsAsk.doCRLF(-1);
		tlRmsAsk.addBigText(ResourceBundle.getString("reset_rms_no"), tlRmsAsk.getTextColor(), Font.STYLE_BOLD, RMS_ASK_RESULT_NO);
		tlRmsAsk.doCRLF(1);
		tlRmsAsk.addBigText(ResourceBundle.getString("reset_rms_yes"), tlRmsAsk.getTextColor(), Font.STYLE_BOLD, RMS_ASK_RESULT_YES);
		tlRmsAsk.doCRLF(2);
		tlRmsAsk.selectTextByIndex(RMS_ASK_RESULT_NO);
		tlRmsAsk.addCommandEx(JimmUI.cmdSelect, VirtualList.MENU_TYPE_RIGHT_BAR);

		tlRmsAsk.setVLCommands(this);
		tlRmsAsk.setCommandListener(this);

		tlRmsAsk.activate(Jimm.display);
	}

	private void InitColorThemeUI()
	{
		tlColorScheme = new TextList(ResourceBundle.getString("color_scheme"));
		JimmUI.setColorScheme(tlColorScheme, false, -1, true);
		
		final String[] sceme_names = Util.explode(
			"black_on_white" + "|" +
			"white_on_black" + "|" +
			"white_on_blue" + "|" +
			"pink_scheme" + "|" +
			"green_scheme" + "|" +
			"sand_scheme" + "|" +
			"hacker_scheme" + "|" +
			"aqua_scheme" + "|" +
			"green_night_scheme" + "|" +
			"opera_mini_scheme" + "|" +
			"ergonomic_scheme" + "|" +
			"golem_scheme" + "|" +
			"snowy_scheme" + "|" +
			"bento_scheme"  + "|" +
			"quake_scheme"  + "|" +
			"green2_scheme"  + "|" +
			"silver_scheme"  + "|" + 
			"neon_theme",
			'|'
		);
		
		for (int i = 0; i < sceme_names.length; i++)
			JimmUI.addTextListItem(tlColorScheme, sceme_names[i], null, i, true, -1, Font.STYLE_PLAIN);
		
		tlColorScheme.addCommandEx(JimmUI.cmdOk, VirtualList.MENU_TYPE_RIGHT_BAR);
		tlColorScheme.addCommandEx(JimmUI.cmdCancel, VirtualList.MENU_TYPE_LEFT_BAR);
		
		tlColorScheme.selectTextByIndex(Options.getInt(Options.OPTION_COLOR_SCHEME));
		
		tlColorScheme.setVLCommands(this);
		tlColorScheme.setCommandListener(this);
		
		tlColorScheme.activate(Jimm.display);
	}

/*****************************************************************************/
/*****************************************************************************/
/*****************************************************************************/	
	
	private Object[] hotKeysOptCodes = {
		new Integer(Options.OPTION_EXT_CLKEY0),     "ext_clhotkey0", null,
		new Integer(Options.OPTION_EXT_CLKEY1),     "ext_clhotkey1", null,
		new Integer(Options.OPTION_EXT_CLKEY2),     "ext_clhotkey2", null,
		new Integer(Options.OPTION_EXT_CLKEY3),     "ext_clhotkey3", null,
		new Integer(Options.OPTION_EXT_CLKEY4),     "ext_clhotkey4", null,
		new Integer(Options.OPTION_EXT_CLKEY5),     "ext_clhotkey5", null,
		new Integer(Options.OPTION_EXT_CLKEY6),     "ext_clhotkey6", null,
		new Integer(Options.OPTION_EXT_CLKEY7),     "ext_clhotkey7", null,
		new Integer(Options.OPTION_EXT_CLKEY8),     "ext_clhotkey8", null,
		new Integer(Options.OPTION_EXT_CLKEY9),     "ext_clhotkey9", null,
		new Integer(Options.OPTION_EXT_CLKEYSTAR),  "ext_clhotkeystar", null,
		new Integer(Options.OPTION_EXT_CLKEYPOUND), "ext_clhotkeypound", null,
//#sijapp cond.if target is "SIEMENS2"#		
		new Integer(Options.OPTION_EXT_CLKEYCALL),  "ext_clhotkeycall", null,
//#sijapp cond.end#
	};

	static private final int hotKeysOptCodesSize = 3;
	static private int HOTKEYS_COL_VALUE = 0;
	static private int HOTKEYS_COL_NAME  = 1;
	
	private Vector hotKeysNames = new Vector();
	
	private void fillHotkeysActions(boolean toArray)
	{
		if (toArray) hotKeysNames.removeAllElements();
		else actionMenu.clear();
		showHotkeyAction(Options.HOTKEY_NONE, "ext_hotkey_action_none", toArray);
		showHotkeyAction(Options.HOTKEY_INFO, "info", toArray);
		showHotkeyAction(Options.HOTKEY_NEWMSG, "send_message", toArray);
//#sijapp cond.if modules_HISTORY is "true"#		
		showHotkeyAction(Options.HOTKEY_HISTORY, "history", toArray);
//#sijapp cond.end#		
		showHotkeyAction(Options.HOTKEY_USER_GROUPS, "ext_hotkey_action_groups", toArray);
		showHotkeyAction(Options.HOTKEY_ONOFF, "ext_hotkey_action_onoff", toArray);
		showHotkeyAction(Options.HOTKEY_OPTIONS, "options_lng", toArray);
		showHotkeyAction(Options.HOTKEY_MENU, "menu", toArray);
		showHotkeyAction(Options.HOTKEY_LOCK, "keylock", toArray);
//#sijapp cond.if target is "MIDP2"#
		if (Jimm.device.featureSupported(Device.FEATURE_MINIMIZE))
			showHotkeyAction(Options.HOTKEY_MINIMIZE, "minimize", toArray);
//#sijapp cond.end#
		showHotkeyAction(Options.HOTKEY_CLI_INFO, "dc_info", toArray);
//#sijapp cond.if target != "DEFAULT"#		
		showHotkeyAction(Options.HOTKEY_FULLSCR, "full_screen", toArray);
		showHotkeyAction(Options.HOTKEY_SOUNDOFF, "#sound_off", toArray);
		if (Jimm.device.featureSupported(Device.FEATURE_LIGHT_OFF))
			showHotkeyAction(Options.HOTKEY_LIGHT_ONOFF, "light_onoff", toArray);
		if (Jimm.device.featureSupported(Device.FEATURE_LIGHT_INTENSITY))
		{
			showHotkeyAction(Options.HOTKEY_INC_LIGHT, "light_inc", toArray);
			showHotkeyAction(Options.HOTKEY_DEC_LIGHT, "light_dec", toArray);
		}
//#sijapp cond.end#
		
		showHotkeyAction(Options.HOTKEY_UP, "up", toArray);
		showHotkeyAction(Options.HOTKEY_DOWN, "down", toArray);
		showHotkeyAction(Options.HOTKEY_GOTO_TOP, "goto_top", toArray);
		showHotkeyAction(Options.HOTKEY_GOTO_BOTTOM, "goto_bottom", toArray);
		showHotkeyAction(Options.HOTKEY_PAGE_UP, "page_up", toArray);
		showHotkeyAction(Options.HOTKEY_PAGE_DOWN, "page_down", toArray);
		showHotkeyAction(Options.HOTKEY_NEXT_CHAT, "next_chat", toArray);
		showHotkeyAction(Options.HOTKEY_PREV_CHAT, "prev_chat", toArray);
		showHotkeyAction(Options.HOTKEY_SELECT, "select", toArray);
		
	}
	
	private void showHotkeyAction(int value, String name, boolean toArray)
	{
		if (toArray)
			hotKeysNames.addElement(new Object[] {new Integer(value), name});
		else
			JimmUI.addTextListItem(actionMenu, name, null, value, true, -1, Font.STYLE_PLAIN);
	}

	private String getHotKeyActName(String langStr, int index)
	{
		int optionValue = ((Integer)hotKeysOptCodes[index*hotKeysOptCodesSize+2]).intValue();
		for (int i = 0; i < hotKeysNames.size(); i++)
		{
			Object[] array = (Object[])hotKeysNames.elementAt(i);
			Integer value = (Integer)array[HOTKEYS_COL_VALUE];
			String name = (String)array[HOTKEYS_COL_NAME];
			if (value.intValue() == optionValue)
				return ResourceBundle.getString(langStr) + ": " + ResourceBundle.getString(name);
		}
		return ResourceBundle.getString(langStr) + ": <???>";
	}
	
	private void InitHotkeyMenuUI()
	{
		int lastItemIndex = keysMenu.getCurrTextIndex();
		keysMenu.clear();
		JimmUI.setColorScheme(keysMenu, false, -1, true);
		
		int index = 0;
		for (int i = 0; i < hotKeysOptCodes.length; i += hotKeysOptCodesSize)
		{
			String lngStr = (String)hotKeysOptCodes[i+1];
			JimmUI.addTextListItem(
				keysMenu, getHotKeyActName(lngStr, index), 
				null, index, false, -1, Font.STYLE_PLAIN
			);
			index++;
		}
		
		keysMenu.selectTextByIndex(lastItemIndex);

//#sijapp cond.if target!="RIM" & target!="DEFAULT"#
		keysMenu.addCommandEx(JimmUI.cmdMenu, VirtualList.MENU_TYPE_RIGHT_BAR);
//#sijapp cond.end#

		keysMenu.addCommandEx(JimmUI.cmdSave, VirtualList.MENU_TYPE_RIGHT);
		keysMenu.addCommandEx(JimmUI.cmdSelect, VirtualList.MENU_TYPE_RIGHT);
		keysMenu.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR);
		
		
		keysMenu.activate(Jimm.display);
	}


/*****************************************************************************/
/*****************************************************************************/
/*****************************************************************************/	
	
	
	/* Show form for adding user */
	private void showTextBoxForm(String caption, String label, String text, int fieldType)
	{
		txtUIN = new TextField(ResourceBundle.getString(label), text, 16, fieldType);
		optionsForm.append(txtUIN);
		Jimm.display.setCurrent(optionsForm);
		Jimm.setBkltOn(true);
	}
	

	///////////////////////////////////////////////////////////////////////////

	// Accounts
	private Command cmdAddNewAccount = new Command(ResourceBundle
			.getString("add_new"), Command.ITEM, 3);

	private Command cmdDeleteAccount = new Command(ResourceBundle.getString(
			"delete", ResourceBundle.FLAG_ELLIPSIS), Command.ITEM, 3);



	private int currAccount;

	private Vector uins = new Vector();

	private Vector passwords = new Vector();

	private int maxAccountsCount = Options.accountKeys.length / 2;




	private void readAccontsData()
	{
		uins.removeAllElements();
		passwords.removeAllElements();
		int index;
		String uin;
		for (int i = 0; i < maxAccountsCount; i++)
		{
			index = i * 2;
			uin = Options.getString(Options.accountKeys[index]);
			if ((i != 0) && (uin.length() == 0))
				continue;
			uins.addElement(uin);
			passwords.addElement(Options
					.getString(Options.accountKeys[index + 1]));
		}
		currAccount = Options.getInt(Options.OPTION_CURR_ACCOUNT);
	}

	private String checkUin(String value)
	{
		if ((value == null) || (value.length() == 0))
			return "---";
		return value;
	}

	public void addAccount (String uin, String password)
	{
		readAccontsControls();
		if (checkUin((String) uins.elementAt(currAccount)).equals("---"))
		{
			uins.setElementAt(uin, currAccount);
			passwords.setElementAt(password, currAccount);
		} else
		{
			uins.addElement(uin);
			passwords.addElement(password);
		}
		optionsForm.addCommand(JimmUI.cmdSave);
		clearForm();
		showAccountControls();
	}

	private void showAccountControls()
	{
		int size = uins.size();

		if (size != 1)
		{
			if (choiceCurAccount == null)
				choiceCurAccount = new ChoiceGroup(ResourceBundle
						.getString("options_account"), Choice.EXCLUSIVE);
//#sijapp cond.if target="MIDP2" | target="MOTOROLA" | target="SIEMENS2" | target="RIM"#
			choiceCurAccount.deleteAll();
//#sijapp cond.else#
			while (choiceCurAccount.size() > 0) { choiceCurAccount.delete(0); }
//#sijapp cond.end#

			for (int i = 0; i < size; i++)
				choiceCurAccount.append(checkUin((String) uins.elementAt(i)),
						null);
			optionsForm.append(choiceCurAccount);
			if (currAccount >= size)
				currAccount = size - 1;
			choiceCurAccount.setSelectedIndex(currAccount, true);
		}

		uinTextField = new TextField[size];
		passwordTextField = new TextField[size];
		TextField uinFld;
		TextField passFld;
		for (int i = 0; i < size; i++)
		{
			if (size > 1)
				optionsForm.append("---");

			String add = (size == 1) ? "" : "-" + (i + 1);

			uinFld = new TextField(ResourceBundle.getString("uin")
					+ add, (String) uins.elementAt(i), 12, TextField.NUMERIC);
			passFld = new TextField(ResourceBundle
					.getString("password")
					+ add, (String) passwords.elementAt(i), 32,
					TextField.PASSWORD);

			optionsForm.append(uinFld);
			optionsForm.append(passFld);

			uinTextField[i] = uinFld;
			passwordTextField[i] = passFld;
		}
		uinFld = null;
		passFld = null;

		if (size != maxAccountsCount) {
			optionsForm.addCommand(cmdAddNewAccount);
		}
		if (size != 1)
			optionsForm.addCommand(cmdDeleteAccount);
	}

	// Включена ли сеть по настройке пункта меню (у eXpress — число 1/2 с 0.71,
	// у остальных — флажок).
	private static boolean netEnabled(int mode)
	{
		if (mode == OPTIONS_NET_TELEGRAM) return Options.getBoolean(Options.OPTION_TELEGRAM_ON);
		if (mode == OPTIONS_NET_MAX) return Options.getBoolean(Options.OPTION_MAX_ON);
		return Options.getInt(Options.OPTION_EXPRESS) != 2;
	}

	private static void setNetEnabled(int mode, boolean on)
	{
		if (mode == OPTIONS_NET_TELEGRAM) Options.setBoolean(Options.OPTION_TELEGRAM_ON, on);
		else if (mode == OPTIONS_NET_MAX) Options.setBoolean(Options.OPTION_MAX_ON, on);
		else Options.setInt(Options.OPTION_EXPRESS, on ? 1 : 2);
	}

	private static int netLimitOption(int mode)
	{
		return mode == OPTIONS_NET_TELEGRAM ? Options.OPTION_MEDIA_ROSTER_LIMIT
				: (mode == OPTIONS_NET_MAX ? Options.OPTION_MAX_ROSTER_LIMIT : Options.OPTION_EXPRESS_ROSTER_LIMIT);
	}

	private void showNetworkForm(int mode)
	{
		netEnabled = new ChoiceGroup(ResourceBundle.getString("net_bridge"), Choice.MULTIPLE);
		netEnabled.append(ResourceBundle.getString("net_enabled"), null);
		netEnabled.setSelectedIndex(0, netEnabled(mode));
		optionsForm.append(netEnabled);
		int roster = Options.getInt(netLimitOption(mode));
		netRosterLimit = new TextField(ResourceBundle.getString("media_roster_limit"),
				roster <= 0 ? "" : (roster == MEDIA_ROSTER_ALL ? "0" : String.valueOf(roster)), 4, TextField.NUMERIC);
		optionsForm.append(netRosterLimit);
	}

	private void readNetworkForm(int mode)
	{
		setNetEnabled(mode, netEnabled.isSelected(0));
		Options.setInt(netLimitOption(mode), parseRosterLimit(netRosterLimit.getString()));
	}

	// Поле «чатов в списке»: пусто — как в мосте (0), 0 — все (65535).
	private static int parseRosterLimit(String raw)
	{
		String text = raw.trim();
		if (text.length() == 0) return 0;
		try
		{
			int n = Integer.parseInt(text);
			return n <= 0 ? MEDIA_ROSTER_ALL : Math.min(9999, n);
		}
		catch (Exception ignore) { return 0; }
	}

	private void setAccountOptions()
	{
		int size = uins.size();
		String uin, pass;

		for (int i = 0; i < maxAccountsCount; i++)
		{
			if (i < size)
			{
				uin = (String) uins.elementAt(i);
				pass = (String) passwords.elementAt(i);
			} else
				uin = pass = Options.emptyString;

			Options.setString(Options.accountKeys[2 * i], uin);
			Options.setString(Options.accountKeys[2 * i + 1], pass);
		}

		if (currAccount >= size)
			currAccount = size - 1;
		Options.setInt(Options.OPTION_CURR_ACCOUNT, currAccount);
	}

	private void readAccontsControls()
	{
		uins.removeAllElements();
		passwords.removeAllElements();
		for (int i = 0; i < uinTextField.length; i++)
		{
			uins.addElement(uinTextField[i].getString());
			passwords.addElement(passwordTextField[i].getString());
		}

		currAccount = (choiceCurAccount == null) ? 0 : choiceCurAccount
				.getSelectedIndex();
	}

	public void itemStateChanged(Item item)
	{

		if (uinTextField != null)
		{
			int accCount = uinTextField.length;
			if (accCount != 1)
			{
				for (int i = 0; i < accCount; i++)
				{
					if (uinTextField[i] != item)
						continue;
					choiceCurAccount.set(i, checkUin(uinTextField[i]
							.getString()), null);
					return;
				}
			}
		}
	}

	///////////////////////////////////////////////////////////////////////////

	public void activateForm()
	{
		// Store some last values
		lastUILang      = Options.getString (Options.OPTION_UI_LANGUAGE);
		lastHideOffline = Options.getBoolean(Options.OPTION_CL_HIDE_OFFLINE);
		lastHideEmpty   = Options.getBoolean(Options.OPTION_CL_HIDE_EMPTY);
		lastGroupsUsed  = Options.getBoolean(Options.OPTION_USE_GROUPS);
		lastSortMethod  = Options.getInt    (Options.OPTION_CL_SORT_BY);

		initOptionsList(TYPE_TOP_OPTIONS);
		JimmUI.setLastScreen(this, false);
	}

	public void activateContactList()
	{
		initOptionsList(TYPE_MCL_OPTIONS);
		JimmUI.setLastScreen(this, false);
	}

	/* Activate options menu */
	public void activate()
	{
		initOptionsList(currOptType);
		JimmUI.setLastScreen(this, false);
	}
	
	public boolean isScreenActive()
	{
		return JimmUI.isControlActive(optionsMenu) || optionsForm.isShown();
	}

	final private static int TAG_DELETE_ACCOUNT = 1;

	/* Helpers for options UI: */
	static private void addStr(ChoiceGroup chs, String lngStr)
	{
		String[] strings = Util.explode(lngStr, '|');
		for (int i = 0; i < strings.length; i++)
			chs.append(ResourceBundle.getString(strings[i]), null);
	}

	static private ChoiceGroup createSelector(String cap, String items,
			int optValue)
	{
		ChoiceGroup chs = new ChoiceGroup(ResourceBundle.getString(cap),
				Choice.EXCLUSIVE);
		addStr(chs, items);
		int value = Options.getInt(optValue);
		if ((value >= 0) && (value < chs.size())) chs.setSelectedIndex(value, true);
		return chs;
	}

	static private void setChecked(ChoiceGroup chs, String lngStr, int optValue)
	{
		addStr(chs, lngStr);
		chs.setSelectedIndex(chs.size() - 1, Options.getBoolean(optValue));
	}
	
	private void dataToForm(int mode)
	{
		optionsForm.removeCommand(JimmUI.cmdSave);
		optionsForm.removeCommand(JimmUI.cmdBack);
		optionsForm.removeCommand(JimmUI.cmdOk);
		
		// Delete all items
		clearForm();

		// Add elements, depending on selected option menu item
		switch (mode)
		{
		case OPTIONS_ACCOUNT:
			readAccontsData();
			showAccountControls();
			break;

		case OPTIONS_NETWORK:
			showNetworkOptions();
			break;

//#sijapp cond.if modules_PROXY is "true"#
		case OPTIONS_PROXY:
			showProxyOptions();
			break;
//#sijapp cond.end#
			
		case OPTIONS_INTERFACE:
			showInterfaceOptions();
			break;

		case OPTIONS_MEDIA:
			showMediaOptions();
			break;

		case OPTIONS_NET_TELEGRAM:
		case OPTIONS_NET_MAX:
		case OPTIONS_NET_EXPRESS:
			showNetworkForm(mode);
			break;

//#sijapp cond.if modules_CAMERA="true"#
		case OPTIONS_CAMERA:
			showCameraOptions();
			break;
//#sijapp cond.end #

		case OPTIONS_HOTKEYS:
			for (int i = 0; i < hotKeysOptCodes.length; i += hotKeysOptCodesSize)
			{
				int optKey = ((Integer)hotKeysOptCodes[i]).intValue();
				hotKeysOptCodes[i+2] = new Integer(Options.getInt(optKey));
			}
			
			InitHotkeyMenuUI();
			return;
			
		case OPTIONS_COLOR_THEME:
			InitColorThemeUI();
			return;
			
//#sijapp cond.if target!="DEFAULT"#
		case OPTIONS_BG_IMAGE:
			showBackgrImageOptions();
			break;
			
//#sijapp cond.end#			

		case OPTIONS_SIGNALING:
			showSignalingOptions();
			break;
			

		//#sijapp cond.if modules_TRAFFIC is "true"#
		case OPTIONS_TRAFFIC:
			showTrafficOptions();
			break;
		//#sijapp cond.end#

		case OPTIONS_TIMEZONE:
			showTimezoneOptions();
			break;
			
			
		case OPTIONS_MANAGE_CL:
			initOptionsList(TYPE_MCL_OPTIONS);
			return;
			
		case OPTIONS_RESET_RMS:
			InitResetRmsUI();
			return;
			
		case OPTIONS_ADD_USER:
			showTextBoxForm("add_user", "uin", null, TextField.NUMERIC);
			optionsForm.addCommand(JimmUI.cmdOk);
			optionsForm.addCommand(JimmUI.cmdBack);
			return;
			
		case OPTIONS_ADD_GROUP:
			showTextBoxForm("add_group", "group_name", null, TextField.ANY);
			optionsForm.addCommand(JimmUI.cmdOk);
			optionsForm.addCommand(JimmUI.cmdBack);
			return;
			
		case OPTIONS_SEARCH_USER:
			Search searchf = new Search();
			searchf.getSearchForm().activate(Search.SearchForm.ACTIV_JUST_SHOW);
			return;

		// TeleMotoMax: весь список чатов моста, включая те, что не влезли
		// в контакт-лист телефона.
		case OPTIONS_ALL_CHATS:
			ChatListViewer.show(null);
			return;
			
		case OPTIONS_PRIVATE_LISTS:
			new PrivateListsForm().activate();
			return;
			
		case OPTIONS_DELETE_GROUP:
			groupSelector = JimmUI.showGroupSelector("del_group", this, JimmUI.SHS_TYPE_EMPTY, -1);
			return;
			
		case OPTIONS_RENAME_GROUP:
			groupSelector = JimmUI.showGroupSelector("rename_group", this, JimmUI.SHS_TYPE_ALL, -1);
			return;
			
			
			
		case OPTIONS_TEMPLATES:
			Templates.showTemplates(null);
			return;
			
//#sijapp cond.if modules_ANTISPAM="true"#			
		case OPTIONS_ANTISPAM:
			showAntispamOptions();
			break;
//#sijapp cond.end#
		}

		/* Activate options form */
		optionsForm.addCommand(JimmUI.cmdSave);
		optionsForm.addCommand(JimmUI.cmdBack);
		Jimm.display.setCurrent(optionsForm);
		Jimm.setBkltOn(true);
	}

	private void showNetworkOptions()
	{
		// Initialize elements (network section)
		srvHostTextField = new TextField(ResourceBundle
				.getString("server_host"), Options
				.getString(Options.OPTION_SRV_HOST), 512, TextField.ANY);
		srvPortTextField = new TextField(ResourceBundle
				.getString("server_port"), Options
				.getString(Options.OPTION_SRV_PORT), 5,
				TextField.NUMERIC);

//#sijapp cond.if modules_PROXY is "true"#
		connTypeChoiceGroup = new ChoiceGroup(ResourceBundle.getString("conn_type"), Choice.EXCLUSIVE);
		addStr(connTypeChoiceGroup, "socket|proxy");
		connTypeChoiceGroup.setSelectedIndex(Options.getInt(Options.OPTION_CONN_TYPE) == Options.CONN_TYPE_PROXY ? 1 : 0, true);
//#sijapp cond.end#

		keepConnAliveChoiceGroup = new ChoiceGroup(ResourceBundle
				.getString("keep_conn_alive"), Choice.MULTIPLE);
		setChecked(keepConnAliveChoiceGroup, "yes",
				Options.OPTION_KEEP_CONN_ALIVE);

		connAliveIntervTextField = new TextField(ResourceBundle
				.getString("timeout_interv"), Options
				.getString(Options.OPTION_CONN_ALIVE_INVTERV), 3,
				TextField.NUMERIC);

		connPropChoiceGroup = new ChoiceGroup(ResourceBundle
				.getString("conn_prop"), Choice.MULTIPLE);
		addStr(connPropChoiceGroup, "md5_login" + "|" + "async" + "|"
				+ "reconnect");
		//#sijapp cond.if target isnot "MOTOROLA"#
		addStr(connPropChoiceGroup, "shadow_con");
		//#sijapp cond.end#
		connPropChoiceGroup.setSelectedIndex(0, Options
				.getBoolean(Options.OPTION_MD5_LOGIN));
		connPropChoiceGroup.setSelectedIndex(1, Options
				.getInt(Options.OPTION_CONN_PROP) != 0);
		connPropChoiceGroup.setSelectedIndex(2, Options
				.getBoolean(Options.OPTION_RECONNECT));
		//#sijapp cond.if target isnot "MOTOROLA"#
		connPropChoiceGroup.setSelectedIndex(3, Options
				.getBoolean(Options.OPTION_SHADOW_CON));
		//#sijapp cond.end#

		autoConnectChoiceGroup = new ChoiceGroup(ResourceBundle
				.getString("auto_connect")
				+ "?", Choice.MULTIPLE);
		setChecked(autoConnectChoiceGroup, "yes",
				Options.OPTION_AUTO_CONNECT);

		reconnectNumberTextField = new TextField(ResourceBundle
				.getString("reconnect_number"), String.valueOf(Options
				.getInt(Options.OPTION_RECONNECT_NUMBER)), 2,
				TextField.NUMERIC);

		optionsForm.append(srvHostTextField);
		optionsForm.append(srvPortTextField);
//#sijapp cond.if modules_PROXY is "true"#
		optionsForm.append(connTypeChoiceGroup);
//#sijapp cond.end#
		optionsForm.append(keepConnAliveChoiceGroup);
		optionsForm.append(connAliveIntervTextField);
		optionsForm.append(autoConnectChoiceGroup);
		optionsForm.append(connPropChoiceGroup);
		optionsForm.append(reconnectNumberTextField);
		encryptionChoiceGroup = new ChoiceGroup(ResourceBundle.getString("secure_connection"), Choice.MULTIPLE);
		setChecked(encryptionChoiceGroup, "yes", Options.OPTION_ENCRYPTION);
		encryptionPskTextField = new TextField(ResourceBundle.getString("secure_psk"),
				Options.getString(Options.OPTION_ENCRYPTION_PSK), 64, TextField.ANY | TextField.PASSWORD);
		optionsForm.append(encryptionChoiceGroup);
		optionsForm.append(encryptionPskTextField);
		
	}

//#sijapp cond.if modules_PROXY is "true"#	
	private void showProxyOptions()
	{
		srvProxyType = createSelector("proxy_type", "proxy_socks4"
				+ "|" + "proxy_socks5" + "|" + "proxy_guess",
				Options.OPTION_PRX_TYPE);

		srvProxyHostTextField = new TextField(ResourceBundle
				.getString("proxy_server_host"), Options
				.getString(Options.OPTION_PRX_SERV), 32, TextField.URL);
		srvProxyPortTextField = new TextField(ResourceBundle
				.getString("proxy_server_port"), Options
				.getString(Options.OPTION_PRX_PORT), 5,
				TextField.NUMERIC);

		srvProxyLoginTextField = new TextField(ResourceBundle
				.getString("proxy_server_login"), Options
				.getString(Options.OPTION_PRX_NAME), 32, TextField.ANY);
		srvProxyPassTextField = new TextField(ResourceBundle
				.getString("proxy_server_pass"), Options
				.getString(Options.OPTION_PRX_PASS), 32,
				TextField.PASSWORD);

		connAutoRetryTextField = new TextField(ResourceBundle
				.getString("auto_retry_count"), Options
				.getString(Options.OPTION_AUTORETRY_COUNT), 5,
				TextField.NUMERIC);

		optionsForm.append(srvProxyType);
		optionsForm.append(srvProxyHostTextField);
		optionsForm.append(srvProxyPortTextField);
		optionsForm.append(srvProxyLoginTextField);
		optionsForm.append(srvProxyPassTextField);
		optionsForm.append(connAutoRetryTextField);
	}
//#sijapp cond.end#	

//#sijapp cond.if modules_CAMERA="true"#	
	private void showCameraOptions()
	{
		//	clCamDevGroup = new ChoiceGroup(ResourceBundle.getString("opt_camerauri"), Choice.EXCLUSIVE);
		//	addStr(clCamDevGroup, "camera://video" + "|" + "camera://image" + "|" + "camera://devcam0" +"|" + "camera://devcam1");
		//	optionsForm.append(clCamDevGroup);
		
		camEnc = new ChoiceGroup(ResourceBundle.getString("opt_camenc"), Choice.EXCLUSIVE);
		camRes = new ChoiceGroup(ResourceBundle.getString("opt_camres"), Choice.EXCLUSIVE);
		String[] imageTypes = Util.explode(System.getProperty("video.snapshot.encodings"), ' ');

//#sijapp cond.if modules_DEBUGLOG is "true"#
		System.out.println ("video.snapshot.encodings = " + System.getProperty("video.snapshot.encodings"));
//#sijapp cond.end #
		String[] params;
		String[] values;
		String width;
		String height;
		for (int i = 0; i < imageTypes.length; i++) {
			params = Util.explode(imageTypes[i], '&');
			width = null;
			height = null;
			for (int j = 0; j < params.length; j++) {
				values = Util.explode(params[j], '=');
				if (values[0].equals("encoding")) {
					boolean found = false;
					for (int k = 0; k < camEnc.size(); k++) {
						if (camEnc.getString(k).equals(values[1]))
							found = true;
					}
					if (!found)
						camEnc.append (values[1], null);
				} else if (values[0].equals("width")) {
					width = values[1];
				} else if (values[0].equals("height")) {
					height = values[1];
				}
				
			}
			if ((width != null) && (height != null)) {
				camRes.append (width + " x " + height, null);
			}
		}
//#sijapp cond.if modules_CAMERA="true"#
		// TeleMotoMax: разрешение для снимка в чат — из того же списка, что
		// знает CameraShot (размеры из свойства, а если телефон их не
		// называет, как V8 с одним «encoding=jpeg», — обычный набор), и
		// с пунктом «как решит телефон». Хранится строкой «WxH», а не
		// номером в списке, который у каждого телефона свой.
		camRes.deleteAll();
		cameraSizes = jimm.CameraShot.snapshotSizes();
		camRes.append(ResourceBundle.getString("camera_size_default"), null);
		for (int i = 0; i < cameraSizes.length; i++) camRes.append(cameraSizes[i], null);
		String chosen = Options.getString(Options.OPTION_CAMERA_SIZE);
		int sel = 0;
		for (int i = 0; i < cameraSizes.length; i++) if (cameraSizes[i].equals(chosen)) sel = i + 1;
		try { camRes.setSelectedIndex(sel, true); } catch (Exception e) {}
		try { if (camEnc.size() > 0) camEnc.setSelectedIndex(Options.getInt(Options.OPTION_CAMERA_ENCODING), true); } catch (Exception e) {}
//#sijapp cond.else#
		try {
			if (camRes.size() > 0) camRes.setSelectedIndex(Options.getInt(Options.OPTION_CAMERA_RES), true);
			if (camEnc.size() > 0) camEnc.setSelectedIndex(Options.getInt(Options.OPTION_CAMERA_ENCODING), true);
		} catch (Exception e) {}
//#sijapp cond.end#
		// clCamDevGroup.setSelectedIndex(Options.getInt(Options.OPTION_CAMERA_LOCATOR), true);
		
		optionsForm.append(camEnc);
		optionsForm.append(camRes);
	}
//#sijapp cond.end#


//#sijapp cond.if modules_ANTISPAM="true"#	
	private void showAntispamOptions()
	{
		chsUseAntispam = new ChoiceGroup(ResourceBundle.getString("antispam_use"), Choice.MULTIPLE);
		setChecked(chsUseAntispam, "yes", Options.OPTION_ANTI_SPAM);
		txtfAntispamQ = new TextField(
				ResourceBundle.getString("antispam_question"),
				Options.getString(Options.OPTION_ANTI_SPAM_QUESTION),
				64, TextField.ANY);
		
		txtfAntispamA = new TextField(
				ResourceBundle.getString("antispam_answer"),
				Options.getString(Options.OPTION_ANTI_SPAM_ANS),
				32, TextField.ANY);
		
		
		optionsForm.append(chsUseAntispam);
		optionsForm.append(txtfAntispamQ);
		optionsForm.append(txtfAntispamA);
	}
//#sijapp cond.end#	

//#sijapp cond.if target!="DEFAULT"#
	private void showBackgrImageOptions()
	{
		backImgGroup = createSelector("background_image", "none"
				+ "|" + "background_int"
				,Options.OPTION_BG_IMAGE);
		backImgModeGroup = createSelector("bg_image_mode", 
				"bg_center"+"|"+"bg_stretch"+"|"+"bg_pave", Options.OPTION_BG_IMAGE_MODE);
		optionsForm.append(backImgGroup);
	}
//#sijapp cond.end#

//#sijapp cond.if modules_TRAFFIC is "true"#
	private void showTrafficOptions()
	{
		/* Initialize elements (cost section) */
		costPerPacketTextField = new TextField(ResourceBundle
				.getString("cpp"), Util.intToDecimal(Options
				.getInt(Options.OPTION_COST_PER_PACKET)), 6,
				TextField.ANY);
		costPerDayTextField = new TextField(ResourceBundle
				.getString("cpd"), Util.intToDecimal(Options
				.getInt(Options.OPTION_COST_PER_DAY)), 6, TextField.ANY);
		costPacketLengthTextField = new TextField(ResourceBundle
				.getString("plength"), String.valueOf(Options
				.getInt(Options.OPTION_COST_PACKET_LENGTH) / 1024), 4,
				TextField.NUMERIC);
		currencyTextField = new TextField(ResourceBundle
				.getString("currency"), Options
				.getString(Options.OPTION_CURRENCY), 4, TextField.ANY);

		optionsForm.append(costPerPacketTextField);
		optionsForm.append(costPerDayTextField);
		optionsForm.append(costPacketLengthTextField);
		optionsForm.append(currencyTextField);
	}
//#sijapp cond.end#
	
	private void showTimezoneOptions()
	{
		int choiceType;
		//#sijapp cond.if target is "MIDP2" | target is "MOTOROLA" | target is "SIEMENS2"#
		choiceType = Choice.POPUP;
		//#sijapp cond.else#
		choiceType = Choice.EXCLUSIVE;
		//#sijapp cond.end#

		chsTimeZone = new ChoiceGroup(ResourceBundle
				.getString("time_zone"), choiceType);
		for (int i = -12; i <= 13; i++)
			chsTimeZone.append("GMT" + (i < 0 ? "" : "+") + i + ":00",
					null);
		chsTimeZone.setSelectedIndex(Options.getInt(Options.OPTION_GMT_OFFSET) + 12, true);

		int[] currDateTime = Util.createDate(Util.createCurrentDate(false));
		chsCurrTime = new ChoiceGroup(ResourceBundle.getString("local_time"), choiceType);
		int minutes = currDateTime[Util.TIME_MINUTE];
		int hour = currDateTime[Util.TIME_HOUR];
		for (int i = 0; i < 24; i++)
			chsCurrTime.append(i + ":" + minutes, null);
		chsCurrTime.setSelectedIndex(hour, true);
		
		int[] phoneTime = Util.createDate(new Date().getTime()/1000);
		currentHour = phoneTime[Util.TIME_HOUR];

		chsDayLight = new ChoiceGroup(ResourceBundle
				.getString("daylight_saving"), Choice.EXCLUSIVE);
		chsDayLight.append(ResourceBundle
				.getString("standard_time"), null);
		chsDayLight.append(ResourceBundle
				.getString("daylight_saving"), null);
		chsDayLight.setSelectedIndex(Options
				.getInt(Options.OPTION_DAYLIGHT_SAVING), true);
		optionsForm.append(chsTimeZone);
		optionsForm.append(chsCurrTime);
		optionsForm.append(chsDayLight);
	}

	private void showInterfaceOptions()
	{
		// Initialize elements (interface section)
		lockPinTextField = new TextField(ResourceBundle.getString("lock_pin"),
				Options.getString(Options.OPTION_LOCK_PIN), Options.LOCK_PIN_MAX,
				TextField.NUMERIC | TextField.PASSWORD);
		optionsForm.append(lockPinTextField);
		if (ResourceBundle.langAvailable.length > 1)
		{
			uiLanguageChoiceGroup = new ChoiceGroup(ResourceBundle
					.getString("language"), Choice.EXCLUSIVE);
			for (int j = 0; j < ResourceBundle.langAvailable.length; j++)
			{
				uiLanguageChoiceGroup.append(ResourceBundle
						.getString("lang_"
								+ ResourceBundle.langAvailable[j]),
						null);
				if (ResourceBundle.langAvailable[j].equals(Options
						.getString(Options.OPTION_UI_LANGUAGE)))
				{
					uiLanguageChoiceGroup.setSelectedIndex(j, true);
				}
			}
		}

		choiceInterfaceMisc = new ChoiceGroup(ResourceBundle.getString("misc"), Choice.MULTIPLE);
		setChecked(choiceInterfaceMisc, "display_date", Options.OPTION_DISPLAY_DATE);
//#sijapp cond.if target is "MIDP2" | target is "MOTOROLA" | target is "SIEMENS2"#
		setChecked(choiceInterfaceMisc, "full_screen", Options.OPTION_FULL_SCREEN);
//#sijapp cond.end#
		setChecked(choiceInterfaceMisc, "mirror_menu", Options.OPTION_MIRROR_MENU);
		setChecked(choiceInterfaceMisc, "small_font", Options.OPTION_SMALL_FONT);

		clSortByChoiceGroup = createSelector("sort_by",
				"sort_by_status" + "|" + "sort_by_name",
				Options.OPTION_CL_SORT_BY);

		choiceContactList = new ChoiceGroup(ResourceBundle.getString("contact_list"), Choice.MULTIPLE);
		setChecked(choiceContactList, "show_user_groups", Options.OPTION_USE_GROUPS);
		setChecked(choiceContactList, "hide_empty", Options.OPTION_CL_HIDE_EMPTY);
		setChecked(choiceContactList, "hide_offline", Options.OPTION_CL_HIDE_OFFLINE);
		setChecked(choiceContactList, "show_deleted_contacts", Options.OPTION_SHOW_DELETED_CONT);

		chrgChat = new ChoiceGroup(ResourceBundle.getString("chat"),
				Choice.MULTIPLE);
		
		//#sijapp cond.if modules_HISTORY is "true"#
		setChecked(chrgChat, "use_history", Options.OPTION_HISTORY);
		setChecked(chrgChat, "show_prev_mess", Options.OPTION_SHOW_LAST_MESS);
		//#sijapp cond.end#
		setChecked(chrgChat, "cp1251", Options.OPTION_CP1251_HACK);
		setChecked(chrgChat, "initcaps", Options.OPTION_INIT_CAPS);
		setChecked(chrgChat, "deliv_info", Options.OPTION_DELIV_MES_INFO);
		
//#sijapp cond.if target="MIDP2" | target="SIEMENS2"#	
		String[] imgScaleText = Util.explode(ResourceBundle.getString("no") + "|120%|140%|160%|180%|200%" , '|');
		imagesScale = new ChoiceGroup(ResourceBundle.getString("images_scale"), Choice.POPUP, imgScaleText, null);
		int imgScale = Options.getInt(Options.OPTION_IMG_SCALE);
		imgScale = (imgScale > 200) ? 200 : ((imgScale < 100) ? 100 : imgScale);
		imagesScale.setSelectedIndex((imgScale-100)/20, true);
//#sijapp cond.end#	
		

		//#sijapp cond.if target="MOTOROLA" | target="MIDP2" #
		lightManual = new ChoiceGroup(ResourceBundle.getString("backlight_manual"), Choice.MULTIPLE);
		lightTimeout = new TextField(ResourceBundle.getString("backlight_timeout"), String.valueOf(Options.getInt(Options.OPTION_LIGHT_TIMEOUT)), 2, TextField.NUMERIC);
		setChecked(lightManual, "yes", Options.OPTION_LIGHT_MANUAL);
		//#sijapp cond.end#
		
		// OPTION_SHOW_MESS_ICON
		chrgMessFormat = new ChoiceGroup(ResourceBundle.getString("mess_format"), Choice.MULTIPLE);
		setChecked(chrgMessFormat, "small_font", Options.OPTION_CHAT_SMALL_FONT);
		setChecked(chrgMessFormat, "show_mess_icon", Options.OPTION_SHOW_MESS_ICON);
		setChecked(chrgMessFormat, "show_mess_nick", Options.OPTION_SHOW_NICK);
		setChecked(chrgMessFormat, "show_mess_date", Options.OPTION_SHOW_MESS_DATE);
		setChecked(chrgMessFormat, "show_mess_clrf", Options.OPTION_SHOW_MESS_CLRF);
		//#sijapp cond.if modules_SMILES_STD="true" | modules_SMILES_ANI="true" #
		setChecked(chrgMessFormat, "use_smiles", Options.OPTION_USE_SMILES);
		//#sijapp cond.end#
		setChecked(chrgMessFormat, "mess_colored_text", Options.OPTION_MESS_COLORED_TEXT);
		setChecked(chrgMessFormat, "full_textbox", Options.OPTION_FULL_TEXTBOX);


		if (uiLanguageChoiceGroup != null)
			optionsForm.append(uiLanguageChoiceGroup);
		optionsForm.append(choiceInterfaceMisc);
		optionsForm.append(choiceContactList);
		optionsForm.append(clSortByChoiceGroup);

		if (chrgChat.size() != 0) optionsForm.append(chrgChat);
		historyCount = new TextField(ResourceBundle.getString("history_count"),
				String.valueOf(Options.getInt(Options.OPTION_HISTORY_COUNT)), 3, TextField.NUMERIC);
		optionsForm.append(historyCount);
		chatMessages = new TextField(ResourceBundle.getString("chat_messages"),
				String.valueOf(Options.getInt(Options.OPTION_CHAT_MESSAGES)), 3, TextField.NUMERIC);
		optionsForm.append(chatMessages);

		optionsForm.append(chrgMessFormat);
		
		//#sijapp cond.if target="MIDP2" | target="SIEMENS2"#
		optionsForm.append(imagesScale);
		//#sijapp cond.end #

		//#sijapp cond.if target="MOTOROLA" | target="MIDP2" #
		optionsForm.append(lightTimeout);
		optionsForm.append(lightManual);
		//#sijapp cond.end #
		
		txtCapOffset = new TextField(ResourceBundle.getString("caption_offset"), String.valueOf(Options.getInt(Options.OPTION_CAPTION_OFFSET)), 2, TextField.NUMERIC); 
		optionsForm.append(txtCapOffset);
	}

	private void showSignalingOptions()
	{
		/* Initialize elements (Signaling section) */

		//#sijapp cond.if target isnot "DEFAULT"#
		unlockedNotificationSoundChoice = createSoundSelector("message_notification",
				Options.OPTION_MESS_UNLOCKED_FILE, (int) Options.getLong(Options.OPTION_MESS_UNLOCKED_MODE), 2);
		unlockedNotificationSoundVolume = new Gauge(ResourceBundle.getString("volume"),
				true, 10, (int) Options.getLong(Options.OPTION_MESS_UNLOCKED_VOL) / 10);
		messageNotificationSoundChoice = createSoundSelector("message_notification_locked",
				Options.OPTION_MESS_NOTIF_FILE, Options.getInt(Options.OPTION_MESS_NOTIF_MODE), 2);
		messageNotificationSoundVolume = new Gauge(ResourceBundle
				.getString("volume"), true, 10, Options
				.getInt(Options.OPTION_MESS_NOTIF_VOL) / 10);
		typingNotificationSoundVolume = new Gauge(ResourceBundle
				.getString("volume"), true, 10, Options
				.getInt(Options.OPTION_TYPING_VOL) / 10);
		typingNotificationSoundChoice = createSoundSelector("typing_notify",
				Options.OPTION_TYPING_FILE, Options.getInt(Options.OPTION_TYPING_MODE), 3);

		vibratorChoiceGroup = new ChoiceGroup(ResourceBundle.getString("vibration"), Choice.POPUP);
		addStr(vibratorChoiceGroup, "no" + "|" + "yes" + "|" + "when_locked" + "|" + "when_idle");
		int vibrationMode = Options.getInt(Options.OPTION_VIBRATOR);
		if (vibrationMode >= 0 && vibrationMode < vibratorChoiceGroup.size())
			vibratorChoiceGroup.setSelectedIndex(vibrationMode, true);
		unlockedVibrationDuration = createVibrationDuration("vibra_unlocked", Options.OPTION_VIBRA_UNLOCKED_MS);
		lockedVibrationDuration = createVibrationDuration("vibra_locked", Options.OPTION_VIBRA_LOCKED_MS);

		//#sijapp cond.end#

		//#sijapp cond.if target isnot "DEFAULT"#     
		optionsForm.append(unlockedNotificationSoundChoice);
		optionsForm.append(unlockedNotificationSoundVolume);
		optionsForm.append(messageNotificationSoundChoice);
		optionsForm.append(messageNotificationSoundVolume);
		optionsForm.append(vibratorChoiceGroup);
		optionsForm.append(unlockedVibrationDuration);
		optionsForm.append(lockedVibrationDuration);
		optionsForm.append(typingNotificationSoundChoice);
		optionsForm.append(typingNotificationSoundVolume);
		//#sijapp cond.end#
		
		//#sijapp cond.if target is "MIDP2" | target is "MOTOROLA" | target is "SIEMENS2"#
		chsBringUp = new ChoiceGroup(ResourceBundle.getString("misc"),
				Choice.MULTIPLE);
		//#sijapp cond.if target is "MIDP2"#
		if (Jimm.getPhoneVendor() == Device.PHONE_SONYERICSSON)
			setChecked(chsBringUp, "bring_up", Options.OPTION_BRING_UP);
		//#sijapp cond.end#
		
		setChecked(chsBringUp, "creeping_line",
				Options.OPTION_CREEPING_LINE);
		optionsForm.append(chsBringUp);
		//#sijapp cond.end#
	}

	private static ChoiceGroup createSoundSelector(String caption, int fileOption, int mode, int soundMode)
	{
		ChoiceGroup choice = new ChoiceGroup(ResourceBundle.getString(caption), Choice.POPUP);
		if (soundMode == 3) addStr(choice, "no" + "|" + "typing_display_only" + "|" + "beep");
		else addStr(choice, "no" + "|" + "beep");
		choice.append("message.mp3", null);
		choice.append("msg_low.mp3", null);
		choice.append("tg.mp3", null);
		choice.append("typing.mp3", null);
		String saved = Options.getString(fileOption);
		int selected = -1;
		for (int i = soundMode; i < choice.size(); i++)
			if (choice.getString(i).equals(saved)) selected = i;
		// Preserve a saved legacy/custom file until another melody is chosen.
		if (selected < 0 && saved != null && saved.length() != 0)
			selected = choice.append(saved, null);
		if (mode < soundMode) selected = mode;
		choice.setSelectedIndex(selected < 0 ? 0 : selected, true);
		return choice;
	}

	private static void readSoundSelector(ChoiceGroup choice, int fileOption, int modeOption, int soundMode)
	{
		int selected = choice.getSelectedIndex();
		int mode = selected < soundMode ? selected : soundMode;
		if (modeOption < 192) Options.setInt(modeOption, mode);
		else Options.setLong(modeOption, mode);
		if (mode == soundMode) Options.setString(fileOption, choice.getString(selected));
	}

	private static ChoiceGroup createVibrationDuration(String caption, int option)
	{
		ChoiceGroup choice = new ChoiceGroup(ResourceBundle.getString(caption), Choice.POPUP);
		choice.append("0.2", null);
		choice.append("0.5", null);
		choice.append("1", null);
		choice.append("1.5", null);
		choice.append("2", null);
		long saved = Options.getLong(option);
		int selected = 1;
		for (int i = 0; i < Options.VIBRATION_DURATIONS.length; i++)
			if (saved == Options.VIBRATION_DURATIONS[i]) selected = i;
		choice.setSelectedIndex(selected, true);
		return choice;
	}
	
	private boolean readDataFromForm()
	{
		// Save values, depending on selected option menu item
		switch (currOptMode)
		{
		case OPTIONS_ACCOUNT:
			readAccontsControls();
			setAccountOptions();
			break;
		case OPTIONS_NETWORK:
			readNetworkOptions();
			break;
			
//#sijapp cond.if modules_PROXY is "true"#
		case OPTIONS_PROXY:
			readProxyOptions();
			break;
//#sijapp cond.end#
			
		case OPTIONS_INTERFACE:
			readInterfaceOptions();
			break;

		case OPTIONS_MEDIA:
			readMediaOptions();
			break;

		case OPTIONS_NET_TELEGRAM:
		case OPTIONS_NET_MAX:
		case OPTIONS_NET_EXPRESS:
			readNetworkForm(currOptMode);
			// Мост должен узнать сразу, не дожидаясь перевхода.
			jimm.comm.Icq.resendClientInfo();
			break;

//#sijapp cond.if target!="DEFAULT"#
		case OPTIONS_BG_IMAGE:
			readBackgrImageOptions();
			break;
			
//#sijapp cond.end#			
			

//#sijapp cond.if modules_CAMERA="true"#
		case OPTIONS_CAMERA:
			readCameraOptions();
			break;
//#sijapp cond.end#

//#sijapp cond.if target!="DEFAULT"#			
		case OPTIONS_SIGNALING:
			readSignalingOptions();
			break;
//#sijapp cond.end#			
			

//#sijapp cond.if modules_TRAFFIC is "true"#
		case OPTIONS_TRAFFIC:
			readTrafficOptions();
			break;
//#sijapp cond.end#

		case OPTIONS_TIMEZONE:
			readTimezoneOptions();
			break;
			
		case OPTIONS_ADD_USER:
			Search search = new Search();
			String data[] = new String[Search.LAST_INDEX];
			data[Search.UIN] = txtUIN.getString();
			return Icq.runActionAndProcessError(new SearchAction(search, data, SearchAction.CALLED_BY_ADDUSER));
			
		case OPTIONS_ADD_GROUP:
			ContactListGroupItem newGroup = new ContactListGroupItem(txtUIN.getString());
			return Icq.runActionAndProcessError(new UpdateContactListAction(newGroup, UpdateContactListAction.ACTION_ADD));
			
		case OPTIONS_RENAME_GROUP:
			ContactListGroupItem group = ContactList.getGroupById(groupSelector.getCurrTextIndex());
			if (group != null)
			{
				group.setName(txtUIN.getString());
				ContactList.safeSave();
				return Icq.runActionAndProcessError(new UpdateContactListAction(group, UpdateContactListAction.ACTION_RENAME));
			}
			return false;
			
//#sijapp cond.if modules_ANTISPAM="true"#
		case OPTIONS_ANTISPAM:
			readAntispamOptions();
			break;
//#sijapp cond.end#
		}
		
		return false;
	}
	
//#sijapp cond.if modules_ANTISPAM="true"#
	private void readAntispamOptions()
	{
		Options.setBoolean(Options.OPTION_ANTI_SPAM, chsUseAntispam.isSelected(0));
		Options.setString(Options.OPTION_ANTI_SPAM_QUESTION, txtfAntispamQ.getString());
		Options.setString(Options.OPTION_ANTI_SPAM_ANS, txtfAntispamA.getString());
	}
//#sijapp cond.end#	

	private void readTimezoneOptions()
	{
		/* Set up time zone*/
		int timeZone = chsTimeZone.getSelectedIndex() - 12;
		Options.setInt(Options.OPTION_GMT_OFFSET, timeZone);

		int dayLight = chsDayLight.getSelectedIndex();
		Options.setInt(Options.OPTION_DAYLIGHT_SAVING, dayLight);
		/* Translate selected time to GMT */
		int gmtHour = chsCurrTime.getSelectedIndex() - timeZone;
		gmtHour -= dayLight; 
		if (gmtHour < 0) gmtHour += 24;
		if (gmtHour >= 24) gmtHour -= 24;

		/* Calculate diff. between selected GMT time and phone time */
		int localOffset = gmtHour - currentHour;
		
		while (localOffset >= 12) localOffset -= 24;
		while (localOffset < -12) localOffset += 24;
		Options.setInt(Options.OPTION_LOCAL_OFFSET, localOffset);
	}

//#sijapp cond.if modules_TRAFFIC is "true"#	
	private void readTrafficOptions()
	{
		int costPerPacket = Util.decimalToInt(costPerPacketTextField.getString()); 
		Options.setInt(Options.OPTION_COST_PER_PACKET, costPerPacket);
		costPerPacketTextField.setString(Util.intToDecimal(costPerPacket));
		Options.setInt(Options.OPTION_COST_PER_DAY, Util.decimalToInt(costPerDayTextField.getString()));
		costPerDayTextField.setString(Util.intToDecimal(Options.getInt(Options.OPTION_COST_PER_DAY)));
		Options.setInt(Options.OPTION_COST_PACKET_LENGTH, Integer.parseInt(costPacketLengthTextField.getString()) * 1024);
		Options.setString(Options.OPTION_CURRENCY, currencyTextField.getString());
	}
//#sijapp cond.end#	



//#sijapp cond.if target!="DEFAULT"#

	private void readSignalingOptions()
	{
		//#sijapp cond.if target isnot "DEFAULT"# ===>
		readSoundSelector(messageNotificationSoundChoice, Options.OPTION_MESS_NOTIF_FILE,
				Options.OPTION_MESS_NOTIF_MODE, 2);
		Options.setInt(Options.OPTION_VIBRATOR, vibratorChoiceGroup
				.getSelectedIndex());
		Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,
				Options.VIBRATION_DURATIONS[unlockedVibrationDuration.getSelectedIndex()]);
		Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,
				Options.VIBRATION_DURATIONS[lockedVibrationDuration.getSelectedIndex()]);
		readSoundSelector(unlockedNotificationSoundChoice, Options.OPTION_MESS_UNLOCKED_FILE,
				Options.OPTION_MESS_UNLOCKED_MODE, 2);
		readSoundSelector(typingNotificationSoundChoice, Options.OPTION_TYPING_FILE,
				Options.OPTION_TYPING_MODE, 3);
   
		Options.setInt(Options.OPTION_MESS_NOTIF_VOL,
				messageNotificationSoundVolume.getValue() * 10);
		Options.setLong(Options.OPTION_MESS_UNLOCKED_VOL,
				unlockedNotificationSoundVolume.getValue() * 10);
		Options.setInt(Options.OPTION_TYPING_VOL,
				typingNotificationSoundVolume.getValue() * 10);
		//#sijapp cond.end# <===

		//#sijapp cond.if target is "MIDP2" | target is "MOTOROLA" | target is "SIEMENS2"#
		int idx = 0;
		//#sijapp cond.if target is "MIDP2"#
		if (Jimm.getPhoneVendor() == Device.PHONE_SONYERICSSON) 
			Options.setBoolean(Options.OPTION_BRING_UP, chsBringUp.isSelected(idx++));
		//#sijapp cond.end#
		Options.setBoolean(Options.OPTION_CREEPING_LINE, chsBringUp.isSelected(idx++));
		//#sijapp cond.end#
	}

	// «Медиа»: что мост отдаёт телефону — размер и качество снимка, кадр,
	// битрейт и длина ролика, «боком», битрейт и длина голосового. Всё
	// выпадающими списками, первый пункт — «как в профиле моста» (0 /
	// пусто — не шлётся). Значения уходят мосту в 01/F2 сразу при
	// сохранении и при каждом входе.
	private ChoiceGroup newMediaChoice(String label)
	{
		int choiceType;
		//#sijapp cond.if target is "MIDP2" | target is "MOTOROLA" | target is "SIEMENS2"#
		choiceType = Choice.POPUP;
		//#sijapp cond.else#
		choiceType = Choice.EXCLUSIVE;
		//#sijapp cond.end#
		return new ChoiceGroup(ResourceBundle.getString(label), choiceType);
	}

	private ChoiceGroup mediaChoice(String label, String[] values, String current)
	{
		ChoiceGroup g = newMediaChoice(label);
		g.append(ResourceBundle.getString("media_profile"), null);
		int sel = 0;
		for (int i = 0; i < values.length; i++)
		{
			g.append(values[i], null);
			if (values[i].equals(current)) sel = i + 1;
		}
		try { g.setSelectedIndex(sel, true); } catch (Exception ignore) {}
		return g;
	}

	private ChoiceGroup mediaChoice(String label, int[] values, int current, boolean tenths)
	{
		String[] names = new String[values.length];
		for (int i = 0; i < values.length; i++)
			names[i] = tenths ? (values[i] / 10) + "." + (values[i] % 10) : String.valueOf(values[i]);
		return mediaChoice(label, names, tenths ? (current / 10) + "." + (current % 10) : String.valueOf(current));
	}

	private static int mediaValue(ChoiceGroup g, int[] values)
	{
		int sel = g.getSelectedIndex();
		return (sel > 0 && sel - 1 < values.length) ? values[sel - 1] : 0;
	}

	private static String mediaValue(ChoiceGroup g, String[] values)
	{
		int sel = g.getSelectedIndex();
		return (sel > 0 && sel - 1 < values.length) ? values[sel - 1] : "";
	}

	private void showMediaOptions()
	{
		mediaPhotoSize = mediaChoice("media_photo_size", MEDIA_PHOTO_SIZES, Options.getString(Options.OPTION_MEDIA_PHOTO_SIZE));
		mediaPhotoQuality = mediaChoice("media_photo_quality", MEDIA_QUALITIES, Options.getInt(Options.OPTION_MEDIA_PHOTO_QUALITY), false);
		mediaPhotoKb = mediaChoice("media_photo_kb", MEDIA_PHOTO_KBS, Options.getInt(Options.OPTION_MEDIA_PHOTO_KB), false);
		mediaVideoSize = mediaChoice("media_video_size", MEDIA_VIDEO_SIZES, Options.getString(Options.OPTION_MEDIA_VIDEO_SIZE));
		mediaVideoKbps = mediaChoice("media_video_kbps", MEDIA_VIDEO_KBPS, Options.mediaVideoKbps(), false);
		mediaVideoSeconds = mediaChoice("media_video_seconds", MEDIA_VIDEO_SECS, Options.getInt(Options.OPTION_MEDIA_VIDEO_SECONDS), false);
		videoRotateChoice = newMediaChoice("video_rotate");
		videoRotateChoice.append(ResourceBundle.getString("video_rotate_auto"), null);
		videoRotateChoice.append(ResourceBundle.getString("video_rotate_always"), null);
		videoRotateChoice.append(ResourceBundle.getString("video_rotate_never"), null);
		try { videoRotateChoice.setSelectedIndex(Options.getInt(Options.OPTION_VIDEO_ROTATE), true); }
		catch (Exception ignore) {}
		photoRotateChoice = newMediaChoice("photo_rotate");
		photoRotateChoice.append(ResourceBundle.getString("video_rotate_auto"), null);
		photoRotateChoice.append(ResourceBundle.getString("video_rotate_always"), null);
		photoRotateChoice.append(ResourceBundle.getString("video_rotate_never"), null);
		try { photoRotateChoice.setSelectedIndex(Options.getInt(Options.OPTION_PHOTO_ROTATE), true); }
		catch (Exception ignore) {}
		mediaVideoKb = mediaChoice("media_video_kb", MEDIA_VIDEO_KBS, Options.getInt(Options.OPTION_MEDIA_VIDEO_KB), false);
		mediaVoiceKbps = mediaChoice("media_voice_kbps", MEDIA_VOICE_KBPS10, Options.getInt(Options.OPTION_MEDIA_VOICE_KBPS10), true);
		mediaVoiceSeconds = mediaChoice("media_voice_seconds", MEDIA_VOICE_SECS, Options.getInt(Options.OPTION_MEDIA_VOICE_SECONDS), false);
		optionsForm.append(mediaPhotoSize);
		optionsForm.append(mediaPhotoQuality);
		optionsForm.append(mediaPhotoKb);
		optionsForm.append(photoRotateChoice);
		optionsForm.append(mediaVideoSize);
		optionsForm.append(mediaVideoKbps);
		optionsForm.append(mediaVideoSeconds);
		optionsForm.append(mediaVideoKb);
		optionsForm.append(videoRotateChoice);
		optionsForm.append(mediaVoiceKbps);
		optionsForm.append(mediaVoiceSeconds);
		// Клиентская настройка, мосту не уходит: сколько ролика класть в
		// память, если плеер не смог взять его файлом. Куча динамическая —
		// свободное место меряется в текущей куче и скачет, поэтому число
		// лучше задать самому; 0 — считать по куче.
		mediaMemKb = new TextField(ResourceBundle.getString("media_mem_kb"),
				String.valueOf(Options.getInt(Options.OPTION_MEDIA_MEM_KB)), 5, TextField.NUMERIC);
		optionsForm.append(mediaMemKb);
	}

	private void readMediaOptions()
	{
		Options.setString(Options.OPTION_MEDIA_PHOTO_SIZE, mediaValue(mediaPhotoSize, MEDIA_PHOTO_SIZES));
		Options.setInt(Options.OPTION_MEDIA_PHOTO_QUALITY, mediaValue(mediaPhotoQuality, MEDIA_QUALITIES));
		Options.setInt(Options.OPTION_MEDIA_PHOTO_KB, mediaValue(mediaPhotoKb, MEDIA_PHOTO_KBS));
		Options.setString(Options.OPTION_MEDIA_VIDEO_SIZE, mediaValue(mediaVideoSize, MEDIA_VIDEO_SIZES));
		Options.setInt(Options.OPTION_MEDIA_VIDEO_KBPS, mediaValue(mediaVideoKbps, MEDIA_VIDEO_KBPS));
		Options.setInt(Options.OPTION_MEDIA_VIDEO_SECONDS, mediaValue(mediaVideoSeconds, MEDIA_VIDEO_SECS));
		Options.setInt(Options.OPTION_MEDIA_VIDEO_KB, mediaValue(mediaVideoKb, MEDIA_VIDEO_KBS));
		Options.setInt(Options.OPTION_VIDEO_ROTATE, videoRotateChoice.getSelectedIndex());
		Options.setInt(Options.OPTION_PHOTO_ROTATE, photoRotateChoice.getSelectedIndex());
		Options.setInt(Options.OPTION_MEDIA_VOICE_KBPS10, mediaValue(mediaVoiceKbps, MEDIA_VOICE_KBPS10));
		Options.setInt(Options.OPTION_MEDIA_VOICE_SECONDS, mediaValue(mediaVoiceSeconds, MEDIA_VOICE_SECS));
		try
		{
			int kb = Integer.parseInt(mediaMemKb.getString().trim());
			Options.setInt(Options.OPTION_MEDIA_MEM_KB, Math.max(0, Math.min(8192, kb)));
		}
		catch (Exception ignore) {}
		jimm.comm.Icq.resendClientInfo();
	}

//#sijapp cond.if modules_CAMERA="true"#
	private void readCameraOptions()
	{
		//Options.setInt(Options.OPTION_CAMERA_LOCATOR, clCamDevGroup.getSelectedIndex());
		Options.setInt(Options.OPTION_CAMERA_ENCODING, camEnc.getSelectedIndex());
//#sijapp cond.if modules_CAMERA="true"#
		int sel = camRes.getSelectedIndex();
		Options.setString(Options.OPTION_CAMERA_SIZE,
				(sel > 0 && cameraSizes != null && sel - 1 < cameraSizes.length) ? cameraSizes[sel - 1] : "");
		Options.setInt(Options.OPTION_CAMERA_RES, 0);
//#sijapp cond.else#
		Options.setInt(Options.OPTION_CAMERA_RES, camRes.getSelectedIndex());
//#sijapp cond.end#
	}
//#sijapp cond.end#

	private void readBackgrImageOptions()
	{
		int oldBgImage = Options.getInt(Options.OPTION_BG_IMAGE);
		int oldBgImageMode = Options.getInt(Options.OPTION_BG_IMAGE_MODE);
		int newBgImage = backImgGroup.getSelectedIndex();
		int newBgImageMode = backImgModeGroup.getSelectedIndex();
		Options.setInt(Options.OPTION_BG_IMAGE, newBgImage);
		Options.setInt(Options.OPTION_BG_IMAGE_MODE, newBgImageMode);
		boolean changed = (oldBgImage!=newBgImage) || (oldBgImageMode!=newBgImageMode);  
		Options.setString (Options.OPTION_BG_IMAGE_URL, Options.emptyString);
		if (changed) Options.setBackgroundImage(backImgGroup.getSelectedIndex(), null, newBgImageMode);
	}
//#sijapp cond.end#	

	private void readInterfaceOptions()
	{
		Options.setString(Options.OPTION_LOCK_PIN, lockPinTextField.getString());
		if (ResourceBundle.langAvailable.length > 1)
			Options.setString(Options.OPTION_UI_LANGUAGE,
					ResourceBundle.langAvailable[uiLanguageChoiceGroup.getSelectedIndex()]);

		int idx = 0;
		
		Options.setBoolean(Options.OPTION_DISPLAY_DATE, choiceInterfaceMisc.isSelected(idx++));
//#sijapp cond.if target is "MIDP2" | target is "MOTOROLA" | target is "SIEMENS2"#
		Options.setBoolean(Options.OPTION_FULL_SCREEN, choiceInterfaceMisc.isSelected(idx++));
//#sijapp cond.end#
		Options.setBoolean(Options.OPTION_MIRROR_MENU, choiceInterfaceMisc.isSelected(idx++));
		boolean newSmallFont = choiceInterfaceMisc.isSelected(idx++);
		Options.setBoolean(Options.OPTION_SMALL_FONT, newSmallFont);
		
		idx = 0;
		boolean newUseGroups = choiceContactList.isSelected(idx++);
		boolean newHideEmpty = choiceContactList.isSelected(idx++);
		boolean newHideOffline = choiceContactList.isSelected(idx++);
		boolean newShowDeletedCont = choiceContactList.isSelected(idx++);

		int newSortMethod = clSortByChoiceGroup.getSelectedIndex();
		Options.setInt(Options.OPTION_CL_SORT_BY, newSortMethod);
		Options.setBoolean(Options.OPTION_CL_HIDE_OFFLINE, newHideOffline);
		Options.setBoolean(Options.OPTION_CL_HIDE_EMPTY, newHideEmpty);
		Options.setBoolean(Options.OPTION_SHOW_DELETED_CONT, newShowDeletedCont); 

		idx = 0;
		//#sijapp cond.if modules_HISTORY is "true"#
		Options.setBoolean(Options.OPTION_HISTORY, chrgChat
				.isSelected(idx++));
		Options.setBoolean(Options.OPTION_SHOW_LAST_MESS, chrgChat
				.isSelected(idx++));
		//#sijapp cond.end#

		Options.setBoolean(Options.OPTION_CP1251_HACK, chrgChat.isSelected(idx++));
		Options.setBoolean(Options.OPTION_INIT_CAPS, chrgChat.isSelected(idx++));
		Options.setBoolean(Options.OPTION_DELIV_MES_INFO, chrgChat.isSelected(idx++));
		
		idx = 0;
		Options.setBoolean(Options.OPTION_CHAT_SMALL_FONT, chrgMessFormat.isSelected(idx++));
		Options.setBoolean(Options.OPTION_SHOW_MESS_ICON, chrgMessFormat.isSelected(idx++));
		Options.setBoolean(Options.OPTION_SHOW_NICK, chrgMessFormat.isSelected(idx++));
		Options.setBoolean(Options.OPTION_SHOW_MESS_DATE, chrgMessFormat.isSelected(idx++));
		Options.setBoolean(Options.OPTION_SHOW_MESS_CLRF, chrgMessFormat.isSelected(idx++));
//#sijapp cond.if modules_SMILES_STD="true" | modules_SMILES_ANI="true" #
		Options.setBoolean(Options.OPTION_USE_SMILES, chrgMessFormat.isSelected(idx++));
//#sijapp cond.end#
		Options.setBoolean(Options.OPTION_MESS_COLORED_TEXT, chrgMessFormat.isSelected(idx++));
		Options.setBoolean(Options.OPTION_FULL_TEXTBOX, chrgMessFormat.isSelected(idx++));

		Options.setBoolean(Options.OPTION_USE_GROUPS, newUseGroups);

		// Set UI options for existing controls
		ContactList.optionsChanged
		(
			(newUseGroups != lastGroupsUsed) || (newHideOffline != lastHideOffline) || (newHideEmpty != lastHideEmpty),
			(newSortMethod != lastSortMethod)
		);

		try
		{
			int n = Integer.parseInt(historyCount.getString());
			if (n < 1) n = 1;
			if (n > 100) n = 100;
			Options.setInt(Options.OPTION_HISTORY_COUNT, n);
		}
		catch (Exception ignore) {}
		try
		{
			int n = Integer.parseInt(chatMessages.getString());
			if (n < 1) n = 1;
			if (n > 100) n = 100;
			Options.setInt(Options.OPTION_CHAT_MESSAGES, n);
		}
		catch (Exception ignore) {}

		//#sijapp cond.if target="MOTOROLA" | target="MIDP2" #
		boolean useBackLight = lightManual.isSelected(0);
		Options.setInt(Options.OPTION_LIGHT_TIMEOUT, Integer.parseInt(lightTimeout.getString()));
		Options.setBoolean(Options.OPTION_LIGHT_MANUAL, useBackLight);
		Jimm.device.setBackLightOnTime(useBackLight, Options.getInt(Options.OPTION_LIGHT_TIMEOUT));
		
		//#sijapp cond.if target="MOTOROLA"#
		if (!useBackLight) Jimm.display.flashBacklight(1);
		//#sijapp cond.end#
		//#sijapp cond.end#
		
		int capOffset = Integer.parseInt(txtCapOffset.getString());
		if (capOffset < 0) capOffset = 0;
		if (capOffset > 50) capOffset = 50;
		Options.setInt(Options.OPTION_CAPTION_OFFSET, capOffset);

		//#sijapp cond.if target="MIDP2" | target="SIEMENS2"#
		int imgScale = (imagesScale.getSelectedIndex()*20)+100; 
		Options.setInt(Options.OPTION_IMG_SCALE, imgScale);
		//#sijapp cond.end#
		
		
		VirtualList.setFullScreenForCurrent(Options.getBoolean(Options.OPTION_FULL_SCREEN));
		VirtualList.setMirrorMenu(Options.getBoolean(Options.OPTION_MIRROR_MENU));
		VirtualList.setCapOffset(capOffset);

		if (!lastUILang.equals(Options.getString(Options.OPTION_UI_LANGUAGE)))
			Options.setBoolean(Options.OPTION_LANG_CHANGED, true);
	}

//#sijapp cond.if modules_PROXY is "true"#	
	private void readProxyOptions()
	{
		Options.setInt(Options.OPTION_PRX_TYPE, srvProxyType
				.getSelectedIndex());
		Options.setString(Options.OPTION_PRX_SERV,
				srvProxyHostTextField.getString());
		Options.setString(Options.OPTION_PRX_PORT,
				srvProxyPortTextField.getString());

		Options.setString(Options.OPTION_PRX_NAME,
				srvProxyLoginTextField.getString());
		Options.setString(Options.OPTION_PRX_PASS,
				srvProxyPassTextField.getString());

		Options.setString(Options.OPTION_AUTORETRY_COUNT,
				connAutoRetryTextField.getString());
	}
//#sijapp cond.end#	

	private void readNetworkOptions()
	{
		Options.setString(Options.OPTION_SRV_HOST, srvHostTextField.getString());
		Options.setString(Options.OPTION_SRV_PORT, srvPortTextField.getString());
//#sijapp cond.if modules_PROXY is "true"#
		Options.setInt(Options.OPTION_CONN_TYPE, connTypeChoiceGroup.getSelectedIndex() == 1 ? Options.CONN_TYPE_PROXY : Options.CONN_TYPE_SOCKET);
//#sijapp cond.end#
		Options.setBoolean(Options.OPTION_KEEP_CONN_ALIVE,
				keepConnAliveChoiceGroup.isSelected(0));
		Options.setString(Options.OPTION_CONN_ALIVE_INVTERV,
				connAliveIntervTextField.getString());
		Options.setBoolean(Options.OPTION_AUTO_CONNECT,
				autoConnectChoiceGroup.isSelected(0));
		Options.setBoolean(Options.OPTION_MD5_LOGIN,
				connPropChoiceGroup.isSelected(0));
		if (connPropChoiceGroup.isSelected(1))
			Options.setInt(Options.OPTION_CONN_PROP, 1);
		else
			Options.setInt(Options.OPTION_CONN_PROP, 0);
		Options.setBoolean(Options.OPTION_RECONNECT,
				connPropChoiceGroup.isSelected(2));
		//#sijapp cond.if target isnot "MOTOROLA"#
		Options.setBoolean(Options.OPTION_SHADOW_CON,
				connPropChoiceGroup.isSelected(3));
		//#sijapp cond.end#
		Options.setInt(Options.OPTION_RECONNECT_NUMBER, Integer
				.parseInt(reconnectNumberTextField.getString()));
		Options.setBoolean(Options.OPTION_ENCRYPTION, encryptionChoiceGroup.isSelected(0));
		Options.setString(Options.OPTION_ENCRYPTION_PSK, encryptionPskTextField.getString().trim());
		
	}

	
	/* Command listener */
	public void commandAction(Command c, Displayable d)
	{
		
		if (JimmUI.isControlActive(groupSelector))
		{
			if (c == JimmUI.cmdOk)
			{
				switch (currOptMode)
				{
				case OPTIONS_RENAME_GROUP:
					String groupName = Util.removeClRfAndTabs(groupSelector.getCurrText(0, false).trim());
					showTextBoxForm("rename_group", "group_name", groupName, TextField.ANY);
					optionsForm.addCommand(JimmUI.cmdOk);
					optionsForm.addCommand(JimmUI.cmdBack);
					break;
					
				case OPTIONS_DELETE_GROUP:
					int groupId = groupSelector.getCurrTextIndex();
					if (groupId != -1)
					{
						Action act = new UpdateContactListAction(ContactList.getGroupById(groupId), UpdateContactListAction.ACTION_DEL);
						Icq.runActionAndProcessError(act);
					}
					break;
				}
			}
			else 
			{
				initOptionsList(TYPE_MCL_OPTIONS);
			}
		}
		
		else if (JimmUI.isControlActive(tlColorScheme))
		{
			if (c == JimmUI.cmdOk)
			{
				int theme = tlColorScheme.getCurrTextIndex();
				if (theme == -1) return;
				Options.setInt(Options.OPTION_COLOR_SCHEME, theme);
				Options.safeSave();
				ContactItem.updateColorValues();
			}
			activate();
			return;
		}
		
		else if (JimmUI.isControlActive(tlRmsAsk))
		{
			if (c == JimmUI.cmdSelect)
			{
			    int index = tlRmsAsk.getCurrTextIndex(); 
			    switch (index)
			    {
			    case RMS_ASK_RESULT_NO:
				    break;
			    case RMS_ASK_RESULT_YES:
				Icq.disconnect(true);
				try
				{
					Options.reset_rms();
				} catch (RecordStoreException re) {}

				// Save traffic
				//#sijapp cond.if modules_TRAFFIC is "true" #
				try
				{
					Traffic.reset();
				} catch (Exception e)
				{ // Do nothing
				}
				//#sijapp cond.end#

					/* Exit app */
				try
				{
					Thread.sleep(500);
				} catch (InterruptedException e1)
				{
					/* Do nothing */
				}
				try
				{
					Jimm.jimm.destroyApp(true);
				} catch (Exception e)
				{ /* Do nothing */
				}
				break;
			    }
			}
			activate();
			return;
		}

		/* Command handler for hotkeys list in Options... */
		else if (keysMenu.isActive())
		{
			if (c == JimmUI.cmdSelect)
			{
				fillHotkeysActions(false);
				
				actionMenu.addCommandEx(JimmUI.cmdOk, VirtualList.MENU_TYPE_RIGHT_BAR);
				actionMenu.addCommandEx(JimmUI.cmdBack, VirtualList.MENU_TYPE_LEFT_BAR);

				int optValue = ((Integer)hotKeysOptCodes[keysMenu.getCurrTextIndex()*hotKeysOptCodesSize+2]).intValue();
				actionMenu.selectTextByIndex(optValue);
				JimmUI.setColorScheme(actionMenu, false, -1, true);
				
				actionMenu.activate(Jimm.display);
				
				return;
			}
			else if (c == JimmUI.cmdSave)
			{
				for (int i = 0; i < hotKeysOptCodes.length; i += hotKeysOptCodesSize)
				{
					int optKey = ((Integer)hotKeysOptCodes[i]).intValue();
					int optValue = ((Integer)hotKeysOptCodes[i+2]).intValue(); 
					Options.setInt(optKey, optValue);
				}
				
				Options.safeSave();
				initOptionsList(TYPE_TOP_OPTIONS);
			}
			else if (c == JimmUI.cmdBack)
			{
				initOptionsList(TYPE_TOP_OPTIONS);
			}
		}

		//Command handler for actions list in Hotkeys...
		else if (actionMenu.isActive())
		{
			if (c == JimmUI.cmdOk)
			{
				hotKeysOptCodes[keysMenu.getCurrTextIndex()*hotKeysOptCodesSize+2] = new Integer(actionMenu.getCurrTextIndex());
			}
			InitHotkeyMenuUI();
			return;
		}

		// Look for select command
		else if (JimmUI.isControlActive(optionsMenu))
		{
			if (c == JimmUI.cmdSelect)
			{
				currOptMode = optionsMenu.getCurrTextIndex();
				dataToForm(currOptMode);
			}
			else if (c == JimmUI.cmdBack)
			{
				if (currOptType == TYPE_TOP_OPTIONS)
				{
					// Exit explicitly: isShown() may change before the queued
					// return runs, which otherwise reopens this options screen.
					JimmUI.removeScreen(this);
					MainThread.backToLastScreenMT();
				}
				else initOptionsList(TYPE_TOP_OPTIONS);
			}
		}

		/* Look for back command */
		else if ((c == JimmUI.cmdBack) || (c == JimmUI.cmdCancel))
		{
			if (d == optionsForm || keysMenu.isActive())
			{
				initOptionsList(currOptType);
			} 
			else
			{
				Options.optionsForm = null;
				JimmUI.removeScreen(this);
				MainThread.backToLastScreenMT();
				return;
			}
		}

		// Look for save command
		else if ((c == JimmUI.cmdSave || c == JimmUI.cmdOk) && d == optionsForm)
		{
			if (currOptMode == OPTIONS_INTERFACE && !Options.validLockPin(lockPinTextField.getString()))
			{
				Alert alert = new Alert(ResourceBundle.getString("error"),
						ResourceBundle.getString("pin_format"), null, AlertType.WARNING);
				alert.setTimeout(Alert.FOREVER);
				Jimm.display.setCurrent(alert, optionsForm);
				return;
			}
			boolean skipNextScreen = readDataFromForm();

			/* Save options */
			Options.safeSave();

			if (!skipNextScreen) activate();
		}

		/* Accounts */
		else if (c == cmdAddNewAccount)
		{
			readAccontsControls();
			uins.addElement(Options.emptyString);
			passwords.addElement(Options.emptyString);
			clearForm();
			showAccountControls();
			return;
		} 
		else if (c == cmdDeleteAccount)
		{
			readAccontsControls();
			int size = uins.size();
			String items[] = new String[size];
			for (int i = 0; i < size; i++) items[i] = checkUin((String) uins.elementAt(i));
			JimmUI.showSelector("delete", items, this, TAG_DELETE_ACCOUNT, false);
			return;
		} 
		else if (JimmUI.getCurScreenTag() == TAG_DELETE_ACCOUNT)
		{
			if (c == JimmUI.cmdOk)
			{
				readAccontsControls();
				int index = JimmUI.getLastSelIndex();
				uins.removeElementAt(index);
				passwords.removeElementAt(index);
			}
			clearForm();
			showAccountControls();
			Jimm.display.setCurrent(optionsForm);
			Jimm.setBkltOn(true);
		}
	}

	private void clearForm()
	{
		lockPinTextField = null;
		optionsForm.removeCommand(cmdAddNewAccount);
		optionsForm.removeCommand(cmdDeleteAccount);
		//#sijapp cond.if target!="DEFAULT"#
		optionsForm.deleteAll();
		//#sijapp cond.else#
		while (optionsForm.size() > 0) { optionsForm.delete(0); }
		//#sijapp cond.end#
	}

} // end of 'class OptionsForm'
