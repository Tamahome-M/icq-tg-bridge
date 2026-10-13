import java.util.Timer;
import java.util.TimerTask;
import javax.microedition.lcdui.Canvas;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Display;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Graphics;
import javax.microedition.lcdui.TextBox;
import javax.microedition.lcdui.TextField;
import javax.microedition.midlet.MIDlet;
import javax.microedition.rms.RecordStore;

/** Records raw MIDP events. It never infers whether the flip is open or closed. */
public final class FlipProbe extends MIDlet implements CommandListener, Runnable {
    private static final int CAPACITY = 96;
    private final String[] lines = new String[CAPACITY];
    private int first;
    private int count;
    private final long origin = System.currentTimeMillis();
    private Display display;
    private ProbeCanvas canvas;
    private Timer timer;
    private boolean started;
    private volatile boolean running;
    private volatile int timerTicks;
    private volatile int threadTicks;
    private volatile int serialTicks;
    private volatile int paintTicks;
    private volatile long lastTimer;
    private volatile long pendingSince;
    private volatile long serialDelay;
    private volatile int shown = -1;
    private volatile int flipState = -2;
    private FlipReader reader;
    private boolean pollFlip;
    private int marks;
    private final Command mark = new Command("Метка", Command.SCREEN, 1);
    private final Command finish = new Command("Закончить", Command.SCREEN, 2);
    private final Command saved = new Command("Прошлый журнал", Command.SCREEN, 3);
    private final Command back = new Command("Назад", Command.BACK, 1);
    private final Command exit = new Command("Выход", Command.EXIT, 9);
    private final Runnable serial = new Runnable() {
        public void run() {
            long since = pendingSince;
            serialDelay = since == 0 ? 0 : System.currentTimeMillis() - since;
            serialTicks++;
            pendingSince = 0;
            if (serialDelay > 2500) log("callSerially delay=" + serialDelay + " ms");
        }
    };

    protected void startApp() {
        log("startApp");
        if (started) return;
        started = true;
        display = Display.getDisplay(this);
        canvas = new ProbeCanvas();
        canvas.addCommand(mark);
        canvas.addCommand(finish);
        canvas.addCommand(saved);
        canvas.addCommand(exit);
        canvas.setCommandListener(this);
        display.setCurrent(canvas);
        log("platform=" + System.getProperty("microedition.platform"));
        log("Background=" + getAppProperty("Background")
                + " FlipInsensitive=" + getAppProperty("FlipInsensitive"));
        // Class.forName triggers class initialization. No protected method is called.
        try {
            Class.forName("com.motorola.synerj.svc.device.Case");
            log("Case.forName: available");
        } catch (Throwable error) {
            log("Case.forName: " + error.getClass().getName());
        }
        try {
            reader = (FlipReader) Class.forName("VodafoneFlip").newInstance();
            pollFlip = true;
            try {
                reader.attach(this);
                log("Vodafone BodyOpenListener registered");
            } catch (Throwable error) {
                log("Vodafone listener: " + error.getClass().getName());
            }
        } catch (Throwable error) {
            log("Vodafone load: " + error.getClass().getName());
        }
        running = true;
        timer = new Timer();
        timer.schedule(new TimerTask() {
            public void run() {
                if (!running) return;
                long now = System.currentTimeMillis();
                long previous = lastTimer;
                lastTimer = now;
                timerTicks++;
                if (previous != 0 && now - previous > 2500)
                    log("Timer gap=" + (now - previous) + " ms");
            }
        }, 1000, 1000);
        new Thread(this).start();
    }

    protected void pauseApp() { log("pauseApp"); }

    protected void destroyApp(boolean unconditional) {
        stop();
    }

    public void run() {
        long previous = System.currentTimeMillis();
        long sampled = previous;
        while (running) {
            try { Thread.sleep(1000); } catch (InterruptedException ignored) { }
            if (!running) break;
            long now = System.currentTimeMillis();
            threadTicks++;
            if (now - previous > 2500) log("Thread.sleep gap=" + (now - previous) + " ms");
            previous = now;
            if (pollFlip) {
                try {
                    int state = reader.readState();
                    if (flipState != state) {
                        flipState = state;
                        log("DeviceControl.getDeviceState(7)=" + state);
                    }
                } catch (Throwable error) {
                    pollFlip = false;
                    log("Vodafone getter: " + error.getClass().getName() + ": " + error.getMessage());
                }
            }
            int currentShown = canvas.isShown() ? 1 : 0;
            if (shown != currentShown) {
                shown = currentShown;
                log("Canvas.isShown=" + currentShown);
            }
            if (pendingSince == 0) {
                pendingSince = now;
                display.callSerially(serial);
            }
            if (now - sampled >= 5000) {
                sampled = now;
                long pending = pendingSince;
                log("thread=" + threadTicks + " timer=" + timerTicks
                        + " serial=" + serialTicks + " paint=" + paintTicks
                        + " pending=" + (pending == 0 ? 0 : now - pending)
                        + " delay=" + serialDelay + " shown=" + shown + " flipApi=" + flipState);
            }
        }
    }

    synchronized void log(String value) {
        int index;
        if (count == CAPACITY) {
            index = first;
            first = (first + 1) % CAPACITY;
        } else {
            index = (first + count) % CAPACITY;
            count++;
        }
        String line = ((System.currentTimeMillis() - origin) / 1000) + "s " + value;
        lines[index] = line.length() > 120 ? line.substring(0, 120) : line;
    }

    private synchronized String report() {
        StringBuffer text = new StringBuffer(8000);
        for (int i = 0; i < count; i++) {
            text.append(lines[(first + i) % CAPACITY]);
            text.append('\n');
        }
        return text.toString();
    }

    private void stop() {
        running = false;
        if (timer != null) timer.cancel();
        if (reader != null) {
            try { reader.detach(); } catch (Throwable ignored) { }
        }
    }

    private void showLog(String title, String text) {
        TextBox view = new TextBox(title, text, 12000, TextField.UNEDITABLE);
        view.addCommand(back);
        view.addCommand(exit);
        view.setCommandListener(this);
        display.setCurrent(view);
    }

    public void commandAction(Command command, Displayable source) {
        if (command == exit) {
            stop();
            notifyDestroyed();
        } else if (command == mark) {
            log("MANUAL MARK " + (++marks));
            canvas.repaint();
        } else if (command == finish) {
            stop();
            log("FINISH thread=" + threadTicks + " timer=" + timerTicks
                    + " serial=" + serialTicks + " paint=" + paintTicks);
            String text = report();
            RecordStore store = null;
            try {
                store = RecordStore.openRecordStore("TmmFlipProbe", true);
                byte[] data = text.getBytes("UTF-8");
                if (store.getNumRecords() == 0) store.addRecord(data, 0, data.length);
                else store.setRecord(1, data, 0, data.length);
                showLog("Журнал сохранён", text);
            } catch (Throwable error) {
                showLog("Журнал: " + error.getClass().getName(), text);
            } finally {
                if (store != null) try { store.closeRecordStore(); } catch (Exception ignored) { }
            }
        } else if (command == saved) {
            // Do not overwrite the previous result just to open it after a restart.
            stop();
            RecordStore store = null;
            try {
                store = RecordStore.openRecordStore("TmmFlipProbe", false);
                showLog("Прошлый журнал", new String(store.getRecord(1), "UTF-8"));
            } catch (Throwable error) {
                showLog("Прошлый журнал", error.getClass().getName());
            } finally {
                if (store != null) try { store.closeRecordStore(); } catch (Exception ignored) { }
            }
        } else if (command == back) {
            display.setCurrent(canvas);
        }
    }

    private final class ProbeCanvas extends Canvas {
        protected void showNotify() { log("Canvas.showNotify"); }
        protected void hideNotify() { log("Canvas.hideNotify"); }
        protected void paint(Graphics graphics) {
            paintTicks++;
            graphics.setColor(0xffffff);
            graphics.fillRect(0, 0, getWidth(), getHeight());
            graphics.setColor(0);
            graphics.drawString("FlipProbe 0.1", 2, 2, Graphics.TOP | Graphics.LEFT);
            graphics.drawString("Открыто: 30 с", 2, 22, Graphics.TOP | Graphics.LEFT);
            graphics.drawString("Закрыто: 60 с", 2, 42, Graphics.TOP | Graphics.LEFT);
            graphics.drawString("Открыть: 10 с", 2, 62, Graphics.TOP | Graphics.LEFT);
            graphics.drawString("Затем «Закончить»", 2, 82, Graphics.TOP | Graphics.LEFT);
        }
    }
}
