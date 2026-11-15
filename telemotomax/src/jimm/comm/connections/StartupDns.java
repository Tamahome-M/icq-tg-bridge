package jimm.comm.connections;

import jimm.ConnLog;
import jimm.JimmException;
import jimm.Options;

/** One startup lookup; after the first complete login, one IP for this run. */
public final class StartupDns
{
    private static boolean started, enabled, pending, failed, destroyed;
    private static String host, pinned;
    private static int[] addresses;
    private static int index;
    private static boolean continuePass;
    private static DnsResolver resolver;
    private static long deadline;

    private StartupDns() {}

    public static void start()
    {
        final String lookupHost, dns;
        final DnsResolver lookup;
        try
        {
            synchronized (StartupDns.class)
            {
                if (started) return;
                started = true;
                enabled = Options.getBoolean(Options.OPTION_STARTUP_DNS);
                if (!enabled) return;
                host = firstHost(Options.getString(Options.OPTION_SRV_HOST));
                if (DnsResolver.isIPv4(host)) return;
                lookupHost = host;
                dns = Options.getString(Options.OPTION_DNS_SERVER).trim();
                pending = true;
                deadline = System.currentTimeMillis() + 13000L;
                lookup = resolver = new DnsResolver();
            }
        }
        catch (Throwable failure)
        {
            synchronized (StartupDns.class) { failed = true; }
            cancelPending();
            return;
        }
        try
        {
            new Thread(new Runnable() {
                public void run()
                {
                    int[] result = null;
                    String reason = null;
                    try { result = lookup.lookup(lookupHost, dns); }
                    catch (Throwable failure)
                    {
                        reason = failure.getMessage();
                        if (reason == null) reason = failure.getClass().getName();
                        if (reason.length() > 96) reason = reason.substring(0, 96);
                    }
                    synchronized (StartupDns.class)
                    {
                        if (resolver != lookup || !pending || destroyed) return;
                        addresses = result;
                        failed = result == null || result.length == 0;
                        pending = false;
                        resolver = null;
                        StartupDns.class.notifyAll();
                        ConnLog.note(failed ? "DNS: нужен перезапуск" + (reason == null ? "" : "; " + reason)
                                : "DNS: адресов " + result.length);
                    }
                }
            }).start();
        }
        catch (Throwable failure) { cancelPending(); }
    }

    private static String firstHost(String value)
    {
        if (value == null) return "";
        int comma = value.indexOf(',');
        return (comma < 0 ? value : value.substring(0, comma)).trim();
    }

    private static boolean sameHost(String left, String right)
    {
        if (left == null || right == null) return false;
        left = left.trim(); right = right.trim();
        if (left.endsWith(".")) left = left.substring(0, left.length() - 1);
        if (right.endsWith(".")) right = right.substring(0, right.length() - 1);
        return left.equalsIgnoreCase(right);
    }

    public static synchronized boolean isEnabled() { return enabled; }

    /** Network/DNS settings are a launch snapshot, never an implicit new lookup. */
    public static synchronized void checkServer(String value) throws JimmException
    {
        continuePass = false;
        if (enabled && (failed || destroyed)) throw new JimmException(195, 0);
        if (enabled && !sameHost(host, firstHost(value))) throw new JimmException(196, 0);
    }

    public static synchronized boolean needsNextAddress()
    {
        return enabled && !destroyed && pinned == null && continuePass;
    }

    /** Called outside socket/Icq monitors, before the native blocking open. */
    static String address(String value, Connection connection) throws JimmException
    {
        int colon = value.lastIndexOf(':');
        String requestedHost = colon < 0 ? value : value.substring(0, colon);
        synchronized (StartupDns.class)
        {
            if (!enabled || !sameHost(host, requestedHost)) return value;
        }
        for (;;)
        {
            boolean cancel = connection.getInputCloseFlag();
            boolean expired;
            synchronized (StartupDns.class)
            {
                expired = pending && System.currentTimeMillis() >= deadline;
                if (!cancel && !expired && pending && !destroyed)
                {
                    try { StartupDns.class.wait(100L); } catch (InterruptedException e) { cancel = true; }
                    if (!cancel) continue;
                }
                if (!cancel && !expired)
                {
                    if (destroyed || failed) throw new JimmException(195, 0, connection.typeNetwork);
                    String selected = pinned;
                    if (selected == null) selected = DnsResolver.isIPv4(host)
                            ? host : DnsResolver.ipv4(addresses[index]);
                    connection.startupDnsAddress = selected;
                    return selected + (colon < 0 ? "" : value.substring(colon));
                }
            }
            if (cancel) throw new JimmException(140, 0, false);
            cancelPending();
        }
    }

    /** Advance only after a network failure of this attempt, not a bad password. */
    public static synchronized boolean failed(Connection connection, int code)
    {
        if (!enabled || pinned != null || addresses == null || connection == null
                || connection.startupDnsAddress == null || connection.startupDnsFailed) return false;
        switch (code)
        {
            case 100: case 113: case 114: case 118: case 120: case 121: case 123: break;
            default: return false;
        }
        connection.startupDnsFailed = true;
        index++;
        continuePass = index < addresses.length;
        if (!continuePass) index = 0;
        if (continuePass) ConnLog.note("DNS: пробуем следующий адрес " + DnsResolver.ipv4(addresses[index]));
        return continuePass;
    }

    public static synchronized void connected(Connection connection)
    {
        if (!enabled || pinned != null || connection == null || connection.startupDnsAddress == null) return;
        pinned = connection.startupDnsAddress;
        addresses = null;
        continuePass = false;
        ConnLog.note("DNS: адрес закреплён до выхода " + pinned);
    }

    public static void cancelPending()
    {
        DnsResolver closing;
        synchronized (StartupDns.class)
        {
            if (!pending) return;
            closing = resolver;
            resolver = null;
            pending = false;
            failed = true;
            StartupDns.class.notifyAll();
        }
        if (closing != null) closing.cancel();
    }

    public static void destroy()
    {
        synchronized (StartupDns.class) { destroyed = true; continuePass = false; }
        cancelPending();
    }
}
