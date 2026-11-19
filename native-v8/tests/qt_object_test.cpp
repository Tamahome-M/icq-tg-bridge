// Actual firmware QObject constructor and blockSignals(), SDK inline reader.
// Parenting exposed the missing SDK bit: custom moc emitters saw blocked=true.
#include <qapplication.h>
#include <qobject.h>
#include <assert.h>
#include <cstdio>
int main(int argc, char **argv) {
    QApplication app(argc, argv, false);
    assert(sizeof(void *) == 4 && sizeof(QObject) == 36);
    QObject owner;
    QObject child(&owner);
    assert(child.parent() == &owner && !child.isWidgetType());
    assert(!owner.signalsBlocked() && !child.signalsBlocked());
    child.blockSignals(true);
    assert(child.signalsBlocked() && !owner.signalsBlocked());
    child.blockSignals(false);
    assert(!child.signalsBlocked());
    owner.blockSignals(true);
    assert(owner.signalsBlocked() && !child.signalsBlocked());
    owner.blockSignals(false);
    assert(!owner.signalsBlocked());
    std::puts(
        "V8 QObject: parented/unparented inline flags match native blockSignals, size 36 PASS");
}
