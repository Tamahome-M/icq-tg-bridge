#ifndef TMM_ROSTER_ORDER_H
#define TMM_ROSTER_ORDER_H
#include "client.h"
#include <stddef.h>
namespace tmm {
// ContactList.vtCompareNodes / ContactItem.getSortWeight and getLowerText.
// Stable equal-name ordering; unread priority is applied by the roster view.
void sortRosterContacts(std::vector<size_t> &items, const std::vector<ContactRecord> &contacts,
                        bool byName);
} // namespace tmm
#endif
