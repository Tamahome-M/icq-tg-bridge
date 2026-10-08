import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.TextList;
import jimm.*;
import jimm.comm.*;
import jimm.comm.connections.Connection;
import jimm.util.ResourceBundle;

public final class ClientUiTest {
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static Field field(Class c,String name) throws Exception {
        Field f=c.getDeclaredField(name);f.setAccessible(true);return f;
    }
    static Method method(Class c,String name,Class... args) throws Exception {
        Method m=c.getDeclaredMethod(name,args);m.setAccessible(true);return m;
    }
    static final class Task extends Action {
        boolean done,error; int cancelled;
        Task(){super(true,false);}
        protected void init(){} protected boolean forward(Packet p){return false;}
        public boolean isCompleted(){return done;} public boolean isError(){return error;}
        public void onEvent(int event){
            if(event==ON_CANCEL){
                cancelled++;
                try {check(field(SplashCanvas.class,"lastAction").get(null)==null,"callback saw stale action");}
                catch(Exception e){throw new RuntimeException(e);}
            }
        }
    }
    static void cancelScreen() throws Exception {
        SplashCanvas screen=new SplashCanvas("test");
        Method press=method(SplashCanvas.class,"keyPressed",Integer.TYPE);
        Method repeat=method(SplashCanvas.class,"keyRepeated",Integer.TYPE);
        Method release=method(SplashCanvas.class,"keyReleased",Integer.TYPE);
        for(int code:new int[]{-22,-7,22,106,-203,112,57346,987}){
            Canvas.keyName=code==987?"Soft2":null;
            Task task=new Task();
            SplashCanvas.addTimerTask(ResourceBundle.key("connecting"),task,true);
            TimerTasks timer=(TimerTasks)field(SplashCanvas.class,"lastTimerTask").get(null);
            check(screen.fullScreen && screen.commands.isEmpty() && screen.listener==null,"connection exposes command bar");
            press.invoke(screen,49);
            check(task.cancelled==0,"unrelated key cancels login");
            press.invoke(screen,code);
            repeat.invoke(screen,code);release.invoke(screen,code);press.invoke(screen,code);
            screen.commandAction(SplashCanvas.cancelCommand,screen);
            check(task.cancelled==1 && timer.isCanceled(),"cancel must stop timer once");
        }
        Canvas.keyName=null;
        for(int state=0;state<4;state++){
            Task task=new Task();task.done=state==0;task.error=state==1;
            SplashCanvas.addTimerTask(ResourceBundle.key("connecting"),task,state!=2);
            if(state==3)SplashCanvas.resetLastTask();
            press.invoke(screen,-22);
            check(task.cancelled==0,"inactive/noncancellable task cancelled");
        }
        Task search=new Task();
        SplashCanvas.addTimerTask("wait",search,true);
        check(!screen.fullScreen && screen.commands.contains(SplashCanvas.cancelCommand) && screen.listener==screen,"search lost native cancellation");
        press.invoke(screen,-22);check(search.cancelled==0,"search uses direct login cancellation");
        screen.commandAction(SplashCanvas.cancelCommand,screen);check(search.cancelled==1,"search command does not cancel");
        Task quiet=new Task();SplashCanvas.addTimerTask(quiet);press.invoke(screen,-22);
        screen.commandAction(SplashCanvas.cancelCommand,screen);check(quiet.cancelled==0,"quiet reconnect became cancellable");
        Task locked=new Task();SplashCanvas.addTimerTask(ResourceBundle.key("connecting"),locked,true);SplashCanvas.lock();
        press.invoke(screen,-22);check(locked.cancelled==0 && SplashCanvas.locked(),"lock key cancelled login");
        SplashCanvas.unlock(false);SplashCanvas.resetLastTask();
        System.out.println("PASS: full-screen login, hidden right-key cancel once, completed/error/quiet/locked guards; search cancel");
    }
    static final class Socket extends Connection {
        Vector packets=new Vector();
        public void sendPacket(Packet p){packets.addElement(p);}
        public void forceDisconnect(){}
    }
    static void statusMenu() throws Exception {
        Socket socket=new Socket();
        field(Icq.class,"c").set(null,socket);
        method(Icq.class,"setConnected").invoke(null);
        field(ContactList.class,"cItems").set(null,new Vector());
        field(ContactList.class,"gItems").set(null,new Vector());
        MainMenu menu=new MainMenu();MainMenu.build();
        TextList list=MainMenu.getUIConrol();
        check(list.labels.contains("set_status"),"main menu lost status");
        Jimm.display.setCurrent(list);list.choose(8);
        TextList statuses=(TextList)Jimm.display.getCurrent();
        check(statuses!=list,"status did not open chooser");
        for(int status:new int[]{ContactList.STATUS_ONLINE,ContactList.STATUS_AWAY,ContactList.STATUS_DND,ContactList.STATUS_INVISIBLE}){
            Jimm.display.setCurrent(list);list.choose(8);
            statuses=(TextList)Jimm.display.getCurrent();
            socket.packets.removeAllElements();statuses.choose(status);
            check(Options.getLong(Options.OPTION_ONLINE_STATUS)==status,"manual status was not saved");
            check(socket.packets.size()==1,"manual status was not sent once");
            SnacPacket packet=(SnacPacket)socket.packets.elementAt(0);
            byte[] data=packet.getData();
            check(packet.getFamily()==1 && packet.getCommand()==0x1e,"wrong status SNAC");
            check(data.length==8 && Util.getWord(data,0)==6 && Util.getWord(data,2)==4,"extended status remains in packet");
            check(Util.getDWord(data,4)==(Util.translateStatusSend(status)|0x10000000),"wrong ordinary status value");
            check(Jimm.display.getCurrent()==null,"status opens text editor instead of returning");
        }
        Icq.setOnlineStatus(ContactList.STATUS_ONLINE,true);
        byte[] login=((SnacPacket)socket.packets.lastElement()).getData();
        check(Util.getWord(login,8)==0x0c && login.length==49,"login lost DC info");
        Class formClass=Class.forName("jimm.OptionsForm");
        Field unsafeField=field(sun.misc.Unsafe.class,"theUnsafe");
        Object form=((sun.misc.Unsafe)unsafeField.get(null)).allocateInstance(formClass);
        field(formClass,"optionsMenu").set(form,new TextList("settings"));
        field(formClass,"optionsForm").set(form,new Form("settings"));
        field(formClass,"lastUILang").set(form,Options.getString(Options.OPTION_UI_LANGUAGE));
        method(formClass,"initOptionsList",Integer.TYPE).invoke(form,10000);
        TextList settings=(TextList)field(formClass,"optionsMenu").get(form);
        for(String forbidden:new String[]{"status","xstatus","auto_away","myself","transparency"})
            check(!settings.labels.contains(forbidden),"retired settings menu remains: "+forbidden);
        check(settings.labels.contains("options_interface") && settings.labels.contains("options_media"),"other settings disappeared");
        method(formClass,"showInterfaceOptions").invoke(form);
        ChoiceGroup choices=(ChoiceGroup)field(formClass,"choiceContactList").get(form);
        check(choices.size()==4 && choices.getString(3).equals("show_deleted_contacts"),"interface checkbox positions shifted");
        choices.setSelectedIndex(3,true);
        method(formClass,"readInterfaceOptions").invoke(form);
        check(Options.getBoolean(Options.OPTION_SHOW_DELETED_CONT),"last contact-list checkbox no longer saved");
        System.out.println("PASS: actual main status menu and OSCAR, login DC info; removed settings; interface checkbox save");
    }
    static void mediaOptions() throws Exception {
        Class formClass=Class.forName("jimm.OptionsForm");
        Object form=((sun.misc.Unsafe)field(sun.misc.Unsafe.class,"theUnsafe").get(null)).allocateInstance(formClass);
        Form media=new Form("media");field(formClass,"optionsForm").set(form,media);
        Options.setString(Options.OPTION_MEDIA_VIDEO_SIZE,"176x144");
        Options.setInt(Options.OPTION_MEDIA_VIDEO_KBPS,48);
        Options.setInt(Options.OPTION_VIDEO_ROTATE,1);
        Options.setInt(Options.OPTION_PHOTO_ROTATE,2);
        Options.setInt(Options.OPTION_MEDIA_MEM_KB,512);
        method(formClass,"showMediaOptions").invoke(form);
        int dropdowns=0;
        for(Object item:media.items){
            if(item instanceof ChoiceGroup){
                check(((ChoiceGroup)item).getType()==Choice.POPUP,"media choice is not a dropdown: "+((ChoiceGroup)item).label);
                dropdowns++;
            }else check(item instanceof TextField,"unexpected media field");
        }
        check(dropdowns==11 && media.items.size()==12,"media choices or memory field lost");
        ChoiceGroup size=(ChoiceGroup)field(formClass,"mediaVideoSize").get(form);
        ChoiceGroup rate=(ChoiceGroup)field(formClass,"mediaVideoKbps").get(form);
        check(size.getString(size.getSelectedIndex()).equals("176x144") && rate.getString(rate.getSelectedIndex()).equals("48"),"dropdown lost saved video selection");
        check(((ChoiceGroup)field(formClass,"videoRotateChoice").get(form)).getSelectedIndex()==1
            && ((ChoiceGroup)field(formClass,"photoRotateChoice").get(form)).getSelectedIndex()==2,"dropdown lost saved rotation");
        for(int i=0;i<rate.size();i++)if(rate.getString(i).equals("64"))rate.setSelectedIndex(i,true);
        ((TextField)field(formClass,"mediaMemKb").get(form)).setString("384");
        method(formClass,"readMediaOptions").invoke(form);
        check(Options.mediaVideoKbps()==64 && Options.getString(Options.OPTION_MEDIA_VIDEO_SIZE).equals("176x144"),"dropdown did not save video selection");
        check(Options.getInt(Options.OPTION_VIDEO_ROTATE)==1 && Options.getInt(Options.OPTION_PHOTO_ROTATE)==2
            && Options.getInt(Options.OPTION_MEDIA_MEM_KB)==384,"media rotation or numeric memory save changed");
        System.out.println("PASS: all 11 media choices are dropdowns; saved video/rotation selections and numeric memory field");
    }
    static void bridgeFeatures() throws Exception {
        Class formClass=Class.forName("jimm.OptionsForm");
        Object form=((sun.misc.Unsafe)field(sun.misc.Unsafe.class,"theUnsafe").get(null)).allocateInstance(formClass);
        Form network=new Form("network");field(formClass,"optionsForm").set(form,network);
        method(formClass,"showNetworkOptions").invoke(form);
        check(network.items.size()==9,"network form contains obsolete transport fields or lost encryption settings");
        ((TextField)network.items.elementAt(0)).setString("bridge.example");
        ((TextField)network.items.elementAt(1)).setString("5190");
        ((ChoiceGroup)network.items.elementAt(2)).setSelectedIndex(0,true);
        ((TextField)network.items.elementAt(3)).setString("120");
        ((ChoiceGroup)field(formClass,"encryptionChoiceGroup").get(form)).setSelectedIndex(0,true);
        String psk="000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";
        ((TextField)field(formClass,"encryptionPskTextField").get(form)).setString(psk);
        method(formClass,"readNetworkOptions").invoke(form);
        check(Options.getBoolean(Options.OPTION_ENCRYPTION) && Options.getString(Options.OPTION_ENCRYPTION_PSK).equals(psk),"encryption switch/key not saved");
        Options.save();method(Options.class,"setDefaults").invoke(null);Options.load();
        check(Options.getBoolean(Options.OPTION_ENCRYPTION) && Options.getString(Options.OPTION_ENCRYPTION_PSK).equals(psk),"encryption switch/key lost after RMS reload");
        Options.setBoolean(Options.OPTION_ENCRYPTION,false);
        check(Options.getString(Options.OPTION_SRV_HOST).equals("bridge.example"),"server field no longer saves");
        check(Options.getString(Options.OPTION_SRV_PORT).equals("5190"),"port field no longer saves");
        check(Options.getBoolean(Options.OPTION_KEEP_CONN_ALIVE) && Options.getString(Options.OPTION_CONN_ALIVE_INVTERV).equals("120"),"keepalive fields shifted");

        ContactItem contact=new ContactItem();
        byte[] caps=new byte[16*4+3]; // unknown client, relay, UTF-8, typing, truncated tail
        Arrays.fill(caps,0,16,(byte)0x7f);
        System.arraycopy(Icq.CAP_AIM_SERVERRELAY,0,caps,16,16);
        System.arraycopy(Icq.CAP_UTF8,0,caps,32,16);
        System.arraycopy(Icq.CAP_MTN,0,caps,48,16);
        Icq.parseCapabilities(contact,caps);
        check(contact.hasCapability(Icq.CAPF_AIM_SERVERRELAY) && contact.hasCapability(Icq.CAPF_UTF8_INTERNAL) && contact.hasCapability(Icq.CAPF_TYPING),"protocol abilities lost with client detection");
        Icq.parseCapabilities(contact,null);
        check(contact.getIntValue(ContactItem.CONTACTITEM_CAPABILITIES)==0,"capabilities were not reset");
        Icq.parseCapabilities(contact,Icq.mergeCapabilities(Icq.CAP_MTN,new byte[]{0x13,0x49,0x13,0x4e,0x13}));
        check(contact.hasCapability(Icq.CAPF_AIM_SERVERRELAY) && contact.hasCapability(Icq.CAPF_UTF8_INTERNAL) && contact.hasCapability(Icq.CAPF_TYPING),"mixed short/long capabilities failed");
        Icq.parseCapabilities(contact,Icq.mergeCapabilities(null,new byte[]{0x13,0x4e}));
        check(contact.hasCapability(Icq.CAPF_UTF8_INTERNAL),"short capabilities alone failed");

        new Icq();Socket socket=new Socket();field(Icq.class,"c").set(null,socket);
        method(Icq.class,"setConnected").invoke(null);field(Icq.class,"reqAction").set(null,new Vector());
        Search search=new Search();Search.SearchForm query=search.getSearchForm();
        Form searchForm=(Form)field(query.getClass(),"searchForm").get(query);
        check(searchForm.items.size()==7,"search filters remain or query fields disappeared");
        for(Object item:searchForm.items)check(item instanceof TextField,"search filter remains");
        ((TextField)field(query.getClass(),"keywordSearchTextBox").get(query)).setString("Ceph");
        query.commandAction((Command)field(query.getClass(),"searchCommand").get(query),searchForm);
        SearchAction action=(SearchAction)((Vector)field(Icq.class,"reqAction").get(null)).lastElement();
        method(SearchAction.class,"init").invoke(action);
        ToIcqSrvPacket packet=(ToIcqSrvPacket)socket.packets.lastElement();
        byte[] data=packet.getData();
        check(Util.getWord(data,0)==0x5f05 && packet.getSubcommand()==0x07d0,"search framing changed");
        check(Util.getWord(data,2)==SearchAction.TLV_TYPE_KEYWORD,"search query is not preserved");
        int length=Util.getWord(data,4,false);
        check(data.length==6+length && Util.byteArrayToString(data,8,length-3).equals("Ceph"),"search sends filters or loses query text");
        SplashCanvas.resetLastTask();field(Icq.class,"reqAction").set(null,new Vector());
        System.out.println("PASS: socket settings and keepalive; protocol capabilities; actual search form and query packet without filters");
    }
    static void incomingMessages(String dir) throws Exception {
        Socket socket=new Socket();field(Icq.class,"c").set(null,socket);
        jimm.MainThread.messages.removeAllElements();
        jimm.comm.ActionListener listener=new jimm.comm.ActionListener();
        Method forward=method(jimm.comm.ActionListener.class,"forward",Packet.class);
        for(String name:new String[]{"plain","url","status"}){
            socket.packets.removeAllElements();
            byte[] body=java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(dir,name+".bin"));
            forward.invoke(listener,new SnacPacket(4,7,0,new byte[0],body));
            if(name.equals("status")){
                check(socket.packets.isEmpty() && jimm.MainThread.messages.size()==2,"retired status request was answered or displayed");
                continue;
            }
            Message message=(Message)jimm.MainThread.messages.lastElement();
            check(message.getText().equals(name.equals("plain")?"Привет":"[видео]"),"incoming UTF-8 text lost");
            if(name.equals("plain")){
                check(message.getAttachKind()==2 && message.getAttachToken().length==16,"video attachment marker lost");
                check(message.getMessageRef()!=null && message.getMessageRef()[0]==(byte)0x80,"native message reference lost or narrowed");
            }else{
                check(message instanceof UrlMessage && ((UrlMessage)message).getUrl().equals("http://bridge.example/v/token"),"browser URL lost");
                check(message.getMessageRef()!=null && message.getMessageRef()[7]==44,"URL message reference lost");
            }
            check(socket.packets.size()==1,"incoming message no longer acknowledged exactly once");
            SnacPacket ack=(SnacPacket)socket.packets.lastElement();byte[] data=ack.getData();
            check(ack.getFamily()==4 && ack.getCommand()==0x0b,"wrong delivery ACK");
            for(int i=0;i<8;i++)check(data[i]==i,"delivery cookie changed");
        }
        byte[] own=java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(dir,"own.bin"));
        forward.invoke(listener,new SnacPacket(4,0x15,0,new byte[0],own));
        check(jimm.MainThread.refUin.equals("1000070") && jimm.MainThread.ref[0]==(byte)0x80,"own message ID was not routed to its chat");
        System.out.println("PASS: actual server channel-2 text, video token, browser URL and delivery ACK; status requests ignored");
    }
    static void preferences() throws Exception {
        Field f=field(Options.class,"options");f.set(null,new Hashtable());
        method(Options.class,"setDefaults").invoke(null);
        int[] retired={7,17,18,34,83,92,96,97,102,103,158,159,161};
        Hashtable values=(Hashtable)f.get(null);
        for(int id:retired) values.put(new Integer(id),id<64?"old":id<128?new Integer(5):Boolean.TRUE);
        values.put(new Integer(83),new Integer(1)); // old HTTP transport
        Options.setInt(Options.OPTION_EXT_CLKEY1,14); // retired status request
        Options.setInt(Options.OPTION_EXT_CLKEY2,Options.HOTKEY_UP);
        Options.setLong(Options.OPTION_ONLINE_STATUS,ContactList.STATUS_DND);
        Options.setString(field(Options.class,"OPTION_UIN1").getInt(null),"100500");
        Options.setString(Options.OPTION_MEDIA_VIDEO_SIZE,"176x144");
        Options.setInt(Options.OPTION_MEDIA_VIDEO_KBPS,48);
        Options.save();f.set(null,new Hashtable());method(Options.class,"setDefaults").invoke(null);Options.load();
        values=(Hashtable)f.get(null);
        for(int id:retired)check(!values.containsKey(new Integer(id)),"obsolete RMS option survived: "+id);
        check(Options.getInt(Options.OPTION_EXT_CLKEY1)==Options.HOTKEY_NONE,"retired hotkey survived");
        check(Options.getInt(Options.OPTION_EXT_CLKEY2)==Options.HOTKEY_UP,"other hotkey changed");
        check(Options.getLong(Options.OPTION_ONLINE_STATUS)==ContactList.STATUS_DND,"RMS manual status changed");
        check(Options.getString(Options.OPTION_UIN).equals("100500"),"RMS account lost");
        check(Options.getString(Options.OPTION_MEDIA_VIDEO_SIZE).equals("176x144") && Options.mediaVideoKbps()==48,"RMS media lost");
        Options.save();
        System.out.println("PASS: old preferences drop retired IDs and retain account, manual status and video settings");
    }
    public static void main(String[] args) throws Exception {
        try {preferences();cancelScreen();statusMenu();mediaOptions();bridgeFeatures();incomingMessages(args[0]);}
        finally {
            Jimm.getTimerRef().cancel();
            ((Timer)field(ContactList.class,"iconTimer").get(null)).cancel();
            ((Timer)field(ContactList.class,"soundTimer").get(null)).cancel();
        }
    }
}
