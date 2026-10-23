#include "Game/System/GameDataPlayerStatus.hpp"
#include "Game/Util/MathUtil.hpp"
#include <JSystem/JSupport/JSUMemoryInputStream.hpp>
#include <JSystem/JSupport/JSUMemoryOutputStream.hpp>
#ifdef PETARI_NATIVE
#include <cstdio>
#include <petari/cheats.hpp>
#endif

GameDataPlayerStatus::GameDataPlayerStatus() {
    initializeData();
}

u32 GameDataPlayerStatus::makeHeaderHashCode() const {
    return 0x27C90F;
}

u32 GameDataPlayerStatus::getSignature() const {
    return 'PLAY';
}

s32 GameDataPlayerStatus::serialize(u8* pBuffer, u32 size) const {
    JSUMemoryOutputStream stream = JSUMemoryOutputStream(pBuffer, size);

    u8 storyProgress = mStoryProgress;
    stream.write(&storyProgress, sizeof(mStoryProgress));

    u32 stockedStarPiece = mStockedStarPiece;
    stream.write(&stockedStarPiece, sizeof(mStockedStarPiece));

    u16 playerLeft = mPlayerLeft;
    stream.write(&playerLeft, sizeof(mPlayerLeft));

    return stream.mPosition;
}

s32 GameDataPlayerStatus::deserialize(const u8* pBuffer, u32 size) {
    initializeData();

    JSUMemoryInputStream stream = JSUMemoryInputStream(pBuffer, size);

    stream.read(&mStoryProgress, sizeof(mStoryProgress));
    stream.read(&mStockedStarPiece, sizeof(mStockedStarPiece));

    if (stream.getAvailable() != 0) {
        stream.read(&mPlayerLeftSupply, sizeof(mPlayerLeftSupply));
    }

    mPlayerLeft = 4;

#ifdef PETARI_NATIVE
    // The file saved its 1-Ups in the field read into mPlayerLeftSupply (10 or
    // more there earns a refill from a Toad). Cheats -> Keep 1-Ups when loading
    // (native/MODS.md) starts with that count instead, and then has no refill.
    // Older files end before the 1-Ups (7 bytes: u8, u32, u16) and keep the 4.
    if (PetariNative::Cheats::keepLives() && size >= sizeof(u8) + sizeof(u32) + sizeof(u16)) {
        mPlayerLeft = MR::clamp(static_cast<s32>(mPlayerLeftSupply), 1, 99);
        mPlayerLeftSupply = 0;
        if (mPlayerLeft != 4) {
            std::fprintf(stderr, "petari: cheats: a loaded file keeps its %d saved 1-Ups\n", static_cast<int>(mPlayerLeft));
        }
    }
#endif

    return 0;
}

void GameDataPlayerStatus::initializeData() {
    mPlayerLeft = 4;
    mPlayerLeftSupply = 4;
    mStockedStarPiece = 0;
    mStoryProgress = 0;
}

s32 GameDataPlayerStatus::getPlayerLeft() const {
    s32 playerLeft = mPlayerLeft;

    return MR::clamp(playerLeft, 0, 99);
}

void GameDataPlayerStatus::addPlayerLeft(int num) {
    s32 playerLeft = mPlayerLeft + num;

    mPlayerLeft = MR::clamp(playerLeft, 0, 99);
}

bool GameDataPlayerStatus::isPlayerLeftSupply() const {
    return mPlayerLeftSupply >= 10;
}

void GameDataPlayerStatus::offPlayerLeftSupply() {
    mPlayerLeftSupply = 0;
}

void GameDataPlayerStatus::addStockedStarPiece(int num) {
    s32 stockedStarPiece = mStockedStarPiece + num;

    mStockedStarPiece = MR::clamp(stockedStarPiece, 0, 9999);
}
