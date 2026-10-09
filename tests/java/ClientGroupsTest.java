import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import jimm.*;

public final class ClientGroupsTest {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    static void invoke(Class c,String name)throws Exception{Method m=c.getDeclaredMethod(name);m.setAccessible(true);m.invoke(null);}
    static ContactListGroupItem group(String name)throws Exception{
        for(String key:new String[]{"gItems","synItems"}){
            Vector items=(Vector)field(ContactList.class,key).get(null);
            for(int i=0;i<items.size();i++){
                ContactListGroupItem g=(ContactListGroupItem)items.elementAt(i);
                if(g.getName().equals(name))return g;
            }
        }
        throw new AssertionError("group missing: "+name);
    }
    static void counts(String name,int online,int total)throws Exception{
        ContactListGroupItem g=group(name);
        check(g.getOnlineCount()==online && field(ContactListGroupItem.class,"totalCount").getInt(g)==total,
                name+" expected "+online+"/"+total+", got "+g.getText());
    }
    static ContactItem contact(int group,String uin,boolean added){
        ContactItem c=new ContactItem(Integer.parseInt(uin),group,uin,uin,false,added);
        c.setIntValue(ContactItem.CONTACTITEM_STATUS,ContactList.STATUS_OFFLINE);return c;
    }
    static void rebuild()throws Exception{
        ContactList.optionsChanged(true,true);invoke(ContactList.class,"buildTree");invoke(ContactList.class,"sortAll");
    }
    public static void main(String[] args){
        try{run();}catch(Throwable error){error.printStackTrace();System.exit(1);}
    }
    static void run()throws Exception{
        field(Options.class,"options").set(null,new Hashtable());invoke(Options.class,"setDefaults");
        Options.setBoolean(Options.OPTION_USE_GROUPS,true);
        Options.setBoolean(Options.OPTION_CL_HIDE_OFFLINE,false);
        Options.setBoolean(Options.OPTION_CL_HIDE_EMPTY,false);
        Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
        new ContactList();
        Vector groups=new Vector();
        groups.addElement(new ContactListGroupItem(1,"Telegram/Work"));
        groups.addElement(new ContactListGroupItem(2,"Telegram/Work/Forum"));
        groups.addElement(new ContactListGroupItem(3,"Telegram/Personal/People"));
        groups.addElement(new ContactListGroupItem(4,"MAX"));
        Vector contacts=new Vector();
        ContactItem one=contact(1,"1000001",true),two=contact(2,"1000002",true);
        contacts.addElement(one);contacts.addElement(two);
        contacts.addElement(contact(3,"1000003",true));contacts.addElement(contact(4,"1000004",true));
        field(ContactList.class,"gItems").set(null,groups);field(ContactList.class,"cItems").set(null,contacts);
        field(ContactList.class,"onlineCounter").setInt(null,0);rebuild();
        counts("Telegram",0,3);counts("Telegram/Work",0,2);counts("Telegram/Personal",0,1);counts("MAX",0,1);
        String stale=group("Telegram").getText();
        ContactList.update("1000002",ContactList.STATUS_ONLINE);
        counts("Telegram/Work/Forum",1,1);counts("Telegram/Work",1,2);counts("Telegram",1,3);counts("MAX",0,1);
        check(group("Telegram").getText().equals("Telegram (1/3)") && !stale.equals(group("Telegram").getText()),"parent label cache stays offline");
        ContactList.update("1000001",ContactList.STATUS_ONLINE);counts("Telegram",2,3);counts("Telegram/Work",2,2);
        ContactList.update("1000002",ContactList.STATUS_AWAY);counts("Telegram",2,3);
        ContactList.update("1000002",ContactList.STATUS_OFFLINE);counts("Telegram",1,3);counts("Telegram/Work",1,2);
        ContactList.update("1000003",ContactList.STATUS_ONLINE);counts("Telegram/Personal",1,1);counts("Telegram",2,3);
        ContactList.update("1000004",ContactList.STATUS_ONLINE);counts("MAX",1,1);counts("Telegram",2,3);
        check(field(ContactList.class,"onlineCounter").getInt(null)==3,"global online count double counts ancestors");
        ContactItem added=contact(2,"1000005",false);added.setIntValue(ContactItem.CONTACTITEM_STATUS,ContactList.STATUS_ONLINE);
        ContactList.addContactItem(added);counts("Telegram",3,4);counts("Telegram/Work",2,3);counts("Telegram/Work/Forum",1,2);
        ContactList.removeContactItem(added);counts("Telegram",2,3);counts("Telegram/Work",1,2);counts("Telegram/Work/Forum",0,1);
        rebuild();counts("Telegram",2,3);counts("Telegram/Work",1,2);
        ContactList.update("1000002",ContactList.STATUS_ONLINE);counts("Telegram",3,3);counts("Telegram/Work",2,2);
        // Moving groups between hierarchies on a rebuild must drop old parents.
        group("Telegram/Work/Forum").setName("MAX/Forum");rebuild();
        counts("Telegram",2,2);counts("MAX",2,2);
        ContactList.update("1000002",ContactList.STATUS_OFFLINE);counts("Telegram",2,2);counts("MAX",1,2);
        Options.setBoolean(Options.OPTION_CL_HIDE_OFFLINE,true);
        check(group("Telegram").getText().equals("Telegram"),"legacy hidden-offline display changed");
        System.out.println("PASS: real nested contact tree; initial offline roster, online/away/offline, real and synthetic ancestors, cached labels, independent networks, add/remove, rebuild and moved parent; global count stays exact");
        System.exit(0);
    }
}
