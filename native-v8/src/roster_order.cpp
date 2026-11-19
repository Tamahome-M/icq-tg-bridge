#include "roster_order.h"
#include <qstring.h>
namespace tmm {
namespace {
unsigned statusWeight(const ContactRecord &contact) {
    // Match Java's Util.translateStatusReceived before getSortWeight.
    uint32_t status = contact.status;
    if (status == 0xffffffffU)
        return contact.inRoster ? 20 : 19;
    if (status & 2)
        return 10; // Do not disturb.
    if (status & 0x100)
        return contact.inRoster ? 20 : 19; // Network unavailable/invisible.
    if (status & 0x10)
        return 9;
    if (status & 4)
        return 8;
    if (status & 0x20)
        return 1;
    if ((status & 0x2001) == 0x2001)
        return 6;
    if ((status & 0x3000) == 0x3000)
        return 2;
    if ((status & 0x5000) == 0x5000)
        return 4;
    if ((status & 0x6000) == 0x6000)
        return 5;
    if (status & 1)
        return 7;
    if (status & 0x4000)
        return 3;
    return 0;
}
struct Key {
    size_t index;
    QString name;
    unsigned weight;
    bool before(const Key &other) const {
        return weight != other.weight ? weight < other.weight : name < other.name;
    }
};
} // namespace
void sortRosterContacts(std::vector<size_t> &items, const std::vector<ContactRecord> &contacts,
                        bool byName) {
    std::vector<Key> keys;
    keys.reserve(items.size());
    for (size_t i = 0; i < items.size(); ++i) {
        const ContactRecord &contact = contacts[items[i]];
        Key key;
        key.index = items[i];
        key.name = QString::fromUtf8(contact.name.c_str()).lower();
        key.weight = byName ? 0 : statusWeight(contact);
        keys.push_back(key);
    }
    // Java TreeNode.sort uses stable binary insertion. Build each folded name
    // once per rebuild, not once per comparison; keep SSI order for equal keys.
    for (size_t i = 1; i < keys.size(); ++i) {
        if (!keys[i].before(keys[i - 1]))
            continue;
        Key key = keys[i];
        size_t low = 0, high = i;
        while (low < high) {
            const size_t middle = low + (high - low) / 2;
            if (key.before(keys[middle]))
                high = middle;
            else
                low = middle + 1;
        }
        for (size_t j = i; j > low; --j)
            keys[j] = keys[j - 1];
        keys[low] = key;
    }
    for (size_t i = 0; i < keys.size(); ++i)
        items[i] = keys[i].index;
}
} // namespace tmm
