
import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.TextList;
import jimm.*;
public class SettingsNavigationTest {
 static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
 static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
 static void defaults()throws Exception{
  field(Options.class,"options").set(null,new Hashtable());
  Method m=Options.class.getDeclaredMethod("setDefaults");m.setAccessible(true);m.invoke(null);
  field(Options.class,"optionsForm").set(null,null);
  ((Vector)field(JimmUI.class,"lastScreens").get(null)).removeAllElements();
 }
 static final class Previous implements JimmScreen {
  final TextList screen=new TextList("chat");
  public void activate(){screen.activate(Jimm.display);JimmUI.setLastScreen(this,true);}
  public boolean isScreenActive(){return screen.isActive();}
 }
 static void scenario(boolean save,boolean hidden,int origin)throws Exception{
  Display.foreground=true;defaults();
  TextList destination=MainMenu.menu;
  if(origin==1){Previous previous=new Previous();previous.activate();destination=previous.screen;}
  else MainMenu.activateMenu();
  Options.editOptions();
  Object owner=field(Options.class,"optionsForm").get(null);Class type=owner.getClass();
  TextList menu=(TextList)field(type,"optionsMenu").get(owner);
  menu.choose(1);Form form=(Form)Jimm.display.getCurrent();
  ((TextField)field(type,"encryptionPskTextField").get(owner)).setString("moto code");
  ((CommandListener)owner).commandAction(save?JimmUI.cmdSave:JimmUI.cmdBack,form);
  check(Jimm.display.getCurrent()==menu,"network form did not return to settings");
  check(Options.getString(Options.OPTION_ENCRYPTION_PSK).equals(save?"moto code":""),"save/cancel changed PSK incorrectly");
  Vector stack=(Vector)field(JimmUI.class,"lastScreens").get(null);
  check(stack.contains(owner),"closing a network form removed the settings screen");
  if(origin==2)stack.removeElementAt(0); // parent unavailable: return must fall back to main menu
  menu.listener.commandAction(JimmUI.cmdBack,null);
  check(MainThread.pending,"exit was not queued");
  if(hidden)Display.foreground=false; // background/visibility changes before callSerially
  MainThread.flush();
  check(Jimm.display.getCurrent()==destination,"Back returned to settings instead of the previous screen; save="+save+", hidden="+hidden+", origin="+origin);
  check(!stack.contains(owner),"closed settings screen remains in the return stack");
  Display.foreground=true;
  System.out.println("PASS: settings exit after network "+(save?"save":"cancel")+", hidden="+hidden+", origin="+origin);
 }
 public static void main(String[] args)throws Exception{
  try{for(int origin=0;origin<3;origin++){scenario(true,false,origin);scenario(false,false,origin);scenario(true,true,origin);scenario(false,true,origin);}}
  finally{Jimm.getTimerRef().cancel();}
 }
}
