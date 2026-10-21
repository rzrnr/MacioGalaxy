/* Presentation interface between the SDK side (present_host.cpp, which reads
 * the native VI and SC state) and the Aurora side (present_aurora.cpp, which
 * the patched aurora_end_frame uses). Plain C, so neither side sees the
 * other's GX headers. Main thread only. */
#ifndef PETARI_GX_PRESENT_H
#define PETARI_GX_PRESENT_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct PetariPresentVideo {
    const void* xfb;             /* XFB latched by VI (VIGetCurrentFrameBuffer) */
    int configured;              /* a render mode is latched */
    int black;                   /* VI output blanked (VISetBlack) */
    int dimmed;                  /* screen-saver dimming active */
    unsigned aspectWidth;        /* display aspect: 16:9 or 4:3 */
    unsigned aspectHeight;
} PetariPresentVideo;

/* Starts presenting XFBs: until then aurora_end_frame presents the EFB as
 * upstream Aurora does. */
void petari_present_enable(void);

/* The video state for the frame the next aurora_end_frame presents. */
void petari_present_set_video(const PetariPresentVideo* video);

/* The displayed image's aspect (16:9 or 4:3) while XFBs are presented, for
 * the patched aurora::window::get_window_size: the EFB render target takes
 * this aspect inside the drawable, so the XFB is shown pixel for pixel.
 * Returns 0 before petari_present_enable. Any thread. */
int petari_present_content_aspect(unsigned* width, unsigned* height);

/* Where the game image is presented, in window points. Returns 0 while there
 * is no surface. */
int petari_present_image_rect(float* x, float* y, float* width, float* height);

/* The Graphics page (petari/graphics.hpp), once per frame. */
enum { PETARI_PRESENT_UPSCALE_FSR1 = 0, PETARI_PRESENT_UPSCALE_BICUBIC = 1, PETARI_PRESENT_UPSCALE_BILINEAR = 2 };
typedef struct PetariPresentGraphics {
    unsigned renderHeight;  /* EFB height in lines; 0: the displayed image's own size */
    int upscaler;           /* PETARI_PRESENT_UPSCALE_*: the filter while the EFB is smaller than the image */
    float sharpness;        /* FSR 1 RCAS after scaling, linear 0..1; 0: none */
    int fxaa;               /* FXAA on the game image before it is scaled */
} PetariPresentGraphics;
void petari_present_set_graphics(const PetariPresentGraphics* graphics);

/* The render height in effect, for the patched aurora::window::get_window_size:
 * 0 (the displayed size) until XFBs are presented. Any thread. */
unsigned petari_present_render_height(void);

#ifdef __cplusplus
}
#endif

#endif
