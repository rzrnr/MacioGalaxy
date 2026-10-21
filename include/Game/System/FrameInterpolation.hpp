#pragma once
#ifdef PETARI_NATIVE
// Frame interpolation (native/FRAME_RATE.md): at 120 frames per second, one extra frame between two
// game steps, drawn with the camera and every model's joints halfway between the step that was just
// shown and the next one. The game itself still runs at 60 steps per second.
//
// The step's frame loop draws step k-1 and then computes step k (GameSystem::frameLoop). Before the
// update, beforeUpdate() keeps the drawn step's camera and joints; after the step's present,
// afterSeam() blends them with step k's, draws and presents the extra frame, and puts step k back
// exactly, so the next frame and the game are as without interpolation.

class GameSystem;
class J3DModel;

namespace FrameInterpolation {
    // Every model's view calculation (J3DModel::viewCalc, Mario's J3DModelX views) records the model.
    void noteModel(J3DModel* pModel);
    // GameScene::calcAnim, when it calculated the views of its draw list (not while a movie plays).
    void noteGameSceneViews();
    // GameSystem::frameLoop, before update(): the drawn step's camera and joints.
    void beforeUpdate();
    // GameSystem::frameLoop, after petari_host_frame_seam(): the extra frame, when it is on and due.
    void afterSeam(GameSystem* pSystem);
    // During the extra frame's view calculation and draw: draw code that must run once per step
    // (draw-sync tokens, EFB captures) checks this.
    bool isDrawingExtraFrame();
}  // namespace FrameInterpolation
#endif
