import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.*;
import jimm.*;
import jimm.util.ResourceBundle;

public class ClientPerformanceTest {
 static boolean baseline;
 static void check(boolean b,String message){if(!b)throw new AssertionError(message);}
 static Field f(Class type,String name)throws Exception{Field field=type.getDeclaredField(name);field.setAccessible(true);return field;}
 static Vector items(Object line)throws Exception{
  Method size=line.getClass().getDeclaredMethod("size");size.setAccessible(true);
  Method at=line.getClass().getDeclaredMethod("elementAt",int.class);at.setAccessible(true);
  Vector result=new Vector();int count=((Integer)size.invoke(line)).intValue();
  for(int i=0;i<count;i++)result.addElement(at.invoke(line,i));return result;
 }
 static String text(Object item)throws Exception{return (String)f(item.getClass(),"text").get(item);}
 static String layout(String value,boolean append)throws Exception {
  TextList list=new TextList("layout");
  if(append)list.addBigText("prefix: ",0,Font.STYLE_BOLD,7);
  list.addBigText(value,0,Font.STYLE_PLAIN,7);
  Vector lines=(Vector)f(TextList.class,"lines").get(list);StringBuffer out=new StringBuffer();
  for(int i=0;i<lines.size();i++){
   Object line=lines.elementAt(i);Vector items=items(line);
   out.append('[');
   for(int j=0;j<items.size();j++)out.append(text(items.elementAt(j))).append('|');
   out.append(':').append((int)f(line.getClass(),"last_charaster").getChar(line)).append(']');
  }
  return out.toString();
 }
 static void layouts()throws Exception {
  String[] cases={"",null,"one two three", "  one  two   three  ","Привет, мир! Строка с кириллицей.",
   "a\r\nb\rc\n\nd", "\r\r\n", "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW",
   "ililililililililililililililililililililililililililililililililil", "line one\nline two\n",
   "word word word word word word word word word word word word word word", "x  y\nz"};
  for(int i=0;i<cases.length;i++)for(int append=0;append<2;append++)
   System.out.println("LAYOUT "+i+" "+append+" "+layout(cases[i],append==1));
  char[] longWord=new char[900];Arrays.fill(longWord,'W');Font.measured=0;Font.strings=0;
  TextList list=new TextList("long word");String word=new String(longWord);
  list.addBigText(word,0,Font.STYLE_PLAIN,7);
  long measured=Font.measured;int strings=Font.strings;
  check(word.equals(list.getTextByIndex(0,false,7)),"long word text changed during wrapping");
  System.out.println("METRIC long-word measured characters="+measured+", stringWidth calls="+strings);
  if(!baseline)check(measured<100000 && strings<100,"long word layout still scans/allocates every shrinking substring");
  System.out.println("PASS: real TextList preserves long-word text");
 }
 static void language(String path)throws Exception {
  DataInputStream in=new DataInputStream(new FileInputStream(path));int size=in.readUnsignedShort();
  String compact=null,named=null;int compressed=0;
  for(int i=0;i<size;i++){
   String key=in.readUTF(),value=in.readUTF();
   check(value.equals(ResourceBundle.getString(key)),"translation changed for "+key);
   if(key.length()<=2){compressed++;compact=key;}else named=key;
  }
  in.close();check(ResourceBundle.getString(null)==null,"null language key changed");
  check("missing_key".equals(ResourceBundle.getString("missing_key")),"unknown key lost fallback");
  String value=ResourceBundle.getString(compact);
  check((value+"...").equals(ResourceBundle.getString(compact,ResourceBundle.FLAG_ELLIPSIS)),"ellipsis translation changed");
  check(value.equals(ResourceBundle.remove(compact)) && compact.equals(ResourceBundle.getString(compact)),"compact key removal failed");
  value=ResourceBundle.getString(named);
  check(value.equals(ResourceBundle.remove(named)) && named.equals(ResourceBundle.getString(named)),"named key removal failed");
  Method load=ResourceBundle.class.getDeclaredMethod("loadLang");load.setAccessible(true);load.invoke(null);
  check(!compact.equals(ResourceBundle.getString(compact)),"language reload failed");
  if(!baseline){
   Hashtable remaining=(Hashtable)f(ResourceBundle.class,"resources").get(null);
   check(remaining.size()==size-compressed,"compact translations still retain Hashtable entries");
  }
  System.out.println("METRIC language entries="+size+", compact keys="+compressed);
  System.out.println("PASS: all real binary language entries, named errors, unknown/null keys, ellipsis, removal and reload");
 }
 static class Previous implements JimmScreen {
  Vector shown=new Vector();Runnable onActivate;
  public void activate(){try{shown.addElement(f(VirtualList.class,"bottomText").get(null));JimmUI.setLastScreen(this,false);
   if(onActivate!=null){Runnable action=onActivate;onActivate=null;action.run();}
  }catch(Exception e){throw new AssertionError(e);}}
  public boolean isScreenActive(){return false;}
 }
 static void tasks()throws Exception {
  Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
  Previous back=new Previous();Vector stack=(Vector)f(JimmUI.class,"lastScreens").get(null);stack.removeAllElements();stack.addElement(back);
  final int showTime=f(MainThread.class,"TYPE_SHOW_TIME").getInt(null);
  for(int i=0;i<100;i++){MainThread.addMainThreadTask(showTime,"event "+i);MainThread.backToLastScreenMT();}
  int calls=Display.queued.size();System.out.println("METRIC 200 UI tasks scheduled callbacks="+calls);
  if(!baseline)check(calls==1,"UI task burst schedules duplicate callbacks");
  Display.flush();check(back.shown.size()==100,"batched UI events were lost");
  if(!baseline)check(((Vector)f(MainThread.class,"mainThreadTasks").get(null)).capacity()<=64,"static UI queue retained burst capacity");
  for(int i=0;i<100;i++)check(("event "+i).equals(back.shown.elementAt(i)),"UI task order changed");
  MainThread.addMainThreadTask(showTime,"next batch");check(Display.queued.size()==1,"queue lost wakeup after previous batch");Display.flush();
  check("next batch".equals(f(VirtualList.class,"bottomText").get(null)),"new UI batch not delivered");
  back.onActivate=new Runnable(){public void run(){MainThread.addMainThreadTask(showTime,"during callback");}};
  MainThread.backToLastScreenMT();Display.flush();
  check("during callback".equals(f(VirtualList.class,"bottomText").get(null)),"UI event queued during a callback lost its wakeup");
  System.out.println("PASS: actual MainThread preserves event order and starts the next batch, including events queued during a callback");
 }
 static void timers()throws Exception {
  int count=0;
  if(f(TextList.class,"aniTimer").get(null)!=null)count++;
  if(f(ContactList.class,"iconTimer").get(null)!=null)count++;
  if(f(ContactList.class,"soundTimer").get(null)!=null)count++;
  System.out.println("METRIC unused watchdog/animation timers="+count);
  if(!baseline){
   check(f(TextList.class,"aniTimer").get(null)==null,"static pictures started an animation timer");
   check(f(ContactList.class,"iconTimer").get(null)==null,"unused avatars started a timer");
   check(f(ContactList.class,"soundTimer").get(null)==null,"unused sound started a timer");
  }
  if(!baseline)System.out.println("PASS: animation/avatar/sound watchdog timers are lazy");
 }
 static void cancel(Class type,String name)throws Exception{Timer timer=(Timer)f(type,name).get(null);if(timer!=null)timer.cancel();}
 static Vector oldWrap(String text,int width,Font font){
  Vector out=new Vector();int start=0;
  while(start<text.length()){
   int nl=text.indexOf('\n',start),end=nl<0?text.length():nl;String para=text.substring(start,end);start=end+1;
   while(para.length()>0){int fit=para.length();while(fit>1 && font.stringWidth(para.substring(0,fit))>width)fit--;
    if(fit<para.length()){int space=para.lastIndexOf(' ',fit);if(space>0)fit=space;}
    out.addElement(para.substring(0,fit));para=para.substring(fit).trim();
   }
  }return out;
 }
 static void wrapped()throws Exception{
  Font font=Font.getDefaultFont();char[] chars=new char[900];Arrays.fill(chars,'W');String word=new String(chars);
  String[] cases={"", "one two three", "  one  two   three  ", "Привет, мир!", "a\n\nb\r\nc",word,"i W Ж", "\t a b \t"};
  for(String value:cases)for(int width:new int[]{1,10,96,164}){
   Vector expected=oldWrap(value,width,font);Graphics.wrapped=new Vector();
   JimmUI.drawWrapped(new Graphics(),value,0,0,width,font);
   check(expected.equals(Graphics.wrapped),"status/path wrapping changed");
  }
  Font.measured=0;Font.strings=0;Graphics.wrapped=new Vector();
  JimmUI.drawWrapped(new Graphics(),word,0,0,164,font);
  System.out.println("METRIC wrapped status: measured characters="+Font.measured+", stringWidth calls="+Font.strings);
  if(!baseline)check(Font.measured<100000 && Font.strings==0,"paint still measures shrinking substring copies");
  Graphics.wrapped=null;
  System.out.println("PASS: status/file-path wrapping matches old layout, including whitespace and narrow screens, without quadratic prefix copies");
 }
 public static void main(String[] args)throws Exception {
  baseline="baseline".equals(args[1]);
  try{
   f(Options.class,"options").set(null,new Hashtable());Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
   language(args[0]);layouts();tasks();timers();wrapped();
  }finally{
   Jimm.getTimerRef().cancel();cancel(TextList.class,"aniTimer");cancel(ContactList.class,"iconTimer");cancel(ContactList.class,"soundTimer");
   Object canvas=f(VirtualList.class,"virtualCanvas").get(null);((Timer)f(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
  }
 }
}
