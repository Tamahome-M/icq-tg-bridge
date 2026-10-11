"""Actual emoticon/link parsers, resource aliases and desktop allocation counts.

Usage: python tests/test_client_text_parsing.py BUILD_WORK [CLASSES] [baseline]
Only MIDP drawing is stubbed. Measurements exclude drawing/layout and are a
desktop comparison, not measurements of Motorola's VM.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_ui import STUBS


def run(work, classes, baseline):
    stubs = dict(STUBS)
    stubs["DrawControls/TextList.java"] = """
package DrawControls;
import java.util.Vector;
import javax.microedition.lcdui.Image;
public class TextList extends VirtualList {
 public boolean capture=true; public Vector labels=new Vector(), icons=new Vector();
 public String lastText; public int lastStyle,lastColor,lastIndex;
 public TextList(String caption){}
 public TextList addBigText(String text,int color,int style,int index){
  lastText=text;lastColor=color;lastStyle=style;lastIndex=index;
  if(capture){labels.addElement(text);icons.addElement(new Integer(-1));}return this;
 }
 public TextList addAniImage(Image[] images,byte[] timing,String text,int index){
  if(capture){labels.addElement(text);icons.addElement(new Integer(images[0].id));}
  return this;
 }
 public void doCRLF(int index){} public void clear(){labels.removeAllElements();icons.removeAllElements();}
}
"""
    stubs["DrawControls/ImageList.java"] = """
package DrawControls;
import javax.microedition.lcdui.Image;
public class ImageList {
 private Image[] images; public static boolean fail;
 public void setScale(int scale){}
 public void load(String resource,int width,int height,int count,boolean alpha){
  if(fail)throw new OutOfMemoryError("simulated image load");
  images=new Image[32];for(int i=0;i<images.length;i++){images[i]=new Image();images[i].id=i;}
 }
 public int size(){return images==null?0:images.length;}
 public Image[] getImages(){return images;}
 public Image elementAt(int i){return images[i];}
 public void removeAllElements(){images=null;}
}
"""
    stubs["javax/microedition/lcdui/Image.java"] = stubs["javax/microedition/lcdui/Image.java"].replace(
        "public class Image {", "public class Image {public int id;public int getWidth(){return 16;}public int getHeight(){return 16;}")
    stubs["jimm/Jimm.java"] = stubs["jimm/Jimm.java"].replace(
        "public static void setBkltOn", "public static void setLoadError(String s){} public static void setBkltOn")
    smiles = (classes / "jimm/Emoticons.class").exists()
    if not smiles:
        stubs["jimm/Emoticons.java"] = """
package jimm;
public class Emoticons {
 public static void addTextWithEmotions(DrawControls.TextList l,String s,int style,int color,int index){throw new AssertionError("Light parsed emoticons");}
}
"""
    stubs["jimm/LinkCheck.java"] = """
package jimm;
public class LinkCheck {
 public static boolean has(String text){return %s;}
 public static boolean visible(String text){return %s;}
}
""" % (("jimm.comm.Util.parseMessageForURL(text)!=null",
        "jimm.comm.Util.parseMessageForURL(VideoLink.visibleText(text))!=null") if baseline else
       ("jimm.comm.Util.hasURL(text)", "VideoLink.hasVisibleURL(text)"))
    cp = os.pathsep.join(map(str, [classes, *sorted((work / "wtk/lib").glob("*.jar"))]))
    with tempfile.TemporaryDirectory(prefix="tmm-text-parsing-") as temp:
        directory = Path(temp)
        sources = []
        for name, source in stubs.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            sources.append(str(path))
        sources.append(str(ROOT / "tests/java/ClientTextParsingTest.java"))
        subprocess.run([str(work / "jdk/bin/javac"), "-encoding", "UTF-8", "-cp", cp,
                        "-d", str(directory), *sources], check=True)
        for name in ("smiles.txt",):
            (directory / name).write_bytes((ROOT / "telemotomax/res/GRAPHICS_8BIT/MODULES/SMILES_STD" / name).read_bytes())
        subprocess.run([str(work / "jdk/bin/java"), "-Xint", "-XX:-DoEscapeAnalysis", "-cp",
                        str(directory) + os.pathsep + cp, "jimm.ClientTextParsingTest",
                        str(directory / "smiles.txt"), "baseline" if baseline else "verify",
                        "smiles" if smiles else "nosmiles"],
                       check=True, timeout=60)


if __name__ == "__main__":
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv) > 2
        else work / "src/build/compile/classes", len(sys.argv) > 3 and sys.argv[3] == "baseline")
