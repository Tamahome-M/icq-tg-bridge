package jimm;

import java.lang.reflect.*;
import java.util.concurrent.TimeUnit;
import javax.microedition.media.Manager;
import javax.microedition.media.Player;

public class ClientCaptureLifecycleTest {
 private static int failures;
 private static boolean baseline;
 static void check(boolean ok,String what){if(!ok)throw new AssertionError(what);}
 static Object field(Object o,String name)throws Exception {Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
 static void call(Object o,String name)throws Exception {Method m=o.getClass().getDeclaredMethod(name,new Class[0]);m.setAccessible(true);m.invoke(o,new Object[0]);}
 static void run(String name,RunnableTest test)throws Exception {
  try{test.run();System.out.println("PASS "+name);}catch(AssertionError e){failures++;System.out.println("FAIL "+name+": "+e.getMessage());if(!baseline)throw e;}
 }
 interface RunnableTest{void run()throws Exception;}
 static void join(Thread t)throws Exception {t.join(4000);check(!t.isAlive(),"worker did not finish");}
 static Manager.Gate gate(int stage){Manager.Gate g=new Manager.Gate();Manager.stage=stage;Manager.gate=g;return g;}
 static void entered(Manager.Gate g)throws Exception{check(g.entered.await(4,TimeUnit.SECONDS),"native call not reached");}
 static Manager.State last(){return (Manager.State)Manager.created.lastElement();}
 static Object open(boolean video)throws Exception {
  Manager.stage=0;Manager.gate=null;
  if(video)VideoRecorder.show("1000001",null);else CameraShot.show("1000001",null);
  Object o=Jimm.display.getCurrent();
  long end=System.currentTimeMillis()+4000;
  while(field(o,"video")==null && System.currentTimeMillis()<end)Thread.sleep(5);
  check(field(o,"video")!=null,"camera did not open");return o;
 }
 static void close(Object o)throws Exception{call(o,"close");}
 static void cancelledOpen(boolean video,int stage)throws Exception {
  Manager.Gate g=gate(stage);
  if(video)VideoRecorder.show("1000001",null);else CameraShot.show("1000001",null);
  Object o=Jimm.display.getCurrent();entered(g);Thread worker=Manager.worker;
  close(o);g.release.countDown();join(worker);Manager.State p=last();
  check(p.state==Player.CLOSED,"cancelled camera leaked");
  check(p.starts==0,"camera started after Back at stage "+stage);
  check(field(o,"player")==null,"cancelled player retained");
 }
 static void stopDuringStart(int stage)throws Exception {
  TempFiles.memory=true;int sent=jimm.comm.Icq.sent;
  Object o=open(true);Manager.State p=last();Manager.Gate g=gate(stage);call(o,"start");entered(g);Thread worker=Manager.worker;
  call(o,"stopAndSend");Thread.sleep(40);g.release.countDown();join(worker);
  long end=System.currentTimeMillis()+3000;
  while(jimm.comm.Icq.sent==sent && System.currentTimeMillis()<end)Thread.sleep(5);
  boolean ok=jimm.comm.Icq.sent==sent+1 && p.commits==1;
  close(o);check(ok,"early Stop lost recording (commits="+p.commits+", sends="+(jimm.comm.Icq.sent-sent)+")");
 }
 static void cancelledSetup(int stage)throws Exception {
  TempFiles.memory=false;TempFiles.files.clear();Object first=open(true);
  Manager.Gate g=gate(stage);call(first,"start");entered(g);Thread worker=Manager.worker;
  String old=(String)field(first,"tempUrl");close(first);
  Object second=open(true);call(second,"start");
  long end=System.currentTimeMillis()+3000;
  while(field(second,"record")==null && System.currentTimeMillis()<end)Thread.sleep(5);
  String fresh=(String)field(second,"tempUrl");check(fresh!=null,"replacement path missing");
  g.release.countDown();join(worker);
  boolean unique=!fresh.equals(old),present=TempFiles.files.containsKey(fresh);
  boolean noOld=TempFiles.files.size()==1 && (old==null || old.equals(fresh) || !TempFiles.files.containsKey(old));
  close(second);check(unique,"two recordings use the same temporary file");
  check(present,"old capture cleanup deleted new recording");check(noOld,"late native setup left a temporary file");
  check(field(first,"record")==null,"closed screen retained late RecordControl");
 }
 static void releaseRecordingBuffer()throws Exception {
  TempFiles.memory=true;Object o=open(true);call(o,"start");
  long end=System.currentTimeMillis()+3000;
  while(field(o,"record")==null && System.currentTimeMillis()<end)Thread.sleep(5);
  Manager.Gate g=gate(10);call(o,"stopAndSend");entered(g);Thread worker=Manager.worker;
  boolean released=field(o,"sink")==null;
  close(o);g.release.countDown();join(worker);
  check(released,"camera retains duplicate recording buffer throughout upload");
 }
 static void cancelledCommit()throws Exception {
  TempFiles.memory=true;int sent=jimm.comm.Icq.sent;Object o=open(true);call(o,"start");
  long end=System.currentTimeMillis()+3000;
  while(field(o,"record")==null && System.currentTimeMillis()<end)Thread.sleep(5);
  Manager.Gate g=gate(8);call(o,"stopAndSend");entered(g);Thread worker=Manager.worker;
  close(o);g.release.countDown();join(worker);
  check(jimm.comm.Icq.sent==sent,"cancelled commit uploaded");
  check(field(o,"sink")==null,"recording buffer retained after Back");
 }
 public static void main(String[] args)throws Exception {
  baseline=args.length>0 && args[0].equals("baseline");
  for(int kind=0;kind<2;kind++)for(int s=1;s<=4;s++){
   final boolean v=kind==1;final int stage=s;
   run((v?"video":"photo")+" Back stage "+s,new RunnableTest(){public void run()throws Exception{cancelledOpen(v,stage);}});
  }
  for(int s=5;s<=7;s++) {final int stage=s;run("Stop during start "+s,new RunnableTest(){public void run()throws Exception{stopDuringStart(stage);}});}
  for(int s=6;s<=7;s++) {final int stage=s;run("Back during record setup "+s,new RunnableTest(){public void run()throws Exception{cancelledSetup(stage);}});}
  run("Back during file lookup",new RunnableTest(){public void run()throws Exception{cancelledSetup(9);}});
  run("Recording buffer released",new RunnableTest(){public void run()throws Exception{releaseRecordingBuffer();}});
  run("Back during commit",new RunnableTest(){public void run()throws Exception{cancelledCommit();}});
  if(baseline)check(failures>0,"baseline unexpectedly passed");
  System.out.println("capture lifecycle: "+(baseline?failures+" reproduced failures":"16 passed"));
 }
}
