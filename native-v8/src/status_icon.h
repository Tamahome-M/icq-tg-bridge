#ifndef TMM_STATUS_ICON_H
#define TMM_STATUS_ICON_H
#include <stdint.h>
namespace tmm {
// The same horizontal statuses.png atlas and priority as Java's JimmUI/Util.
inline unsigned statusIcon(uint32_t status) {
    if (status == 0xffffffffU)
        return 6;
    if (status & 2)
        return 2;
    if (status & 0x300)
        return 3;
    if (status & 0x10)
        return 5;
    if (status & 4)
        return 4;
    if (status & 0x20)
        return 1;
    if ((status & 0x2001) == 0x2001)
        return 12;
    if ((status & 0x3000) == 0x3000)
        return 8;
    if ((status & 0x5000) == 0x5000)
        return 10;
    if ((status & 0x6000) == 0x6000)
        return 11;
    if (status & 1)
        return 0;
    if (status & 0x4000)
        return 9;
    return 7;
}
} // namespace tmm
#endif
