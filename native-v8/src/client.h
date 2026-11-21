#ifndef TMM_NATIVE_CLIENT_H
#define TMM_NATIVE_CLIENT_H
#include <stdint.h>
#include <map>
#include <string>
#include <vector>
namespace tmm {
struct ContactRecord {
    uint32_t uin, status;
    unsigned groupId, itemId, type, network, days, privacy;
    bool inRoster, noAuth, deleted;
    std::string name, group, avatarHash;
    ContactRecord()
        : uin(0), status(0xffffffffU), groupId(0), itemId(0), type(0), network(0), days(65535),
          privacy(0), inRoster(false), noAuth(false), deleted(false) {}
};
struct MessageRecord {
    uint32_t uin, sourceUin, discussionUin, time;
    uint64_t cookie;
    unsigned kind, delivery;
    bool silent, outgoing;
    std::string nativeId, text, senderName, token, url;
    MessageRecord()
        : uin(0), sourceUin(0), discussionUin(0), time(0), cookie(0), kind(0), delivery(0),
          silent(false), outgoing(false) {}
};
struct ClientConfig {
    std::string host, uin, password, psk, dnsServer, cacheDir, ssiEncoding, network, profile;
    unsigned port, pingSeconds, missedPings, reconnectSeconds, reconnectAttempts, networkMask,
        maxMediaBytes;
    uint32_t status;
    bool encryption, startupDns, autoReconnect, md5Login;
    std::map<unsigned, unsigned> media;
    std::vector<uint32_t> quietChats;
    ClientConfig()
        : host("127.0.0.1"), dnsServer("1.1.1.1"), cacheDir("/tmp/telemotomax"),
          ssiEncoding("CP1251"), network("auto"), port(5190), pingSeconds(110), missedPings(3),
          reconnectSeconds(30), reconnectAttempts(0), networkMask(7),
          maxMediaBytes(5 * 1024 * 1024), status(0), encryption(false), startupDns(false),
          autoReconnect(true), md5Login(true) {}
};
struct Command {
    enum Type {
        SendMessage,
        Typing,
        Status,
        History,
        Discussion,
        Avatar,
        Photo,
        Video,
        Voice,
        File,
        AllChats,
        OpenChat,
        Search,
        ContactInfo,
        DeleteChat,
        RemoveMe,
        Quote,
        UploadPhoto,
        UploadVoice,
        UploadVideo,
        UploadFile,
        Settings,
        QuietChats,
        CancelRequest,
        AddContact,
        RenameContact,
        MoveContact,
        AddGroup,
        RenameGroup,
        DeleteGroup,
        Privacy,
        RequestAuthorization,
        GrantAuthorization,
        DenyAuthorization
    };
    Type type;
    uint32_t requestId, uin, sourceUin, status, offset, limit, duration;
    uint64_t cookie;
    unsigned groupId, itemId, mode;
    bool flag;
    std::string text, path, token, nativeId;
    std::map<unsigned, unsigned> media;
    std::vector<uint32_t> uins;
    explicit Command(Type value = History)
        : type(value), requestId(0), uin(0), sourceUin(0), status(0), offset(0), limit(10),
          duration(0), cookie(0), groupId(0), itemId(0), mode(0), flag(false) {}
};
struct Event {
    enum Type {
        State,
        Roster,
        Presence,
        Message,
        Receipt,
        Typing,
        History,
        Chats,
        ContactInfo,
        Media,
        Progress,
        QuoteResult,
        Error,
        CommandResult
    };
    enum ConnectionState { Disconnected, Connecting, Online, Reconnecting };
    Type type;
    uint32_t requestId, uin, status, generation, offset;
    uint64_t cookie, bytes, total;
    unsigned kind, delivery, state;
    int error;
    bool flag, more, silent;
    std::string nativeId, token, text, path, filename, mime;
    std::vector<ContactRecord> contacts;
    std::vector<MessageRecord> messages;
    std::map<std::string, std::string> fields;
    explicit Event(Type value = Error)
        : type(value), requestId(0), uin(0), status(0), generation(0), offset(0), cookie(0),
          bytes(0), total(0), kind(0), delivery(0), state(Disconnected), error(0), flag(false),
          more(false), silent(false) {}
};
/** One worker owns every socket and transfer. No Qt calls or UI pointers. */
class Client {
  public:
    Client();
    ~Client();
    // Keepalive settings take effect online. Other fields apply at the next start.
    void configure(const ClientConfig &config);
    void start();
    void prefetchDns(); // startup DNS only; no OSCAR login, no Connecting event
    void stop();        // asynchronous cancellation; never waits for network I/O
    bool stopAndWait(); // join before explicit destructive local-data reset
    int eventFd() const;
    uint32_t nextRequestId();
    uint32_t sessionGeneration() const;
    bool submit(const Command &command); // false: offline or bounded queue full
    void drainEvents(std::vector<Event> &events);

  private:
    void launch(bool prefetch);
    class Impl;
    Impl *impl_;
    Client(const Client &);
    Client &operator=(const Client &);
};
} // namespace tmm
#endif
