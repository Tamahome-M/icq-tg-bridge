package DrawControls;

import java.lang.management.ManagementFactory;
import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import jimm.*;

public final class TreeMemoryTest {
    static boolean baseline;
    static final int ROUNDS=4096;
    static final com.sun.management.ThreadMXBean meter=(com.sun.management.ThreadMXBean)ManagementFactory.getThreadMXBean();
    static volatile Object sink;
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    static void invoke(Class c,String name)throws Exception{Method m=c.getDeclaredMethod(name);m.setAccessible(true);m.invoke(null);}
    static long bytes(){return meter.getThreadAllocatedBytes(Thread.currentThread().getId());}
    static final class Compare implements VirtualTreeCommands {
        int comparisons;
        public int vtCompareNodes(TreeNode a,TreeNode b){comparisons++;return ((Integer)a.getData()).compareTo((Integer)b.getData());}
        public void vtGetItemDrawData(TreeNode node,ListItem item){}
        public void vtNodeClicked(TreeNode node){}
    }
    static void sorting()throws Exception {
        Compare compare=new Compare();Random random=new Random(118);
        for(int round=0;round<100;round++){
            TreeNode root=new TreeNode(null);Vector expected=new Vector();
            for(int i=0;i<round;i++){TreeNode node=new TreeNode(Integer.valueOf(random.nextInt(20)));root.addItem(node);expected.add(node);}
            Collections.sort(expected,new Comparator(){public int compare(Object a,Object b){return ((Integer)((TreeNode)a).getData()).compareTo((Integer)((TreeNode)b).getData());}});
            Vector backing=root.items;root.sort(compare);
            for(int i=0;i<round;i++){
                check(((TreeNode)expected.get(i)).getData().equals(root.elementAt(i).getData()),"random group sort order changed");
                if(!baseline)check(expected.get(i)==root.elementAt(i),"equal-name contacts lose stable order");
            }
            if(!baseline)check(backing==root.items,"sorting replaces the group's container");
        }
        TreeNode root=new TreeNode(null);for(int i=0;i<97;i++)root.addItem(new TreeNode(Integer.valueOf(i)));
        TreeNode leaf=new TreeNode(null),empty=new TreeNode(null);empty.items=new Vector();
        for(int i=0;i<64;i++){root.sort(compare);leaf.sort(compare);empty.sort(compare);}
        compare.comparisons=0;long before=bytes();
        for(int i=0;i<ROUNDS;i++){root.sort(compare);leaf.sort(compare);empty.sort(compare);sink=root;}
        long allocated=bytes()-before;int calls=compare.comparisons;
        System.out.println("METRIC 4096 sorted 97-contact groups plus empty/leaf: allocated="+allocated+", comparisons="+calls);
        if(!baseline){check(allocated==0,"sort allocates another Vector/backing array");check(calls==ROUNDS*96,"sorted neighbours still require a full insertion search");}
        // Move the last contact to the front without replacing any node.
        TreeNode moved=root.elementAt(96);root.removeItem(96);root.insertChild(moved,0);root.sort(compare);
        for(int i=0;i<97;i++)check(((Integer)root.elementAt(i).getData()).intValue()==i,"nearly-sorted group lost a contact");
        check(root.elementAt(96)==moved,"sort replaces moved node identity");
        System.out.println("PASS: empty/leaf, random and nearly-sorted groups retain nodes and correct order"+(baseline?"":"; stable equal-name order and zero allocation for unchanged groups"));
    }
    static TextItem item(TextList list,int index)throws Exception{
        Vector lines=(Vector)field(TextList.class,"lines").get(list);return ((TextLine)lines.get(index)).elementAt(0);
    }
    static void colours()throws Exception {
        final int incoming=0x01000000,outgoing=0x02000000,other=0x03000000;
        TextList list=new TextList("theme");
        list.addBigText("in",incoming,Font.STYLE_BOLD,1);list.doCRLF(1);
        list.addBigText("out",outgoing,Font.STYLE_PLAIN,2);list.doCRLF(2);
        list.addBigText("literal",0x123456,Font.STYLE_PLAIN,3);list.doCRLF(3);
        list.setIndexedColor(incoming,0x112233);list.setIndexedColor(outgoing,0x445566);
        check(item(list,0).getColor()==0x112233 && item(list,1).getColor()==0x445566 && item(list,2).getColor()==0x123456,"theme update recolours wrong message");
        check(item(list,0).font==Font.STYLE_BOLD,"theme update loses message font");
        list.setIndexedColor(incoming,0x778899);check(item(list,0).getColor()==0x778899,"existing incoming rows keep old theme");
        list.addBigText("new",incoming,Font.STYLE_PLAIN,4);list.doCRLF(4);
        check(item(list,3).getColor()==0x778899,"new message does not use current indexed colour");
        list.setIndexedColor(other,0xaabbcc);list.addBigText("other",other,Font.STYLE_PLAIN,5);list.doCRLF(5);
        check(item(list,4).getColor()==0xaabbcc,"third indexed colour is unsupported");
        list.clear();list.addBigText("after clear",outgoing,Font.STYLE_PLAIN,6);
        check(item(list,0).getColor()==0x445566,"clearing text forgets the colour scheme");
        Object colours=field(TextList.class,"indexedColors").get(list);
        int containers=0,entries=0,boxed=0;
        if(colours instanceof Hashtable){containers=2;entries=((Hashtable)colours).size();boxed=entries*2;}
        else if(colours!=null)containers=1;
        System.out.println("METRIC 3 indexed colours: containers="+containers+", map entries="+entries+", boxed integers="+boxed);
        TextList plain=new TextList(null);
        if(!baseline)check(field(TextList.class,"indexedColors").get(plain)==null,"plain screen eagerly allocates a colour container");
        // Repeated unchanged theme applications should allocate nothing.
        for(int i=0;i<64;i++){list.setIndexedColor(incoming,0x778899);list.setIndexedColor(outgoing,0x445566);}
        long before=bytes();for(int i=0;i<ROUNDS;i++){list.setIndexedColor(incoming,0x778899);list.setIndexedColor(outgoing,0x445566);}
        long allocated=bytes()-before;System.out.println("METRIC 4096 unchanged incoming/outgoing themes: allocated="+allocated);
        if(!baseline)check(allocated==0,"unchanged themes still box keys");
        for(int i=0;i<64;i++)list.addBigText("x",incoming,Font.STYLE_PLAIN,6);
        before=bytes();for(int i=0;i<ROUNDS;i++)list.addBigText("x",incoming,Font.STYLE_PLAIN,6);
        allocated=bytes()-before;System.out.println("METRIC 4096 indexed text fragments: allocated="+allocated);
        check(list.getTextByIndex(0,false,6).startsWith("after clear"),"indexed layout loses prior text");
        System.out.println("PASS: existing/new incoming/outgoing/literal colours, font, third index, and theme retained after clearing text");
    }
    static final class CountedContact extends ContactItem {
        static int strings;
        CountedContact(int id){super(id,1,String.valueOf(1000000+id),"Contact "+(1000+id),false,true);}
        public synchronized String getStringValue(int key){if(key==CONTACTITEM_UIN)strings++;return super.getStringValue(key);}
    }
    static void contacts()throws Exception {
        Options.setBoolean(Options.OPTION_USE_GROUPS,false);Options.setBoolean(Options.OPTION_CL_HIDE_OFFLINE,false);
        Options.setBoolean(Options.OPTION_CL_HIDE_EMPTY,false);new ContactList();
        Vector contacts=new Vector();for(int i=1;i<=97;i++)contacts.add(new CountedContact(i));
        field(ContactList.class,"cItems").set(null,contacts);field(ContactList.class,"gItems").set(null,new Vector());
        ContactList.optionsChanged(true,true);invoke(ContactList.class,"buildTree");invoke(ContactList.class,"sortAll");
        VirtualTree tree=(VirtualTree)ContactList.getVisibleContactListRef();ContactItem last=(ContactItem)contacts.lastElement();
        for(int i=0;i<64;i++)ContactList.contactChanged(last,false,false);
        CountedContact.strings=0;long before=bytes();
        for(int i=0;i<ROUNDS;i++)ContactList.contactChanged(last,false,false);
        long allocated=bytes()-before;
        System.out.println("METRIC 4096 last-contact updates in 97-contact group: UIN strings="+CountedContact.strings+", allocated="+allocated);
        if(!baseline)check(CountedContact.strings==0,"contact lookup still stringifies each sibling UIN");
        TreeNode original=tree.findNodeByData(null,last);ContactItem sameUin=new CountedContact(97);
        ContactList.contactChanged(sameUin,false,false);
        // The equivalent object is absent from cItems, so its existing node
        // is removed rather than adding a duplicate under another identity.
        check(tree.findNodeByData(null,last)==null && tree.getRoot().size()==96,"same UIN cannot locate/remove existing node");
        check(original!=null,"test contact never existed in the tree");
        System.out.println("PASS: real contactChanged matches another object representing the same UIN"+(baseline?"":" without stringifying numeric UINs"));
    }
    public static void main(String[] args)throws Exception{
        baseline="baseline".equals(args[0]);meter.setThreadAllocatedMemoryEnabled(true);
        try{
            field(Options.class,"options").set(null,new Hashtable());invoke(Options.class,"setDefaults");
            Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
            sorting();colours();contacts();
        }finally{
            Jimm.getTimerRef().cancel();
            Object canvas=field(VirtualList.class,"virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
        System.exit(0);
    }
}
