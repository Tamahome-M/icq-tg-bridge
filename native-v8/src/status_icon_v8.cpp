#include "status_icon_v8.h"
#include "status_icon.h"
#include <ZHeader.h>
#include <RES_ICON_Reader.h>
#include <qapplication.h>
#include <stdio.h>
// Verified against SAedition's registerInfo serializer and array destructor.
typedef char TmmAppStatusInfoSize[sizeof(ZHeader::AppStatusInfo_S) == 16 ? 1 : -1];
typedef char TmmAppStatusSize[sizeof(ZHeader::AppStatus_S) == 20 ? 1 : -1];
namespace tmm {
namespace {
StatusIconV8 *applicationIcon = 0;
const char *resources[][2] = {{"im_offline_cli4", "im_offline_idle4"},
                              {"im_icq_cli4", "im_icq_idle5"},
                              {"im_icq_away_cli4", "im_icq_away_idle5"},
                              {"im_busy_cli4", "im_busy_idle4"},
                              {"im_icq_invisible_cli4", "im_icq_invisible_idle5"}};
const char *patchedResources[][2] = {{"tmm_offline_cli", "tmm_offline_main"},
                                     {"im_icq_cli4", "im_icq_idle5"},
                                     {"im_icq_away_cli4", "im_icq_away_idle5"},
                                     {"im_busy_cli4", "im_busy_idle4"},
                                     {"im_icq_invisible_cli4", "im_icq_invisible_idle5"},
                                     {"tmm_msg_offline_cli", "tmm_msg_offline_main"},
                                     {"tmm_msg_online_cli", "tmm_msg_online_main"},
                                     {"tmm_msg_away_cli", "tmm_msg_away_main"},
                                     {"tmm_msg_busy_cli", "tmm_msg_busy_main"},
                                     {"tmm_msg_invisible_cli", "tmm_msg_invisible_main"}};
unsigned nativeState(uint32_t status) {
    switch (statusIcon(status)) {
    case 6:
        return 0; // The firmware's grey offline indicator.
    case 0:
    case 4:
    case 9:
    case 12:
        return 2;
    case 2:
    case 5:
    case 8:
        return 3;
    case 3:
        return 4;
    default:
        return 1;
    }
}
} // namespace
StatusIconV8::StatusIconV8()
    : registered_(false), resourcesChecked_(false), patched_(false), mode_(0), slot_(ZHeader::IM),
      state_(0xffffffffU) {
    if (!applicationIcon)
        applicationIcon = this;
}
StatusIconV8::~StatusIconV8() {
    hide();
    if (applicationIcon == this)
        applicationIcon = 0;
}
void StatusIconV8::configureApplication(unsigned mode, uint32_t status, bool unread) {
    // Apply runtime preferences to the application-owned registration,
    // independently of the foreground window.
    static bool reportedUnavailable = false;
    const bool available = !applicationIcon || applicationIcon->show(mode, status, unread);
    if (!available && !reportedUnavailable)
        fprintf(stderr, "Status icon: Motorola header service is unavailable\n");
    reportedUnavailable = !available;
}
void StatusIconV8::themeChanged() {
    if (applicationIcon) {
        applicationIcon->hide();
        applicationIcon->resourcesChecked_ = false;
    }
}
bool StatusIconV8::show(unsigned mode, uint32_t status, bool unread) {
    if (!mode) {
        hide();
        return true;
    }
    if (mode > 2)
        mode = 1;
    if (!resourcesChecked_) {
        RES_ICON_Reader reader;
        patched_ = !reader.getIcon("tmm_status_v1", false).isNull();
        // Validate the whole bundle once per theme, never on every message.
        for (unsigned i = 0; patched_ && i < 10; ++i)
            for (unsigned d = 0; patched_ && d < 2; ++d)
                patched_ = !reader.getIcon(patchedResources[i][d], false).isNull();
        resourcesChecked_ = true;
    }
    const unsigned state = nativeState(status) + ((patched_ && unread) ? 5 : 0);
    if (registered_ && mode_ == mode) {
        if (state_ == state)
            return true;
        if (!ZHeader::changeStatus(static_cast<ZHeader::HEADER_STATUS>(slot_), state))
            return false;
        state_ = state;
        return true;
    }
    hide();
    // These are existing firmware slots, not new indices into its fixed
    // tables. IM is in the header (shared with BT/USB); ICQ is in the idle row.
    ZHeader::HEADER_STATUS slot = mode == 2 ? ZHeader::ICQ : ZHeader::IM;
    ZHeader::AppStatusInfo_S info;
    info.status = slot;
    info.numStatus = patched_ ? 10 : 5;
    info.priority = 3;
    info.appStatus = new ZHeader::AppStatus_S[info.numStatus];
    for (int i = 0; i < info.numStatus; ++i) {
        info.appStatus[i].status = i;
        for (unsigned display = 0; display < 4; ++display)
            info.appStatus[i].strResID[display] =
                patched_ ? patchedResources[i][display / 2] : resources[i][display / 2];
    }
    // registerInfo serializes the array immediately; its owning info object
    // releases the temporary strings after this call, not while the IPC uses it.
    if (!ZHeader::registerInfo(info))
        return false;
    registered_ = true;
    mode_ = mode;
    slot_ = slot;
    if (!ZHeader::changeStatus(slot, state)) {
        hide();
        return false;
    }
    state_ = state;
    return true;
}
void StatusIconV8::hide() {
    if (!registered_)
        return;
    registered_ = false;
    mode_ = 0;
    state_ = 0xffffffffU;
    ZHeader::HEADER_STATUS slot = static_cast<ZHeader::HEADER_STATUS>(slot_);
    ZHeader::changeStatus(slot, ZHeader::EMPTY_STATUS);
    ZHeader::unregisterInfo(slot);
    // main's event loop has already stopped on normal exit. Deliver the
    // queued QWS messages without re-entering any application callbacks.
    QApplication::flushX();
}
} // namespace tmm
