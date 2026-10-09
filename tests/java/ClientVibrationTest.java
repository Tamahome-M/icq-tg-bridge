import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import jimm.*;
import jimm.comm.PlainMessage;

public final class ClientVibrationTest {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    static Method method(Class c,String name,Class... args)throws Exception{Method m=c.getDeclaredMethod(name,args);m.setAccessible(true);return m;}
    static void defaults()throws Exception {
        field(Options.class,"options").set(null,new Hashtable());method(Options.class,"setDefaults").invoke(null);
        Options.setBoolean(Options.OPTION_DISPLAY_DATE,false);
    }
    static void reload()throws Exception{defaults();Options.load();Options.setBoolean(Options.OPTION_DISPLAY_DATE,false);}
    static Hashtable values()throws Exception{return (Hashtable)field(Options.class,"options").get(null);}
    static void legacyMode(int mode)throws Exception{values().put(new Integer(75),new Integer(mode));}
    static void profiles(int active,int locked,String why){
        check(Options.vibrationMillis(false)==active && Options.vibrationMillis(true)==locked,why);
    }
    static void migration()throws Exception {
        for(boolean durationsSaved:new boolean[]{false,true})for(int mode=0;mode<4;mode++){
            defaults();legacyMode(mode);
            if(durationsSaved){
                Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,200);
                Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,1500);
            }else{
                values().remove(new Integer(Options.OPTION_VIBRA_UNLOCKED_MS));
                values().remove(new Integer(Options.OPTION_VIBRA_LOCKED_MS));
            }
            Options.save();reload();
            int active=mode==1?(durationsSaved?200:500):0;
            int locked=mode==0?0:(durationsSaved?1500:500);
            profiles(active,locked,"legacy condition/duration mapped incorrectly: "+mode);
            check(!values().containsKey(new Integer(75)),"retired global vibration mode retained");
            reload();profiles(active,locked,"migration ran again on next startup");
            check(!values().containsKey(new Integer(75)),"migration did not persist removal of legacy mode");
        }
        for(long bad:new long[]{-1,0,1,700,Long.MAX_VALUE}){
            defaults();legacyMode(1);
            Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,bad);Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,bad);
            Options.save();reload();profiles(500,500,"legacy invalid duration did not fall back to 500ms");
        }
        for(int bad:new int[]{-1,4,Integer.MAX_VALUE}){
            defaults();legacyMode(bad);Options.save();reload();profiles(0,0,"invalid legacy condition enabled vibration");
        }
        for(int[] old:new int[][]{{50,1500},{200,50},{50,50},{0,50},{50,0}}){
            defaults();Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,old[0]);Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,old[1]);
            Options.save();reload();
            int active=old[0]==50?100:old[0],locked=old[1]==50?100:old[1];
            profiles(active,locked,"retired 50ms did not migrate independently to 100ms");
            check(Options.getLong(Options.OPTION_VIBRA_UNLOCKED_MS)==active
                    && Options.getLong(Options.OPTION_VIBRA_LOCKED_MS)==locked,"stored 50ms value was not replaced");
            reload();profiles(active,locked,"50ms replacement not persisted on next startup");
        }
        System.out.println("PASS: legacy off/always/locked/idle migrate once to independent profiles; old durations retained, absent/invalid durations use 500ms, retired RMS mode removed");
        System.out.println("PASS: retired 50ms choices migrate independently to 100ms; disabled/other profile values and repeated startup preserved");
    }
    static void preferences()throws Exception {
        defaults();profiles(0,0,"fresh install does not default to disabled vibration");
        check(!values().containsKey(new Integer(75)),"fresh install recreates retired global mode");
        Class c=Class.forName("jimm.OptionsForm");Constructor ctor=c.getDeclaredConstructor();ctor.setAccessible(true);Object form=ctor.newInstance();
        method(c,"showSignalingOptions").invoke(form);
        ChoiceGroup active=(ChoiceGroup)field(c,"unlockedVibrationDuration").get(form),locked=(ChoiceGroup)field(c,"lockedVibrationDuration").get(form);
        String[] labels={"Нет","0.1","0.2","0.5","1","1.5","2"};
        for(ChoiceGroup group:new ChoiceGroup[]{active,locked}){
            check(group.getType()==Choice.POPUP && group.size()==7 && group.getSelectedIndex()==0,"vibration dropdown/default wrong");
            for(int i=0;i<labels.length;i++)check(group.getString(i).equals(labels[i]),"duration label wrong");
        }
        int[] durations={0,100,200,500,1000,1500,2000};
        for(int i=0;i<durations.length;i++){
            active.setSelectedIndex(i,true);locked.setSelectedIndex(6-i,true);
            method(c,"readSignalingOptions").invoke(form);Options.save();reload();
            profiles(durations[i],durations[6-i],"independent off/duration choices not saved in RMS");
            check(!values().containsKey(new Integer(75)),"saving new profiles recreates retired global mode");
        }
        for(long bad:new long[]{-1,1,700,Long.MAX_VALUE}){
            Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,bad);Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,bad);
            Options.save();reload();profiles(0,0,"invalid new RMS duration enabled vibration");
        }
        method(c,"showSignalingOptions").invoke(form);
        check(((ChoiceGroup)field(c,"unlockedVibrationDuration").get(form)).getSelectedIndex()==0
                && ((ChoiceGroup)field(c,"lockedVibrationDuration").get(form)).getSelectedIndex()==0,"invalid saved duration is not shown as disabled");
        System.out.println("PASS: two independent vibration dropdowns default to off; off and all six durations from 100ms survive RMS; invalid new values stay disabled");
    }
    static final class Previous implements JimmScreen {
        public void activate(){JimmUI.setLastScreen(this,false);}public boolean isScreenActive(){return false;}
    }
    static void message(){MainThread.addMessageSerially(new PlainMessage("1000037","100500",1,"test",false));Display.flush();}
    static void expect(int duration){
        Display.vibrations.clear();message();check(Display.vibrations.size()==1 && ((Integer)Display.vibrations.firstElement()).intValue()==duration,"wrong actual Display.vibrate call: "+Display.vibrations);
    }
    static void quiet(){Display.vibrations.clear();message();check(Display.vibrations.isEmpty(),"suppressed message vibrates");}
    static void delivery()throws Exception {
        defaults();new SplashCanvas("test");JimmUI.setLastScreen(new Previous(),false);
        Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
        quiet();SplashCanvas.lock();quiet();SplashCanvas.unlock(false);
        Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,100);Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,2000);
        expect(100);SplashCanvas.lock();expect(2000);SplashCanvas.unlock(false);
        for(int duration:new int[]{100,200,500,1000,1500,2000}){
            Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,duration);Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,duration);
            expect(duration);SplashCanvas.lock();expect(duration);SplashCanvas.unlock(false);
        }
        Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,0);quiet();SplashCanvas.lock();expect(2000);SplashCanvas.unlock(false);
        Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,100);Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,0);
        expect(100);SplashCanvas.lock();quiet();SplashCanvas.unlock(false);
        Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,700);quiet();Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,100);
        ContactList.reading=true;quiet();ContactList.reading=false;
        ContactList.lastAlertAllowed=false;quiet();ContactList.lastAlertAllowed=true;
        ContactList.accepted=false;quiet();ContactList.accepted=true;
        Options.setBoolean(Options.OPTION_SILENT_MODE,true);expect(100);
        System.out.println("PASS: queued MainThread sends all six durations in both lock states; off makes no motor call; profiles independent, reading/burst/message gates preserved");
    }
    public static void main(String[] args)throws Exception {
        try{migration();preferences();delivery();}
        finally{
            Jimm.getTimerRef().cancel();
            for(String name:new String[]{"t1","t2"}){Timer timer=(Timer)field(SplashCanvas.class,name).get(null);if(timer!=null)timer.cancel();}
            Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
