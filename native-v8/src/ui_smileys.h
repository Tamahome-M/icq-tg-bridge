#ifndef TMM_UI_SMILEYS_H
#define TMM_UI_SMILEYS_H
#include <string>
#include <vector>
namespace tmm {
struct SmileyDefinition {
    unsigned index;
    std::string label, code;
    SmileyDefinition(unsigned image, const std::string &name, const std::string &text)
        : index(image), label(name), code(text) {}
};
// Reads the shared Java SMILES_STD manifest, including every selectable entry.
// On failure neither definitions nor cellSize is replaced by partial data.
bool loadJavaSmileys(const std::string &path, std::vector<SmileyDefinition> &definitions,
                     unsigned &cellSize, std::string &error);
} // namespace tmm
#endif
