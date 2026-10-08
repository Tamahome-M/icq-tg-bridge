"""Actual J2ME BART photo action, encrypted socket and viewer; desktop MIDP/JPEG stubs.
Usage: python tests/test_client_photos.py BUILD_WORK [COMPILED_CLASSES]
"""
from pathlib import Path
import asyncio, io, os, subprocess, sys, tempfile, re, json
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from tests.test_client_secure import CONNECTOR
from tests.test_client_ui import STUBS
from tests.test_secure import SecureDialer
from tests.test_telemotomax import make_server, small_jpeg
from tests.fake_jimm import FakeJimm
from bridge import photos

async def run(work,classes):
 cp=os.pathsep.join(str(p) for p in [classes,*sorted((work/'wtk/lib').glob('*.jar'))])
 with tempfile.TemporaryDirectory(prefix='tmm-photo-probe-') as temp:
  directory=Path(temp);stubs=dict(STUBS);stubs['javax/microedition/io/Connector.java']=CONNECTOR
  # The release compresses language keys; resolve them like the UI harness so
  # assertions can distinguish decode, memory and transport error labels.
  alphabet="_0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
  keys=re.findall(r'^"([^"\n]+)"',(work/'src/build/init/src/lng/RU.lang').read_text(),re.M)
  mappings=[];counter=0
  for key in dict.fromkeys(keys):
   if key.startswith(('error_','lang_')):continue
   value=counter;short=""
   while True:
    short+=alphabet[value%len(alphabet)];value//=len(alphabet)
    if not value:break
   counter+=1;mappings.append(f'keys.put({json.dumps(short)},{json.dumps(key)});')
  stubs['jimm/util/ResourceBundle.java']='''package jimm.util;
  public class ResourceBundle {
   public static String[] langAvailable={"RU"};private static java.util.Hashtable keys=new java.util.Hashtable();
   static {MAPPINGS}
   public static String getString(String s){String v=(String)keys.get(s);return v==null?s:v;}
   public static String getString(String s,int flags){return getString(s);}public static String remove(String s){return getString(s);}
  }'''.replace('MAPPINGS',''.join(mappings))
  stubs['javax/microedition/lcdui/Image.java']='''package javax.microedition.lcdui;
  public class Image {
   public static int mode;
   public static Image createImage(String s)throws java.io.IOException {throw new java.io.IOException();}
   public static Image createImage(byte[] b,int off,int length){
    if(mode==1)throw new OutOfMemoryError("simulated native decoder heap pressure");
    if(mode==2)throw new IllegalArgumentException("simulated unsupported JPEG");
    try{
    java.awt.image.BufferedImage v=javax.imageio.ImageIO.read(new java.io.ByteArrayInputStream(b,off,length));
    if(v==null || v.getWidth()!=176 || v.getHeight()!=132)throw new IllegalArgumentException();return new Image();
   }catch(java.io.IOException e){throw new IllegalArgumentException();}}
  }'''
  stubs['javax/microedition/lcdui/Graphics.java']='''package javax.microedition.lcdui;
  public class Graphics {
   public java.util.Vector lines=new java.util.Vector();
   public void setColor(int c){}public void fillRect(int x,int y,int w,int h){}public void setFont(Font f){}
   public void drawImage(Image i,int x,int y,int anchor){}
   public void drawString(String s,int x,int y,int anchor){lines.addElement(s);}
  }'''
  sources=[]
  for name,source in stubs.items():
   path=directory/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source);sources.append(str(path))
  path=root/'tests/java/PhotoLoadingTest.java'
  subprocess.run([str(work/'jdk/bin/javac'),'-encoding','UTF-8','-cp',cp,'-d',str(directory),*sources,str(path)],check=True)
  data,w,h=photos.shrink(small_jpeg(),176,132,7*1024)
  # Valid JPEG comment pads to the size in the user's report.
  pad=4814-len(data)-4
  assert pad>=0
  data=data[:-2]+b'\xff\xfe'+(pad+2).to_bytes(2,'big')+bytes(pad)+data[-2:]
  assert len(data)==4814
  (directory/'photo.jpg').write_bytes(data)
  server,storage=make_server(0);server.cfg.avatars=True;server.cfg.oscar_psk='1234'
  async def fetch(*args):return data
  server.fetch_attachment=fetch
  token=server.register_attachment(1000001,'photo:42')
  await server.start();port=server._server.sockets[0].getsockname()[1];server.cfg.oscar_port=port
  try:
   for secure in (False,True):
    client=FakeJimm('127.0.0.1',port,'100500','s3cret');client.tmm_version=(0,91)
    if secure:
     from bridge.oscar.secure import parse_psk
     client.open_transport=SecureDialer(parse_psk('1234'))
    try:
     await client.connect();await client.bos(await client.login_md5_jimm());await client.drain_for(.05)
     cookie=server.new_cookie('bart')
     process=await asyncio.create_subprocess_exec(str(work/'jdk/bin/java'),'-cp',str(directory)+os.pathsep+cp,'PhotoLoadingTest',f'127.0.0.1:{port}',cookie.hex(),token.hex(),str(directory/'photo.jpg'),'true' if secure else 'false')
     assert await asyncio.wait_for(process.wait(),20)==0
    finally:await client.close();await asyncio.sleep(.05)
  finally:await server.stop();await asyncio.sleep(.03);storage.close()

if __name__=='__main__':
 work=Path(sys.argv[1]);asyncio.run(run(work,Path(sys.argv[2]) if len(sys.argv)>2 else work/'src/build/compile/classes'))
