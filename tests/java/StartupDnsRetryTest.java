import java.lang.reflect.Field;
import jimm.Threads;
import jimm.comm.Icq;
import jimm.comm.connections.StartupDns;

public class StartupDnsRetryTest
{
    private static Field field(String name) throws Exception
    {
        Field result = Threads.class.getDeclaredField(name);
        result.setAccessible(true); return result;
    }
    public static void main(String[] args) throws Exception
    {
        String mode = args[0];
        if (mode.startsWith("sleeping_") || "replacement".equals(mode))
        {
            jimm.Options.auto = true;
            field("reconnectPending").setBoolean(null, true);
            Threads old = new Threads(Threads.TYPE_RECONNECT);
            field("delay").setLong(old, 150);
            Thread worker = new Thread(old); worker.start();
            Thread.sleep(25);
            Threads.cancelReconnect();
            StartupDns.next = false;
            if ("sleeping_cancel".equals(mode)) Icq.disconnected = true;
            if ("replacement".equals(mode))
            {
                Icq.failImmediately = false;
                Threads.reconnect(0);
                if (Icq.calls != 0 || !field("reconnectPending").getBoolean(null))
                    throw new AssertionError("replacement must wait for the sole old scheduler");
            }
            worker.join(2000);
            if (worker.isAlive() || Icq.calls != 0 || field("reconnectPending").getBoolean(null))
                throw new AssertionError("stale scheduler survived " + mode);
            Threads.checkReconnect();
            long until = System.currentTimeMillis() + 1500;
            while ("replacement".equals(mode) && Icq.calls < 1 && System.currentTimeMillis() < until) Thread.sleep(5);
            Thread.sleep(20);
            if (Icq.calls != ("replacement".equals(mode) ? 1 : 0))
                throw new AssertionError("wrong replacement count " + Icq.calls);
            System.out.println("PASS startup DNS retry " + mode); return;
        }
        // Reproduce an immediate network failure on the new ICQ worker while
        // its previous reconnect scheduler is still inside Icq.connect().
        field("reconnectPending").setBoolean(null, true);
        if ("regular".equals(mode)) StartupDns.next = false;
        if (mode.startsWith("auto")) { StartupDns.next = false; jimm.Options.auto = true; }
        Threads scheduler = new Threads(Threads.TYPE_RECONNECT);
        field("delay").setLong(scheduler, 0);
        scheduler.run();
        long retry = field("retryAt").getLong(null);
        if ("regular".equals(mode))
        {
            if (retry != 0) throw new AssertionError("regular auto-off retry must not be added");
        }
        else
        {
            if (retry == 0) throw new AssertionError("instant next-address failure lost while reconnectPending");
            if ("cancel".equals(mode)) Icq.disconnected = true;
            if ("fatal".equals(mode)) StartupDns.next = false;
            if ("connected".equals(mode)) { StartupDns.next = false; Icq.connected = true; }
            if ("auto_cancel".equals(mode)) { Threads.cancelReconnect(); Icq.disconnected = true; }
            if ("auto_fatal".equals(mode)) Threads.cancelReconnect();
            Threads.checkReconnect();
            long until = System.currentTimeMillis() + 1500;
            boolean retryExpected = "next".equals(mode) || "auto".equals(mode);
            while (retryExpected && Icq.calls < 2 && System.currentTimeMillis() < until) Thread.sleep(5);
            Thread.sleep(20);
            int expected = retryExpected ? 2 : 1;
            if (Icq.calls != expected) throw new AssertionError("unexpected reconnect after " + mode + ": " + Icq.calls);
            if (field("retryAt").getLong(null) != 0) throw new AssertionError("retry must be consumed once");
        }
        System.out.println("PASS startup DNS retry " + mode);
    }
}
