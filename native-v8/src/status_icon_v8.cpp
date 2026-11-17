#include "status_icon_v8.h"
#include <ZHeader.h>
#include <qapplication.h>
#include <stdio.h>
// Verified against SAedition's registerInfo serializer and array destructor.
typedef char TmmAppStatusInfoSize[sizeof(ZHeader::AppStatusInfo_S) == 16 ? 1 : -1];
typedef char TmmAppStatusSize[sizeof(ZHeader::AppStatus_S) == 20 ? 1 : -1];
namespace tmm {
namespace {
StatusIconV8 *applicationIcon = 0;
}
StatusIconV8::StatusIconV8() : registered_(false), mode_(0), slot_(ZHeader::IM) {
    if (!applicationIcon)
        applicationIcon = this;
}
StatusIconV8::~StatusIconV8() {
    hide();
    if (applicationIcon == this)
        applicationIcon = 0;
}
void StatusIconV8::configureApplication(unsigned mode) {
    // Apply runtime preferences to the application-owned registration,
    // independently of the foreground window or network session.
    if (applicationIcon && !applicationIcon->show(mode))
        fprintf(stderr, "Status icon: Motorola header service is unavailable\n");
}
bool StatusIconV8::show(unsigned mode) {
    if (!mode) {
        hide();
        return true;
    }
    if (mode > 2)
        mode = 1;
    if (registered_ && mode_ == mode)
        return true;
    hide();
    // These are existing firmware slots, not new indices into its fixed
    // tables. IM is in the header (shared with BT/USB); ICQ is in the idle row.
    ZHeader::HEADER_STATUS slot = mode == 2 ? ZHeader::ICQ : ZHeader::IM;
    ZHeader::AppStatusInfo_S info;
    info.status = slot;
    info.numStatus = 1;
    info.priority = 3;
    info.appStatus = new ZHeader::AppStatus_S[1];
    info.appStatus[0].status = 0;
    info.appStatus[0].strResID[0] = "im_icq_cli4";
    info.appStatus[0].strResID[1] = "im_icq_cli4";
    info.appStatus[0].strResID[2] = "im_icq_idle5";
    info.appStatus[0].strResID[3] = "im_icq_idle5";
    // registerInfo serializes the array immediately; its owning info object
    // releases the temporary strings after this call, not while the IPC uses it.
    if (!ZHeader::registerInfo(info))
        return false;
    registered_ = true;
    mode_ = mode;
    slot_ = slot;
    if (!ZHeader::changeStatus(slot, 0)) {
        hide();
        return false;
    }
    return true;
}
void StatusIconV8::hide() {
    if (!registered_)
        return;
    registered_ = false;
    mode_ = 0;
    ZHeader::HEADER_STATUS slot = static_cast<ZHeader::HEADER_STATUS>(slot_);
    ZHeader::changeStatus(slot, ZHeader::EMPTY_STATUS);
    ZHeader::unregisterInfo(slot);
    // main's event loop has already stopped on normal exit. Deliver the
    // queued QWS messages without re-entering any application callbacks.
    QApplication::flushX();
}
} // namespace tmm
