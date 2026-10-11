import java.lang.reflect.Field;
import jimm.ConnLog;
import jimm.Jimm;
import jimm.JimmException;
import jimm.Options;
import jimm.TimerTasks;
import jimm.comm.Icq;
import jimm.comm.Packet;
import jimm.comm.connections.Connection;

/** Real keepalive tasks; one run represents one configured ping interval. */
public final class ClientPingTest {
    static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    static Field field(String name) throws Exception {
        Field f = Icq.class.getDeclaredField(name); f.setAccessible(true); return f;
    }
    static void set(String name, Object value) throws Exception { field(name).set(null, value); }
    static final class Socket extends Connection {
        int pings, closes;
        public void sendPacket(Packet packet) {
            byte[] bytes = packet.toByteArray();
            check(bytes.length == 6 && bytes[1] == 5, "watchdog sent a non-keepalive packet");
            pings++;
        }
        public void forceDisconnect() { closes++; }
    }
    static final class Session {
        final Thread owner = new Thread();
        final Socket socket = new Socket();
        final TimerTasks timer = new TimerTasks(TimerTasks.ICQ_KEEPALIVE, owner, socket);
        Session(int limit) throws Exception {
            Icq.disconnect(true);
            Options.limit = limit; Options.keepalive = true;
            JimmException.errors = 0; ConnLog.last = null;
            set("thread", owner); set("c", socket); set("connected", true);
            set("keepAliveTimerTask", timer); Icq.resetPingWatch();
        }
        void noReply() throws Exception {
            // Desktop tests do not wait minutes; keep the actual timestamp
            // ordering from an unanswered ping across the next timer run.
            set("lastServerData", 0L);
        }
    }
    static void threshold(int limit) throws Exception {
        Session s = new Session(limit);
        check(Icq.getUnansweredPings(s.owner, s.socket) == 0, "new session inherited unanswered pings");
        for (int sent = 1; sent <= limit; sent++) {
            s.timer.run();
            check(s.socket.pings == sent && Icq.isConnected() && JimmException.errors == 0,
                  "disconnected before giving ping " + sent + " an interval to reply; limit=" + limit);
            s.noReply();
            check(Icq.getUnansweredPings(s.owner, s.socket) == sent, "wrong unanswered count");
        }
        s.timer.run();
        check(!Icq.isConnected() && s.socket.closes == 1 && s.socket.pings == limit
              && s.timer.isCanceled() && JimmException.errors == 1,
              "watchdog did not disconnect exactly at " + limit + " unanswered pings");
        check(ConnLog.last.contains("на " + limit + " пингов"), "log reports a different threshold");
        s.timer.run();
        check(s.socket.pings == limit && JimmException.errors == 1, "cancelled watchdog fired twice");
        System.out.println("PASS: disconnect after " + limit + " unanswered pings, with a full final interval");
    }
    static void replies() throws Exception {
        Session s = new Session(3);
        for (int i = 0; i < 20; i++) {
            s.timer.run(); s.noReply();
            check(Icq.getUnansweredPings(s.owner, s.socket) == 1, "answered pings carried over");
            Icq.noteServerData();
            check(Icq.getUnansweredPings(s.owner, s.socket) == 0, "server data did not clear the watchdog");
        }
        check(s.socket.pings == 20 && JimmException.errors == 0 && Icq.isConnected(), "healthy connection was cut off");
        s.timer.run(); s.noReply(); s.timer.run(); s.noReply();
        Icq.noteServerData(); s.timer.run(); s.noReply();
        check(Icq.getUnansweredPings(s.owner, s.socket) == 1 && Icq.isConnected(), "late reply failed to reset accumulated misses");
        System.out.println("PASS: any bridge data clears misses, including a reply near the limit");
    }
    static void changesAndOwnership() throws Exception {
        Session old = new Session(3);
        old.timer.run(); old.noReply(); old.timer.run(); old.noReply();
        Options.limit = 5;
        old.timer.run(); old.noReply();
        check(Icq.isConnected() && old.socket.pings == 3, "raising threshold required a reconnect");
        Options.limit = 2; old.timer.run();
        check(!Icq.isConnected() && old.socket.pings == 3, "lower threshold was not applied at the next interval");

        Session next = new Session(1);
        old.timer.run();
        check(next.socket.pings == 0 && JimmException.errors == 0 && Icq.isConnected()
              && Icq.getUnansweredPings(old.owner, old.socket) == 0, "old watchdog changed the new session");
        Options.keepalive = false;
        for (int i = 0; i < 15; i++) next.timer.run();
        check(next.socket.pings == 0 && Icq.isConnected(), "disabled keepalive sent packets or disconnected");
        Options.keepalive = true; next.timer.run(); next.noReply();
        set("connected", false); next.timer.run();
        check(JimmException.errors == 0 && next.socket.pings == 1, "watchdog cut off a login in progress");
        Icq.resetPingWatch(); set("connected", true); next.timer.run();
        check(next.socket.pings == 2 && JimmException.errors == 0, "session reset inherited old misses");
        System.out.println("PASS: live threshold changes, stale timers, disabled keepalive and session reset");
    }
    public static void main(String[] args) {
        int status = 0;
        try {
            new Icq();
            for (int limit = 1; limit <= 10; limit++) threshold(limit);
            replies(); changesAndOwnership();
        } catch (Throwable error) { error.printStackTrace(); status = 1; }
        finally { Icq.disconnect(true); Jimm.jimm.cancelTimer(); }
        System.exit(status);
    }
}
