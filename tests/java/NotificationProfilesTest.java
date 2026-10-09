import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import javax.microedition.media.Manager;
import jimm.*;

public final class NotificationProfilesTest {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name) throws Exception {
        Field f=c.getDeclaredField(name);f.setAccessible(true);return f;
    }
    static Method method(Class c,String name,Class... types) throws Exception {
        Method m=c.getDeclaredMethod(name,types);m.setAccessible(true);return m;
    }
    static void defaults() throws Exception {
        field(Options.class,"options").set(null,new Hashtable());
        method(Options.class,"setDefaults").invoke(null);
    }
    static void reload() throws Exception {defaults();Options.load();}
    static void migration() throws Exception {
        javax.microedition.rms.RecordStore.stores.clear();defaults();
        check(Options.getString(Options.OPTION_MESS_UNLOCKED_FILE).equals("msg_low.mp3"),"active default is not quiet");
        for(int mode=0;mode<=2;mode++){
            defaults();Hashtable values=(Hashtable)field(Options.class,"options").get(null);
            for(int id:new int[]{36,193,194})values.remove(new Integer(id));
            values.put(new Integer(5),"online.mp3");values.put(new Integer(68),new Integer(2));values.put(new Integer(69),new Integer(90));
            Options.setInt(Options.OPTION_MESS_NOTIF_MODE,mode);
            Options.setInt(Options.OPTION_MESS_NOTIF_VOL,30);
            Options.setString(Options.OPTION_MESS_NOTIF_FILE,"custom.mp3");Options.save();reload();
            check(Options.getInt(Options.OPTION_MESS_NOTIF_MODE)==mode && Options.getInt(Options.OPTION_MESS_NOTIF_VOL)==30,"old locked mode/volume lost");
            check(Options.getString(Options.OPTION_MESS_NOTIF_FILE).equals("custom.mp3"),"old melody lost");
            check(Options.getLong(Options.OPTION_MESS_UNLOCKED_MODE)==mode && Options.getLong(Options.OPTION_MESS_UNLOCKED_VOL)==30,"old silence/beep/volume ignored on upgrade");
            check(Options.getString(Options.OPTION_MESS_UNLOCKED_FILE).equals("msg_low.mp3"),"upgrade did not choose quiet melody");
            values=(Hashtable)field(Options.class,"options").get(null);
            for(int id:new int[]{5,68,69})check(!values.containsKey(new Integer(id)),"online preference survived");
            Options.setString(Options.OPTION_MESS_UNLOCKED_FILE,"tg.mp3");
            Options.setLong(Options.OPTION_MESS_UNLOCKED_MODE,2);Options.setLong(Options.OPTION_MESS_UNLOCKED_VOL,70);
            Options.save();reload();
            check(Options.getString(Options.OPTION_MESS_UNLOCKED_FILE).equals("tg.mp3") && Options.getLong(Options.OPTION_MESS_UNLOCKED_VOL)==70,"new preferences reset on reload");
        }
        System.out.println("PASS: old silent/beep/sound settings migrate; independent profile choices persist; online settings removed");
    }
    static ChoiceGroup choice(Object form,String name) throws Exception {
        return (ChoiceGroup)field(form.getClass(),name).get(form);
    }
    static void menu() throws Exception {
        defaults();Options.setString(Options.OPTION_MESS_NOTIF_FILE,"legacy.wav");
        Class c=Class.forName("jimm.OptionsForm");Constructor ctor=c.getDeclaredConstructor();ctor.setAccessible(true);
        Object form=ctor.newInstance();method(c,"showSignalingOptions").invoke(form);
        ChoiceGroup active=choice(form,"unlockedNotificationSoundChoice"),locked=choice(form,"messageNotificationSoundChoice"),typing=choice(form,"typingNotificationSoundChoice");
        for(ChoiceGroup group:new ChoiceGroup[]{active,locked,typing}){
            check(group.getType()==Choice.POPUP,"sound control is not dropdown");
            int offset=group==typing?3:2;
            String[] names={"message.mp3","msg_low.mp3","tg.mp3","typing.mp3"};
            for(int i=0;i<names.length;i++)check(group.getString(i+offset).equals(names[i]),"packaged melody missing from dropdown");
        }
        Form screen=(Form)field(c,"optionsForm").get(form);
        int dropdowns=0;for(Object item:screen.items)if(item instanceof ChoiceGroup && ((ChoiceGroup)item).getType()==Choice.POPUP)dropdowns++;
        check(dropdowns==6,"expected three sound dropdowns, vibration mode and two durations");
        check(active.getSelectedIndex()==3,"active default selection wrong");
        check(locked.getString(locked.getSelectedIndex()).equals("legacy.wav"),"legacy file discarded by menu");
        for(int activeMode=0;activeMode<2;activeMode++){
            active.setSelectedIndex(activeMode,true);locked.setSelectedIndex(4,true);typing.setSelectedIndex(1,true);
            method(c,"readSignalingOptions").invoke(form);Options.save();reload();
            check(Options.getLong(Options.OPTION_MESS_UNLOCKED_MODE)==activeMode,"silent/beep selection not saved");
            check(Options.getString(Options.OPTION_MESS_UNLOCKED_FILE).equals("msg_low.mp3"),"silent/beep selection overwrites saved melody");
            check(Options.getInt(Options.OPTION_MESS_NOTIF_MODE)==2 && Options.getString(Options.OPTION_MESS_NOTIF_FILE).equals("tg.mp3"),"melody selection does not enable sound");
            check(Options.getInt(Options.OPTION_TYPING_MODE)==1,"typing display-only lost");
        }
        active.setSelectedIndex(4,true);locked.setSelectedIndex(1,true);typing.setSelectedIndex(6,true);
        ((Gauge)field(c,"unlockedNotificationSoundVolume").get(form)).setValue(2);
        ((Gauge)field(c,"messageNotificationSoundVolume").get(form)).setValue(8);
        method(c,"readSignalingOptions").invoke(form);Options.save();reload();
        check(Options.getString(Options.OPTION_MESS_UNLOCKED_FILE).equals("tg.mp3") && Options.getLong(Options.OPTION_MESS_UNLOCKED_VOL)==20 && Options.getLong(Options.OPTION_MESS_UNLOCKED_MODE)==2,"active form values not saved");
        check(Options.getString(Options.OPTION_MESS_NOTIF_FILE).equals("tg.mp3") && Options.getInt(Options.OPTION_MESS_NOTIF_VOL)==80 && Options.getInt(Options.OPTION_MESS_NOTIF_MODE)==1,"locked form values not saved");
        check(Options.getInt(Options.OPTION_TYPING_MODE)==3 && Options.getString(Options.OPTION_TYPING_FILE).equals("typing.mp3"),"typing sound selection not saved");
        System.out.println("PASS: one combined sound dropdown per profile; silence/beep/melody and typing display-only persist; separate volumes and legacy files preserved");
    }
    static Manager.Sound last(){return (Manager.Sound)Manager.started.lastElement();}
    static void sound(String dir,String name,int volume) throws Exception {
        check(Arrays.equals(last().bytes,java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(dir,name))),"wrong sound resource: "+name);
        check(last().volume==volume && last().type.equals("audio/mpeg"),"wrong volume/MIME: "+name);
    }
    static void playback(String dir) throws Exception {
        defaults();
        // Bypass roster construction; the actual notification code only needs
        // its monitor/player listener. The native UI tree is outside this test.
        Field uf=field(sun.misc.Unsafe.class,"theUnsafe");sun.misc.Unsafe unsafe=(sun.misc.Unsafe)uf.get(null);
        ContactList list=(ContactList)unsafe.allocateInstance(ContactList.class);field(ContactList.class,"_this").set(null,list);
        new SplashCanvas("test");Options.setBoolean(Options.OPTION_DISPLAY_DATE,false);
        Options.setInt(Options.OPTION_MESS_NOTIF_VOL,80);Options.setLong(Options.OPTION_MESS_UNLOCKED_VOL,20);
        Manager.started.clear();ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);sound(dir,"msg_low.mp3",20);last().finish();
        SplashCanvas.lock();ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);sound(dir,"message.mp3",80);last().finish();
        SplashCanvas.unlock(false);Options.setString(Options.OPTION_MESS_UNLOCKED_FILE,"tg.mp3");
        ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);sound(dir,"tg.mp3",20);
        Manager.Sound first=last();SplashCanvas.lock();ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);
        SplashCanvas.unlock(false);first.finish();sound(dir,"message.mp3",80);last().finish();
        int count=Manager.started.size();Options.setLong(Options.OPTION_MESS_UNLOCKED_MODE,0);
        ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);check(count==Manager.started.size(),"active silence ignored");
        SplashCanvas.lock();ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);check(Manager.started.size()==count+1,"active silence mutes locked profile");last().finish();
        Options.setInt(Options.OPTION_MESS_NOTIF_MODE,1);ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);check(Manager.toneVolume==80,"locked beep wrong volume");
        SplashCanvas.unlock(false);Options.setLong(Options.OPTION_MESS_UNLOCKED_MODE,1);ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);check(Manager.toneVolume==20,"active beep wrong volume");
        Options.setInt(Options.OPTION_TYPING_MODE,2);Options.setInt(Options.OPTION_TYPING_VOL,40);
        ContactList.playSoundNotification(ContactList.SOUND_TYPE_TYPING);check(Manager.toneVolume==40,"typing beep uses another profile's volume");
        Options.setInt(Options.OPTION_TYPING_MODE,3);ContactList.playSoundNotification(ContactList.SOUND_TYPE_TYPING);sound(dir,"typing.mp3",40);last().finish();
        count=Manager.started.size();int tones=Manager.toneCount;ContactList.playSoundNotification(2);
        Options.setBoolean(Options.OPTION_SILENT_MODE,true);ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);ContactList.playSoundNotification(ContactList.SOUND_TYPE_TYPING);
        check(count==Manager.started.size() && tones==Manager.toneCount,"online notification/global silence regression");
        System.out.println("PASS: real MP3 resource selection, lock profiles, captured queued volume, silence/beep and typing volume");
    }
    public static void main(String[] args) throws Exception {
        try{migration();menu();playback(args[0]);}
        finally{Jimm.getTimerRef().cancel();Timer timer=(Timer)field(ContactList.class,"soundTimer").get(null);if(timer!=null)timer.cancel();}
    }
}
