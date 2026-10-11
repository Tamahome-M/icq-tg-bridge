package jimm;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import javax.microedition.lcdui.*;
import DrawControls.*;
import jimm.comm.*;
import jimm.comm.connections.*;

public class FaultUiTest {
 static Field field(Class c,String n)throws Exception{Field f=c.getDeclaredField(n);f.setAccessible(true);return f;}
 static Object call(Class c,String n,Class[] types,Object o,Object... args)throws Exception{
  Method m=c.getDeclaredMethod(n,types);m.setAccessible(true);return m.invoke(o,args);
 }
 static void resetQueue()throws Exception{
  field(MainThread.class,"mainThreadTasks").set(null,new Vector());field(MainThread.class,"queuedBytes").setInt(null,0);field(MainThread.class,"queueScheduled").setBoolean(null,false);Display.queued.removeAllElements();
 }
 static void queue()throws Exception{
  resetQueue();Display.fail=true;
  MainThread.showTime();
  Display.fail=false;MainThread.showTime();
  Vector q=(Vector)field(MainThread.class,"mainThreadTasks").get(null);
  check(q.size()==2 && Display.queued.size()==1,"queue failed to retry/coalesce after scheduling OOM");
  resetQueue();
  Vector broken=new Vector(){int additions;public synchronized void addElement(Object o){if(++additions==2)throw new OutOfMemoryError("second pair element");super.addElement(o);}};
  field(MainThread.class,"mainThreadTasks").set(null,broken);
  try{MainThread.showTime();}catch(OutOfMemoryError expected){}
  check(broken.isEmpty(),"OOM left a half event");
  ((Runnable)field(MainThread.class,"_this").get(null)).run();
  resetQueue();
  Display.fail=true;Runnable nothing=new Runnable(){public void run(){}};
  for(int i=0;i<64;i++)MainThread.runSerially(nothing);
  final CountDownLatch finished=new CountDownLatch(1);
  Thread producer=new Thread(){public void run(){MainThread.showTime();finished.countDown();}};
  producer.start();Thread.sleep(30);check(finished.getCount()==1,"queue cap not enforced");
  Display.fail=false;
  long limit=System.currentTimeMillis()+2000;
  while(Display.queued.isEmpty()&&System.currentTimeMillis()<limit)Thread.sleep(5);
  check(!Display.queued.isEmpty(),"full queue failed to retry scheduling");
  drain();check(finished.await(2,TimeUnit.SECONDS),"bounded producer never resumed");drain();
  resetQueue();
  final int run=field(MainThread.class,"TYPE_RUN").getInt(null);
  MainThread.addMainThreadTask(run,nothing,new byte[12000]);
  final CountDownLatch bytesDone=new CountDownLatch(1);
  Thread bytesProducer=new Thread(){public void run(){MainThread.addMainThreadTask(run,new Runnable(){public void run(){}},new byte[12000]);bytesDone.countDown();}};
  bytesProducer.start();Thread.sleep(30);
  check(bytesDone.getCount()==1&&field(MainThread.class,"queuedBytes").getInt(null)==12000,"queued payload budget not enforced");
  drain();check(bytesDone.await(2,TimeUnit.SECONDS),"payload producer did not resume");drain();
  check(field(MainThread.class,"queuedBytes").getInt(null)==0,"payload budget retained after drain");resetQueue();
 }
 static Object settings()throws Exception{
  Class c=Class.forName("jimm.OptionsForm");
  Object obj=((sun.misc.Unsafe)field(sun.misc.Unsafe.class,"theUnsafe").get(null)).allocateInstance(c);
  field(c,"optionsForm").set(obj,new Form("settings"));return obj;
 }
 static void options()throws Exception{
  Object o=settings();Class c=o.getClass();
  call(c,"showInterfaceOptions",new Class[0],o);
  Object previous=field(c,"choiceContactList").get(o);Form form=(Form)field(c,"optionsForm").get(o);
  int before=form.items.size();call(c,"clearForm",new Class[0],o);
  call(c,"showMediaOptions",new Class[0],o);
  check(field(c,"choiceContactList").get(o)==null && !form.items.contains(previous),"settings retained previous widgets");
  o=settings();c=o.getClass();call(c,"showNetworkOptions",new Class[0],o);
  ((TextField)field(c,"srvHostTextField").get(o)).setString("changed.example");
  ((TextField)field(c,"connAliveIntervTextField").get(o)).setString("0");
  String oldHost=Options.getString(Options.OPTION_SRV_HOST);
  try{call(c,"readNetworkOptions",new Class[0],o);throw new AssertionError("zero interval accepted");}catch(InvocationTargetException expected){check(expected.getCause() instanceof IllegalArgumentException,"wrong numeric error");}
  check(oldHost.equals(Options.getString(Options.OPTION_SRV_HOST)),"invalid form partially saved");
  ((TextField)field(c,"connAliveIntervTextField").get(o)).setString("120");
  ((TextField)field(c,"srvHostTextField").get(o)).setString("partially.changed.example");
  ((TextField)field(c,"reconnectNumberTextField").get(o)).setString("");
  try{call(c,"readNetworkOptions",new Class[0],o);throw new AssertionError("empty retries accepted");}catch(InvocationTargetException expected){}
  check(oldHost.equals(Options.getString(Options.OPTION_SRV_HOST)),"empty retries partially saved host");
 }
 static final class Previous implements JimmScreen {
  final Displayable screen=new Form("previous");int returns;
  public void activate(){returns++;Jimm.display.setCurrent(screen);}
  public boolean isScreenActive(){return Jimm.display.getCurrent()==screen;}
 }
 static ChatListViewer viewer(Previous back)throws Exception{
  Constructor c=ChatListViewer.class.getDeclaredConstructor(JimmScreen.class);c.setAccessible(true);
  ChatListViewer v=(ChatListViewer)c.newInstance(back);
  field(ChatListViewer.class,"current").set(null,v);
  field(ChatListViewer.class,"list").set(v,new TextList("chats"));return v;
 }
 static void drain()throws Exception{
  int guard=0;while(!Display.queued.isEmpty()){if(++guard>100)throw new AssertionError("UI loop");Runnable r=(Runnable)Display.queued.elementAt(0);Display.queued.removeElementAt(0);r.run();}
 }
 static byte[] rows(int count)throws Exception{
  ByteArrayOutputStream b=new ByteArrayOutputStream();DataOutputStream out=new DataOutputStream(b);
  for(int i=0;i<count;i++){byte[] name=("chat "+i).getBytes("UTF-8");out.writeInt(1000001+i);out.writeByte(0);out.writeShort(1);out.writeShort(name.length);out.write(name);}return b.toByteArray();
 }
 static void chatList()throws Exception{
  final Previous back=new Previous();final ChatListViewer v=viewer(back);v.onBart(rows(80));drain();
  check(((Vector)field(ChatListViewer.class,"uins").get(v)).size()==20,"all chats not bounded");
  check(field(ChatListViewer.class,"hasMore").getBoolean(v),"legacy list lost remaining pages");
  field(Icq.class,"reqAction").set(null,new Vector());field(Icq.class,"connected").setBoolean(null,true);
  call(ChatListViewer.class,"open",new Class[0],v);
  RequestBartAction request=(RequestBartAction)((Vector)field(Icq.class,"reqAction").get(null)).lastElement();
  new SplashCanvas();Options.setString(Options.OPTION_LOCK_PIN,"1234");field(SplashCanvas.class,"isLocked").setBoolean(null,true);SplashCanvas.show();
  ((RequestBartAction.Listener)field(RequestBartAction.class,"listener").get(request)).onBart(new byte[]{0});drain();
  check(SplashCanvas.pinLocked() && Jimm.display.getCurrent()!=back.screen,"chat opening bypassed PIN");
  field(SplashCanvas.class,"isLocked").setBoolean(null,false);
  final ChatListViewer cancelling=viewer(back);
  Font.beforeMeasure=new Runnable(){public void run(){cancelling.commandAction(JimmUI.cmdBack,null);}};
  cancelling.onBart(rows(80));drain();
  check(field(ChatListViewer.class,"current").get(null)==null && field(ChatListViewer.class,"list").get(cancelling)==null,"Back left parsing live");
 }
 static void chats()throws Exception{
  field(ChatHistory.class,"historyTable").set(null,new Hashtable());field(ChatHistory.class,"historyUins").set(null,new Vector());
  new ContactList();field(Icq.class,"connected").setBoolean(null,false);
  Vector items=new Vector();field(ContactList.class,"cItems").set(null,items);
  for(int i=0;i<20;i++){
   ContactItem c=new ContactItem(1000001+i,1,String.valueOf(1000001+i),"contact",false,true);
   c.setBooleanValue(ContactItem.CONTACTITEM_B_PLMESSAGES,true);items.addElement(c);ChatHistory.openChat(c);c.setBooleanValue(ContactItem.CONTACTITEM_B_PLMESSAGES,true);
  }
  check(((Hashtable)field(ChatHistory.class,"historyTable").get(null)).size()==12,"unread chats bypassed cache limit");
  for(int i=0;i<items.size();i++)check(((ContactItem)items.elementAt(i)).isContainingUnreadMessages(),"eviction lost unread flag");
  ContactListGroupItem parent=new ContactListGroupItem(-1,"Telegram"),child=new ContactListGroupItem(1,"Telegram/forum");
  child.setParent(parent);child.changeMessCount(1);
  check(child.getMessCount()==1 && parent.getMessCount()==1,"nested unread not propagated");child.setMessCount(0);check(parent.getMessCount()==0,"parent unread not cleared");
  ChatHistory.currentChat=null;Options.setBoolean(Options.OPTION_CREEPING_LINE,false);
  TextList list=new TextList("normal");list.activate(Jimm.display);field(JimmUI.class,"flashTimerTask").set(null,null);
  JimmUI.showCreepingLine(list,"message",(ContactItem)items.elementAt(0));
  check(field(JimmUI.class,"flashTimerTask").get(null)==null,"disabled creeping task");
  com.sun.management.ThreadMXBean meter=(com.sun.management.ThreadMXBean)java.lang.management.ManagementFactory.getThreadMXBean();
  meter.setThreadAllocatedMemoryEnabled(true);long id=Thread.currentThread().getId();
  String longText=new String(new char[900]).replace('\0','Ж');ContactItem contact=(ContactItem)items.elementAt(0);
  for(int i=0;i<100;i++)JimmUI.showCreepingLine(list,longText,contact);
  long start=meter.getThreadAllocatedBytes(id);for(int i=0;i<1000;i++)JimmUI.showCreepingLine(list,longText,contact);
  check((meter.getThreadAllocatedBytes(id)-start)/1000<128,"disabled creeping copied text");
 }
 static void timer()throws Exception{
  field(Icq.class,"thread").set(null,new Thread());
  final CountDownLatch attempted=new CountDownLatch(1),survived=new CountDownLatch(1);
  Connection socket=new Connection(){public void forceDisconnect(){}public void sendPacket(Packet p){attempted.countDown();throw new OutOfMemoryError("ping serialization");}};
  field(Icq.class,"c").set(null,socket);field(Icq.class,"connected").setBoolean(null,true);Icq.resetPingWatch();
  Options.setBoolean(Options.OPTION_KEEP_CONN_ALIVE,true);
  Options.setBoolean(Options.OPTION_RECONNECT,false);
  java.util.Timer t=new java.util.Timer(true);t.schedule(new TimerTasks(TimerTasks.ICQ_KEEPALIVE,(Thread)field(Icq.class,"thread").get(null),socket),0,1000);
  if(!attempted.await(2,TimeUnit.SECONDS))throw new AssertionError("ping not attempted");
  t.schedule(new java.util.TimerTask(){public void run(){survived.countDown();}},50);
  check(survived.await(2,TimeUnit.SECONDS),"ping OOM killed shared timer");
  check(!Icq.isConnected(),"ping OOM left client online");t.cancel();
  resetQueue();final CountDownLatch blocked=new CountDownLatch(1),resume=new CountDownLatch(1);
  Jimm.getTimerRef().schedule(new java.util.TimerTask(){public void run(){blocked.countDown();try{resume.await(3,TimeUnit.SECONDS);}catch(InterruptedException ignore){}}},0);
  check(blocked.await(2,TimeUnit.SECONDS),"network timer not blocked");JimmUI.startTaskForTimeString();
  long end=System.currentTimeMillis()+2000;while(Display.queued.isEmpty()&&System.currentTimeMillis()<end)Thread.sleep(5);
  check(!Display.queued.isEmpty(),"blocked network timer stopped UI/autolock clock");resume.countDown();drain();
 }
 static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}

 public static void main(String[] args){
  try{field(Options.class,"options").set(null,new Hashtable());call(Options.class,"setDefaults",new Class[0],null);
   Constructor c=MainThread.class.getDeclaredConstructor();c.setAccessible(true);c.newInstance();new Icq();
   queue();options();chatList();chats();timer();System.out.println("PASS: queue OOM, widgets, numeric forms, paged chat cancellation/PIN, cache, groups, idle allocations and timer recovery");
  }catch(Throwable e){e.printStackTrace();System.exit(1);}System.exit(0);
 }
}
