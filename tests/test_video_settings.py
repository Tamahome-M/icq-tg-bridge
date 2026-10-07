"""JVM checks of real Options/OptionsForm/Icq: workdir, classes dir, v3|v8."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_client_lifecycle import STUBS


CHOICE = """
package javax.microedition.lcdui;
public class ChoiceGroup extends Item implements Choice {
 private java.util.Vector labels=new java.util.Vector(); private int selected;
 public ChoiceGroup(String label,int type) {}
 public int size(){return labels.size();}
 public String getString(int i){return (String)labels.elementAt(i);}
 public Image getImage(int i){return null;}
 public int append(String s,Image image){labels.addElement(s);return labels.size()-1;}
 public void insert(int i,String s,Image image){labels.insertElementAt(s,i);}
 public void delete(int i){labels.removeElementAt(i);}
 public void deleteAll(){labels.removeAllElements();}
 public void set(int i,String s,Image image){labels.setElementAt(s,i);}
 public boolean isSelected(int i){return selected==i;}
 public int getSelectedIndex(){return selected;}
 public int getSelectedFlags(boolean[] a){return 0;}
 public void setSelectedIndex(int i,boolean value){if(value)selected=i;}
 public void setSelectedFlags(boolean[] a){}
 public void setFitPolicy(int p){}
 public int getFitPolicy(){return 0;}
 public void setFont(int i,Font f){}
 public Font getFont(int i){return null;}
}
"""


def run(work: Path, classes: Path, variant: str) -> None:
    root = Path(__file__).resolve().parents[1]
    classpath = os.pathsep.join(str(p) for p in [classes, *sorted((work / "wtk/lib").glob("*.jar"))])
    stubs = {name: STUBS[name] for name in ("jimm/util/ResourceBundle.java",)}
    stubs["javax/microedition/lcdui/ChoiceGroup.java"] = CHOICE
    stubs["javax/microedition/lcdui/Item.java"] = "package javax.microedition.lcdui; public abstract class Item {}"
    with tempfile.TemporaryDirectory(prefix="tmm-video-settings-") as temp:
        directory = Path(temp)
        sources = []
        for name, source in stubs.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            sources.append(str(path))
        subprocess.run([str(work / "jdk/bin/javac"), "-encoding", "UTF-8", "-cp", classpath,
                        "-d", str(directory), *sources, str(root / "tests/java/VideoSettingsTest.java")], check=True)
        subprocess.run([str(work / "jdk/bin/java"), "-cp", str(directory) + os.pathsep + classpath,
                        "VideoSettingsTest", variant], check=True, timeout=30)


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3])
