package jimm;

import java.io.ByteArrayOutputStream;
import javax.microedition.lcdui.*;
import DrawControls.VirtualList;
import jimm.comm.*;
import jimm.util.ResourceBundle;

/** Holds the source network reference, without copying message text to a clipboard. */
public final class NativeQuote extends Action
{
    public static final Command cmdSelect = new Command(ResourceBundle.getString("quote"), Command.ITEM, 3);
    public static final Command cmdPaste = new Command(ResourceBundle.getString("quote_here"), Command.ITEM, 3);
    private static String selectedUin;
    private static byte[] selectedRef;
    private static NativeQuote pending;
    private final String source, target;
    private final byte[] ref;
    private final int requestId;
    private long started;
    private boolean done, notified;

    private NativeQuote(String target)
    {
        super(false, true);
        this.source = selectedUin;
        this.ref = selectedRef;
        this.target = target;
        requestId = Util.getCounter();
    }

    public static void select(String uin, byte[] ref)
    {
        if (ref == null || ref.length != 8) return;
        selectedUin = uin;
        selectedRef = new byte[8];
        System.arraycopy(ref, 0, selectedRef, 0, 8);
        refreshMenus();
    }

    public static void updateMenu(VirtualList list, byte[] ref)
    {
        list.removeCommandEx(cmdSelect);
        list.removeCommandEx(cmdPaste);
        if (ref != null) list.addCommandEx(cmdSelect, VirtualList.MENU_TYPE_RIGHT);
        if (selectedRef != null && pending == null) list.addCommandEx(cmdPaste, VirtualList.MENU_TYPE_RIGHT);
    }

    public static void paste(String uin)
    {
        if (selectedRef == null || pending != null) return;
        NativeQuote action = new NativeQuote(uin);
        pending = action;
        refreshMenus();
        try { Icq.requestAction(action); }
        catch (JimmException e) { action.finish(ResourceBundle.getString("quote_failed")); }
    }

    public static void disconnected()
    {
        if (pending != null) pending.finish(ResourceBundle.getString(pending.started > 0 ? "quote_timeout" : "quote_failed"));
    }

    private static void refreshMenus()
    {
        ChatHistory.refreshQuoteMenus();
        HistoryViewer.refreshQuoteMenu();
    }

    protected void init() throws JimmException
    {
        started = System.currentTimeMillis();
        ByteArrayOutputStream body = new ByteArrayOutputStream();
        byte[] dst = Util.stringToByteArray(target), src = Util.stringToByteArray(source);
        body.write(dst.length); body.write(dst, 0, dst.length);
        body.write(src.length); body.write(src, 0, src.length);
        body.write(ref, 0, ref.length);
        try { Icq.sendPacket(new SnacPacket(0x10, 0x09, requestId, new byte[0], body.toByteArray())); }
        catch (JimmException e) { finish(ResourceBundle.getString("quote_failed")); }
    }

    protected boolean forward(Packet packet) throws JimmException
    {
        if (!(packet instanceof SnacPacket)) return false;
        SnacPacket reply = (SnacPacket)packet;
        if (reply.getFamily() != 0x10 || reply.getReference() != requestId) return false;
        if (reply.getCommand() == 1)
        {
            finish(ResourceBundle.getString("quote_failed"));
            return true;
        }
        if (reply.getCommand() != 0x0a) return false;
        byte[] data = reply.getDataRef();
        if (data.length == 0) finish(ResourceBundle.getString("quote_failed"));
        else finish(data[0] == 0 ? null : (data.length > 1 ? Util.byteArrayToString(data, 1, data.length - 1, true) : ResourceBundle.getString("quote_failed")));
        return true;
    }

    private void finish(String error)
    {
        if (notified) return;
        notified = true;
        done = true;
        MainThread.nativeQuoteResult(this, error);
    }

    public boolean isCompleted() { return done; }
    public boolean isError()
    {
        if (!done && started > 0 && System.currentTimeMillis() - started > 60000)
            finish(ResourceBundle.getString("quote_timeout"));
        return false;
    }

    public void showResult(String error)
    {
        if (pending != this) return;
        pending = null;
        // Keep a newly selected source; success only consumes this operation's selection.
        if (error == null && selectedRef == ref) { selectedRef = null; selectedUin = null; }
        refreshMenus();
        Alert alert = new Alert(ResourceBundle.getString("quote"),
                error == null ? ResourceBundle.getString("quote_done") : error,
                null, error == null ? AlertType.INFO : AlertType.ERROR);
        alert.setTimeout(4000);
        Displayable screen = Jimm.display.getCurrent();
        if (screen != null) Jimm.display.setCurrent(alert, screen);
        else Jimm.display.setCurrent(alert);
    }
}
