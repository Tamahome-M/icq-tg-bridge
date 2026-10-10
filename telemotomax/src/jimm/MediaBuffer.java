package jimm;

import java.io.IOException;
import java.io.OutputStream;

/** One pending, immutable BART packet; the writer owns the other packet.
 * Do not copy its payload or accumulate a whole clip in the Java heap. */
final class MediaBuffer {
    private byte[] pending;
    private int offset, length;
    private boolean finished, success;

    synchronized boolean put(byte[] data, int off, int len) {
        long deadline = System.currentTimeMillis() + 15000;
        while (pending != null && !finished) {
            long remaining = deadline - System.currentTimeMillis();
            if (remaining <= 0) { finish(false); return false; }
            try { wait(remaining); }
            catch (InterruptedException e) { finish(false); return false; }
        }
        if (finished) return false;
        pending = data; offset = off; length = len;
        notifyAll();
        return true;
    }

    synchronized void finish(boolean ok) {
        // Cancellation/failure cannot subsequently become success.
        if (finished && !success) return;
        finished = true; success = ok;
        if (!ok) pending = null;
        notifyAll();
    }

    boolean writeTo(OutputStream out) throws IOException {
        for (;;) {
            byte[] data;
            int off, len;
            synchronized (this) {
                while (pending == null && !finished) {
                    try { wait(); }
                    catch (InterruptedException e) { finish(false); return false; }
                }
                if (finished && !success) return false;
                if (pending == null) return success;
                data = pending; off = offset; len = length;
                pending = null;
                notifyAll();
            }
            out.write(data, off, len);
        }
    }
}
