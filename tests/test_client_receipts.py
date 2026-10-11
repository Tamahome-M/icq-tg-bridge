"""Actual ACK/read parser, queued UI, chat receipts and the real check sprite."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.test_client_chat_memory import make_stubs


def run(work,classes):
    stubs=make_stubs()
    stubs.pop('jimm/ChatTextList.java')
    stubs['javax/microedition/lcdui/Image.java']='''package javax.microedition.lcdui;
public class Image {
 private final int width,height;public final int[] pixels;public static int rgbCreates;public static boolean failRGB;
 public Image(){width=height=16;pixels=new int[256];}
 private Image(int[] data,int w,int h){width=w;height=h;pixels=data.clone();}
 public static Image createImage(String s)throws java.io.IOException {throw new java.io.IOException();}
 public static Image sprite(int index){try{
  java.awt.image.BufferedImage source=javax.imageio.ImageIO.read(new java.io.File(System.getProperty("tmm.checks")));
  int h=source.getHeight();return new Image(source.getRGB(index*h,0,h,h,null,0,h),h,h);
 }catch(Exception e){throw new IllegalStateException(e);}}
 public static Image createRGBImage(int[] data,int w,int h,boolean alpha){if(failRGB)throw new OutOfMemoryError();rgbCreates++;return new Image(data,w,h);}
 public int getWidth(){return width;}public int getHeight(){return height;}
 public void getRGB(int[] out,int offset,int scan,int x,int y,int w,int h){for(int row=0;row<h;row++)System.arraycopy(pixels,(y+row)*width+x,out,offset+row*scan,w);}
}'''
    stubs['DrawControls/ImageList.java']='''package DrawControls;
public class ImageList {
 private String path;public void setScale(int i){}public void load(String s,int a,int b,int c,boolean d){path=s;}
 public javax.microedition.lcdui.Image elementAt(int i){return "/messages.png".equals(path)?javax.microedition.lcdui.Image.sprite(i):new javax.microedition.lcdui.Image();}
}'''
    stubs['javax/microedition/lcdui/Canvas.java']=stubs['javax/microedition/lcdui/Canvas.java'].replace(
        'public void repaint(){}','public void repaint(){} public void repaint(int x,int y,int w,int h){}')
    stubs['javax/microedition/rms/RecordStore.java']=stubs['javax/microedition/rms/RecordStore.java'].replace(
        'public static RecordStore openRecordStore','public static String[] listRecordStores(){return new String[0];}'
        'public static void deleteRecordStore(String s){stores.remove(s);} public static RecordStore openRecordStore')
    cp=os.pathsep.join(map(str,[classes,*sorted((work/'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-receipts-') as temp:
        directory=Path(temp);resources=directory/'resources';resources.mkdir()
        for name in ('RU.lng','langlist.lng'):shutil.copy2(work/'src/build/res'/name,resources/name)
        sources=[]
        for name,source in stubs.items():
            path=directory/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source);sources.append(str(path))
        sources.append(str(ROOT/'tests/java/ClientReceiptsTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'),'-encoding','UTF-8','-cp',cp,'-d',str(directory),*sources],check=True)
        subprocess.run([str(work/'jdk/bin/java'),'-Xbootclasspath/a:'+str(resources),'-cp',str(directory)+os.pathsep+cp,
                        'jimm.ClientReceiptsTest',str(work/'src/build/res/messages.png')],check=True,timeout=25)


if __name__=='__main__':
    work=Path(sys.argv[1]).resolve()
    run(work,Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
