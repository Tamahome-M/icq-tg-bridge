import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.*;
import jimm.*;
import jimm.comm.*;

/** Actual history parsing and text layout; message IDs/tokens must follow prepend. */
public final class HistoryMemoryTest {
 static boolean baseline;
 static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 static Field f(Class type,String name)throws Exception{Field field=type.getDeclaredField(name);field.setAccessible(true);return field;}
 static Method m(Class type,String name,Class... args)throws Exception{Method method=type.getDeclaredMethod(name,args);method.setAccessible(true);return method;}
 static class Back implements JimmScreen {
  public void activate(){Jimm.display.setCurrent((Displayable)null);}
  public boolean isScreenActive(){return false;}
 }
 static HistoryViewer viewer()throws Exception{
  Constructor c=HistoryViewer.class.getDeclaredConstructor(JimmScreen.class,String.class,String.class);c.setAccessible(true);
  HistoryViewer viewer=(HistoryViewer)c.newInstance(new Back(),"1000037","History");
  f(HistoryViewer.class,"current").set(null,viewer);m(HistoryViewer.class,"build").invoke(viewer);return viewer;
 }
 static TextList list(HistoryViewer viewer)throws Exception{return (TextList)f(HistoryViewer.class,"list").get(viewer);}
 static Vector lines(TextList list)throws Exception{return (Vector)f(TextList.class,"lines").get(list);}
 static void render(HistoryViewer viewer,byte[] data)throws Exception{m(HistoryViewer.class,"render",byte[].class).invoke(viewer,(Object)data);}
 static byte[] id(long id){byte[] bytes=new byte[8];for(int i=7;i>=0;i--){bytes[i]=(byte)id;id>>>=8;}return bytes;}
 static byte[] token(int id){byte[] bytes=new byte[16];Arrays.fill(bytes,(byte)id);return bytes;}
 static String body="[07.10 12:00] Автор: "+new String(new char[280]).replace('\0','W');
 static byte[] page(int first,int count,int form,boolean more,boolean mixed)throws Exception{
  ByteArrayOutputStream bytes=new ByteArrayOutputStream();DataOutputStream out=new DataOutputStream(bytes);
  if(form==2)out.writeByte(255);if(form>0)out.writeByte(more?1:0);
  for(int i=0;i<count;i++){
   int value=first+i,kind=value%4+1,flag=mixed?0x31:0x20;
   if(mixed){if(kind==2)flag|=2;if(kind==3)flag|=4;if(kind==4)flag|=6;if((value&1)!=0)flag|=8;}
   String text=body;
   if(mixed)text=kind==2?"[видео](http://host/v/"+value+") 0:24\n[07.10 12:00] Автор: подпись"
      :"[07.10 12:00] Автор: сообщение "+value+"\nстрока :-)";
   byte[] raw=text.getBytes("UTF-8");out.writeShort(raw.length);out.write(raw);out.writeByte(flag);
   if(mixed){out.write(token(value));out.writeInt(1000000+value);}
   out.write(id(0x8000000000000000L+value));
  }
  return bytes.toByteArray();
 }
 static String layout(TextList list)throws Exception{
  Vector lines=lines(list);StringBuffer text=new StringBuffer();
  for(int i=0;i<lines.size();i++){
   Object line=lines.elementAt(i);Vector items=(Vector)f(line.getClass(),"items").get(line);
   if(items.isEmpty())continue;
   text.append('[').append(f(line.getClass(),"bigTextIndex").getInt(line)).append(':');
   for(int j=0;j<items.size();j++){
    Object item=items.elementAt(j);text.append(f(item.getClass(),"text").get(item)).append('|')
      .append(f(item.getClass(),"font").getShort(item)).append('|').append(f(item.getClass(),"color").getInt(item)).append(';');
   }
   text.append((int)f(line.getClass(),"last_charaster").getChar(line)).append(']');
  }
  return text.toString();
 }
 static void metadata(HistoryViewer viewer,int first,int count)throws Exception{
  TextList list=list(viewer);
  for(int i=0;i<count;i++){
   int value=first+i;list.selectTextByIndex(i);
   check(Arrays.equals(token(value),(byte[])m(HistoryViewer.class,"currentToken").invoke(viewer)),"token shifted away from text");
   check(Arrays.equals(id(0x8000000000000000L+value),(byte[])m(HistoryViewer.class,"currentRef").invoke(viewer)),"64-bit reference shifted away from text");
   check(String.valueOf(1000000+value).equals(m(HistoryViewer.class,"currentThread").invoke(viewer)),"discussion shifted away from text");
   check(((Integer)m(HistoryViewer.class,"currentKind").invoke(viewer)).intValue()==value%4+1,"attachment kind shifted away from text");
   Object url=m(HistoryViewer.class,"currentVideoUrl").invoke(viewer);
   check(value%4+1==2? ("http://host/v/"+value).equals(url):url==null,"video URL shifted away from text");
  }
 }
 static void golden()throws Exception{
  for(int form=0;form<3;form++){
   HistoryViewer viewer=viewer();render(viewer,page(5,4,form,true,true));render(viewer,page(1,4,form,false,true));
   metadata(viewer,1,8);System.out.println("HISTORY_LAYOUT "+form+" "+layout(list(viewer)));
   viewer.commandAction(JimmUI.cmdBack,null);
  }
  System.out.println("PASS: legacy/flagged/marked pages retain order, header colours, video labels, tokens, discussion and 64-bit references");
 }
 static void memory()throws Exception{
  HistoryViewer viewer=viewer();Font.measured=0;long firstWork=0;
  for(int batch=0;batch<10;batch++){
   Vector before=(Vector)lines(list(viewer)).clone();long beforeWork=Font.measured;
   render(viewer,page(91-batch*10,10,2,true,false));
   if(batch==0)firstWork=Font.measured;
   if(!baseline && batch>0){
    Vector after=lines(list(viewer));
    for(int i=0;i<before.size();i++)check(after.contains(before.elementAt(i)),"older-page load rebuilt existing TextLines");
    check(Font.measured-beforeWork<firstWork*2,"older-page load measured existing messages again");
   }
  }
  long stored=0;
  if(baseline){Vector texts=(Vector)f(HistoryViewer.class,"texts").get(viewer);for(int i=0;i<texts.size();i++)stored+=((String)texts.elementAt(i)).length();}
  else{
   Vector urls=(Vector)f(HistoryViewer.class,"videoUrls").get(viewer);for(int i=0;i<urls.size();i++)check(urls.elementAt(i)==null,"plain history retained its full message text");
   check(f(HistoryViewer.class,"kinds").get(viewer) instanceof byte[],"attachment types still use boxed Integers");
  }
  check(f(HistoryViewer.class,"shown").getInt(viewer)==100,"page offset did not advance");
  System.out.println("METRIC history 10 pages / 100 messages: measured characters="+Font.measured+", separately stored message characters="+stored);
  if(!baseline)System.out.println("PASS: only incoming messages are formatted; previous TextLine objects survive and full-message storage is absent");
  viewer.commandAction(JimmUI.cmdBack,null);
 }
 static void waitDone(HistoryViewer viewer)throws Exception{
  long until=System.currentTimeMillis()+5000;
  while(f(HistoryViewer.class,"loading").getBoolean(viewer) && System.currentTimeMillis()<until)Thread.sleep(5);
  check(!f(HistoryViewer.class,"loading").getBoolean(viewer),"history worker stuck loading");
 }
 static void failures()throws Exception{
  HistoryViewer viewer=viewer();render(viewer,page(5,4,2,true,true));TextList list=list(viewer);
  list.selectTextByIndex(1);Object first=lines(list).firstElement();String before=layout(list);int selected=list.getCurrTextIndex();
  f(HistoryViewer.class,"loading").setBoolean(viewer,true);viewer.onBart(new byte[]{0,10,'x'});waitDone(viewer);
  check(before.equals(layout(list)) && lines(list).firstElement()==first,"malformed page destroyed loaded history");
  check(list.getCurrTextIndex()==selected && f(HistoryViewer.class,"shown").getInt(viewer)==4,"failure changed selection or offset");
  check(Jimm.display.getCurrent() instanceof Alert,"malformed page error invisible");viewer.activate();
  Font.beforeMeasure=new Runnable(){public void run(){throw new OutOfMemoryError("page layout");}};
  f(HistoryViewer.class,"loading").setBoolean(viewer,true);viewer.onBart(page(1,4,2,true,true));waitDone(viewer);
  check(before.equals(layout(list)) && lines(list).firstElement()==first,"page layout OOM destroyed loaded history");
  viewer.activate();render(viewer,page(1,4,2,true,true));metadata(viewer,1,8);
  int index=list.getCurrTextIndex();String loaded=layout(list);render(viewer,new byte[]{(byte)255,0});
  check(loaded.equals(layout(list)) && list.getCurrTextIndex()==index,"empty older page rebuilt history or moved selection");
  check(f(HistoryViewer.class,"exhausted").getBoolean(viewer),"empty page left history open-ended");
  viewer.commandAction(JimmUI.cmdBack,null);
  System.out.println("PASS: malformed/OOM older pages preserve history, selection and retry; empty older page leaves existing lines intact");
 }
 static void limits()throws Exception{
  HistoryViewer viewer=viewer();render(viewer,page(1001,190,2,true,false));
  new SplashCanvas("test");new Icq();m(Icq.class,"setConnected").invoke(null);Vector queued=new Vector();f(Icq.class,"reqAction").set(null,queued);
  Options.setInt(Options.OPTION_HISTORY_COUNT,100);m(HistoryViewer.class,"request").invoke(viewer);
  RequestBartAction request=(RequestBartAction)queued.lastElement();byte[] token=(byte[])f(RequestBartAction.class,"token").get(request);
  check(Util.getWord(token,0)==10 && Util.getWord(token,2)==190,"next request can exceed the 200-message limit or has a wrong offset");
  render(viewer,page(971,30,2,true,false));check(f(HistoryViewer.class,"shown").getInt(viewer)==200,"oversized page exceeded memory limit");
  check(((Vector)f(HistoryViewer.class,"tokens").get(viewer)).size()==200,"metadata exceeded 200 messages");
  list(viewer).selectTextByIndex(0);check(Arrays.equals(id(0x8000000000000000L+991),(byte[])m(HistoryViewer.class,"currentRef").invoke(viewer)),"oversized page discarded its newest records");
  int pending=queued.size();m(HistoryViewer.class,"request").invoke(viewer);check(queued.size()==pending,"More still requests pages after the limit");
  viewer.commandAction(JimmUI.cmdBack,null);
  System.out.println("PASS: request count/offset and oversized replies obey the strict 200-message cap");
 }
 static void rangeAndClose()throws Exception{
  HistoryViewer viewer=viewer();byte[] page=page(1,4,2,true,true),raw=new byte[page.length+17];System.arraycopy(page,0,raw,9,page.length);
  f(HistoryViewer.class,"loading").setBoolean(viewer,true);
  m(HistoryViewer.class,"onBart",byte[].class,int.class,int.class).invoke(viewer,raw,9,page.length);waitDone(viewer);metadata(viewer,1,4);
  final HistoryViewer closing=viewer;
  Font.beforeMeasure=new Runnable(){public void run(){closing.commandAction(JimmUI.cmdBack,null);}};
  f(HistoryViewer.class,"loading").setBoolean(viewer,true);viewer.onBart(page(1,4,2,true,true));
  long until=System.currentTimeMillis()+5000;while(f(HistoryViewer.class,"list").get(viewer)!=null && System.currentTimeMillis()<until)Thread.sleep(5);
  for(String field:new String[]{"list","videoUrls","tokens","kinds","threads","refs"})check(f(HistoryViewer.class,field).get(viewer)==null,"Back retained history "+field);
  Thread.sleep(30);check(f(HistoryViewer.class,"current").get(null)==null,"late reply reopened a closed history");
  viewer.activate();check(f(HistoryViewer.class,"current").get(null)==null,"stale activation reopened a closed history");
  System.out.println("PASS: nonzero BART range parses without a payload copy; Back during layout releases all history and ignores a late result");
 }
 static void inactive()throws Exception{
  HistoryViewer viewer=viewer();render(viewer,page(5,4,2,true,true));String before=layout(list(viewer));
  f(HistoryViewer.class,"loading").setBoolean(viewer,true);f(HistoryViewer.class,"current").set(null,null);
  viewer.onBart(page(1,4,2,true,true));
  check(!f(HistoryViewer.class,"loading").getBoolean(viewer),"inactive history remains stuck waiting for a dropped reply");
  viewer.activate();check(before.equals(layout(list(viewer))),"return from child lost loaded history");
  render(viewer,page(1,4,2,true,true));metadata(viewer,1,8);viewer.commandAction(JimmUI.cmdBack,null);
  System.out.println("PASS: reply to inactive history is dropped without a stuck loading flag; returning and retrying preserves records");
 }
 static void cancel(Class type,String name)throws Exception{Timer timer=(Timer)f(type,name).get(null);if(timer!=null)timer.cancel();}
 public static void main(String[] args)throws Exception{
  baseline=args[0].equals("baseline");
  try{
   f(Options.class,"options").set(null,new Hashtable());m(Options.class,"setDefaults").invoke(null);
   Options.setBoolean(Options.OPTION_USE_SMILES,false);Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
   golden();memory();if(!baseline){failures();limits();rangeAndClose();inactive();}
  }finally{
   Jimm.getTimerRef().cancel();cancel(TextList.class,"aniTimer");cancel(ContactList.class,"iconTimer");cancel(ContactList.class,"soundTimer");
   Object canvas=f(VirtualList.class,"virtualCanvas").get(null);((Timer)f(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
  }
 }
}
