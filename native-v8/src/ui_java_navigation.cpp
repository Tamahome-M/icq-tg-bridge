#include "window.h"
#include "ui_language.h"
#include "ui_settings.h"
#include <ZKeyDef.h>
#include <algorithm>

namespace tmm {
bool Window::javaKey(int code) {
    const bool left = code == KEYCODE_LSK;
    const bool right = code == KEYCODE_RSK;
    const bool clear = code == KEYCODE_CLEAR;
    const bool fire = code == KEYCODE_CENTER_SELECT || code == Key_Enter;
    if (connectionProgressVisible()) {
        if (left || right || clear)
            disconnectClient();
        return true;
    }
    if (mediaKey(code))
        return true;
    if (view().kind == View::Picture) {
        if (left || right || clear || fire || code == KEYCODE_0 || code == KEYCODE_5)
            back();
        else if (code == KEYCODE_UP) {
            int zoom = std::min(400, pictureZoom_ + 25);
            uint64_t pixels = uint64_t(picture_.width()) * picture_.height();
            if (pixels * zoom * zoom / 10000 <= 2000000)
                pictureZoom_ = zoom;
        } else if (code == KEYCODE_DOWN)
            pictureZoom_ = std::max(1, pictureZoom_ - (pictureZoom_ > 25 ? 25 : 5));
        else if (code == KEYCODE_LEFT)
            pictureRotation_ = (pictureRotation_ + 270) % 360;
        else if (code == KEYCODE_RIGHT)
            pictureRotation_ = (pictureRotation_ + 90) % 360;
        update();
        return true;
    }
    // Java TextLists wrap the menu cursor and never select section headers.
    if (systemMenuVisible() && view().kind != View::Roster &&
        (code == KEYCODE_UP || code == KEYCODE_DOWN)) {
        const int count = view().rows.size();
        for (int i = 0; i < count; ++i) {
            view().selected = (view().selected + (code == KEYCODE_DOWN ? 1 : count - 1)) % count;
            if (!view().rows[view().selected].action.empty() &&
                view().rows[view().selected].action != "settings-heading")
                break;
        }
        update();
        return true;
    }
    if (view().context == "privacy-editor") {
        if (left || clear)
            back();
        else if (right)
            activate(Row(QString::null, "privacy-menu"));
        else if (code == KEYCODE_LEFT || code == KEYCODE_RIGHT)
            activate(Row(QString::null, "privacy-column", 0,
                         (view().offset + (code == KEYCODE_RIGHT ? 1 : 2)) % 3));
        else if (fire)
            return true;
        else
            return false;
        return true;
    }
    if (settingsPageActive()) {
        if (left || clear)
            finishSettings(false);
        else if (right)
            finishSettings(true);
        else
            return false;
        return true;
    }
    if (view().context == "quiet-settings") {
        if (left)
            activate(Row(QString::null, "quiet-save", view().uin));
        else if (right || clear)
            back();
        else
            return false;
        return true;
    }
    if (view().kind == View::Popup) {
        if (left || clear) {
            back();
            return true;
        }
        if (right || fire || code == KEYCODE_5) {
            activateSelected();
            return true;
        }
    }
    if (view().context == "contact-info" && (code == KEYCODE_UP || code == KEYCODE_DOWN)) {
        View &v = view();
        if (!v.rows.empty()) {
            int overflow = std::max(0, rowHeight(v.rows[v.selected]) - (height() - 56));
            if (code == KEYCODE_DOWN && v.scroll < overflow)
                v.scroll = std::min(overflow, v.scroll + std::max(20, height() / 3));
            else if (code == KEYCODE_UP && v.scroll > 0)
                v.scroll = std::max(0, v.scroll - std::max(20, height() / 3));
            else {
                v.selected = std::max(0, std::min(int(v.rows.size()) - 1,
                                                  v.selected + (code == KEYCODE_DOWN ? 1 : -1)));
                v.scroll = 0;
            }
        }
        update();
        return true;
    }
    if (!(left || right || clear))
        return false;
    if (view().kind == View::Roster) {
        if (right)
            activateSelected();
        else
            mainMenu();
    } else if (view().kind == View::Chat) {
        if (right)
            chatMenu();
        else
            home();
    } else if (view().kind == View::History) {
        if (right)
            messageMenu();
        else
            back();
    } else if (view().kind == View::Templates) {
        if (right)
            templateMenu(view().context == "insert");
        else if (left && view().context == "insert")
            activateSelected();
        else
            back();
    } else if (view().kind == View::Text || view().context == "contact-info") {
        if (right && view().context == "contact-info" && !view().request) {
            View menu(View::Popup, uiText("Меню"));
            menu.context = "info-menu";
            menu.rows.push_back(Row(uiText("Коп-ть всё"), "info-copy-all"));
            menu.rows.push_back(Row(uiText("Копировать"), "info-copy"));
            menu.selected = 1;
            push(menu);
        } else if (!right)
            back();
    } else if (view().context == "main-menu" && left && !contacts_.empty())
        home();
    else if (right)
        activateSelected();
    else
        back();
    return true;
}
} // namespace tmm
