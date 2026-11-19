#include "media_cache.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
static std::string file(const std::string &root, const char *name, unsigned size = 4) {
    std::string path = root + "/" + name;
    FILE *out = fopen(path.c_str(), "wb");
    assert(out);
    for (unsigned i = 0; i < size; ++i)
        assert(fputc('x', out) != EOF);
    assert(fclose(out) == 0);
    return path;
}
int main() {
    char directory[] = "/tmp/tmm-media-cache-XXXXXX";
    assert(mkdtemp(directory));
    const std::string root(directory);
    std::string path, name;
    tmm::MediaCache cache(2, 10);
    cache.setDirectory(root);
    std::string a = file(root, "media-a.jpg"), b = file(root, "media-b.3gp");
    assert(cache.store("a", a, "photo.jpg") && cache.store("b", b, "video.3gp"));
    assert(cache.find("a", path, name) && path == a && name == "photo.jpg");
    std::string c = file(root, "media-c.jpg");
    assert(cache.store("c", c, "c.jpg"));
    assert(access(b.c_str(), F_OK) && !cache.find("b", path, name));
    assert(!access(a.c_str(), F_OK)); // Reopening a made b the least recent.
    b = file(root, "media-b.3gp", 7);
    assert(cache.store("b", b, "b.3gp")); // Byte limit evicts both 4-byte entries.
    assert(!cache.owns(a) && !cache.owns(c) && cache.owns(b));
    assert(access(a.c_str(), F_OK) && access(c.c_str(), F_OK));
    assert(unlink(b.c_str()) == 0 && !cache.find("b", path, name));
    a = file(root, "media-a.jpg");
    assert(cache.store("a", a, "a.jpg"));
    file(root, "media-a.jpg", 1);
    assert(!cache.find("a", path, name)); // A truncated file must be downloaded again.
    a = file(root, "original.jpg");
    b = file(root, "recording-owned.3gp");
    c = file(root, "media-too-large.3gp", 11);
    assert(!cache.store("a", a, "a") && !cache.store("b", b, "b") && !cache.store("c", c, "c"));
    const std::string link = root + "/media-link.jpg";
    assert(symlink(a.c_str(), link.c_str()) == 0 && !cache.store("link", link, "l"));
    const std::string nested = root + "/media-nested";
    assert(mkdir(nested.c_str(), 0700) == 0);
    const std::string child = file(nested, "child");
    assert(!cache.store("child", child, "c"));
    const std::string owned = file(root, "media-owned.jpg");
    assert(cache.store("owned", owned, "o") && cache.store("new-key", owned, "o"));
    cache.clear();
    assert(access(owned.c_str(), F_OK) && !access(a.c_str(), F_OK) && !access(b.c_str(), F_OK));
    assert(!access(c.c_str(), F_OK) && !access(child.c_str(), F_OK));
    tmm::Command request(tmm::Command::Video);
    request.uin = 1000001;
    request.token = std::string(16, '\0');
    request.media[1] = 176;
    const std::string key = tmm::MediaCache::requestKey(request);
    request.requestId = 99;
    request.nativeId = "first segment only";
    assert(tmm::MediaCache::requestKey(request) == key);
    request.offset = 1;
    assert(tmm::MediaCache::requestKey(request) != key);
    request.offset = 0;
    request.mode = 0x20;
    assert(tmm::MediaCache::requestKey(request) != key);
    request.mode = 0;
    request.media[1] = 128;
    assert(tmm::MediaCache::requestKey(request) != key);
    request.media[1] = 176;
    request.uin++;
    assert(tmm::MediaCache::requestKey(request) != key);
    request.uin--;
    request.type = tmm::Command::Photo;
    assert(tmm::MediaCache::requestKey(request) != key);
    unlink(a.c_str());
    unlink(b.c_str());
    unlink(c.c_str());
    unlink(link.c_str());
    unlink(child.c_str());
    rmdir(nested.c_str());
    rmdir(directory);
    puts(
        "Media disk cache: LRU, byte limits, missing files, ownership and request profiles passed");
}
