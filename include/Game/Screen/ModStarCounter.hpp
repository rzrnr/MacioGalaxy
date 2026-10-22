#pragma once

#include "Game/Screen/LayoutActor.hpp"

class CountUpPaneRumbler;
class CounterLayoutAppearer;

// The stars of mods' galaxies (native/CUSTOM_GALAXY.md) under the game's star counter, shown and
// hidden with it. Its layout, LayoutData/GuglisStars.arc, is the star counter's with a star icon in
// the mods' theme colour (native/mods/theme.py); a mod with galaxies brings it, and without it there
// is no counter.
// Not part of the original game.
class ModStarCounter : public LayoutActor {
public:
    ModStarCounter();

    static bool isExistLayout();

    virtual void init(const JMapInfoIter& rIter);
    virtual void appear();
    virtual void control();

    void disappear();
    bool isWait() const;
    void exeAppear();
    void exeWait();
    void exeCountUp();
    void exeDisappear();

private:
    s32 mPowerStarNum;
    CounterLayoutAppearer* mLayoutAppearer;
    CountUpPaneRumbler* mPaneRumbler;
};
