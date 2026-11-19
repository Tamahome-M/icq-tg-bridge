#include "roster_order.h"
#include <qstring.h>
#include <assert.h>
#include <stdio.h>
using namespace tmm;
static ContactRecord contact(const char *name, uint32_t status = 0, bool saved = true) {
    ContactRecord c;
    c.name = name;
    c.status = status;
    c.inRoster = saved;
    return c;
}
static std::vector<size_t> reversed(size_t count) {
    std::vector<size_t> order;
    for (size_t i = count; i; --i)
        order.push_back(i - 1);
    return order;
}
int main() {
    std::vector<ContactRecord> contacts;
    // Exact Java status priority; names deliberately oppose status order.
    const uint32_t statuses[] = {0, 0x20, 0x3000, 0x4000, 0x5000, 0x6000,     0x2001,
                                 1, 4,    0x10,   2,      0x100,  0xffffffffU};
    for (unsigned i = 0; i < sizeof(statuses) / sizeof(statuses[0]); ++i) {
        char name[30];
        sprintf(name, "%02u", 99 - i);
        contacts.push_back(contact(name, statuses[i]));
    }
    std::vector<size_t> order = reversed(contacts.size());
    sortRosterContacts(order, contacts, false);
    for (size_t i = 0; i < 11; ++i)
        assert(order[i] == i);
    // Invisible and offline share a Java weight, so their names decide.
    assert(order[11] == 12 && order[12] == 11);
    contacts.clear();
    contacts.push_back(contact("Яна"));
    contacts.push_back(contact("борис"));
    contacts.push_back(contact("Анна"));
    contacts.push_back(contact("alice"));
    contacts.push_back(contact("Bob"));
    contacts.push_back(contact("АЛИСА"));
    contacts.push_back(contact("Алиса"));
    order = reversed(contacts.size());
    sortRosterContacts(order, contacts, true);
    const size_t expected[] = {3, 4, 6, 5, 2, 1, 0};
    for (size_t i = 0; i < order.size(); ++i)
        assert(order[i] == expected[i]);
    // Mixed case names compare equal, retaining the input roster order.
    sortRosterContacts(order, contacts, true);
    for (size_t i = 0; i < order.size(); ++i)
        assert(order[i] == expected[i]);
    contacts.clear();
    contacts.push_back(contact("A saved", 0xffffffffU));
    contacts.push_back(contact("Z temporary", 0x100, false));
    contacts.push_back(contact("A away", 1));
    contacts.push_back(contact("Z online", 0));
    order = reversed(contacts.size());
    sortRosterContacts(order, contacts, false);
    assert(order[0] == 3 && order[1] == 2 && order[2] == 1 && order[3] == 0);
    // Received status flags use Java's normalization precedence.
    contacts.clear();
    contacts.push_back(contact("A busy", 0x10112));
    contacts.push_back(contact("Z away", 0x10001));
    order = reversed(contacts.size());
    sortRosterContacts(order, contacts, false);
    assert(order[0] == 1 && order[1] == 0);
    order.clear();
    sortRosterContacts(order, contacts, false);
    puts("ROSTER ORDER PASS: Java presence weights, Cyrillic/Latin case folding, stable ties, "
         "temporary contacts and status flags");
    return 0;
}
