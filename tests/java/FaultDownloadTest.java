package jimm;

import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import javax.microedition.lcdui.*;

public class FaultDownloadTest {
 static Field f(Class c,String n)throws Exception{Field f=c.getDeclaredField(n);f.setAccessible(true);return f;}
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static FileDownloader download(String name,byte[] bytes)throws Exception{
  Constructor ctor=FileDownloader.class.getDeclaredConstructor(String.class,JimmScreen.class);ctor.setAccessible(true);
  FileDownloader dl=(FileDownloader)ctor.newInstance("1000001",null);
  f(FileDownloader.class,"current").set(null,dl);f(FileDownloader.class,"fileName").set(dl,name);
  f(FileDownloader.class,"filePath").set(dl,"file:///c/tmm/"+name);
  MediaBuffer queue=new MediaBuffer();queue.put(bytes,0,bytes.length);queue.finish(true);
  f(FileDownloader.class,"partQueue").set(dl,queue);return dl;
 }
 static Thread write(final FileDownloader dl){Thread t=new Thread(){public void run(){try{
  Method m=FileDownloader.class.getDeclaredMethod("writeParts");m.setAccessible(true);m.invoke(dl);
 }catch(Exception e){throw new AssertionError(e);}}};t.start();return t;}
 public static void main(String[] args)throws Exception{
  f(Options.class,"options").set(null,new Hashtable());Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
  Constructor ui=MainThread.class.getDeclaredConstructor();ui.setAccessible(true);ui.newInstance();
  String path="file:///c/tmm/photo.jpg";byte[] old={9,8,7},fresh={1,2,3,4};NativeFiles.files.put(path,old);
  Method target=FileDownloader.class.getDeclaredMethod("targetUrl",String.class);target.setAccessible(true);target.invoke(null,"photo.jpg");
  check(Arrays.equals(old,(byte[])NativeFiles.files.get(path)),"directory probe deleted existing file");
  FileDownloader first=download("photo.jpg",fresh);Thread one=write(first);one.join(2000);check(!one.isAlive(),"writer hung");
  check(Arrays.equals(old,(byte[])NativeFiles.files.get(path)),"download replaced existing file");
  check(Arrays.equals(fresh,(byte[])NativeFiles.files.get("file:///c/tmm/photo-1.jpg")),"completed file not renamed");
  NativeFiles.Gate gate=new NativeFiles.Gate();NativeFiles.gate=gate;
  FileDownloader cancelled=download("second.bin",old);Thread blocked=write(cancelled);
  check(gate.entered.await(2,TimeUnit.SECONDS),"writer not blocked");
  ((MediaBuffer)f(FileDownloader.class,"partQueue").get(cancelled)).finish(false);
  FileDownloader replacement=download("second.bin",fresh);Thread next=write(replacement);next.join(2000);
  gate.resume.countDown();blocked.join(2000);
  check(!blocked.isAlive()&&!next.isAlive(),"cancelled writer hung");
  check(Arrays.equals(fresh,(byte[])NativeFiles.files.get("file:///c/tmm/second.bin")),"old cancellation deleted new download");
  for(Enumeration keys=NativeFiles.files.keys();keys.hasMoreElements();)check(!((String)keys.nextElement()).endsWith(".part"),"temporary file retained");
  System.out.println("PASS: non-destructive probe, completed rename, cancelled writer ownership and old file preservation");System.exit(0);
 }
}
