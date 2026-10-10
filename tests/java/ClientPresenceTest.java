import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.*;
import jimm.*;
import jimm.comm.*;

public final class ClientPresenceTest {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    static void invoke(Class c,String name)throws Exception{Method m=c.getDeclaredMethod(name);m.setAccessible(true);m.invoke(null);}
    static class Rows extends Vector {int rebuilds;public synchronized void removeAllElements(){rebuilds++;super.removeAllElements();}}
    static VirtualTree tree;static Vector contacts;static Rows rows;
    static byte[] read(String path)throws Exception{
        FileInputStream in=new FileInputStream(path);byte[] data=new byte[(int)new File(path).length()];
        new DataInputStream(in).readFully(data);in.close();return data;
    }
    static void reset(boolean hidden)throws Exception{
        Options.setBoolean(Options.OPTION_USE_GROUPS,true);
        Options.setBoolean(Options.OPTION_CL_HIDE_OFFLINE,hidden);
        Options.setBoolean(Options.OPTION_CL_HIDE_EMPTY,false);
        Options.setInt(Options.OPTION_CL_SORT_BY,ContactList.SORT_BY_STATUS);
        new ContactList();
        Vector groups=new Vector();groups.addElement(new ContactListGroupItem(1,"Telegram/Work/Forum"));groups.addElement(new ContactListGroupItem(2,"MAX"));
        contacts=new Vector();
        for(int i=0;i<97;i++){
            String uin=String.valueOf(1000001+i),name="Contact "+(1000+i);
            ContactItem c=new ContactItem(Integer.parseInt(uin),i<65?1:2,uin,name,false,true);
            c.setIntValue(ContactItem.CONTACTITEM_STATUS,ContactList.STATUS_OFFLINE);contacts.addElement(c);
        }
        field(ContactList.class,"gItems").set(null,groups);field(ContactList.class,"cItems").set(null,contacts);
        field(ContactList.class,"onlineCounter").setInt(null,0);
        ContactList.optionsChanged(true,true);invoke(ContactList.class,"buildTree");invoke(ContactList.class,"sortAll");
        tree=(VirtualTree)ContactList.getVisibleContactListRef();
        for(Enumeration e=((Hashtable)field(ContactList.class,"gNodes").get(null)).elements();e.hasMoreElements();)
            tree.setExpandFlag((TreeNode)e.nextElement(),true);
        Method size=VirtualTree.class.getDeclaredMethod("getSize");size.setAccessible(true);size.invoke(tree);
        tree.activate(Jimm.display);
        rows=new Rows();rows.addAll((Vector)field(VirtualTree.class,"drawItems").get(tree));
        field(VirtualTree.class,"drawItems").set(tree,rows);
        Display.queued.removeAllElements();((Vector)field(MainThread.class,"mainThreadTasks").get(null)).removeAllElements();
    }
    static int status(int i){return i%10==0?ContactList.STATUS_OFFLINE:i%3==0?ContactList.STATUS_AWAY:ContactList.STATUS_ONLINE;}
    static void sorted(TreeNode root){
        ContactItem previous=null;
        for(int i=0;i<root.size();i++){
            Object data=root.elementAt(i).getData();
            if(data instanceof ContactItem){
                ContactItem current=(ContactItem)data;
                if(previous!=null)check(previous.getSortWeight()<current.getSortWeight()
                    || previous.getSortWeight()==current.getSortWeight() && previous.getSortText().compareTo(current.getSortText())<=0,"presence sort order changed");
                previous=current;
            } else sorted(root.elementAt(i));
        }
    }
    static int visible(TreeNode root){int count=0;for(int i=0;i<root.size();i++){
        TreeNode node=root.elementAt(i);count+=node.getData() instanceof ContactItem?1:visible(node);
    }return count;}
    static void verify(boolean hidden)throws Exception{
        int online=0;for(int i=0;i<97;i++){
            ContactItem c=(ContactItem)contacts.elementAt(i);
            check(c.getIntValue(ContactItem.CONTACTITEM_STATUS)==status(i),"contact status lost at "+i);
            if(status(i)!=ContactList.STATUS_OFFLINE)online++;
            check((c.getIntValue(ContactItem.CONTACTITEM_CAPABILITIES)&Icq.CAPF_TYPING)!=0,"typing capability lost");
            check(Arrays.equals(c.getBytesArray(ContactItem.CONTACTITEM_BUDDYICON_HASH),new byte[]{7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7}),"avatar hash lost");
            check(c.getIntValue(ContactItem.CONTACTITEM_ONLINE)==3600,"online time lost");
        }
        check(field(ContactList.class,"onlineCounter").getInt(null)==online,"global online count changed");
        check(visible(tree.getRoot())==(hidden?online:97),"hidden offline membership changed");
        sorted(tree.getRoot());
        if(!hidden){
            Vector syn=(Vector)field(ContactList.class,"synItems").get(null);
            for(int i=0;i<syn.size();i++){
                ContactListGroupItem group=(ContactListGroupItem)syn.elementAt(i);
                if(group.getName().equals("Telegram"))check(group.getOnlineCount()==58,"parent online count lost");
            }
        }
    }
    static void dispatch(byte[] data)throws Exception{
        Method method=ActionListener.class.getDeclaredMethod("forward",Packet.class);method.setAccessible(true);
        method.invoke(new ActionListener(),new SnacPacket(3,11,1,new byte[0],data));
    }
    static void run(String[] args)throws Exception{
        field(Options.class,"options").set(null,new Hashtable());invoke(Options.class,"setDefaults");
        Constructor constructor=MainThread.class.getDeclaredConstructor();constructor.setAccessible(true);constructor.newInstance();
        byte[] initial=read(args[0]),departed=read(args[1]);
        reset(false);
        for(int i=0;i<97;i++)ContactList.update(String.valueOf(1000001+i),status(i));
        int individual=rows.rebuilds;Display.flush();
        reset(false);TreeNode selected=tree.findNodeByData(null,contacts.elementAt(40));tree.setCurrentItem(selected);rows.rebuilds=0;
        dispatch(initial);
        check(Display.queued.size()==1 && ((Vector)field(MainThread.class,"mainThreadTasks").get(null)).size()==2,"one packet produced per-contact UI tasks");
        check(((ContactItem)contacts.elementAt(1)).getIntValue(ContactItem.CONTACTITEM_STATUS)==ContactList.STATUS_OFFLINE,"comm thread updated UI state");
        Display.flush();verify(false);
        check(tree.getCurrentItem()==selected,"selected contact jumped during initial statuses");
        check(rows.rebuilds==1 && individual>=80,"batch still rebuilds tree per contact: "+rows.rebuilds);
        check(Display.queued.isEmpty(),"per-contact caption callbacks survived the batch");
        System.out.println("METRIC actual expanded tree: 97 statuses, visible-list rebuilds "+individual+" -> "+rows.rebuilds);
        reset(false);
        DataInputStream packets=new DataInputStream(new ByteArrayInputStream(read(args[2])));
        int packetCount=0;
        while(packets.available()!=0){
            byte[] packet=new byte[packets.readUnsignedShort()];packets.readFully(packet);
            dispatch(packet);Display.flush();packetCount++;
        }
        verify(false);check(packetCount==5 && rows.rebuilds==5,"bounded initial packets still rebuild per contact");
        System.out.println("METRIC bridge-sized batches: 97 statuses, five <=20-contact packets, visible-list rebuilds "+individual+" -> "+rows.rebuilds);
        // A live away/online change must reorder within the online contacts too.
        ContactList.update("1000002",ContactList.STATUS_AWAY);sorted(tree.getRoot());
        ContactList.update("1000002",ContactList.STATUS_ONLINE);sorted(tree.getRoot());
        PresenceUpdate.apply(departed,false);check(field(ContactList.class,"onlineCounter").getInt(null)==0,"departed batch count wrong");
        check(((ContactItem)contacts.elementAt(1)).getBytesArray(ContactItem.CONTACTITEM_BUDDYICON_HASH)[0]==7,"offline cleared avatar hash");
        reset(true);PresenceUpdate.apply(initial,true);verify(true);
        PresenceUpdate.apply(departed,false);check(visible(tree.getRoot())==0,"offline nodes stayed visible");
        reset(false);
        try{PresenceUpdate.apply(Arrays.copyOf(initial,initial.length-1),true);throw new AssertionError("truncated TLV accepted");}
        catch(JimmException expected){check(!expected.isCritical(),"malformed status disconnected main session");}
        check(field(ContactList.class,"presenceDepth").getInt(null)==0 && ((Vector)field(ContactList.class,"presenceGroups").get(null)).isEmpty(),"malformed batch retained lock/nodes");
        int before=Canvas.repaints;tree.setCaption("after error");check(Canvas.repaints>before,"malformed batch left tree repaint locked");
        // In-place capability ranges must agree with the old expand/merge path.
        byte[] old=new byte[32];System.arraycopy(Icq.CAP_MTN,0,old,0,16);System.arraycopy(Icq.CAP_UTF8,0,old,16,16);
        byte[] shortCaps={0x13,0x49,0x13,0x4E,0x12,0x34};byte[] frame=new byte[60];System.arraycopy(old,0,frame,3,32);System.arraycopy(shortCaps,0,frame,40,6);
        ContactItem first=(ContactItem)contacts.elementAt(0),second=(ContactItem)contacts.elementAt(1);
        Icq.parseCapabilities(first,Icq.mergeCapabilities(old,shortCaps));Icq.parseCapabilities(second,frame,3,32,40,6);
        check(first.getIntValue(ContactItem.CONTACTITEM_CAPABILITIES)==second.getIntValue(ContactItem.CONTACTITEM_CAPABILITIES),"range capabilities differ from legacy expansion");
        PresenceUpdate.apply(read(args[3]),true);
        check(second.getIntValue(ContactItem.CONTACTITEM_IDLE)==37
            && second.getIntValue(ContactItem.CONTACTITEM_SIGNON)==(int)Util.gmtTimeToLocalTime(1000),"idle/signon TLVs changed");
        System.out.println("PASS: actual ActionListener/UI/tree handle batched and live presence, exact status/capabilities/avatars/counters, sorted groups, preserved cursor, offline filtering and malformed-batch cleanup");
    }
    public static void main(String[] args){try{run(args);}catch(Throwable error){error.printStackTrace();System.exit(1);}finally{Jimm.getTimerRef().cancel();}System.exit(0);}
}
