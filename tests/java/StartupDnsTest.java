package jimm.comm.connections;

import jimm.Options;
import jimm.JimmException;

public class StartupDnsTest
{
    private static void check(boolean ok, String text) { if (!ok) throw new AssertionError(text); }
    private static void eq(String wanted, String actual) { check(wanted.equals(actual), wanted + " != " + actual); }
    private static String address(Connection c) throws Exception { return StartupDns.address("bridge.example:5190", c); }
    private static void waitLookup() throws Exception
    {
        long until = System.currentTimeMillis() + 2000;
        while (DnsResolver.calls == 0 && System.currentTimeMillis() < until) Thread.sleep(5);
        check(DnsResolver.calls == 1, "one lookup starts asynchronously");
    }
    private static void error(Connection c, int expected) throws Exception
    {
        try { address(c); throw new AssertionError("expected error " + expected); }
        catch (JimmException e) { check(e.code == expected, "wrong error " + e.code); }
    }

    public static void main(String[] args) throws Exception
    {
        String mode = args[0];
        Connection first = new Connection();
        if ("disabled".equals(mode))
        {
            Options.enabled = false;
            StartupDns.start(); Options.enabled = true; StartupDns.start();
            eq("bridge.example:5190", address(first));
            check(!StartupDns.isEnabled() && DnsResolver.calls == 0, "disabled launch remains disabled");
        }
        else if ("literal".equals(mode))
        {
            Options.host = "9.8.7.6";
            StartupDns.start(); StartupDns.checkServer("9.8.7.6");
            eq("9.8.7.6:7777", StartupDns.address("9.8.7.6:7777", first));
            StartupDns.connected(first);
            eq("9.8.7.6:5190", StartupDns.address("9.8.7.6:5190", new Connection()));
            check(DnsResolver.calls == 0, "literal must not use DNS");
        }
        else if ("pin".equals(mode))
        {
            StartupDns.start(); StartupDns.checkServer("bridge.example");
            eq("1.2.3.4:5190", address(first));
            eq("1.2.3.4:443", StartupDns.address("BRIDGE.EXAMPLE.:443", first));
            eq("1.2.3.4:7777", StartupDns.address(" BRIDGE.EXAMPLE. :7777", first));
            eq("other.example:5190", StartupDns.address("other.example:5190", first));
            eq("11.12.13.14:443", StartupDns.address("11.12.13.14:443", first));
            check(!StartupDns.failed(first, 111), "password failure must not advance");
            check(StartupDns.failed(first, 120), "network failure selects second cached IP");
            check(!StartupDns.failed(first, 120), "same error cannot advance twice");
            check(StartupDns.needsNextAddress(), "continue initial pass even when autoreconnect disabled");
            StartupDns.checkServer("bridge.example");
            check(!StartupDns.needsNextAddress(), "scheduled continuation consumed by next login");
            Connection second = new Connection();
            eq("5.6.7.8:5190", address(second));
            check(!StartupDns.failed(second, 118), "end of bounded initial pass");
            Connection retry = new Connection();
            eq("1.2.3.4:5190", address(retry));
            check(StartupDns.failed(retry, 121), "manual/normal retry reuses cached list");
            Connection success = new Connection();
            eq("5.6.7.8:5190", address(success));
            StartupDns.connected(success);
            check(!StartupDns.failed(success, 120), "established IP never rotates");
            for (int i=0;i<5;i++) {
                Connection reconnect = new Connection();
                eq("5.6.7.8:5190", address(reconnect));
                check(!StartupDns.failed(reconnect, 120), "reconnect IP fixed");
                StartupDns.start();
            }
            eq("bridge.example,legacy.example", Options.host);
            check(DnsResolver.calls == 1, "retries/resume never query DNS again");
        }
        else if ("snapshot".equals(mode))
        {
            DnsResolver.blocked = true;
            StartupDns.start(); waitLookup();
            Options.enabled = false; Options.host = "changed.example"; Options.dns = "8.8.8.8";
            StartupDns.start();
            try { StartupDns.checkServer(Options.host); throw new AssertionError("changed host must require restart"); }
            catch (JimmException e) { check(e.code == 196, "changed host error"); }
            DnsResolver.blocked = false;
            eq("1.2.3.4:5190", address(first));
            eq("bridge.example", DnsResolver.requestedHost); eq("1.1.1.1", DnsResolver.requestedDns);
            check(StartupDns.isEnabled(), "mode snapshot survives edits");
        }
        else if ("failure".equals(mode))
        {
            DnsResolver.fail = true; StartupDns.start();
            error(first, 195); DnsResolver.fail = false; StartupDns.start();
            error(new Connection(), 195);
            check(DnsResolver.calls == 1, "failure cached until exit; no native DNS fallback");
        }
        else if ("cancel".equals(mode))
        {
            DnsResolver.blocked = true; StartupDns.start(); waitLookup();
            first.closed = true; error(first, 140);
            check(DnsResolver.cancels == 0, "cancelled login must not cancel the app's DNS lookup");
            DnsResolver.blocked = false;
            eq("1.2.3.4:5190", address(new Connection()));
            check(DnsResolver.calls == 1, "manual retry awaits same lookup");
        }
        else if ("deadline".equals(mode))
        {
            DnsResolver.blocked = true; StartupDns.start(); waitLookup();
            java.lang.reflect.Field field = StartupDns.class.getDeclaredField("deadline");
            field.setAccessible(true); field.setLong(null, System.currentTimeMillis() - 1);
            error(first, 195);
            check(DnsResolver.cancels == 1, "bounded connection wait cancels resolver");
        }
        StartupDns.destroy();
        System.out.println("PASS startup DNS " + mode);
    }
}
