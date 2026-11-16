import java.io.IOException;
import javax.microedition.io.Connector;
import jimm.comm.connections.DnsResolver;

/** Compiled production resolver against a real DNS/TCP server. */
public final class DnsWireTest {
    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    public static void main(String[] args) throws Exception {
        String mode = args[0];
        Connector.port = Integer.parseInt(args[1]);
        DnsResolver resolver = new DnsResolver();
        boolean expectedFailure = mode.equals("eof") || mode.equals("oversize");
        try {
            int[] result = resolver.lookup("bridge.example.org", "127.0.0.1");
            check(!expectedFailure, "invalid TCP response accepted");
            int count = mode.equals("large") ? 4 : 2;
            check(result.length == count && result[0] == 0x7f000002
                    && result[1] == 0x7f000003, "wrong DNS addresses");
        } catch (IOException failure) {
            if (!expectedFailure) throw failure;
        }
        check(Connector.udpCalls == 0, "used forbidden UDP API");
        check(Connector.sockets == 1, "unexpected DNS connection count");
        check(Connector.closed == 1 && Connector.inputsClosed == 1
                && Connector.outputsClosed == 1, "DNS connection/streams leaked");
        System.out.println("PASS real DNS/TCP wire exchange with UDP denied: " + mode);
    }
}
