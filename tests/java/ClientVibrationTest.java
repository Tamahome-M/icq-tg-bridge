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
    static void preferences()throws Exception {
        for(int mode=0;mode<4;mode++){
            defaults();Options.setInt(Options.OPTION_VIBRATOR,mode);
            Hashtable values=(Hashtable)field(Options.class,"options").get(null);
            values.remove(new Integer(Options.OPTION_VIBRA_UNLOCKED_MS));values.remove(new Integer(Options.OPTION_VIBRA_LOCKED_MS));
            Options.save();reload();
            check(Options.getInt(Options.OPTION_VIBRATOR)==mode,"upgrade changed vibration enable/condition");
            check(Options.vibrationMillis(false)==500 && Options.vibrationMillis(true)==500,"upgrade changed 500ms duration");
        }
        Class c=Class.forName("jimm.OptionsForm");Constructor ctor=c.getDeclaredConstructor();ctor.setAccessible(true);Object form=ctor.newInstance();
        method(c,"showSignalingOptions").invoke(form);
        ChoiceGroup active=(ChoiceGroup)field(c,"unlockedVibrationDuration").get(form),locked=(ChoiceGroup)field(c,"lockedVibrationDuration").get(form);
        ChoiceGroup mode=(ChoiceGroup)field(c,"vibratorChoiceGroup").get(form);
        check(mode.getType()==Choice.POPUP && mode.size()==4,"vibration condition is not dropdown or lost choices");
        String[] labels={"0.2","0.5","1","1.5","2"};
        for(ChoiceGroup group:new ChoiceGroup[]{active,locked}){
            check(group.getType()==Choice.POPUP && group.size()==5 && group.getSelectedIndex()==1,"duration dropdown/default wrong");
            for(int i=0;i<labels.length;i++)check(group.getString(i).equals(labels[i]),"duration label wrong");
        }
        int[] durations={200,500,1000,1500,2000};
        for(int i=0;i<durations.length;i++){
            active.setSelectedIndex(i,true);locked.setSelectedIndex(4-i,true);mode.setSelectedIndex(i%4,true);
            method(c,"readSignalingOptions").invoke(form);Options.save();reload();
            check(Options.vibrationMillis(false)==durations[i] && Options.vibrationMillis(true)==durations[4-i],"duration/lock profile not saved in RMS");
            check(Options.getInt(Options.OPTION_VIBRATOR)==i%4,"condition not saved");
        }
        for(long bad:new long[]{-1,0,1,700,Long.MAX_VALUE}){
            Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,bad);Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,bad);
            check(Options.vibrationMillis(false)==500 && Options.vibrationMillis(true)==500,"invalid RMS duration passed to motor");
        }
        System.out.println("PASS: old vibration condition persists with 500ms default; dropdowns and all five independent durations survive RMS; invalid values fall back");
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
        Options.setInt(Options.OPTION_VIBRATOR,1);Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,200);Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,2000);
        expect(200);SplashCanvas.lock();expect(2000);SplashCanvas.unlock(false);
        for(int duration:new int[]{200,500,1000,1500,2000}){Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,duration);expect(duration);}
        Options.setInt(Options.OPTION_VIBRATOR,0);quiet();SplashCanvas.lock();quiet();SplashCanvas.unlock(false);
        Options.setInt(Options.OPTION_VIBRATOR,2);quiet();SplashCanvas.lock();expect(2000);SplashCanvas.unlock(false);
        Options.setInt(Options.OPTION_VIBRATOR,3);DrawControls.VirtualList.touch();quiet();
        Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);
        field(canvas.getClass(),"lastKeyTime").setLong(null,System.currentTimeMillis()-61000);expect(2000);
        SplashCanvas.lock();expect(2000);SplashCanvas.unlock(false);
        Options.setInt(Options.OPTION_VIBRATOR,1);ContactList.reading=true;quiet();ContactList.reading=false;
        ContactList.lastAlertAllowed=false;quiet();ContactList.lastAlertAllowed=true;
        ContactList.accepted=false;quiet();ContactList.accepted=true;
        Options.setBoolean(Options.OPTION_SILENT_MODE,true);expect(2000);
        System.out.println("PASS: real queued MainThread sends selected durations to Display.vibrate; normal/locked, disabled/locked-only/idle conditions and reading/burst/message gates preserved");
    }
    public static void main(String[] args)throws Exception {
        try{preferences();delivery();}
        finally{
            Jimm.getTimerRef().cancel();
            for(String name:new String[]{"t1","t2"}){Timer timer=(Timer)field(SplashCanvas.class,name).get(null);if(timer!=null)timer.cancel();}
            Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
