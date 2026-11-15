package jimm.comm;

import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import jimm.*;
import jimm.comm.connections.*;

/** Incoming BOS traffic must not authenticate, fail or advance the BART handshake. */
public final class BartHandshakeTest {
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static Field field(Class type,String name)throws Exception{Field f=type.getDeclaredField(name);f.setAccessible(true);return f;}
 static final class Sink implements RequestBartAction.Listener {public void onBart(byte[] data){}}
 static Action action(boolean icon){
  return icon?new RequestBuddyIconAction("1000001",new byte[16]):
   new RequestBartAction("1000001",RequestBartAction.BART_HISTORY,new byte[16],new Sink());
 }
 static int state(Action action)throws Exception{return field(action.getClass(),"state").getInt(action);}
 static void oldActivity(Action action)throws Exception{
  Field f=field(action.getClass(),"lastActivity");
  if(f.getType()==Long.TYPE)f.setLong(action,1000);else f.set(action,new Date(1000));
 }
 static byte[] body(byte[][] tlvs)throws Exception{
  ByteArrayOutputStream out=new ByteArrayOutputStream();for(byte[] part:tlvs)out.write(part);return out.toByteArray();
 }
 static byte[] tlv(int type,byte[] value)throws Exception{
  ByteArrayOutputStream out=new ByteArrayOutputStream();out.write(type>>8);out.write(type);
  out.write(value.length>>8);out.write(value.length);out.write(value);return out.toByteArray();
 }
 static final byte[] COOKIE={11,22,33,44};
 static byte[] redirect(boolean extra,boolean service)throws Exception{return redirect(extra,service,"service.test:6180");}
 static byte[] redirect(boolean extra,boolean service,String address)throws Exception{
  Vector parts=new Vector();
  parts.addElement(tlv(6,COOKIE));
  if(extra)parts.addElement(tlv(0x9999,new byte[]{7,8,9}));
  parts.addElement(tlv(5,address.getBytes("US-ASCII")));
  if(service)parts.addElement(tlv(13,new byte[]{0,16}));
  byte[][] all=new byte[parts.size()][];parts.copyInto(all);return body(all);
 }
 static SnacPacket snac(int family,int command,byte[] bytes){return new SnacPacket(family,command,0x00010004,new byte[0],bytes);}
 static void prepare(Action action)throws Exception{
  SOCKETConnection main=new SOCKETConnection(),bart=new SOCKETConnection();main.connect("bos");bart.connect("service");
  Icq.c=main;Icq.bartC=bart;field(Icq.class,"bartReady").setBoolean(null,false);
  SOCKETConnection.packets.clear();action.init();
  check(state(action)==0 && SOCKETConnection.packets.size()==1,"test did not enter BART redirect wait");
  SnacPacket request=(SnacPacket)SOCKETConnection.packets.elementAt(0);
  check(request.getFamily()==1 && request.getCommand()==4 && Util.getWord(request.getDataRef(),0)==16,"service request malformed");
 }
 static void foreign(Action action)throws Exception{
  oldActivity(action);long deadline=action.getDeadline();int before=SOCKETConnection.packets.size(),priorState=state(action);
  for(int[] type:new int[][]{{3,11},{3,12},{4,7},{4,20},{1,15},{1,1},{16,7}}){
   check(!action.forward(snac(type[0],type[1],new byte[0])),"BART swallowed unrelated SNAC "+type[0]+"/"+type[1]);
   check(state(action)==priorState && action.getDeadline()==deadline,"unrelated SNAC advances handshake or extends timeout");
   check(!field(action.getClass(),"active").getBoolean(action),"ignored packet leaves action busy and disables timeout");
   check(SOCKETConnection.packets.size()==before,"unrelated SNAC sends cookie/ready/media request");
  }
 }
 static void success(boolean icon,boolean extra,boolean service)throws Exception{
  Action action=action(icon);prepare(action);foreign(action);
  long deadlineBefore=action.getDeadline();int sentBefore=SOCKETConnection.packets.size();
  byte[] wrongService=body(new byte[][]{tlv(13,new byte[]{0,2}),tlv(5,"other.test:99".getBytes("US-ASCII")),tlv(6,new byte[]{55})});
  check(!action.forward(snac(1,5,wrongService)),"redirect for another service swallowed");
  check(state(action)==0 && action.getDeadline()==deadlineBefore && SOCKETConnection.packets.size()==sentBefore,"foreign service redirect advances handshake");
  check(field(action.getClass(),"clicookie").get(action)==null,"foreign service redirect installs another authentication cookie");
  check(action.forward(snac(1,5,redirect(extra,service))),"valid redirect ignored");
  check(state(action)==1,"redirect did not attach to live service socket");
  oldActivity(action);long deadline=action.getDeadline();int sent=SOCKETConnection.packets.size();
  check(!action.forward(new ConnectPacket(new byte[]{9})),"cookie packet accepted as service hello");
  check(!action.forward(new ConnectPacket("1000001","valid")),"identity packet accepted as service hello");
  check(state(action)==1 && action.getDeadline()==deadline && SOCKETConnection.packets.size()==sent,"non-hello connect packet advances handshake");
  check(action.forward(new ConnectPacket()),"service hello not accepted");
  check(state(action)==2,"service hello did not send cookie");
  check(SOCKETConnection.packets.lastElement() instanceof ConnectPacket,"service cookie missing");
  foreign(action);
  check(action.forward(snac(1,3,new byte[]{0,16})),"service-ready not accepted");
  check(state(action)==4 && SOCKETConnection.packets.size()==4,"service handshake fails to send exactly one ready and one request");
  SnacPacket request=(SnacPacket)SOCKETConnection.packets.lastElement();
  check(request.getFamily()==16 && request.getCommand()==6,"wrong service request after handshake");
  byte[] data=request.getDataRef();int length=Util.getByte(data,0);
  check(length==7 && Util.byteArrayToString(data,1,length).equals("1000001"),"history target UIN changed during redirect");
  check(Util.getWord(data,length+2)==(icon?1:RequestBartAction.BART_HISTORY),"history/avatar type changed during redirect");
  check(Icq.bartUsable(),"validated service handshake not reusable");
 }
 static void addresses(boolean icon)throws Exception{
  for(String address:new String[]{"service.test:6180","service.test"}){
   Action action=action(icon);prepare(action);Icq.disconnectBart(true);
   check(action.forward(snac(1,5,redirect(false,true,address))),"address redirect ignored");
   long until=System.currentTimeMillis()+2000;
   while(state(action)==6 && System.currentTimeMillis()<until)Thread.sleep(5);
   check(state(action)==1,"redirect socket did not connect");
   check(SOCKETConnection.lastHost.equals(address.indexOf(':')<0?address+":5190":address),"redirect duplicates or discards server port: "+SOCKETConnection.lastHost);
   Icq.disconnectBart(true);
  }
 }
 static void malformed(boolean icon)throws Exception{
  byte[][] invalid={
   new byte[0],new byte[]{0,5,0},new byte[]{0,6,0,8,1},
   tlv(5,"service.test".getBytes("US-ASCII")),tlv(6,COOKIE),
   body(new byte[][]{tlv(5,"service.test".getBytes("US-ASCII")),tlv(6,new byte[0])}),
   body(new byte[][]{tlv(5,new byte[0]),tlv(6,COOKIE)}),
   body(new byte[][]{redirect(false,true),new byte[]{0,8,0,2,1}}),
   body(new byte[][]{redirect(false,false),tlv(13,new byte[]{16})})
  };
  for(byte[] bytes:invalid){
   Action action=action(icon);prepare(action);int sent=SOCKETConnection.packets.size(),opened=SOCKETConnection.opened;
   try{action.forward(snac(1,5,bytes));throw new AssertionError("malformed redirect accepted");}
   catch(JimmException error){check(error.getErrCode()==133,"malformed service redirect reported as UIN/password error: "+error.getFullErrCode());}
   check(state(action)==-1,"malformed redirect stays pending");
   check(SOCKETConnection.packets.size()==sent && SOCKETConnection.opened==opened,"malformed redirect opens socket or sends authentication");
  }
 }
 public static void main(String[] args)throws Exception{
  try{
   new Icq();field(Icq.class,"thread").set(null,new Thread());
   for(boolean icon:new boolean[]{false,true}){
    success(icon,false,true);success(icon,true,true);success(icon,false,false);addresses(icon);malformed(icon);
   }
   System.out.println("PASS: history/avatar handshakes ignore unrelated BOS traffic and non-hello packets without extending deadlines; foreign-service redirects ignored; valid reordered/extra/legacy redirects reach one ready/request and preserve custom ports; malformed redirects report protocol error, never missing UIN/password");
  }finally{Icq.disconnect(true);Jimm.getTimerRef().cancel();}
 }
}
