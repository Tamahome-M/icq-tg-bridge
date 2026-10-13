import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import jimm.*;

/** Exercise real SplashCanvas with a concurrent MIDP paint callback. */
public final class ClientStartupTest {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    public static void main(String[] args)throws Exception{
        try{
            field(Options.class,"options").set(null,new Hashtable());
            Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
            Options.setBoolean(Options.OPTION_DISPLAY_DATE,false);
            SplashCanvas screen=new SplashCanvas("Загрузка");Jimm.display.setCurrent(screen);
            Canvas.threadedRepaint=true;
            for(int n=10;n<=90;n+=10){
                SplashCanvas.setProgress(n);screen.awaitPaint();
                check(Canvas.paintFailure==null,"startup paint failed: "+Canvas.paintFailure);
                check(SplashCanvas.getProgress()==n,"startup progress lost");
            }
            check(Canvas.repaints==9,"startup did not request repaints");
            int previous=Canvas.repaints;SplashCanvas.setProgress(90);
            check(Canvas.repaints==previous,"unchanged progress repaints unnecessarily");
            // The MIDP UI queue may be paused while the loading thread runs.
            Canvas.suspendRepaint=true;SplashCanvas.setProgress(100);
            check(SplashCanvas.getProgress()==100,"suspended UI prevents completing startup");
            check(Canvas.repaintWaits==0,"startup waits for native drawing");
            Canvas.suspendRepaint=false;screen.repaint();screen.awaitPaint();
            check(Canvas.paintFailure==null,"deferred paint failed on resume");
            System.out.println("PASS: real startup progress completes with concurrent and suspended UI; resumed paint succeeds; unchanged progress coalesces");
        }finally{
            Jimm.getTimerRef().cancel();
            Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
