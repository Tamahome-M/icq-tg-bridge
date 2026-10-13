public interface FlipReader {
    void attach(FlipProbe probe);
    int readState();
    void detach();
}
