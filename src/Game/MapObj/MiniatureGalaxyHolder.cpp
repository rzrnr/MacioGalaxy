#include "Game/MapObj/MiniatureGalaxyHolder.hpp"
#include "Game/LiveActor/LiveActorGroup.hpp"
#include "Game/Map/SphereSelector.hpp"
#include "Game/MapObj/MiniatureGalaxy.hpp"
#include "Game/Scene/SceneObjHolder.hpp"
#include "Game/Util/DemoUtil.hpp"
#include "Game/Util/EventUtil.hpp"
#include "Game/Util/StringUtil.hpp"

#ifdef PETARI_NATIVE
#include <petari/mod_galaxies.hpp>

namespace {
    bool isModMiniature(const MiniatureGalaxy* pGalaxy) {
        return PetariNative::ModGalaxies::isMod(pGalaxy->mGalaxyName);
    }
}  // namespace
#endif

namespace {
    MiniatureGalaxyHolder* getHolder() {
        return MR::getSceneObj< MiniatureGalaxyHolder >(SceneObj_MiniatureGalaxyHolder);
    }
};  // namespace

MiniatureGalaxyHolder::MiniatureGalaxyHolder()
    : LiveActor("ミニチュアギャラクシー保持"), mMiniatureGalaxyGroup(), _90(), mCometGalaxy(), mCometID(-1), _9C() {
    mMiniatureGalaxyGroup = new LiveActorGroup("ミニチュアギャラクシーグループ", 16);
}

void MiniatureGalaxyHolder::registerActor(LiveActor* pActor, const JMapInfoIter& rIter) {
    mMiniatureGalaxyGroup->registerActor(pActor);

    if (_90) {
        return;
    }

    MR::tryRegisterDemoCast(this, rIter);
    MR::registerDemoActionFunctor(this, MR::Functor(this, &MiniatureGalaxyHolder::killAllMiniatureGalaxy), "飛び出す");

    _90 = true;
}

void MiniatureGalaxyHolder::init(const JMapInfoIter& rIter) {
    makeActorAppeared();
}

#pragma push
#pragma ppc_iro_level 1

bool MiniatureGalaxyHolder::isRegisteredActor(const LiveActor* pActor) {
    for (int i = 0; i < mMiniatureGalaxyGroup->getObjNum(); i++) {
        if (mMiniatureGalaxyGroup->getActor(i) == pActor) {
            return true;
        }
    }

    return false;
}

#pragma ppc_iro_level 2

MiniatureGalaxy* MiniatureGalaxyHolder::findMiniatureGalaxy(const char* pGalaxyName) const {
    MiniatureGalaxy* miniatureGalaxy;

    for (int i = 0; i < mMiniatureGalaxyGroup->getObjNum(); i++) {
        miniatureGalaxy = static_cast< MiniatureGalaxy* >(mMiniatureGalaxyGroup->getActor(i));

        if (MR::isEqualString(miniatureGalaxy->mGalaxyName, pGalaxyName)) {
            return miniatureGalaxy;
        }
    }

    return nullptr;
}

void MiniatureGalaxyHolder::killAllMiniatureGalaxy() {
    for (int i = 0; i < mMiniatureGalaxyGroup->getObjNum(); i++) {
        mMiniatureGalaxyGroup->getActor(i)->kill();
    }
}

s32 MiniatureGalaxyHolder::calcIndex(const LiveActor* pActor) const {
    const char* galaxyName = static_cast< const MiniatureGalaxy* >(pActor)->mGalaxyName;
    s32 mStarNum = MR::getPowerStarNumToOpenGalaxy(galaxyName);
    s32 index = 0;
#ifdef PETARI_NATIVE
    // A mod's galaxies (native/CUSTOM_GALAXY.md) orbit outside the dome's own, in placement order,
    // and inside the Bowser or Bowser Jr. one; the dome's own keep their places.
    const MiniatureGalaxy* pSelf = static_cast< const MiniatureGalaxy* >(pActor);
    if (pSelf->mType != MiniatureGalaxyType_Koopa) {
        const bool selfMod = isModMiniature(pSelf);
        bool beforeSelf = true;  // in placement order
        for (int i = 0; i < mMiniatureGalaxyGroup->getObjNum(); i++) {
            const MiniatureGalaxy* pOther = static_cast< const MiniatureGalaxy* >(mMiniatureGalaxyGroup->getActor(i));
            if (pOther == pSelf) {
                beforeSelf = false;
                continue;
            }
            if (pOther->mType == MiniatureGalaxyType_Koopa) {
                continue;
            }
            const bool otherMod = isModMiniature(pOther);
            if (selfMod && !otherMod) {
                index++;
            } else if (selfMod && otherMod) {
                index += beforeSelf ? 1 : 0;
            } else if (!selfMod && !otherMod && MR::getPowerStarNumToOpenGalaxy(pOther->mGalaxyName) < mStarNum) {
                index++;
            }
        }
        return index;
    }
#endif
    MiniatureGalaxy* actorGalaxy = findMiniatureGalaxy(galaxyName);

    for (int i = 0; i < mMiniatureGalaxyGroup->getObjNum(); i++) {
        MiniatureGalaxy* currMiniGalaxy = static_cast< MiniatureGalaxy* >(mMiniatureGalaxyGroup->getActor(i));

        if (currMiniGalaxy->mType == MiniatureGalaxyType_Koopa) {
            continue;
        }
        if (currMiniGalaxy == actorGalaxy) {
            continue;
        }

        if (actorGalaxy->mType == MiniatureGalaxyType_Koopa) {
            index++;
        } else if (MR::getPowerStarNumToOpenGalaxy(currMiniGalaxy->mGalaxyName) < mStarNum) {
            index++;
        }
    }

    return index;
}

#pragma ppc_iro_level 1

void MiniatureGalaxyHolder::updateCometStatus() {
    mCometGalaxy = nullptr;
    mCometID = -1;
    _9C = 0;

    for (int i = 0; i < mMiniatureGalaxyGroup->getObjNum(); i++) {
        MiniatureGalaxy* miniatureGalaxy = static_cast< MiniatureGalaxy* >(mMiniatureGalaxyGroup->getActor(i));

        if (MR::isGalaxyCometLandInStage(miniatureGalaxy->mGalaxyName)) {
            mCometGalaxy = miniatureGalaxy;
            break;
        }
    }

    if (mCometGalaxy != nullptr) {
        mCometID = MR::getEncounterGalaxyCometNameId(mCometGalaxy->mGalaxyName);
    }
}

void MiniatureGalaxyFunction::registerMiniatureGalaxyToHolder(LiveActor* pActor, const JMapInfoIter& rIter) {
    MR::createSceneObj(SceneObj_MiniatureGalaxyHolder);
    ::getHolder()->registerActor(pActor, rIter);
}

s32 MiniatureGalaxyFunction::getMiniatureGalaxyNum() {
    return ::getHolder()->mMiniatureGalaxyGroup->getObjNum();
}

s32 MiniatureGalaxyFunction::calcMiniatureGalaxyIndex(const LiveActor* pActor) {
    return ::getHolder()->calcIndex(pActor);
}

void MiniatureGalaxyFunction::updateCometStatus() {
    ::getHolder()->updateCometStatus();
}

MiniatureGalaxy* MiniatureGalaxyFunction::getCometLandMiniatureGalaxy() {
    return ::getHolder()->mCometGalaxy;
}

s32 MiniatureGalaxyFunction::getCometNameId() {
    return ::getHolder()->mCometID;
}

MiniatureGalaxy* MiniatureGalaxyFunction::getPointingMiniatureGalaxy() {
    if (SphereSelectorFunction::isPointingTarget()) {
        LiveActor* pointingTarget = SphereSelectorFunction::getPointingTarget();

        if (::getHolder()->isRegisteredActor(pointingTarget)) {
            return static_cast< MiniatureGalaxy* >(pointingTarget);
        }
    }

    return nullptr;
}
