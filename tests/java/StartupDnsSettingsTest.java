import java.lang.reflect.*;
import java.util.Hashtable;
import javax.microedition.lcdui.*;
import jimm.*;

public final class StartupDnsSettingsTest {
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
 static Method method(Class c,String name)throws Exception{Method m=c.getDeclaredMethod(name);m.setAccessible(true);return m;}
 static void defaults()throws Exception{
  field(Options.class,"options").set(null,new Hashtable());
  method(Options.class,"setDefaults").invoke(null);
 }
 static void reload()throws Exception{defaults();Options.load();}
 static Object network()throws Exception{
  Class c=Class.forName("jimm.OptionsForm");
  Object o=((sun.misc.Unsafe)field(sun.misc.Unsafe.class,"theUnsafe").get(null)).allocateInstance(c);
  field(c,"optionsForm").set(o,new Form("network"));method(c,"showNetworkOptions").invoke(o);return o;
 }
 static ChoiceGroup choice(Object o)throws Exception{return (ChoiceGroup)field(o.getClass(),"startupDnsChoice").get(o);}
 static TextField resolver(Object o)throws Exception{return (TextField)field(o.getClass(),"dnsServerTextField").get(o);}
 static void read(Object o)throws Exception{method(o.getClass(),"readNetworkOptions").invoke(o);}
 static void persistence()throws Exception{
  javax.microedition.rms.RecordStore.stores.clear();defaults();
  check(!Options.getBoolean(Options.OPTION_STARTUP_DNS),"DNS must be disabled by default");
  check(Options.getString(Options.OPTION_DNS_SERVER).equals("1.1.1.1"),"default resolver missing");
  Hashtable saved=(Hashtable)field(Options.class,"options").get(null);
  saved.remove(Integer.valueOf(Options.OPTION_STARTUP_DNS));saved.remove(Integer.valueOf(Options.OPTION_DNS_SERVER));
  Options.setString(Options.OPTION_SRV_HOST,"bridge.example");Options.save();reload();
  check(!Options.getBoolean(Options.OPTION_STARTUP_DNS) && Options.getString(Options.OPTION_DNS_SERVER).equals("1.1.1.1"),"legacy RMS lost safe defaults");
  check(Options.getString(Options.OPTION_SRV_HOST).equals("bridge.example"),"DNS migration changed bridge hostname");
  Object o=network();ChoiceGroup mode=choice(o);Form form=(Form)field(o.getClass(),"optionsForm").get(o);
  check(mode.getType()==Choice.POPUP && mode.size()==2 && mode.getSelectedIndex()==0,"DNS mode is not an Off/On dropdown");
  check(form.items.contains(mode) && form.items.contains(resolver(o)),"DNS controls missing from network form");
  boolean note=false;for(Object item:form.items)if(item instanceof String && ((String)item).length()>0)note=true;
  check(note,"restart note missing");
  mode.setSelectedIndex(1,true);resolver(o).setString(" 9.9.9.9 ");read(o);Options.save();reload();
  check(Options.getBoolean(Options.OPTION_STARTUP_DNS) && Options.getString(Options.OPTION_DNS_SERVER).equals("9.9.9.9"),"DNS mode/resolver not persisted or whitespace retained");
  Object reopened=network();check(choice(reopened).getSelectedIndex()==1 && resolver(reopened).getString().equals("9.9.9.9"),"network form ignores saved DNS values");
  method(reopened.getClass(),"clearForm").invoke(reopened);
  check(field(reopened.getClass(),"startupDnsChoice").get(reopened)==null && field(reopened.getClass(),"dnsServerTextField").get(reopened)==null,"closed form retains DNS widgets");
  System.out.println("PASS: DNS disabled/default resolver, legacy RMS, dropdown/restart note, persistence and widget cleanup");
 }
 static void validation()throws Exception{
  for(String invalid:new String[]{"","dns.example","https://1.1.1.1","1.1.1.1:53","1.1.1.1/path","1.1.1.1;foo","1.1.1.1\n8.8.8.8","1.1.1","1.1.1.1.1","256.0.0.1","1.01.1.1","1.-1.1.1","+1.1.1.1","::1"}){
   defaults();Options.setString(Options.OPTION_SRV_HOST,"original.example");Object o=network();
   choice(o).setSelectedIndex(1,true);resolver(o).setString(invalid);
   ((TextField)field(o.getClass(),"srvHostTextField").get(o)).setString("edited.example");
   boolean refused=false;try{read(o);}catch(InvocationTargetException e){refused=e.getCause() instanceof IllegalArgumentException;}
   check(refused,"enabled resolver accepted non-IPv4: "+invalid);
   check(!Options.getBoolean(Options.OPTION_STARTUP_DNS) && Options.getString(Options.OPTION_DNS_SERVER).equals("1.1.1.1") && Options.getString(Options.OPTION_SRV_HOST).equals("original.example"),"invalid DNS partially saved network options");
  }
  defaults();Object o=network();choice(o).setSelectedIndex(0,true);resolver(o).setString("");read(o);Options.save();reload();
  check(!Options.getBoolean(Options.OPTION_STARTUP_DNS),"disabled DNS blocked saving normal network settings");
  for(String valid:new String[]{"1.1.1.1","8.8.8.8","192.168.1.1","127.0.0.1"}){
   o=network();choice(o).setSelectedIndex(1,true);resolver(o).setString(valid);read(o);
   check(Options.getString(Options.OPTION_DNS_SERVER).equals(valid),"valid IPv4 not saved: "+valid);
  }
  System.out.println("PASS: enabled DNS accepts literal IPv4 only; invalid form saves are atomic; disabled DNS does not validate resolver");
 }
 public static void main(String[] args)throws Exception{
  try{persistence();validation();}finally{Jimm.getTimerRef().cancel();}
 }
}
