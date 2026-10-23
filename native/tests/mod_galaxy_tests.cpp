// The mod galaxy registry (native/platform/dvd/mod_galaxy.cpp): galaxy.json parsing, messages by
// language with the English fallback, music borrowing, rejection, the save key, and loading from
// mod folders. Links: petari_platform_dvd.
#include <petari/platform/mod_galaxy.hpp>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>

namespace G = PetariNative::Platform::ModGalaxy;

static int sFailures = 0;
static void check(bool condition, const char* text) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", text);
        ++sFailures;
    }
}

static std::u16string u(const char16_t* p) { return p != nullptr ? std::u16string(p) : std::u16string(u"(null)"); }

static void testParse() {
    G::clear();
    std::string error;
    const char* json = R"({ "format": 1, "galaxies": [ {
        "name": "ModTestGalaxy",
        "title": { "en": "Blockout Test Galaxy", "fr": "Galaxie d'essai é" },
        "missions": [ { "en": "The Checkered Box" }, "Second" ],
        "music": "EggStarGalaxy" } ] })";
    check(G::loadText(json, "GalaxyTest", &error), "a valid galaxy.json loads");
    const G::Galaxy* pGalaxy = G::find("ModTestGalaxy");
    check(pGalaxy != nullptr && pGalaxy->mod == "GalaxyTest" && pGalaxy->missions.size() == 2, "the galaxy is registered with its missions");
    check(G::find("modtestgalaxy") == nullptr, "names are case-sensitive, like the game's tables");
    check(u(G::message("GalaxyName_ModTestGalaxy", "en")) == u"Blockout Test Galaxy", "galaxy name in English");
    check(u(G::message("GalaxyName_ModTestGalaxy", "fr")) == u"Galaxie d'essai é", "galaxy name in French (UTF-8 and \\u escapes)");
    check(u(G::message("GalaxyName_ModTestGalaxy", "es")) == u"Blockout Test Galaxy", "a missing language falls back to English");
    check(u(G::message("GalaxyNameShort_ModTestGalaxy", "en")) == u"Blockout Test Galaxy", "the short name defaults to the title");
    check(u(G::message("ScenarioName_ModTestGalaxy1", "en")) == u"The Checkered Box", "mission 1");
    check(u(G::message("ScenarioName_ModTestGalaxy2", "en")) == u"Second", "mission 2 as a plain string");
    check(G::message("ScenarioName_ModTestGalaxy3", "en") == nullptr, "no mission 3");
    check(G::message("GalaxyName_EggStarGalaxy", "en") == nullptr, "disc galaxies are not answered");
    check(G::message("ScenarioName_ModTestGalaxyX", "en") == nullptr, "a malformed mission id is not answered");
    const char16_t* pBefore = G::message("GalaxyName_ModTestGalaxy", "en");
    check(G::loadText(R"({"format":1,"galaxies":[{"name":"OtherGalaxy","title":"Other"}]})", "Other", &error), "a second mod loads");
    check(G::message("GalaxyName_ModTestGalaxy", "en") == pBefore, "message pointers stay valid as galaxies are added");
    check(G::musicFrom("ModTestGalaxy") != nullptr && std::string(G::musicFrom("ModTestGalaxy")) == "EggStarGalaxy", "borrowed music");
    check(G::musicFrom("OtherGalaxy") == nullptr && G::musicFrom("EggStarGalaxy") == nullptr, "no music borrowed otherwise");
    check(G::loadText(R"({"format":1,"galaxies":[{"name":"ModTestGalaxy","title":"Dup"}]})", "Late", &error) &&
              G::find("ModTestGalaxy")->mod == "GalaxyTest",
          "a name already registered by an earlier mod is kept");
    // The level editor's Missions panel: the mod's own galaxy changes in place; old texts stay readable.
    const char16_t* pMission = G::message("ScenarioName_ModTestGalaxy1", "en");
    check(G::update(R"({"format":1,"galaxies":[{"name":"ModTestGalaxy","title":"Renamed","missions":["Uno","Dos","Tres"],"music":"FlowerGalaxy"}]})",
                    "GalaxyTest", &error),
          "update loads");
    check(u(G::message("GalaxyName_ModTestGalaxy", "en")) == u"Renamed" && u(G::message("ScenarioName_ModTestGalaxy3", "en")) == u"Tres" &&
              std::string(G::musicFrom("ModTestGalaxy")) == "FlowerGalaxy",
          "update replaces the names, missions and music");
    check(u(pBefore) == u"Blockout Test Galaxy" && u(pMission) == u"The Checkered Box", "message pointers from before the update stay valid");
    check(G::update(R"({"format":1,"galaxies":[{"name":"ModTestGalaxy","title":"Stolen"}]})", "Late", &error) &&
              u(G::message("GalaxyName_ModTestGalaxy", "en")) == u"Renamed",
          "another mod's update leaves the galaxy alone");
    G::reject("OtherGalaxy", "test");
    check(G::find("OtherGalaxy") == nullptr && G::message("GalaxyName_OtherGalaxy", "en") == nullptr && G::all().size() == 1,
          "a rejected galaxy is gone");
}

static void testRefused() {
    G::clear();
    std::string error;
    check(!G::loadText("{", "M", &error) && !error.empty(), "broken JSON is refused");
    check(!G::loadText(R"({"format":2,"galaxies":[]})", "M", &error), "an unknown format is refused");
    check(!G::loadText(R"({"format":1,"galaxies":[]})", "M", &error), "an empty list is refused");
    check(!G::loadText(R"({"format":1,"galaxies":[{"name":"Bad Name","title":"x"}]})", "M", &error), "a name with a space is refused");
    check(!G::loadText(R"({"format":1,"galaxies":[{"name":"AVeryLongGalaxyNameThatDoesNotFitTheBuffers1234","title":"x"}]})", "M", &error),
          "a name longer than 40 is refused");
    check(!G::loadText(R"({"format":1,"galaxies":[{"name":"NoTitle"}]})", "M", &error), "a galaxy without a title is refused");
    check(!G::loadText(R"({"format":1,"galaxies":[{"name":"A","title":"a"},{"name":"B"}]})", "M", &error) && G::find("A") == nullptr,
          "one bad galaxy refuses the whole file");
    check(G::all().empty(), "nothing registered from refused files");
}

static void testSaveKey() {
    // The game's JGadget hash truncated to 16 bits (GameDataGalaxyStorage's record key).
    std::uint32_t h = 0;
    for (const char* p = "EggStarGalaxy"; *p; p++) {
        h = static_cast< std::uint32_t >(*p) + h * 31;
    }
    check(G::saveKey("EggStarGalaxy") == static_cast< std::uint16_t >(h), "save key = 16-bit JGadget hash");
    check(G::saveKey("ModTestGalaxy") != G::saveKey("EggStarGalaxy"), "distinct names, distinct keys here");
}

static void testLoadFromFolders() {
    G::clear();
    namespace fs = std::filesystem;
    const fs::path root = fs::temp_directory_path() / "petari_mod_galaxy_tests";
    fs::remove_all(root);
    fs::create_directories(root / "Good");
    fs::create_directories(root / "Broken");
    fs::create_directories(root / "Empty");
    std::ofstream(root / "Good" / "galaxy.json") << R"({"format":1,"galaxies":[{"name":"FolderGalaxy","title":"Folder"}]})";
    std::ofstream(root / "Broken" / "galaxy.json") << "not json";
    std::vector< std::string > log;
    G::load({root / "Good", root / "Broken", root / "Empty"}, &log);
    check(G::find("FolderGalaxy") != nullptr && G::find("FolderGalaxy")->mod == "Good", "loaded from <mod>/galaxy.json");
    bool refused = false, registered = false;
    for (const std::string& line : log) {
        refused = refused || line.find("Broken/galaxy.json refused") != std::string::npos;
        registered = registered || line.find("FolderGalaxy from mod Good") != std::string::npos;
    }
    check(refused && registered && log.size() == 2, "the log names what was registered and refused; a mod without galaxy.json is silent");
    fs::remove_all(root);
}

static void testSidecar() {
    namespace fs = std::filesystem;
    G::clear();
    std::string error;
    G::loadText(R"({"format":1,"galaxies":[{"name":"ModTestGalaxy","title":"T"},{"name":"SecondGalaxy","title":"S"}]})", "GalaxyTest", &error);
    G::loadText(R"({"format":1,"galaxies":[{"name":"OtherModGalaxy","title":"O"}]})", "OtherMod", &error);
    G::GalaxyRecord a;
    a.galaxy = "ModTestGalaxy";
    a.stars = 1;
    a.visited = 3;
    a.coins[0] = 42;
    check(G::saveRecords("mario1", {a}, &error), "no directory: saving is a no-op");
    check(G::loadRecords("mario1").empty(), "no directory: nothing loads");

    const fs::path dir = fs::temp_directory_path() / "petari_mod_galaxy_sidecar";
    fs::remove_all(dir);
    G::setSaveDirectory(dir);
    G::GalaxyRecord b = a;
    b.galaxy = "OtherModGalaxy";
    b.stars = 2;
    G::GalaxyRecord stray = a;
    stray.galaxy = "EggStarGalaxy";
    check(G::saveRecords("mario1", {a, b, stray}, &error), "save");
    check(fs::exists(dir / "GalaxyTest.json") && fs::exists(dir / "OtherMod.json") && !fs::exists(dir / "GalaxyTest.json.tmp"),
          "one sidecar per mod, written whole");
    G::GalaxyRecord c = a;
    c.stars = 5;
    check(G::saveRecords("mario2", {c}, &error), "save another user file");
    const std::vector< G::GalaxyRecord > one = G::loadRecords("mario1");
    bool foundA = false, foundB = false;
    for (const G::GalaxyRecord& r : one) {
        foundA = foundA || (r.galaxy == "ModTestGalaxy" && r.stars == 1 && r.visited == 3 && r.coins[0] == 42);
        foundB = foundB || (r.galaxy == "OtherModGalaxy" && r.stars == 2);
    }
    check(one.size() == 2 && foundA && foundB, "the first user file's records survive saving another file");
    const std::vector< G::GalaxyRecord > two = G::loadRecords("mario2");
    check(two.size() == 1 && two[0].stars == 5, "the second user file's record");
    check(G::loadRecords("mario3").empty(), "a file with no records");

    // A galaxy the registry no longer has is not loaded (its entry stays in the file).
    G::reject("SecondGalaxy", "test");
    G::GalaxyRecord d = a;
    d.galaxy = "SecondGalaxy";
    check(G::saveRecords("mario1", {a, d}, &error), "save with an unregistered galaxy");
    for (const G::GalaxyRecord& r : G::loadRecords("mario1")) {
        check(r.galaxy != "SecondGalaxy", "unregistered galaxies are not loaded");
    }
    G::setSaveDirectory({});
    fs::remove_all(dir);
}

// A user file created, deleted or copied (SaveDataHandler): its records follow it in every sidecar,
// also of a mod that is off now, so a new file in that slot inherits nothing.
static void testClearAndCopy() {
    namespace fs = std::filesystem;
    G::clear();
    std::string error;
    G::loadText(R"({"format":1,"galaxies":[{"name":"ModTestGalaxy","title":"T"}]})", "GalaxyTest", &error);
    G::loadText(R"({"format":1,"galaxies":[{"name":"OtherModGalaxy","title":"O"}]})", "OtherMod", &error);
    const fs::path dir = fs::temp_directory_path() / "petari_mod_galaxy_clear";
    fs::remove_all(dir);
    G::setSaveDirectory(dir);
    G::GalaxyRecord a;
    a.galaxy = "ModTestGalaxy";
    a.stars = 1;
    a.coins[0] = 30;
    G::GalaxyRecord b = a;
    b.galaxy = "OtherModGalaxy";
    b.stars = 2;
    check(G::saveRecords("mario1", {a, b}, &error) && G::saveRecords("luigi1", {a}, &error), "save two user files");

    check(G::copyRecords("mario2", "mario1", &error), "copy a user file");
    const std::vector< G::GalaxyRecord > copied = G::loadRecords("mario2");
    bool copiedA = false, copiedB = false;
    for (const G::GalaxyRecord& r : copied) {
        copiedA = copiedA || (r.galaxy == "ModTestGalaxy" && r.stars == 1 && r.coins[0] == 30);
        copiedB = copiedB || (r.galaxy == "OtherModGalaxy" && r.stars == 2);
    }
    check(copied.size() == 2 && copiedA && copiedB, "the copy has the source's records in both sidecars");

    G::clear();  // OtherMod is off now: its sidecar is still cleared
    G::loadText(R"({"format":1,"galaxies":[{"name":"ModTestGalaxy","title":"T"}]})", "GalaxyTest", &error);
    check(G::clearRecords("mario1", &error), "clear a user file");
    check(G::loadRecords("mario1").empty() && G::loadRecords("luigi1").size() == 1, "cleared: only that file's records go");
    G::loadText(R"({"format":1,"galaxies":[{"name":"OtherModGalaxy","title":"O"}]})", "OtherMod", &error);
    bool otherLeft = false;
    for (const G::GalaxyRecord& r : G::loadRecords("mario1")) otherLeft = otherLeft || r.galaxy == "OtherModGalaxy";
    check(!otherLeft, "the sidecar of a mod that was off is cleared too");
    check(G::loadRecords("mario2").size() == 2, "the copy keeps its records");

    check(G::copyRecords("mario2", "mario3", &error), "copy an empty user file over one with records");
    check(G::loadRecords("mario2").empty(), "an empty source leaves the destination empty");
    G::setSaveDirectory({});
    fs::remove_all(dir);
}

int main() {
    testParse();
    testRefused();
    testSaveKey();
    testLoadFromFolders();
    testSidecar();
    testClearAndCopy();
    if (sFailures != 0) {
        std::fprintf(stderr, "%d mod galaxy check(s) failed\n", sFailures);
        return 1;
    }
    std::puts("mod galaxy registry tests passed");
    return 0;
}
