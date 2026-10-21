#ifdef PETARI_NATIVE
// Frame interpolation (Game/System/FrameInterpolation.hpp, native/FRAME_RATE.md).
#include "Game/System/FrameInterpolation.hpp"
#include "Game/Camera/CameraContext.hpp"
#include "Game/Player/MarioAccess.hpp"
#include "Game/Player/MarioActor.hpp"
#include "Game/Scene/SceneObjHolder.hpp"
#include "Game/System/GameSystem.hpp"
#include "Game/System/GameSystemObjHolder.hpp"
#include "Game/System/MainLoopFramework.hpp"
#include "Game/Util/DemoUtil.hpp"
#include "Game/Util/ScreenUtil.hpp"
#include "Game/Util/SceneUtil.hpp"
#include <JSystem/J3DGraphAnimator/J3DModel.hpp>
#include <JSystem/J3DGraphAnimator/J3DModelData.hpp>
#include <JSystem/J3DGraphAnimator/J3DMtxBuffer.hpp>

#include <petari/app.hpp>

#include <cmath>
#include <cstring>

namespace SceneFunction {
    void executeCalcViewAndEntryList();
}

extern void (*gJ3DModelViewCalcHook)(J3DModel*);  // J3DModel.cpp


namespace {
    constexpr int kMaxModels = 1024;
    constexpr int kMaxMatrices = 16384;
    // A model whose root moves further than this in one step was placed, not moved: drawn exactly.
    constexpr f32 kModelCut = 1000.0f;
    // A camera that moves further, or turns more than 45 degrees, in one step cut: no extra frame.
    constexpr f32 kCameraCut = 1500.0f;
    constexpr f32 kCameraCutCosHalfAngle = 0.9239f;

    struct ModelState {
        J3DModel* model;
        J3DModelData* data;
        Mtx* anm;      // the joint matrices, shared by Mario's models
        u16 joints;
        bool ownsAnm;  // the first entry with this anm buffer keeps (and blends) its matrices
        int matrices;  // index of the joint matrices in Snapshot::matrices
        Mtx base;
        Vec scale;
    };

    struct CameraState {
        TPos3f view;
        TPos3f viewInv;
        TProj3f projection;
        f32 fovy;
        TVec2f shake;
    };

    struct Snapshot {
        ModelState models[kMaxModels];
        int modelCount;
        Mtx matrices[kMaxMatrices];
        int matrixCount;
        CameraState camera;
        bool valid;
    };

    Snapshot sBefore;  // the step that was drawn, kept before the update
    Snapshot sAfter;   // the new step, kept while the extra frame is drawn
    J3DModel* sSeen[kMaxModels];
    int sSeenCount = 0;
    bool sDrawingExtraFrame = false;
    bool sGameSceneViews = false;  // GameScene::calcAnim calculated its views this step
    alignas(32) u8 sMarioBytes[sizeof(MarioActor)];
    // The extra frame's display copy: its own XFB address, so the present shows it without
    // touching VI's XFBs (native/gx/present).
    alignas(32) u8 sExtraXfb[640 * 576 * 2];

    CameraContext* cameraContext() {
        return MR::isExistSceneObj(SceneObj_CameraContext) ? MR::getSceneObj< CameraContext >(SceneObj_CameraContext) : nullptr;
    }

    void take(Snapshot* pSnapshot) {
        pSnapshot->modelCount = 0;
        pSnapshot->matrixCount = 0;
        pSnapshot->valid = false;
        CameraContext* pCamera = cameraContext();
        if (pCamera == nullptr) {
            return;
        }
        pSnapshot->camera.view = pCamera->mView;
        pSnapshot->camera.viewInv = pCamera->mViewInv;
        pSnapshot->camera.projection = pCamera->mProjection;
        pSnapshot->camera.fovy = pCamera->mFovy;
        pSnapshot->camera.shake = pCamera->mShakeOffset;
        for (int i = 0; i < sSeenCount; i++) {
            J3DModel* pModel = sSeen[i];
            J3DMtxBuffer* pBuffer = pModel->getMtxBuffer();
            const u16 joints = pModel->getModelData()->getJointNum();
            if (pSnapshot->modelCount >= kMaxModels) {
                return;
            }
            bool owns = true;
            for (int j = 0; j < pSnapshot->modelCount; j++) {
                owns = owns && pSnapshot->models[j].anm != pBuffer->mpAnmMtx;
            }
            if (owns && pSnapshot->matrixCount + joints > kMaxMatrices) {
                return;
            }
            ModelState& state = pSnapshot->models[pSnapshot->modelCount++];
            state.model = pModel;
            state.data = pModel->getModelData();
            state.anm = pBuffer->mpAnmMtx;
            state.joints = joints;
            state.ownsAnm = owns;
            state.matrices = pSnapshot->matrixCount;
            PSMTXCopy(pModel->mBaseTransformMtx, state.base);
            state.scale = pModel->mBaseScale;
            if (owns) {
                std::memcpy(pSnapshot->matrices[pSnapshot->matrixCount], state.anm, joints * sizeof(Mtx));
                pSnapshot->matrixCount += joints;
            }
        }
        pSnapshot->valid = true;
    }

    const ModelState* findBefore(const ModelState& rAfter) {
        for (int i = 0; i < sBefore.modelCount; i++) {
            const ModelState& state = sBefore.models[i];
            if (state.model == rAfter.model) {
                const bool same = state.data == rAfter.data && state.anm == rAfter.anm && state.joints == rAfter.joints &&
                                  state.ownsAnm == rAfter.ownsAnm;
                return same ? &state : nullptr;
            }
        }
        return nullptr;
    }

    // --- Halfway between two matrices: translation and scale averaged, rotation by quaternion. ---
    struct Quat {
        f32 x, y, z, w;
    };

    Quat toQuat(const f32 m[3][3]) {
        Quat q;
        const f32 trace = m[0][0] + m[1][1] + m[2][2];
        if (trace > 0.0f) {
            const f32 s = std::sqrt(trace + 1.0f) * 2.0f;
            q.w = 0.25f * s;
            q.x = (m[2][1] - m[1][2]) / s;
            q.y = (m[0][2] - m[2][0]) / s;
            q.z = (m[1][0] - m[0][1]) / s;
        } else if (m[0][0] > m[1][1] && m[0][0] > m[2][2]) {
            const f32 s = std::sqrt(1.0f + m[0][0] - m[1][1] - m[2][2]) * 2.0f;
            q.w = (m[2][1] - m[1][2]) / s;
            q.x = 0.25f * s;
            q.y = (m[0][1] + m[1][0]) / s;
            q.z = (m[0][2] + m[2][0]) / s;
        } else if (m[1][1] > m[2][2]) {
            const f32 s = std::sqrt(1.0f + m[1][1] - m[0][0] - m[2][2]) * 2.0f;
            q.w = (m[0][2] - m[2][0]) / s;
            q.x = (m[0][1] + m[1][0]) / s;
            q.y = 0.25f * s;
            q.z = (m[1][2] + m[2][1]) / s;
        } else {
            const f32 s = std::sqrt(1.0f + m[2][2] - m[0][0] - m[1][1]) * 2.0f;
            q.w = (m[1][0] - m[0][1]) / s;
            q.x = (m[0][2] + m[2][0]) / s;
            q.y = (m[1][2] + m[2][1]) / s;
            q.z = 0.25f * s;
        }
        return q;
    }

    void fromQuat(const Quat& q, f32 m[3][3]) {
        const f32 xx = q.x * q.x, yy = q.y * q.y, zz = q.z * q.z;
        const f32 xy = q.x * q.y, xz = q.x * q.z, yz = q.y * q.z;
        const f32 wx = q.w * q.x, wy = q.w * q.y, wz = q.w * q.z;
        m[0][0] = 1.0f - 2.0f * (yy + zz);
        m[0][1] = 2.0f * (xy - wz);
        m[0][2] = 2.0f * (xz + wy);
        m[1][0] = 2.0f * (xy + wz);
        m[1][1] = 1.0f - 2.0f * (xx + zz);
        m[1][2] = 2.0f * (yz - wx);
        m[2][0] = 2.0f * (xz - wy);
        m[2][1] = 2.0f * (yz + wx);
        m[2][2] = 1.0f - 2.0f * (xx + yy);
    }

    // The rotation and per-axis scale of a 3x4 matrix's 3x3 part (columns scaled); false for shear,
    // mirroring or a zero axis, which are blended element by element instead.
    bool decompose(const Mtx m, f32 rotation[3][3], f32 scale[3]) {
        for (int c = 0; c < 3; c++) {
            scale[c] = std::sqrt(m[0][c] * m[0][c] + m[1][c] * m[1][c] + m[2][c] * m[2][c]);
            if (scale[c] < 1e-6f) {
                return false;
            }
            for (int r = 0; r < 3; r++) {
                rotation[r][c] = m[r][c] / scale[c];
            }
        }
        for (int a = 0; a < 3; a++) {
            for (int b = a + 1; b < 3; b++) {
                const f32 dot = rotation[0][a] * rotation[0][b] + rotation[1][a] * rotation[1][b] + rotation[2][a] * rotation[2][b];
                if (std::fabs(dot) > 0.01f) {
                    return false;
                }
            }
        }
        const f32 det = rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1]) -
                        rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0]) +
                        rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0]);
        return det > 0.0f;
    }

    void halfway(const Mtx a, const Mtx b, Mtx out) {
        for (int r = 0; r < 3; r++) {
            out[r][3] = (a[r][3] + b[r][3]) * 0.5f;
        }
        f32 ra[3][3], rb[3][3], sa[3], sb[3];
        if (!decompose(a, ra, sa) || !decompose(b, rb, sb)) {
            for (int r = 0; r < 3; r++) {
                for (int c = 0; c < 3; c++) {
                    out[r][c] = (a[r][c] + b[r][c]) * 0.5f;
                }
            }
            return;
        }
        const Quat qa = toQuat(ra);
        Quat qb = toQuat(rb);
        if (qa.x * qb.x + qa.y * qb.y + qa.z * qb.z + qa.w * qb.w < 0.0f) {
            qb = {-qb.x, -qb.y, -qb.z, -qb.w};
        }
        // Halfway, the normalized sum is the exact slerp.
        Quat q = {qa.x + qb.x, qa.y + qb.y, qa.z + qb.z, qa.w + qb.w};
        const f32 length = std::sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
        q = {q.x / length, q.y / length, q.z / length, q.w / length};
        f32 rotation[3][3];
        fromQuat(q, rotation);
        for (int c = 0; c < 3; c++) {
            const f32 scale = (sa[c] + sb[c]) * 0.5f;
            for (int r = 0; r < 3; r++) {
                out[r][c] = rotation[r][c] * scale;
            }
        }
    }

    f32 distance(const Mtx a, const Mtx b) {
        const f32 x = a[0][3] - b[0][3], y = a[1][3] - b[1][3], z = a[2][3] - b[2][3];
        return std::sqrt(x * x + y * y + z * z);
    }

    // The camera halfway, in world space (position and orientation), unless it cut.
    bool blendCamera(CameraContext* pCamera) {
        const CameraState& before = sBefore.camera;
        const CameraState& after = sAfter.camera;
        if (distance(before.viewInv, after.viewInv) > kCameraCut) {
            return false;
        }
        f32 ra[3][3], rb[3][3], sa[3], sb[3];
        if (decompose(before.viewInv, ra, sa) && decompose(after.viewInv, rb, sb)) {
            const Quat qa = toQuat(ra);
            const Quat qb = toQuat(rb);
            if (std::fabs(qa.x * qb.x + qa.y * qb.y + qa.z * qb.z + qa.w * qb.w) < kCameraCutCosHalfAngle) {
                return false;
            }
        }
        TPos3f viewInv;
        halfway(before.viewInv, after.viewInv, viewInv);
        TPos3f view;
        PSMTXInverse(viewInv, view);
        pCamera->mView = view;
        pCamera->mViewInv = viewInv;
        pCamera->mShakeOffset.set((before.shake.x + after.shake.x) * 0.5f, (before.shake.y + after.shake.y) * 0.5f);
        pCamera->setFovy((before.fovy + after.fovy) * 0.5f);
        return true;
    }

    void restoreCamera(CameraContext* pCamera) {
        const CameraState& after = sAfter.camera;
        pCamera->mView = after.view;
        pCamera->mViewInv = after.viewInv;
        pCamera->mProjection = after.projection;
        pCamera->mFovy = after.fovy;
        pCamera->mShakeOffset = after.shake;
    }

    // Writes the halfway joints of every model drawn in both steps; restore writes step k back.
    void writeModels(bool restore) {
        for (int i = 0; i < sAfter.modelCount; i++) {
            const ModelState& after = sAfter.models[i];
            const ModelState* pBefore = restore ? nullptr : findBefore(after);
            if (restore || pBefore == nullptr ||
                (after.ownsAnm && after.joints > 0 &&
                 distance(sBefore.matrices[pBefore->matrices], sAfter.matrices[after.matrices]) > kModelCut)) {
                if (restore) {
                    PSMTXCopy(after.base, after.model->mBaseTransformMtx);
                    if (after.ownsAnm) {
                        std::memcpy(after.anm, sAfter.matrices[after.matrices], after.joints * sizeof(Mtx));
                    }
                    after.model->calcWeightEnvelopeMtx();
                }
                continue;
            }
            halfway(pBefore->base, after.base, after.model->mBaseTransformMtx);
            if (after.ownsAnm) {
                for (u16 joint = 0; joint < after.joints; joint++) {
                    halfway(sBefore.matrices[pBefore->matrices + joint], sAfter.matrices[after.matrices + joint], after.anm[joint]);
                }
            }
            after.model->calcWeightEnvelopeMtx();
        }
    }

    void drawGameSystem(void* pSystem) {
        static_cast< GameSystem* >(pSystem)->draw();
    }
}  // namespace

namespace FrameInterpolation {
    void noteModel(J3DModel* pModel) {
        for (int i = 0; i < sSeenCount; i++) {
            if (sSeen[i] == pModel) {
                return;
            }
        }
        if (sSeenCount < kMaxModels) {
            sSeen[sSeenCount++] = pModel;
        }
    }

    void noteGameSceneViews() {
        sGameSceneViews = true;
    }

    void beforeUpdate() {
        gJ3DModelViewCalcHook = noteModel;
        if (sGameSceneViews) {
            take(&sBefore);
        } else {
            sBefore.valid = false;
        }
        sGameSceneViews = false;
        sSeenCount = 0;
    }

    void afterSeam(GameSystem* pSystem) {
        if (!sBefore.valid || !sGameSceneViews || MR::isActiveMoviePlayer() || !MainLoopFramework::sManager->mDoRenderFrame) {
            return;
        }
        CameraContext* pCamera = cameraContext();
        if (pCamera == nullptr || petari_host_interp_wait() == 0) {
            return;
        }
        take(&sAfter);
        if (!sAfter.valid || !blendCamera(pCamera)) {
            restoreCamera(pCamera);
            return;
        }
        // Draw code below runs once more for the extra frame; what it changes in Mario and the
        // random number generator is put back afterwards.
        JMath::TRandom_fast_& random = pSystem->mObjHolder->mRandom;
        const JMath::TRandom_fast_ savedRandom = random;
        MarioActor* pMario = MR::isExistSceneObj(SceneObj_MarioHolder) ? MarioAccess::getPlayerActor() : nullptr;
        if (pMario != nullptr) {
            std::memcpy(sMarioBytes, static_cast< void* >(pMario), sizeof(MarioActor));
        }

        writeModels(false);
        sDrawingExtraFrame = true;
        SceneFunction::executeCalcViewAndEntryList();
        MainLoopFramework::sManager->drawExtraFrame(drawGameSystem, pSystem, sExtraXfb);
        sDrawingExtraFrame = false;

        // Step k back: joints, camera and every view, as calcAnim left them.
        restoreCamera(pCamera);
        writeModels(true);
        SceneFunction::executeCalcViewAndEntryList();
        if (pMario != nullptr) {
            std::memcpy(static_cast< void* >(pMario), sMarioBytes, sizeof(MarioActor));
        }
        random = savedRandom;

        petari_host_present_seam();
    }

    bool isDrawingExtraFrame() {
        return sDrawingExtraFrame;
    }
}  // namespace FrameInterpolation
#endif
