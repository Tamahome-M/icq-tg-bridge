package jimm;

import java.lang.reflect.*;
import java.util.*;
import java.io.*;
import java.util.concurrent.TimeUnit;
import javax.microedition.lcdui.*;
import javax.microedition.media.Manager;
import jimm.comm.*;
import jimm.comm.connections.Connection;
import DrawControls.*;

public class ClientAuditFixesTest {
 static Field f(Class c,String s)throws Exception{Field f=c.getDeclaredField(s);f.setAccessible(true);return f;}
 static Object call(Class c,Object o,String n,Class[] ts,Object...args)throws Exception{Method m=c.getDeclaredMethod(n,ts);m.setAccessible(true);return m.invoke(o,args);}
 static void check(boolean x,String s){if(!x)throw new AssertionError(s);}
 static void drain(){Display.flush();}
 static class Previous implements JimmScreen {
  int returns;final Displayable screen=new Form("previous");
  public void activate(){returns++;Jimm.display.setCurrent(screen);}public boolean isScreenActive(){return Jimm.display.getCurrent()==screen;}
 }
 static class FailThreads extends SecurityManager {
  int attempts;
  public void checkPermission(java.security.Permission p){}
  public void checkAccess(ThreadGroup group){attempts++;throw new OutOfMemoryError("native thread allocation");}
 }
 static class Wire extends Connection {
  Vector packets=new Vector();public void forceDisconnect(){}public void sendPacket(Packet packet){packets.addElement(packet);}
 }
 static Vector requests()throws Exception{return (Vector)f(Icq.class,"reqAction").get(null);}
 static void connect()throws Exception{
  f(Icq.class,"connected").setBoolean(null,true);f(Icq.class,"thread").set(null,new Thread());
  f(Icq.class,"c").set(null,new Wire());f(Icq.class,"reqAction").set(null,new Vector());
 }
 static void draft()throws Exception{
  f(Icq.class,"connected").setBoolean(null,false);ContactItem contact=new ContactItem(1,1,"1000001","Test",false,true);Vector items=new Vector();items.addElement(contact);f(ContactList.class,"cItems").set(null,items);
  JimmUI.writeMessage(contact,"valuable draft");TextBox box=(TextBox)Jimm.display.getCurrent();box.listener.commandAction(JimmUI.cmdSend,box);
  check(JimmException.errors==1,"offline send wasn't rejected");check(box.getString().equals("valuable draft")&&Jimm.display.getCurrent()==box,"rejected send erased draft or closed editor");
  ChatTextList chat=ChatHistory.getChatHistoryAt("1000001");check(chat==null||chat.messageCount()==0,"rejected send created a sent bubble");
  connect();box.listener.commandAction(JimmUI.cmdSend,box);check(box.getString().length()==0,"accepted send retained duplicate draft");
  int sends=0;for(Object action:requests())if(action instanceof SendMessageAction)sends++;
  check(sends==1,"retry did not enqueue exactly one message");check(ChatHistory.getChatHistoryAt("1000001").messageCount()==1,"accepted message not displayed");
  System.out.println("PASS: rejected send retains editor/draft; retry queues and displays one message");
 }
 static HistoryViewer history()throws Exception{
  Constructor c=HistoryViewer.class.getDeclaredConstructor(JimmScreen.class,String.class,String.class);c.setAccessible(true);
  HistoryViewer h=(HistoryViewer)c.newInstance(new Previous(),"1000001","test");f(HistoryViewer.class,"current").set(null,h);f(HistoryViewer.class,"list").set(h,new TextList("history"));return h;
 }
 static void historyThread()throws Exception{
  HistoryViewer h=history();f(HistoryViewer.class,"loading").setBoolean(h,true);FailThreads fail=new FailThreads();System.setSecurityManager(fail);
  try{h.onBart(new byte[0]);}finally{System.setSecurityManager(null);}
  check(fail.attempts>0&&!f(HistoryViewer.class,"loading").getBoolean(h),"failed worker remains loading");
  h.activate();h.onBart(new byte[]{(byte)255,0});long until=System.currentTimeMillis()+2000;
  while(!f(HistoryViewer.class,"exhausted").getBoolean(h)&&System.currentTimeMillis()<until)Thread.sleep(5);
  check(f(HistoryViewer.class,"exhausted").getBoolean(h),"history cannot retry after allocation failure");h.commandAction(JimmUI.cmdBack,null);
  System.out.println("PASS: failed history worker clears loading and permits a successful retry");
 }
 static void reconnectThread()throws Exception{
  f(Threads.class,"reconnectPending").setBoolean(null,false);f(Icq.class,"connected").setBoolean(null,false);f(Icq.class,"thread").set(null,null);Icq.setDisconnected(false);Options.setBoolean(Options.OPTION_RECONNECT,true);
  FailThreads fail=new FailThreads();System.setSecurityManager(fail);
  try{
   Threads.reconnect(60000);check(!f(Threads.class,"reconnectPending").getBoolean(null),"failed start reserves reconnect forever");
   int before=fail.attempts;Threads.checkReconnect();check(fail.attempts==before,"memory retry is a busy loop");
   f(Threads.class,"retryAt").setLong(null,System.currentTimeMillis()-1);Threads.checkReconnect();check(fail.attempts>before,"clock did not retry after the deadline");
   check(!f(Threads.class,"reconnectPending").getBoolean(null),"second failure reserved gate");
  }finally{System.setSecurityManager(null);}
  Icq.setDisconnected(true);f(Threads.class,"retryAt").setLong(null,1);Threads.checkReconnect();check(f(Threads.class,"retryAt").getLong(null)==0,"manual disconnect leaves automatic retry");
  Options.setBoolean(Options.OPTION_RECONNECT,false);System.out.println("PASS: native thread failure releases reconnect gate, retries after 60s and respects manual disconnect");
 }
 static void historyCancel()throws Exception{
  connect();HistoryViewer.show("1000001","test",new Previous());HistoryViewer h=(HistoryViewer)f(HistoryViewer.class,"current").get(null);RequestBartAction request=(RequestBartAction)requests().lastElement();
  f(RequestBartAction.class,"parts").set(request,new byte[512]);h.commandAction(JimmUI.cmdBack,null);drain();
  check(f(HistoryViewer.class,"list").get(h)==null&&!requests().contains(request),"Back leaves queued history alive");
  check(f(RequestBartAction.class,"listener").get(request)==null&&f(RequestBartAction.class,"parts").get(request)==null,"cancel retains closed viewer/multipart data");
  h.onBart(new byte[0]);h.activate();check(f(HistoryViewer.class,"current").get(null)==null,"late response resurrected closed history");
  System.out.println("PASS: Back cancels history, releases multipart data and ignores obsolete replies");
 }
 static byte[] page(int first)throws Exception{
  ByteArrayOutputStream b=new ByteArrayOutputStream();DataOutputStream o=new DataOutputStream(b);o.writeByte('C');o.writeByte('P');o.writeByte('1');o.writeByte(1);
  for(int i=0;i<20;i++){byte[] text=("chat"+(first+i)).getBytes("UTF-8");o.writeInt(1000001+first+i);o.writeByte(0);o.writeShort(1);o.writeShort(text.length);o.write(text);}return b.toByteArray();
 }
 static int requestOffset()throws Exception{return Util.getWord((byte[])f(RequestBartAction.class,"token").get(requests().lastElement()),2);}
 static void chatListError()throws Exception{
  connect();Constructor c=ChatListViewer.class.getDeclaredConstructor(JimmScreen.class);c.setAccessible(true);ChatListViewer v=(ChatListViewer)c.newInstance(new Previous());f(ChatListViewer.class,"current").set(null,v);f(ChatListViewer.class,"list").set(v,new TextList("chats"));v.onBart(page(0));drain();
  TextList old=(TextList)f(ChatListViewer.class,"list").get(v);Vector names=(Vector)f(ChatListViewer.class,"uins").get(v);Command more=(Command)f(ChatListViewer.class,"more").get(v);
  v.commandAction(more,null);check(requestOffset()==20,"next page offset wrong");v.onBartError("timeout");drain();
  check(f(ChatListViewer.class,"list").get(v)==old&&f(ChatListViewer.class,"uins").get(v)==names&&names.size()==20,"timeout destroyed previous page");
  check(f(ChatListViewer.class,"hasMore").getBoolean(v),"timeout removed retry");v.commandAction(more,null);check(requestOffset()==20,"retry skipped failed page");
  Font.beforeMeasure=new Runnable(){public void run(){throw new OutOfMemoryError("page");}};v.onBart(page(20));drain();
  check(f(ChatListViewer.class,"list").get(v)==old&&names.size()==20,"layout failure destroyed old page");v.commandAction(more,null);check(requestOffset()==20,"layout retry skipped page");
  v.onBart(page(20));drain();check(f(ChatListViewer.class,"pageOffset").getInt(v)==20,"accepted page did not advance");v.commandAction(more,null);check(requestOffset()==40,"next page repeated previous page");v.commandAction(JimmUI.cmdBack,null);drain();requests().clear();
  System.out.println("PASS: chat-list timeout/OOM preserve rows and retry the same offset; success advances once");
 }
 static void waitStopped(VoiceRecorder r)throws Exception{
  long end=System.currentTimeMillis()+2000;while(f(VoiceRecorder.class,"recording").getBoolean(r)&&System.currentTimeMillis()<end)Thread.sleep(5);
  check(!f(VoiceRecorder.class,"recording").getBoolean(r),"microphone never stopped");
 }
 static VoiceRecorder microphone(Previous back)throws Exception{VoiceRecorder.show("1000001",back);return (VoiceRecorder)f(VoiceRecorder.class,"current").get(null);}
 static void microphoneFailures()throws Exception{
  for(int failure:new int[]{1,2,3,4}){
   Manager.created.clear();Manager.capture=failure!=1;Manager.setupFailure=failure;VoiceRecorder r=microphone(new Previous());call(VoiceRecorder.class,r,"start",new Class[0]);waitStopped(r);
   check(Manager.created.size()==1,"microphone not created");Manager.Fake p=(Manager.Fake)Manager.created.firstElement();check(p.closes==1&&f(VoiceRecorder.class,"player").get(r)==null,"setup failure leaked microphone: "+failure);r.commandAction(JimmUI.cmdBack,null);drain();check(p.closes==1,"Back closed microphone twice");
  }
  Manager.setupFailure=0;Manager.capture=true;
  Manager.Gate gate=new Manager.Gate();Manager.gate=gate;Manager.stage=1;Previous back=new Previous();VoiceRecorder r=microphone(back);call(VoiceRecorder.class,r,"start",new Class[0]);check(gate.entered.await(2,TimeUnit.SECONDS),"open not blocked");r.commandAction(JimmUI.cmdBack,null);drain();gate.release.countDown();Manager.worker.join(2000);check(((Manager.Fake)Manager.created.lastElement()).closes==1,"microphone opened after Back was leaked");check(Jimm.display.getCurrent()==back.screen,"late setup failure replaced Back screen");
  connect();gate=new Manager.Gate();Manager.gate=gate;Manager.stage=5;Manager.recorded=new byte[16001];Arrays.fill(Manager.recorded,(byte)23);Manager.commits=0;r=microphone(new Previous());call(VoiceRecorder.class,r,"start",new Class[0]);check(gate.entered.await(2,TimeUnit.SECONDS),"setup not blocked");call(VoiceRecorder.class,r,"stopAndSend",new Class[0]);call(VoiceRecorder.class,r,"stopAndSend",new Class[0]);gate.release.countDown();Manager.worker.join(2000);
  Wire wire=(Wire)f(Icq.class,"c").get(null);long until=System.currentTimeMillis()+5000;while(wire.packets.size()<3&&System.currentTimeMillis()<until)Thread.sleep(10);
  check(wire.packets.size()==3&&Manager.commits==1,"early/repeated Stop lost or duplicated recording: packets="+wire.packets.size()+", commits="+Manager.commits+", status="+f(VoiceRecorder.class,"status").get(r));for(Object raw:wire.packets)check(((SnacPacket)raw).getCommand()==4,"voice stream used wrong subtype");
  check(f(VoiceRecorder.class,"player").get(r)==null&&f(VoiceRecorder.class,"sink").get(r)==null,"sent voice retains recorder resources");r.commandAction(JimmUI.cmdBack,null);drain();
  System.out.println("PASS: all microphone setup failures close Player; Back during open and early/double Stop preserve ownership");
 }
 static void recordingBuffer()throws Exception{
  Class type=Class.forName("jimm.VoiceRecorder$RecordingBuffer");Constructor c=type.getDeclaredConstructor(int.class);c.setAccessible(true);OutputStream buffer=(OutputStream)c.newInstance(5000);byte[] source=new byte[5100];for(int i=0;i<source.length;i++)source[i]=(byte)(i*13);
  try{buffer.write(source);throw new AssertionError("buffer unbounded");}catch(IOException expected){}
  check(((Integer)call(type,buffer,"size",new Class[0])).intValue()==5000,"write limit exceeded");Vector chunks=(Vector)f(type,"chunks").get(buffer);check(chunks.size()==3,"unexpected recording copies");Object first=chunks.firstElement();InputStream stream=(InputStream)call(type,buffer,"input",new Class[0]);check(chunks.firstElement()==first,"sealing copied recording");byte[] block=new byte[2048];check(stream.read(block)==2048&&chunks.firstElement()==null,"uploaded chunk was retained");check(Arrays.equals(block,Arrays.copyOf(source,2048)),"voice byte order changed");ByteArrayOutputStream tail=new ByteArrayOutputStream();int got;while((got=stream.read(block))>=0)tail.write(block,0,got);check(Arrays.equals(tail.toByteArray(),Arrays.copyOfRange(source,2048,5000)),"chunk boundary lost bytes");stream.close();check(chunks.isEmpty(),"closed recording retains chunks");
  System.out.println("PASS: voice buffer enforces limit during write, streams identical bytes without a full copy and frees consumed chunks");
 }
 static class CountVector extends Vector{int visits;public synchronized Object elementAt(int n){visits++;return super.elementAt(n);}}
 static void lookup()throws Exception{
  CountVector contacts=new CountVector();for(int i=0;i<125;i++)contacts.addElement(new ContactItem(i+1,1,String.valueOf(1000001+i),"chat",false,true));f(ContactList.class,"cItems").set(null,contacts);
  for(int i=0;i<125;i++)check(ContactList.getItembyUIN(String.valueOf(1000001+i))==contacts.get(i),"lookup reordered contacts");
  check(contacts.visits<250,"lookup still scans roster for each status");System.out.println("METRIC contact lookup: "+contacts.visits+" vector visits vs 7875 in 1.15");
  ContactItem last=ContactList.createTempContact("1000999");check(ContactList.getItembyUIN("1000999")==last,"temporary addition invisible to index");ContactList.removeContactItem(last);check(ContactList.getItembyUIN("1000999")==null,"deleted contact retained by index");
  ContactItem old=(ContactItem)contacts.get(5);ContactList.removeContactItem(old);ContactItem replacement=new ContactItem(4,1,"1000006","replacement",false,false);ContactList.addContactItem(replacement);check(ContactList.getItembyUIN("1000006")==replacement,"same-size roster replacement reused stale index");check(ContactList.getItembyUIN("?")==null,"invalid UIN failed");
  System.out.println("PASS: indexed lookups preserve order and follow temporary addition, removal and same-size replacement");
 }
 static void quoteDeadline()throws Exception{
  f(NativeQuote.class,"selectedUin").set(null,"1000001");f(NativeQuote.class,"selectedRef").set(null,new byte[8]);Constructor ctor=NativeQuote.class.getDeclaredConstructor(String.class);ctor.setAccessible(true);NativeQuote q=(NativeQuote)ctor.newInstance("1000002");f(NativeQuote.class,"started").setLong(q,System.currentTimeMillis()-61000);Vector actions=new Vector();actions.addElement(q);f(Icq.class,"actAction").set(null,actions);
  long delay=((Long)call(Icq.class,null,"nextActionDelay",new Class[0])).longValue();check(delay<=1,"overdue quote leaves idle loop asleep");q.isError();check(q.isCompleted(),"quote did not time out");drain();actions.clear();
  System.out.println("PASS: quote timeout wakes the idle action loop without incoming traffic");
 }
 static void searchWire(String file)throws Exception{
  connect();Previous back=new Previous();Search search=new Search(back);SearchAction action=new SearchAction(search,"1000001",true);call(SearchAction.class,action,"init",new Class[0]);
  ToIcqSrvPacket query=(ToIcqSrvPacket)((Wire)f(Icq.class,"c").get(null)).packets.lastElement();byte[] raw=query.getData();
  check(Util.getWord(raw,0)==0x5f05&&Util.getWord(raw,2)==SearchAction.TLV_TYPE_UIN&&Util.getDWord(raw,6,false)==1000001,"UIN lookup packet changed");
  byte[] reply=java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(file));
  FromIcqSrvPacket packet=new FromIcqSrvPacket(0,0,0,2,"100500",0x07da,new byte[0],reply);
  check(((Boolean)call(SearchAction.class,action,"forward",new Class[]{Packet.class},packet)).booleanValue()&&action.isCompleted(),"bridge lookup result not consumed/completed");
  action.onEvent(Action.ON_COMPLETE);drain();TextList result=(TextList)f(Search.class,"results").get(search);
  check(result.getCurrText(0,false).indexOf("Чат Ceph")>=0,"bridge nickname decoding changed");
  check(((Vector)f(Search.class,"found").get(search)).size()==1,"single UIN lookup returned wrong result count");
  System.out.println("PASS: real bridge search bytes match UIN lookup framing and compact result decoding");
 }
 static void searchCancel()throws Exception{
  connect();Previous back=new Previous();Search search=new Search(back);SearchAction action=new SearchAction(search,"1000001",true);action.onEvent(Action.ON_CANCEL);drain();check(Jimm.display.getCurrent()==back.screen&&back.returns==1,"cancel reopened legacy search filters");action.onEvent(Action.ON_COMPLETE);drain();check(back.returns==1,"cancelled result reopened UI");
  search=new Search(back);search.show();Form query=(Form)Jimm.display.getCurrent();check(query.items.size()==1,"search still creates seven filters");search.addResult("1000001","Found",false);search.finished(Action.ON_COMPLETE);drain();TextList results=(TextList)f(Search.class,"results").get(search);check(results.getCurrText(0,false).indexOf("Found")>=0,"compact result missing");Jimm.display.setCurrent(new Form("contact info"));JimmUI.backToLastScreen();
  check(((Vector)f(JimmUI.class,"lastScreens").get(null)).contains(search)&&results.isActive(),"Back from contact info lost search results");
  search.commandAction(JimmUI.cmdBack,null);check(Jimm.display.getCurrent()==query,"Back from name results lost query");
  search.commandAction(JimmUI.cmdBack,null);drain();check(!((Vector)f(JimmUI.class,"lastScreens").get(null)).contains(search),"closed search retained its result UI");
  System.out.println("PASS: UIN lookup cancellation returns to caller; compact name search retains results and query navigation");
 }
 public static void main(String[]args)throws Exception{
  f(Options.class,"options").set(null,new Hashtable());call(Options.class,null,"setDefaults",new Class[0]);Options.setBoolean(Options.OPTION_RECONNECT,false);Options.setBoolean(Options.OPTION_USE_SMILES,false);Options.setInt(Options.OPTION_TYPING_MODE,0);
  Constructor ui=JimmUI.class.getDeclaredConstructor();ui.setAccessible(true);ui.newInstance();Constructor mt=MainThread.class.getDeclaredConstructor();mt.setAccessible(true);mt.newInstance();new Icq();new ContactList();new ChatHistory();new SplashCanvas();
  try { draft();historyThread();reconnectThread();historyCancel();chatListError();microphoneFailures();recordingBuffer();lookup();quoteDeadline();searchWire(args[0]);searchCancel(); }
  catch(Throwable failure){failure.printStackTrace();System.exit(1);}System.exit(0);
 }
}
