import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.util.Vector;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import jimm.Jimm;
import jimm.JimmException;
import jimm.TimerTasks;
import jimm.comm.ConnectAction;
import jimm.comm.Icq;
import jimm.comm.Packet;
import jimm.comm.connections.Connection;

/** Exercises the compiled client with blocked login and socket operations. */
public final class ClientLifecycleTest {
    private static Field field(String name) throws Exception {
        Field field = Icq.class.getDeclaredField(name);
        field.setAccessible(true);
        return field;
    }

    private static Object get(String name) throws Exception {
        return field(name).get(null);
    }

    private static void set(String name, Object value) throws Exception {
        field(name).set(null, value);
    }

    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }

    private static void await(CountDownLatch latch) throws Exception {
        check(latch.await(3, TimeUnit.SECONDS), "operation did not reach its barrier");
    }

    private static void join(Thread thread) throws Exception {
        thread.join(3000);
        check(!thread.isAlive(), "connection thread did not stop");
    }

    private static final class Login extends ConnectAction {
        final CountDownLatch entered = new CountDownLatch(1);
        final CountDownLatch finish = new CountDownLatch(1);

        Login() { super("100500", "test", "localhost", "5190", true); }

        protected void init() {
            entered.countDown();
            try { await(finish); }
            catch (Exception e) { throw new RuntimeException(e); }
        }

        public boolean isCompleted() { return finish.getCount() == 0; }
        public boolean isError() { return false; }
        public void onEvent(int event) { }
    }

    private static final class Socket extends Connection {
        int pings;
        CountDownLatch entered;
        CountDownLatch finish;
        boolean fail;

        public void sendPacket(Packet packet) throws JimmException {
            pings++;
            if (entered != null) {
                entered.countDown();
                try { await(finish); }
                catch (Exception e) { throw new RuntimeException(e); }
            }
            if (fail) throw new JimmException(120, 3, JimmException.ICQ_MAIN);
        }

        public void forceDisconnect() { }
    }

    private static TimerTasks keepalive(Thread owner, Connection socket) throws Exception {
        // The fallback lets the same regression run against the previous client.
        try {
            Constructor<TimerTasks> ctor = TimerTasks.class.getConstructor(
                int.class, Thread.class, Connection.class);
            return ctor.newInstance(TimerTasks.ICQ_KEEPALIVE, owner, socket);
        } catch (NoSuchMethodException e) {
            return new TimerTasks(TimerTasks.ICQ_KEEPALIVE);
        }
    }

    private static void duplicateLogin() throws Exception {
        Login first = new Login();
        Login second = new Login();
        Thread owner = null;
        try {
            Icq.requestAction(first);
            await(first.entered);
            owner = (Thread) get("thread");
            TimerTasks timer = (TimerTasks) get("keepAliveTimerTask");
            Icq.requestAction(second);
            check(get("thread") == owner, "second login replaced the active connection thread");
            check(((Vector) get("reqAction")).isEmpty(), "second login was queued");
            Icq.connect();
            check(get("keepAliveTimerTask") == timer, "second login replaced keepalive");
            check(!timer.isCanceled(), "active keepalive was cancelled");
        } finally {
            Icq.disconnect(true);
            first.finish.countDown();
            second.finish.countDown();
            if (owner != null) join(owner);
        }
        System.out.println("PASS: repeated manual/automatic login starts one connection");
    }

    private static void disconnectBeforeStartup(Icq client) throws Exception {
        Thread pending = new Thread(client);
        Socket socket = new Socket();
        TimerTasks timer = keepalive(pending, socket);
        set("thread", pending);
        set("c", null);
        set("keepAliveTimerTask", timer);
        Icq.setDisconnected(false);
        Icq.disconnect(true);
        check(Icq.isDisconnected(), "disconnect with no socket did not stop automatic login");
        check(get("thread") == null, "pending startup survived disconnect");
        check(timer.isCanceled(), "pending keepalive survived disconnect");
        pending.start();
        join(pending);
        check(get("c") == null, "cancelled startup created a socket");
        check(get("keepAliveTimerTask") == null, "cancelled startup created a keepalive");
        System.out.println("PASS: disconnect before socket creation cancels pending startup");
    }

    private static void staleThreadExit() throws Exception {
        Login first = new Login();
        Login second = new Login();
        Thread oldOwner = null;
        Thread newOwner = null;
        try {
            Icq.requestAction(first);
            await(first.entered);
            oldOwner = (Thread) get("thread");
            TimerTasks oldTimer = (TimerTasks) get("keepAliveTimerTask");
            Icq.disconnect(true);
            Icq.requestAction(second);
            await(second.entered);
            newOwner = (Thread) get("thread");
            TimerTasks newTimer = (TimerTasks) get("keepAliveTimerTask");
            Object newSocket = get("c");
            first.finish.countDown();
            join(oldOwner);
            check(oldTimer.isCanceled(), "old connection retained a keepalive");
            check(get("thread") == newOwner, "old exit cleared the new connection owner");
            check(get("keepAliveTimerTask") == newTimer && !newTimer.isCanceled(),
                "old exit cancelled the new keepalive");
            check(get("c") == newSocket, "old exit replaced the new socket");
        } finally {
            Icq.disconnect(true);
            first.finish.countDown();
            second.finish.countDown();
            if (oldOwner != null) join(oldOwner);
            if (newOwner != null) join(newOwner);
        }
        System.out.println("PASS: old thread exit preserves the replacement session");
    }

    private static void staleKeepalive() throws Exception {
        Thread oldOwner = new Thread();
        Socket oldSocket = new Socket();
        TimerTasks timer = keepalive(oldOwner, oldSocket);
        Socket newSocket = new Socket();
        set("thread", new Thread());
        set("c", newSocket);
        set("connected", true);
        Icq.resetPingWatch();
        timer.run();
        check(oldSocket.pings == 0 && newSocket.pings == 0,
            "stale keepalive sent a ping after replacement");
        check(timer.isCanceled(), "stale keepalive did not cancel itself");
        Icq.disconnect(true);
        System.out.println("PASS: stale timer sends no ping to the new session");
    }

    private static void activeKeepalive() throws Exception {
        Socket socket = new Socket();
        set("thread", new Thread());
        set("c", socket);
        set("connected", true);
        TimerTasks timer = keepalive((Thread) get("thread"), socket);
        set("keepAliveTimerTask", timer);
        Icq.resetPingWatch();
        timer.run();
        check(socket.pings == 1 && Icq.getPingMisses() == 0,
            "active timer did not send exactly one ping");
        // Preserve the watchdog's timestamp ordering even on a fast desktop JVM.
        set("lastServerData", 0L);
        timer.run();
        timer.run();
        check(socket.pings == 3 && Icq.getPingMisses() == 2,
            "unanswered active pings were not counted");
        Icq.noteServerData();
        timer.run();
        check(socket.pings == 4 && Icq.getPingMisses() == 0,
            "server reply did not reset the active watchdog");
        Icq.disconnect(true);
        System.out.println("PASS: active timer sends once and retains reply monitoring");
    }

    private static void inflightKeepalive(boolean fail) throws Exception {
        Socket oldSocket = new Socket();
        oldSocket.fail = fail;
        oldSocket.entered = new CountDownLatch(1);
        oldSocket.finish = new CountDownLatch(1);
        set("thread", new Thread());
        set("c", oldSocket);
        set("connected", true);
        final TimerTasks timer = keepalive((Thread) get("thread"), oldSocket);
        set("keepAliveTimerTask", timer);
        final Throwable[] error = new Throwable[1];
        Thread sending = new Thread(new Runnable() {
            public void run() {
                try { timer.run(); }
                catch (Throwable e) { error[0] = e; }
            }
        });
        sending.start();
        try {
            await(oldSocket.entered);
            Icq.disconnect(true);
            Socket newSocket = new Socket();
            set("thread", new Thread());
            set("c", newSocket);
            set("connected", true);
            Icq.resetPingWatch();
            oldSocket.finish.countDown();
            join(sending);
            check(error[0] == null, "old ping raised an unhandled exception: " + error[0]);
            check(oldSocket.pings == 1 && newSocket.pings == 0,
                "in-flight ping changed its destination");
            check(((Long) get("lastPingAt")).longValue() == 0,
                "old ping changed the replacement watchdog");
            check(Icq.isConnected() && get("c") == newSocket,
                "old ping error disconnected the replacement session");
        } finally {
            oldSocket.finish.countDown();
            join(sending);
            Icq.disconnect(true);
        }
        System.out.println(fail ? "PASS: old ping failure preserves the new session" :
            "PASS: in-flight old ping leaves the new watchdog untouched");
    }

    public static void main(String[] args) {
        int status = 0;
        try {
            Icq client = new Icq();
            duplicateLogin();
            disconnectBeforeStartup(client);
            staleThreadExit();
            staleKeepalive();
            activeKeepalive();
            inflightKeepalive(false);
            inflightKeepalive(true);
        } catch (Throwable e) {
            e.printStackTrace();
            status = 1;
        } finally {
            Jimm.jimm.cancelTimer();
        }
        System.exit(status);
    }
}
