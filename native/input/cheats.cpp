#include "petari/cheats.hpp"

#include <fstream>
#include <mutex>
#include <sstream>

namespace PetariNative::Cheats {
namespace {

std::atomic<bool> gKeepLives{true};
std::mutex gStoreLock;
std::filesystem::path gStore;  // under gStoreLock; empty before load

std::string trim(const std::string& text) {
    const auto first = text.find_first_not_of(" \t\r");
    if (first == std::string::npos) return {};
    const auto last = text.find_last_not_of(" \t\r");
    return text.substr(first, last - first + 1);
}

}  // namespace

bool keepLives() { return gKeepLives.load(std::memory_order_relaxed); }

void setKeepLives(bool on) { gKeepLives.store(on, std::memory_order_relaxed); }

std::string serialize() {
    std::ostringstream out;
    out << "# Petari cheats (native/MODS.md)\n"
        << "KeepLives=" << (keepLives() ? "on" : "off") << "\n";
    return out.str();
}

bool parse(const std::string& text, std::string* error) {
    std::istringstream in(text);
    std::string line;
    bool keep = keepLives();
    int number = 0;
    while (std::getline(in, line)) {
        number++;
        line = trim(line);
        if (line.empty() || line[0] == '#') continue;
        const auto equals = line.find('=');
        const std::string key = equals == std::string::npos ? line : trim(line.substr(0, equals));
        if (key != "KeepLives") continue;  // unknown lines are ignored
        const std::string value = equals == std::string::npos ? std::string() : trim(line.substr(equals + 1));
        if (value != "on" && value != "off") {
            if (error) *error = "line " + std::to_string(number) + ": KeepLives must be on or off";
            return false;
        }
        keep = value == "on";
    }
    setKeepLives(keep);
    return true;
}

bool load(const std::filesystem::path& file, std::string* error) {
    {
        std::lock_guard<std::mutex> guard(gStoreLock);
        gStore = file;
    }
    std::ifstream in(file);
    if (!in) return true;  // no file: defaults
    std::ostringstream text;
    text << in.rdbuf();
    if (!parse(text.str(), error)) {
        if (error) *error = file.string() + ": " + *error;
        return false;
    }
    return true;
}

bool save(std::string* error) {
    std::lock_guard<std::mutex> guard(gStoreLock);
    if (gStore.empty()) return true;
    const std::filesystem::path temporary = gStore.string() + ".tmp";
    {
        std::ofstream out(temporary, std::ios::trunc);
        out << serialize();
        if (!out) {
            if (error) *error = "cannot write " + temporary.string();
            return false;
        }
    }
    std::error_code ec;
    std::filesystem::rename(temporary, gStore, ec);
    if (ec) {
        if (error) *error = "cannot replace " + gStore.string() + ": " + ec.message();
        return false;
    }
    return true;
}

void resetForTesting() {
    std::lock_guard<std::mutex> guard(gStoreLock);
    gStore.clear();
    setKeepLives(true);
    currentLives.store(-1);
    requestedLives.store(-1);
}

}  // namespace PetariNative::Cheats
