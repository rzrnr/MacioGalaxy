// Aurora side of XFB presentation (README.md in this directory). Compiled
// with Aurora's lib/ on the quote include path; no SDK headers.

#include "present_aurora.hpp"

#include "gfx/render_worker.hpp"
#include "gx/gx.hpp"
#include "webgpu/gpu.hpp"
#include "window.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <mutex>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <thread>
#include <vector>

#include <petari/efb_dump_mark.hpp>
#include <petari/host_allocation.hpp>
#include <petari/png_write.hpp>
#include <petari/screenshot.hpp>

#include "present.h"

namespace petari_present {
namespace {

// VI dimming darkens the picture. The Wii's exact level is not documented in
// the SDK; this is an approximation (README.md).
constexpr float kDimOpacity = 0.5f;

bool gEnabled = false;
// The EFB's aspect, read by the patched window size (any thread).
std::atomic<bool> gAspectEnabled{false};
std::atomic<unsigned> gAspectWidth{4};
std::atomic<unsigned> gAspectHeight{3};

// Keeps the EFB's aspect at the displayed image's; a change resizes the frame
// buffer (deferred by Aurora to the next frame boundary).
void setContentAspect(unsigned width, unsigned height) {
  if (width == 0 || height == 0) {
    width = 4;
    height = 3;
  }
  const bool widthChanged = gAspectWidth.exchange(width) != width;
  const bool heightChanged = gAspectHeight.exchange(height) != height;
  if ((widthChanged || heightChanged) && gAspectEnabled.load()) {
    aurora::window::request_frame_buffer_resize();
  }
}
PetariPresentVideo gVideo{};
const void* gMissingXfb = nullptr;  // last XFB reported without a display copy

// The F1 menu's Graphics page (petari_present_set_graphics). The requested render
// height takes effect in take(), which resizes the frame buffer; gRenderHeight is
// the height in effect (0: the displayed size), read by the patched window size
// (any thread).
std::atomic<unsigned> gRequestedHeight{0};
std::atomic<unsigned> gRenderHeight{0};
std::atomic<int> gUpscaler{PETARI_PRESENT_UPSCALE_FSR1};
std::atomic<float> gSharpness{0.0f};
std::atomic<bool> gFxaa{false};

// Main thread, once per frame.
void applyRenderHeight() {
  const unsigned requested = gRequestedHeight.load();
  if (requested == gRenderHeight.load()) {
    return;
  }
  gRenderHeight.store(requested);
  if (gAspectEnabled.load()) {
    aurora::window::request_frame_buffer_resize();
  }
}

// 1x1 black with kDimOpacity alpha (premultiplied), for draw_dim.
wgpu::Texture gDimTexture;
wgpu::TextureView gDimView;

// PETARI_TRACE_BOOT: the sizes along the presentation path, logged when they
// change: the drawable (surface), the EFB render target, the latched XFB's
// copy texture, and the viewport it is drawn into. A scale of 1.00 means the
// XFB is shown pixel for pixel; below 1 it is shrunk, above 1 enlarged.
bool traceSizes() {
  static const bool enabled = [] {
    const char* value = std::getenv("PETARI_TRACE_BOOT");
    return value != nullptr && value[0] != '\0' && value[0] != '0';
  }();
  return enabled;
}

void traceFrame(const Frame& frame) {
  using namespace aurora::webgpu;
  struct Sizes {
    uint32_t surfaceW, surfaceH, efbW, efbH, xfbW, xfbH, viewW, viewH, aspectW, aspectH;
    bool operator==(const Sizes& o) const {
      return surfaceW == o.surfaceW && surfaceH == o.surfaceH && efbW == o.efbW && efbH == o.efbH && xfbW == o.xfbW &&
             xfbH == o.xfbH && viewW == o.viewW && viewH == o.viewH && aspectW == o.aspectW && aspectH == o.aspectH;
    }
  };
  static Sizes last{};
  const uint32_t surfaceW = g_graphicsConfig.surfaceConfiguration.width;
  const uint32_t surfaceH = g_graphicsConfig.surfaceConfiguration.height;
  const Viewport viewport = calculate_present_viewport(surfaceW, surfaceH, frame.aspectWidth, frame.aspectHeight);
  const AuroraWindowSize window = aurora::window::get_window_size();
  const Sizes sizes{surfaceW,
                    surfaceH,
                    window.fb_width,
                    window.fb_height,
                    frame.xfb ? frame.xfb->size.width : 0,
                    frame.xfb ? frame.xfb->size.height : 0,
                    static_cast<uint32_t>(viewport.width),
                    static_cast<uint32_t>(viewport.height),
                    frame.aspectWidth,
                    frame.aspectHeight};
  if (sizes == last || sizes.xfbW == 0) {
    return;
  }
  last = sizes;
  std::fprintf(stderr,
               "Petari present: surface %ux%u, EFB %ux%u, XFB texture %ux%u, viewport %ux%u (%u:%u), scale %.2f x %.2f\n",
               sizes.surfaceW, sizes.surfaceH, sizes.efbW, sizes.efbH, sizes.xfbW, sizes.xfbH, sizes.viewW, sizes.viewH,
               sizes.aspectW, sizes.aspectH, static_cast<double>(viewport.width) / sizes.xfbW,
               static_cast<double>(viewport.height) / sizes.xfbH);
}

aurora::webgpu::TextureWithSampler xfb_source(const aurora::gfx::TextureRef& ref) {
  return {
      .texture = ref.texture,
      .view = ref.sampleTextureView,
      .size = ref.size,
      .format = ref.format,
      .sampler = aurora::webgpu::present_source().sampler,
  };
}


// --- Opt-in dump of the presented image (PETARI_XFB_DUMP=<dir>), free when unset. -------------
// Reads the XFB display copy VI latched (the final frame, unlike the mid-frame EFB snapshots)
// and writes <dir>/<label>-<frame since mark>.png every PETARI_XFB_DUMP_EVERY (default 20)
// presented frames, for up to PETARI_XFB_DUMP_SPAN (default 400) frames after each phase mark
// (petari/efb_dump_mark.hpp) whose label is in PETARI_XFB_DUMP_LABELS (default "idle,walk,jump").
// The readback runs on the render worker, in order after the display copy, and blocks it briefly.
// A listed label matches a mark whose label starts with it ("dome-select" matches "dome-select-EggStarGalaxy").
bool labelListed(const std::string& list, const char* label) {
  size_t at = 0;
  const std::string mark = label;
  while (at <= list.size()) {
    const size_t comma = std::min(list.find(',', at), list.size());
    const std::string token = list.substr(at, comma - at);
    if (!token.empty() && mark.compare(0, token.size(), token) == 0) return true;
    at = comma + 1;
  }
  return false;
}

struct XfbDumpConfig {
  std::string dir, labels = "idle,walk,jump";
  unsigned long every = 20, span = 400;
  bool enabled = false;
};
const XfbDumpConfig& xfbDumpConfig() {
  static const XfbDumpConfig config = [] {
    XfbDumpConfig c;
    if (const char* dir = std::getenv("PETARI_XFB_DUMP"); dir && *dir) {
      c.dir = dir;
      c.enabled = true;
      if (const char* v = std::getenv("PETARI_XFB_DUMP_LABELS")) c.labels = v;
      if (const char* v = std::getenv("PETARI_XFB_DUMP_EVERY")) c.every = std::max(1ul, std::strtoul(v, nullptr, 10));
      if (const char* v = std::getenv("PETARI_XFB_DUMP_SPAN")) c.span = std::strtoul(v, nullptr, 10);
    }
    return c;
  }();
  return config;
}

constexpr const char* kXfbShader = R"(
@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var<storage, read_write> rgb: array<u32>;
@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) id: vec3u) {
  let size = textureDimensions(src);
  if (id.x >= size.x || id.y >= size.y) { return; }
  let c = vec3u(round(clamp(textureLoad(src, vec2i(id.xy), 0).rgb, vec3f(0), vec3f(1)) * 255.0));
  rgb[id.y * size.x + id.x] = (c.r << 16u) | (c.g << 8u) | c.b;
}
)";

bool readXfb(const aurora::gfx::TextureHandle& xfb, std::vector<unsigned char>& rgb, uint32_t& width, uint32_t& height) {
  PetariNative::HostAllocationScope host;
  using aurora::webgpu::g_device;
  using aurora::webgpu::g_queue;
  width = xfb->size.width;
  height = xfb->size.height;
  const uint64_t bytes = uint64_t(width) * height * 4;
  static wgpu::ComputePipeline* pipeline = nullptr;
  if (!pipeline) {
    const wgpu::ShaderSourceWGSL wgsl{wgpu::ShaderSourceWGSL::Init{.code = kXfbShader}};
    const wgpu::ShaderModuleDescriptor moduleDesc{.nextInChain = &wgsl, .label = "Petari XFB dump"};
    const auto module = g_device.CreateShaderModule(&moduleDesc);
    const wgpu::ComputePipelineDescriptor pipelineDesc{
        .label = "Petari XFB dump", .compute = wgpu::ComputeState{.module = module, .entryPoint = "main"}};
    pipeline = new wgpu::ComputePipeline(g_device.CreateComputePipeline(&pipelineDesc));
  }
  const wgpu::BufferDescriptor storageDesc{
      .label = "Petari XFB dump storage", .usage = wgpu::BufferUsage::Storage | wgpu::BufferUsage::CopySrc, .size = bytes};
  const auto storage = g_device.CreateBuffer(&storageDesc);
  const wgpu::BufferDescriptor readDesc{
      .label = "Petari XFB dump readback", .usage = wgpu::BufferUsage::MapRead | wgpu::BufferUsage::CopyDst, .size = bytes};
  const auto readback = g_device.CreateBuffer(&readDesc);
  const std::array entries{wgpu::BindGroupEntry{.binding = 0, .textureView = xfb->sampleTextureView},
                           wgpu::BindGroupEntry{.binding = 1, .buffer = storage, .size = bytes}};
  const wgpu::BindGroupDescriptor bindDesc{
      .label = "Petari XFB dump", .layout = pipeline->GetBindGroupLayout(0), .entryCount = entries.size(), .entries = entries.data()};
  const auto binding = g_device.CreateBindGroup(&bindDesc);
  const auto encoder = g_device.CreateCommandEncoder();
  const auto pass = encoder.BeginComputePass();
  pass.SetPipeline(*pipeline);
  pass.SetBindGroup(0, binding);
  pass.DispatchWorkgroups((width + 7) / 8, (height + 7) / 8);
  pass.End();
  encoder.CopyBufferToBuffer(storage, 0, readback, 0, bytes);
  const auto commands = encoder.Finish();
  g_queue.Submit(1, &commands);
  std::atomic<int> state{0};
  readback.MapAsync(wgpu::MapMode::Read, 0, bytes, wgpu::CallbackMode::AllowSpontaneous,
                    [&state](wgpu::MapAsyncStatus status, wgpu::StringView) { state = status == wgpu::MapAsyncStatus::Success ? 1 : -1; });
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (state == 0 && std::chrono::steady_clock::now() < deadline) {
    aurora::webgpu::g_instance.ProcessEvents();
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  if (state != 1) {
    std::fprintf(stderr, "Petari XFB dump: readback failed\n");
    return false;
  }
  const auto* data = static_cast<const uint32_t*>(readback.GetConstMappedRange(0, bytes));
  rgb.clear();
  rgb.reserve(size_t(width) * height * 3);
  for (size_t i = 0; i < size_t(width) * height; ++i) {
    rgb.push_back(static_cast<unsigned char>(data[i] >> 16));
    rgb.push_back(static_cast<unsigned char>(data[i] >> 8));
    rgb.push_back(static_cast<unsigned char>(data[i]));
  }
  readback.Unmap();
  return true;
}

void dumpXfb(aurora::gfx::TextureHandle xfb, std::string path) {
  std::vector<unsigned char> rgb;
  uint32_t width = 0, height = 0;
  if (readXfb(xfb, rgb, width, height)) PetariNative::writePngRgb(path, width, height, rgb.data());
}


// --- Opt-in dump of the final window image (PETARI_SURFACE_DUMP=<dir>), free when unset. ------
// Unlike PETARI_XFB_DUMP (the game's frame only) this includes everything drawn over it: the Home menu,
// progress badges and other ImGui overlays. Same schedule as the XFB dump: PETARI_SURFACE_DUMP_EVERY frames
// (default 20), up to _SPAN frames (default 400) after each phase mark whose label is in _LABELS (default
// "idle,walk,jump,dome-ready,dome-select"). Files: <dir>/surface-<label>-<index>.png.
struct SurfaceDumpConfig {
  std::string dir, labels = "idle,walk,jump,dome-ready,dome-select";
  unsigned long every = 20, span = 400;
  bool enabled = false;
};
const SurfaceDumpConfig& surfaceDumpConfig() {
  static const SurfaceDumpConfig config = [] {
    SurfaceDumpConfig c;
    if (const char* dir = std::getenv("PETARI_SURFACE_DUMP"); dir && *dir) {
      c.dir = dir;
      c.enabled = true;
      if (const char* v = std::getenv("PETARI_SURFACE_DUMP_LABELS")) c.labels = v;
      if (const char* v = std::getenv("PETARI_SURFACE_DUMP_EVERY")) c.every = std::max(1ul, std::strtoul(v, nullptr, 10));
      if (const char* v = std::getenv("PETARI_SURFACE_DUMP_SPAN")) c.span = std::strtoul(v, nullptr, 10);
    }
    return c;
  }();
  return config;
}

// PETARI_XFB_HASH=<file>: one line per presented frame, "<index> <black|xfb> <dim> <hash>" (FNV-1a 64 of the
// RGB image), for the first PETARI_XFB_HASH_FRAMES (default 6000) frames. Compares presentation modes
// without storing images. Lines may be out of order; sort by index.
struct HashConfig {
  std::string path;
  uint64_t frames = 6000;
  bool enabled = false;
};
const HashConfig& hashConfig() {
  static const HashConfig config = [] {
    HashConfig c;
    if (const char* p = std::getenv("PETARI_XFB_HASH"); p && *p) {
      c.path = p;
      c.enabled = true;
      if (const char* v = std::getenv("PETARI_XFB_HASH_FRAMES")) c.frames = std::strtoull(v, nullptr, 10);
    }
    return c;
  }();
  return config;
}
std::mutex gHashMutex;
void hashLine(uint64_t index, const char* kind, float dim, uint64_t hash) {
  std::lock_guard<std::mutex> lock(gHashMutex);
  if (std::FILE* file = std::fopen(hashConfig().path.c_str(), "a")) {
    std::fprintf(file, "%llu %s %.3f %016llx\n", static_cast<unsigned long long>(index), kind, static_cast<double>(dim),
                 static_cast<unsigned long long>(hash));
    std::fclose(file);
  }
}
void hashFrame(uint64_t index, const Frame& frame) {
  if (frame.black || !frame.xfb) {
    hashLine(index, "black", frame.dimOpacity, 0);
    return;
  }
  aurora::gfx::render_worker::enqueue_work([index, xfb = frame.xfb, dim = frame.dimOpacity] {
    std::vector<unsigned char> rgb;
    uint32_t width = 0, height = 0;
    uint64_t hash = 14695981039346656037ULL;
    if (readXfb(xfb, rgb, width, height)) {
      for (unsigned char c : rgb) hash = (hash ^ c) * 1099511628211ULL;
    }
    hashLine(index, "xfb", dim, hash);
  });
}

// Main thread, once per presented frame with an XFB.
void maybeDumpXfb(const aurora::gfx::TextureHandle& xfb) {
  // Photo mode's screenshot (petari/screenshot.hpp): this frame, once.
  if (PetariNative::Screenshot::pending.load(std::memory_order_acquire)) {
    std::string path = PetariNative::Screenshot::path;
    PetariNative::Screenshot::pending.store(false, std::memory_order_release);
    aurora::gfx::render_worker::enqueue_work([xfb, path = std::move(path)] {
      std::vector<unsigned char> rgb;
      uint32_t width = 0, height = 0;
      bool ok = readXfb(xfb, rgb, width, height);
      if (ok) {
        PetariNative::writePngRgb(path, width, height, rgb.data());
        std::FILE* written = std::fopen(path.c_str(), "rb");
        ok = written != nullptr;
        if (written) std::fclose(written);
      }
      std::fprintf(stderr, "[photo] screenshot %s: %s (%ux%u)\n", ok ? "saved" : "FAILED", path.c_str(), width, height);
    });
  }
  const auto& config = xfbDumpConfig();
  if (!config.enabled) return;
  static uint64_t seenMark = 0, sinceMark = 0;
  static const char* label = "none";
  static bool directoryMade = false;
  const auto counter = PetariNative::EfbDump::markCounter.load(std::memory_order_acquire);
  if (counter != seenMark) {
    seenMark = counter;
    sinceMark = 0;
    label = PetariNative::EfbDump::markLabel.load(std::memory_order_acquire);
  }
  const auto index = sinceMark++;
  if (index >= config.span || index % config.every != 0) return;
  if (!labelListed(config.labels, label)) return;
  if (!directoryMade) {
    if (std::system(("mkdir -p '" + config.dir + "'").c_str()) != 0) return;
    directoryMade = true;
  }
  auto path = config.dir + "/xfb-" + label + "-" + std::to_string(index) + ".png";
  aurora::gfx::render_worker::enqueue_work([xfb, path = std::move(path)] { dumpXfb(xfb, path); });
}

}  // namespace

Frame takeImpl() noexcept {
  Frame frame;
  if (!gEnabled) {
    return frame;
  }
  frame.active = true;
  frame.aspectWidth = gVideo.aspectWidth != 0 ? gVideo.aspectWidth : 4;
  frame.aspectHeight = gVideo.aspectHeight != 0 ? gVideo.aspectHeight : 3;
  if (!gVideo.configured || gVideo.black || gVideo.xfb == nullptr) {
    return frame;
  }
  const auto& copies = aurora::gx::g_gxState.copyTextures;
  const auto it = copies.find(gVideo.xfb);
  if (it == copies.end() || !it->second) {
    // An XFB the GPU never copied to (for example one written by the CPU)
    // cannot be shown.
    if (gMissingXfb != gVideo.xfb) {
      gMissingXfb = gVideo.xfb;
      std::fprintf(stderr, "Petari present: XFB %p has no display copy; showing black\n", gVideo.xfb);
    }
    return frame;
  }
  frame.black = false;
  frame.xfb = it->second.handle;
  maybeDumpXfb(frame.xfb);
  frame.dimOpacity = gVideo.dimmed ? kDimOpacity : 0.0f;
  if (traceSizes()) {
    traceFrame(frame);
  }
  return frame;
}

Frame take() noexcept {
  applyRenderHeight();
  Frame frame = takeImpl();
  frame.upscaler = gUpscaler.load();
  frame.sharpness = gSharpness.load();
  frame.fxaa = gFxaa.load();
  if (frame.active && hashConfig().enabled) {
    static uint64_t presented = 0;
    const uint64_t index = presented++;
    if (index < hashConfig().frames) hashFrame(index, frame);
  }
  return frame;
}

void surface_dump_prepare() noexcept {
  const auto& config = surfaceDumpConfig();
  static bool done = false;
  if (!config.enabled || done) return;
  done = true;
  // The surface is created render-only; reconfigure once with copy-source usage so it can be read back.
  using namespace aurora::webgpu;
  g_graphicsConfig.surfaceConfiguration.usage |= wgpu::TextureUsage::CopySrc;
  auto configuration = g_graphicsConfig.surfaceConfiguration;
  configuration.device = g_device;
  g_surface.Configure(&configuration);
}

std::function<void()> surface_dump_encode(const wgpu::CommandEncoder& encoder, const wgpu::Texture& texture) noexcept {
  const auto& config = surfaceDumpConfig();
  if (!config.enabled || !texture) return {};
  static uint64_t seenMark = 0, sinceMark = 0;
  static const char* label = "none";
  static bool directoryMade = false;
  const auto counter = PetariNative::EfbDump::markCounter.load(std::memory_order_acquire);
  if (counter != seenMark) {
    seenMark = counter;
    sinceMark = 0;
    label = PetariNative::EfbDump::markLabel.load(std::memory_order_acquire);
  }
  const auto index = sinceMark++;
  if (index >= config.span || index % config.every != 0) return {};
  if (!labelListed(config.labels, label)) return {};
  if (!directoryMade) {
    if (std::system(("mkdir -p '" + config.dir + "'").c_str()) != 0) return {};
    directoryMade = true;
  }
  if (!(texture.GetUsage() & wgpu::TextureUsage::CopySrc)) return {};
  PetariNative::HostAllocationScope host;
  const uint32_t width = texture.GetWidth(), height = texture.GetHeight();
  const bool bgra = texture.GetFormat() == wgpu::TextureFormat::BGRA8Unorm;
  const uint32_t rowBytes = (width * 4 + 255) / 256 * 256;
  const uint64_t bytes = uint64_t(rowBytes) * height;
  const wgpu::BufferDescriptor readDesc{
      .label = "Petari surface dump", .usage = wgpu::BufferUsage::MapRead | wgpu::BufferUsage::CopyDst, .size = bytes};
  const auto readback = aurora::webgpu::g_device.CreateBuffer(&readDesc);
  const wgpu::TexelCopyTextureInfo source{.texture = texture};
  const wgpu::TexelCopyBufferInfo destination{.layout = {.bytesPerRow = rowBytes, .rowsPerImage = height}, .buffer = readback};
  const wgpu::Extent3D extent{width, height, 1};
  encoder.CopyTextureToBuffer(&source, &destination, &extent);
  auto path = config.dir + "/surface-" + label + "-" + std::to_string(index) + ".png";
  return [readback, bytes, width, height, rowBytes, bgra, path = std::move(path)] {
    PetariNative::HostAllocationScope scope;
    std::atomic<int> state{0};
    readback.MapAsync(wgpu::MapMode::Read, 0, bytes, wgpu::CallbackMode::AllowSpontaneous,
                      [&state](wgpu::MapAsyncStatus status, wgpu::StringView) { state = status == wgpu::MapAsyncStatus::Success ? 1 : -1; });
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (state == 0 && std::chrono::steady_clock::now() < deadline) {
      aurora::webgpu::g_instance.ProcessEvents();
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    if (state != 1) {
      std::fprintf(stderr, "Petari surface dump: readback failed for %s\n", path.c_str());
      return;
    }
    const auto* data = static_cast<const unsigned char*>(readback.GetConstMappedRange(0, bytes));
    std::vector<unsigned char> rgb;
    rgb.reserve(size_t(width) * height * 3);
    for (uint32_t y = 0; y < height; ++y) {
      const unsigned char* row = data + size_t(y) * rowBytes;
      for (uint32_t x = 0; x < width; ++x) {
        rgb.push_back(row[x * 4 + (bgra ? 2 : 0)]);
        rgb.push_back(row[x * 4 + 1]);
        rgb.push_back(row[x * 4 + (bgra ? 0 : 2)]);
      }
    }
    readback.Unmap();
    PetariNative::writePngRgb(path, width, height, rgb.data());
  };
}

// --- The Graphics page's scaling filters, FSR 1 and FXAA (native/GRAPHICS.md). Render worker only. ---
// Without FSR 1 or sharpening the XFB is drawn straight into the present viewport: with Aurora's copy
// pipeline when the sizes match or the bilinear upscaler is chosen, otherwise with a Catmull-Rom bicubic
// filter when enlarging or an area (box) filter in linear light when shrinking a supersampled image.
// FSR 1's EASU upscaler and RCAS sharpening need the scaled image in a texture of the viewport's size
// first; RCAS (or a copy) then draws it into the window. FXAA runs before scaling, at the XFB's size.
//
// fs_easu and fs_rcas port AMD FidelityFX Super Resolution 1.0 (ffx_fsr1.h, the 32-bit FsrEasuF and
// FsrRcasF paths) to WGSL. Copyright (c) 2021 Advanced Micro Devices, Inc. All rights reserved.
// Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
// associated documentation files (the "Software"), to deal in the Software without restriction,
// including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
// and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
// subject to the following conditions: The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS",
// WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
// MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS
// OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
// CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
// OTHER DEALINGS IN THE SOFTWARE.
constexpr const char* kImageShader = R"(
@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var srcSampler: sampler;

struct Params {
    outputSize: vec2<f32>,  // EASU: the viewport's size in pixels
    sharpness: f32,         // RCAS: linear 0..1
    unused: f32,
};
@group(0) @binding(2) var<uniform> params: Params;

struct VertexOutput {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

var<private> positions: array<vec2<f32>, 3> = array<vec2<f32>, 3>(vec2(-1.0, 1.0), vec2(-1.0, -3.0), vec2(3.0, 1.0));
var<private> uvs: array<vec2<f32>, 3> = array<vec2<f32>, 3>(vec2(0.0, 0.0), vec2(0.0, 2.0), vec2(2.0, 0.0));

@vertex
fn vs_main(@builtin(vertex_index) index: u32) -> VertexOutput {
    var out: VertexOutput;
    out.pos = vec4<f32>(positions[index], 0.0, 1.0);
    out.uv = uvs[index];
    return out;
}

fn texel(p: vec2<i32>, size: vec2<i32>) -> vec3<f32> {
    return textureLoad(src, clamp(p, vec2<i32>(0), size - vec2<i32>(1)), 0).rgb;
}

@fragment
fn fs_bilinear(in: VertexOutput) -> @location(0) vec4<f32> {
    return vec4<f32>(textureSampleLevel(src, srcSampler, in.uv, 0.0).rgb, 1.0);
}

// Catmull-Rom weights of the taps at -1, 0, 1 and 2 for a sample t texels past tap 0.
fn catmull_rom(t: f32) -> vec4<f32> {
    let t2 = t * t;
    let t3 = t2 * t;
    return vec4<f32>(-0.5 * t3 + t2 - 0.5 * t, 1.5 * t3 - 2.5 * t2 + 1.0, -1.5 * t3 + 2.0 * t2 + 0.5 * t, 0.5 * t3 - 0.5 * t2);
}

@fragment
fn fs_bicubic(in: VertexOutput) -> @location(0) vec4<f32> {
    let size = vec2<i32>(textureDimensions(src));
    let p = in.uv * vec2<f32>(size) - vec2<f32>(0.5);
    let base = vec2<i32>(floor(p));
    var wx = catmull_rom(p.x - floor(p.x));
    var wy = catmull_rom(p.y - floor(p.y));
    var color = vec3<f32>(0.0);
    for (var j = 0; j < 4; j++) {
        var row = vec3<f32>(0.0);
        for (var i = 0; i < 4; i++) {
            row += wx[i] * texel(base + vec2<i32>(i - 1, j - 1), size);
        }
        color += wy[j] * row;
    }
    return vec4<f32>(clamp(color, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0);
}

// Each output pixel averages the source texels it covers, weighted by coverage.
@fragment
fn fs_area(in: VertexOutput) -> @location(0) vec4<f32> {
    let size = vec2<i32>(textureDimensions(src));
    let footprint = max(fwidth(in.uv) * vec2<f32>(size), vec2<f32>(1.0));
    let center = in.uv * vec2<f32>(size);
    let lo = center - footprint * 0.5;
    let hi = center + footprint * 0.5;
    let first = vec2<i32>(floor(lo));
    let last = min(vec2<i32>(ceil(hi)) - vec2<i32>(1), first + vec2<i32>(7));
    var sum = vec3<f32>(0.0);
    var weight = 0.0;
    for (var y = first.y; y <= last.y; y++) {
        let wy = min(hi.y, f32(y + 1)) - max(lo.y, f32(y));
        for (var x = first.x; x <= last.x; x++) {
            let w = wy * (min(hi.x, f32(x + 1)) - max(lo.x, f32(x)));
            sum += w * pow(texel(vec2<i32>(x, y), size), vec3<f32>(2.2));
            weight += w;
        }
    }
    return vec4<f32>(pow(sum / max(weight, 1e-6), vec3<f32>(1.0 / 2.2)), 1.0);
}

fn luma(c: vec3<f32>) -> f32 {
    return dot(c, vec3<f32>(0.299, 0.587, 0.114));
}

fn bilinear(uv: vec2<f32>) -> vec3<f32> {
    return textureSampleLevel(src, srcSampler, uv, 0.0).rgb;
}

// FXAA: where the corners' luma shows an edge, blend along the edge with up to four
// bilinear taps, and keep the wider blend only if it stays in the local luma range.
@fragment
fn fs_fxaa(in: VertexOutput) -> @location(0) vec4<f32> {
    let size = vec2<i32>(textureDimensions(src));
    let p = vec2<i32>(in.pos.xy);
    let rgbM = texel(p, size);
    let lumaM = luma(rgbM);
    let lumaNW = luma(texel(p + vec2<i32>(-1, -1), size));
    let lumaNE = luma(texel(p + vec2<i32>(1, -1), size));
    let lumaSW = luma(texel(p + vec2<i32>(-1, 1), size));
    let lumaSE = luma(texel(p + vec2<i32>(1, 1), size));
    let lumaMin = min(lumaM, min(min(lumaNW, lumaNE), min(lumaSW, lumaSE)));
    let lumaMax = max(lumaM, max(max(lumaNW, lumaNE), max(lumaSW, lumaSE)));
    if (lumaMax - lumaMin < max(0.0312, lumaMax * 0.125)) {
        return vec4<f32>(rgbM, 1.0);
    }
    var dir = vec2<f32>((lumaSW + lumaSE) - (lumaNW + lumaNE), (lumaNW + lumaSW) - (lumaNE + lumaSE));
    let reduce = max((lumaNW + lumaNE + lumaSW + lumaSE) * 0.03125, 1.0 / 128.0);
    dir = clamp(dir / (min(abs(dir.x), abs(dir.y)) + reduce), vec2<f32>(-8.0), vec2<f32>(8.0)) / vec2<f32>(size);
    let uv = (vec2<f32>(p) + vec2<f32>(0.5)) / vec2<f32>(size);
    let rgbA = 0.5 * (bilinear(uv - dir / 6.0) + bilinear(uv + dir / 6.0));
    let rgbB = 0.5 * rgbA + 0.25 * (bilinear(uv - dir * 0.5) + bilinear(uv + dir * 0.5));
    let lumaB = luma(rgbB);
    if (lumaB < lumaMin || lumaB > lumaMax) {
        return vec4<f32>(rgbA, 1.0);
    }
    return vec4<f32>(rgbB, 1.0);
}

// ffx_a.h's approximations, as FSR 1 uses them.
fn prx_lo_rcp(a: f32) -> f32 {
    return bitcast<f32>(0x7ef07ebbu - bitcast<u32>(a));
}
fn prx_med_rcp(a: f32) -> f32 {
    let b = bitcast<f32>(0x7ef19fffu - bitcast<u32>(a));
    return b * (-b * a + 2.0);
}
fn prx_lo_rsq(a: f32) -> f32 {
    return bitcast<f32>(0x5f347d74u - (bitcast<u32>(a) >> 1u));
}

// FsrEasuTapF: one tap of the 12-tap kernel, a windowed Lanczos 2 approximation
// stretched along the local edge direction.
fn easu_tap(aC: ptr<function, vec3<f32>>, aW: ptr<function, f32>, off: vec2<f32>, dir: vec2<f32>, len: vec2<f32>, lob: f32,
            clp: f32, c: vec3<f32>) {
    var v = vec2<f32>(off.x * dir.x + off.y * dir.y, off.x * (-dir.y) + off.y * dir.x);
    v *= len;
    let d2 = min(v.x * v.x + v.y * v.y, clp);
    var wB = 2.0 / 5.0 * d2 - 1.0;
    var wA = lob * d2 - 1.0;
    wB *= wB;
    wA *= wA;
    wB = 25.0 / 16.0 * wB - (25.0 / 16.0 - 1.0);
    let w = wB * wA;
    *aC += c * w;
    *aW += w;
}

// FsrEasuSetF: direction and length from the '+' around one of the four centre texels,
// weighted by its bilinear weight w.
fn easu_set(dir: ptr<function, vec2<f32>>, len: ptr<function, f32>, w: f32, lA: f32, lB: f32, lC: f32, lD: f32, lE: f32) {
    let dc = lD - lC;
    let cb = lC - lB;
    var lenX = prx_lo_rcp(max(abs(dc), abs(cb)));
    let dirX = lD - lB;
    (*dir).x += dirX * w;
    lenX = clamp(abs(dirX) * lenX, 0.0, 1.0);
    lenX *= lenX;
    *len += lenX * w;
    let ec = lE - lC;
    let ca = lC - lA;
    var lenY = prx_lo_rcp(max(abs(ec), abs(ca)));
    let dirY = lE - lA;
    (*dir).y += dirY * w;
    lenY = clamp(abs(dirY) * lenY, 0.0, 1.0);
    lenY *= lenY;
    *len += lenY * w;
}

// FsrEasuF: edge-adaptive upscaling from the XFB to the viewport's size.
@fragment
fn fs_easu(in: VertexOutput) -> @location(0) vec4<f32> {
    let inputSize = vec2<f32>(textureDimensions(src));
    let ip = floor(in.pos.xy);
    // FsrEasuCon with the viewport covering the whole input.
    let scale = inputSize / params.outputSize;
    let rcpIn = vec2<f32>(1.0) / inputSize;
    var pp = ip * scale + (0.5 * scale - vec2<f32>(0.5));
    let fp = floor(pp);
    pp -= fp;
    //    b c
    //  e f g h
    //  i j k l
    //    n o
    let p0 = fp * rcpIn + vec2<f32>(rcpIn.x, -rcpIn.y);
    let p1 = p0 + vec2<f32>(-rcpIn.x, 2.0 * rcpIn.y);
    let p2 = p0 + vec2<f32>(rcpIn.x, 2.0 * rcpIn.y);
    let p3 = p0 + vec2<f32>(0.0, 4.0 * rcpIn.y);
    let bczzR = textureGather(0, src, srcSampler, p0);
    let bczzG = textureGather(1, src, srcSampler, p0);
    let bczzB = textureGather(2, src, srcSampler, p0);
    let ijfeR = textureGather(0, src, srcSampler, p1);
    let ijfeG = textureGather(1, src, srcSampler, p1);
    let ijfeB = textureGather(2, src, srcSampler, p1);
    let klhgR = textureGather(0, src, srcSampler, p2);
    let klhgG = textureGather(1, src, srcSampler, p2);
    let klhgB = textureGather(2, src, srcSampler, p2);
    let zzonR = textureGather(0, src, srcSampler, p3);
    let zzonG = textureGather(1, src, srcSampler, p3);
    let zzonB = textureGather(2, src, srcSampler, p3);
    // Luma times 2.
    let bczzL = bczzB * 0.5 + (bczzR * 0.5 + bczzG);
    let ijfeL = ijfeB * 0.5 + (ijfeR * 0.5 + ijfeG);
    let klhgL = klhgB * 0.5 + (klhgR * 0.5 + klhgG);
    let zzonL = zzonB * 0.5 + (zzonR * 0.5 + zzonG);
    let bL = bczzL.x;
    let cL = bczzL.y;
    let iL = ijfeL.x;
    let jL = ijfeL.y;
    let fL = ijfeL.z;
    let eL = ijfeL.w;
    let kL = klhgL.x;
    let lL = klhgL.y;
    let hL = klhgL.z;
    let gL = klhgL.w;
    let oL = zzonL.z;
    let nL = zzonL.w;
    var dir = vec2<f32>(0.0);
    var len = 0.0;
    easu_set(&dir, &len, (1.0 - pp.x) * (1.0 - pp.y), bL, eL, fL, gL, jL);
    easu_set(&dir, &len, pp.x * (1.0 - pp.y), cL, fL, gL, hL, kL);
    easu_set(&dir, &len, (1.0 - pp.x) * pp.y, fL, iL, jL, kL, nL);
    easu_set(&dir, &len, pp.x * pp.y, gL, jL, kL, lL, oL);
    // Normalize with approximation, and clean up close to zero.
    let dir2 = dir * dir;
    var dirR = dir2.x + dir2.y;
    let zero = dirR < 1.0 / 32768.0;
    dirR = select(prx_lo_rsq(dirR), 1.0, zero);
    dir.x = select(dir.x, 1.0, zero);
    dir *= dirR;
    // From {0 to 2} to {0 to 1}, shaped with a square.
    len = len * 0.5;
    len *= len;
    // Stretch the kernel from 1.0 (vertical, horizontal) to sqrt(2) (diagonal).
    let stretch = (dir.x * dir.x + dir.y * dir.y) * prx_lo_rcp(max(abs(dir.x), abs(dir.y)));
    let len2 = vec2<f32>(1.0 + (stretch - 1.0) * len, 1.0 - 0.5 * len);
    let lob = 0.5 + ((1.0 / 4.0 - 0.04) - 0.5) * len;
    let clp = prx_lo_rcp(lob);
    // Min and max of the four nearest, for deringing.
    let f = vec3<f32>(ijfeR.z, ijfeG.z, ijfeB.z);
    let g = vec3<f32>(klhgR.w, klhgG.w, klhgB.w);
    let j = vec3<f32>(ijfeR.y, ijfeG.y, ijfeB.y);
    let k = vec3<f32>(klhgR.x, klhgG.x, klhgB.x);
    let min4 = min(min(f, min(g, j)), k);
    let max4 = max(max(f, max(g, j)), k);
    var aC = vec3<f32>(0.0);
    var aW = 0.0;
    easu_tap(&aC, &aW, vec2<f32>(0.0, -1.0) - pp, dir, len2, lob, clp, vec3<f32>(bczzR.x, bczzG.x, bczzB.x));  // b
    easu_tap(&aC, &aW, vec2<f32>(1.0, -1.0) - pp, dir, len2, lob, clp, vec3<f32>(bczzR.y, bczzG.y, bczzB.y));  // c
    easu_tap(&aC, &aW, vec2<f32>(-1.0, 1.0) - pp, dir, len2, lob, clp, vec3<f32>(ijfeR.x, ijfeG.x, ijfeB.x));  // i
    easu_tap(&aC, &aW, vec2<f32>(0.0, 1.0) - pp, dir, len2, lob, clp, j);                                        // j
    easu_tap(&aC, &aW, vec2<f32>(0.0, 0.0) - pp, dir, len2, lob, clp, f);                                        // f
    easu_tap(&aC, &aW, vec2<f32>(-1.0, 0.0) - pp, dir, len2, lob, clp, vec3<f32>(ijfeR.w, ijfeG.w, ijfeB.w));  // e
    easu_tap(&aC, &aW, vec2<f32>(1.0, 1.0) - pp, dir, len2, lob, clp, k);                                        // k
    easu_tap(&aC, &aW, vec2<f32>(2.0, 1.0) - pp, dir, len2, lob, clp, vec3<f32>(klhgR.y, klhgG.y, klhgB.y));   // l
    easu_tap(&aC, &aW, vec2<f32>(2.0, 0.0) - pp, dir, len2, lob, clp, vec3<f32>(klhgR.z, klhgG.z, klhgB.z));   // h
    easu_tap(&aC, &aW, vec2<f32>(1.0, 0.0) - pp, dir, len2, lob, clp, g);                                        // g
    easu_tap(&aC, &aW, vec2<f32>(1.0, 2.0) - pp, dir, len2, lob, clp, vec3<f32>(zzonR.z, zzonG.z, zzonB.z));   // o
    easu_tap(&aC, &aW, vec2<f32>(0.0, 2.0) - pp, dir, len2, lob, clp, vec3<f32>(zzonR.w, zzonG.w, zzonB.w));   // n
    return vec4<f32>(min(max4, max(min4, aC / aW)), 1.0);
}

// FsrRcasF: sharpening of the scaled image, drawn 1:1 into the viewport. The limiters'
// divisions are guarded against black and white rings, where FSR divides by zero.
@fragment
fn fs_rcas(in: VertexOutput) -> @location(0) vec4<f32> {
    let size = vec2<i32>(textureDimensions(src));
    let sp = vec2<i32>(floor(in.uv * vec2<f32>(size)));
    //    b
    //  d e f
    //    h
    let b = texel(sp + vec2<i32>(0, -1), size);
    let d = texel(sp + vec2<i32>(-1, 0), size);
    let e = texel(sp, size);
    let f = texel(sp + vec2<i32>(1, 0), size);
    let h = texel(sp + vec2<i32>(0, 1), size);
    let mn4 = min(min(b, d), min(f, h));
    let mx4 = max(max(b, d), max(f, h));
    let peakC = vec2<f32>(1.0, -4.0);
    let hitMin = min(mn4, e) / max(4.0 * mx4, vec3<f32>(1e-6));
    let hitMax = (peakC.x - max(mx4, e)) / min(4.0 * mn4 + peakC.y, vec3<f32>(-1e-6));
    let lobeRGB = max(-hitMin, hitMax);
    let lobe = max(-(0.25 - 1.0 / 16.0), min(max(lobeRGB.r, max(lobeRGB.g, lobeRGB.b)), 0.0)) * params.sharpness;
    let rcpL = prx_med_rcp(4.0 * lobe + 1.0);
    return vec4<f32>((lobe * (b + d + h + f) + e) * rcpL, 1.0);
}
)";

enum ImageFilter { FilterBilinear, FilterBicubic, FilterArea, FilterFxaa, FilterEasu, FilterRcas, FilterCount };
constexpr const char* kFilterEntries[FilterCount] = {"fs_bilinear", "fs_bicubic", "fs_area", "fs_fxaa", "fs_easu", "fs_rcas"};
constexpr bool kFilterSampler[FilterCount] = {true, false, false, true, true, false};
constexpr bool kFilterParams[FilterCount] = {false, false, false, false, true, true};

// The filters for one render target format.
struct ImagePipelines {
  wgpu::TextureFormat format = wgpu::TextureFormat::Undefined;
  wgpu::RenderPipeline filters[FilterCount];
};
ImagePipelines gSurfacePipelines;       // into the window
ImagePipelines gIntermediatePipelines;  // into gFxaaTexture and gScaledTexture
constexpr wgpu::TextureFormat kIntermediateFormat = wgpu::TextureFormat::RGBA8Unorm;
wgpu::ShaderModule gImageModule;
wgpu::Sampler gImageSampler;
wgpu::Buffer gImageParams;  // Params in kImageShader
wgpu::Texture gFxaaTexture;    // the XFB after FXAA, at its size
wgpu::TextureView gFxaaView;
wgpu::Texture gScaledTexture;  // the scaled image, at the viewport's size, for RCAS
wgpu::TextureView gScaledView;

// What draw_image draws this frame.
struct ImageDraw {
  wgpu::RenderPipeline pipeline;
  wgpu::BindGroup bindGroup;
};
ImageDraw gImageDraw;

const ImagePipelines& imagePipelines(ImagePipelines& pipelines, wgpu::TextureFormat format) {
  using aurora::webgpu::g_device;
  if (pipelines.format == format) {
    return pipelines;
  }
  PetariNative::HostAllocationScope host;
  if (!gImageModule) {
    const wgpu::ShaderSourceWGSL wgsl{wgpu::ShaderSourceWGSL::Init{.code = kImageShader}};
    const wgpu::ShaderModuleDescriptor moduleDescriptor{.nextInChain = &wgsl, .label = "Petari image filters"};
    gImageModule = g_device.CreateShaderModule(&moduleDescriptor);
    const wgpu::SamplerDescriptor samplerDescriptor{
        .label = "Petari image sampler",
        .addressModeU = wgpu::AddressMode::ClampToEdge,
        .addressModeV = wgpu::AddressMode::ClampToEdge,
        .magFilter = wgpu::FilterMode::Linear,
        .minFilter = wgpu::FilterMode::Linear,
    };
    gImageSampler = g_device.CreateSampler(&samplerDescriptor);
    const wgpu::BufferDescriptor paramsDescriptor{
        .label = "Petari image params", .usage = wgpu::BufferUsage::Uniform | wgpu::BufferUsage::CopyDst, .size = 16};
    gImageParams = g_device.CreateBuffer(&paramsDescriptor);
  }
  for (int filter = 0; filter < FilterCount; filter++) {
    const wgpu::ColorTargetState target{.format = format, .writeMask = wgpu::ColorWriteMask::All};
    const wgpu::FragmentState fragment{
        .module = gImageModule, .entryPoint = kFilterEntries[filter], .targetCount = 1, .targets = &target};
    const wgpu::RenderPipelineDescriptor descriptor{
        .label = kFilterEntries[filter],
        .vertex = wgpu::VertexState{.module = gImageModule, .entryPoint = "vs_main"},
        .primitive = wgpu::PrimitiveState{.topology = wgpu::PrimitiveTopology::TriangleList},
        .multisample = wgpu::MultisampleState{.count = 1, .mask = UINT32_MAX},
        .fragment = &fragment,
    };
    pipelines.filters[filter] = g_device.CreateRenderPipeline(&descriptor);
  }
  pipelines.format = format;
  return pipelines;
}

wgpu::BindGroup imageBindGroup(const ImagePipelines& pipelines, ImageFilter filter, const wgpu::TextureView& view) {
  std::array<wgpu::BindGroupEntry, 3> entries;
  size_t count = 0;
  entries[count++] = wgpu::BindGroupEntry{.binding = 0, .textureView = view};
  if (kFilterSampler[filter]) {
    entries[count++] = wgpu::BindGroupEntry{.binding = 1, .sampler = gImageSampler};
  }
  if (kFilterParams[filter]) {
    entries[count++] = wgpu::BindGroupEntry{.binding = 2, .buffer = gImageParams, .size = 16};
  }
  const wgpu::BindGroupDescriptor descriptor{.label = "Petari image",
                                             .layout = pipelines.filters[filter].GetBindGroupLayout(0),
                                             .entryCount = count,
                                             .entries = entries.data()};
  return aurora::webgpu::g_device.CreateBindGroup(&descriptor);
}

// A render target texture of the intermediate format, recreated when the size changes.
void ensureTarget(wgpu::Texture& texture, wgpu::TextureView& view, uint32_t width, uint32_t height, const char* label) {
  if (texture && texture.GetWidth() == width && texture.GetHeight() == height) {
    return;
  }
  PetariNative::HostAllocationScope host;
  const wgpu::TextureDescriptor descriptor{
      .label = label,
      .usage = wgpu::TextureUsage::RenderAttachment | wgpu::TextureUsage::TextureBinding,
      .dimension = wgpu::TextureDimension::e2D,
      .size = {width, height, 1},
      .format = kIntermediateFormat,
  };
  texture = aurora::webgpu::g_device.CreateTexture(&descriptor);
  view = texture.CreateView();
}

// One full-target pass of a filter from source into target.
void runFilter(const wgpu::CommandEncoder& encoder, ImageFilter filter, const wgpu::TextureView& source,
               const wgpu::TextureView& target, const char* label) {
  const ImagePipelines& pipelines = imagePipelines(gIntermediatePipelines, kIntermediateFormat);
  const wgpu::RenderPassColorAttachment attachment{.view = target, .loadOp = wgpu::LoadOp::Clear, .storeOp = wgpu::StoreOp::Store};
  const wgpu::RenderPassDescriptor descriptor{.label = label, .colorAttachmentCount = 1, .colorAttachments = &attachment};
  const auto pass = encoder.BeginRenderPass(&descriptor);
  pass.SetPipeline(pipelines.filters[filter]);
  pass.SetBindGroup(0, imageBindGroup(pipelines, filter, source), 0, nullptr);
  pass.Draw(3);
  pass.End();
}

bool prepare_image(const wgpu::CommandEncoder& encoder, const Frame& frame, float viewWidth, float viewHeight) noexcept {
  if (frame.black || !frame.xfb) {
    return false;
  }
  using namespace aurora::webgpu;
  PetariNative::HostAllocationScope host;
  TextureWithSampler source = xfb_source(*frame.xfb);
  imagePipelines(gIntermediatePipelines, kIntermediateFormat);  // the shared sampler and params buffer
  if (frame.fxaa) {
    ensureTarget(gFxaaTexture, gFxaaView, source.size.width, source.size.height, "Petari FXAA image");
    runFilter(encoder, FilterFxaa, source.view, gFxaaView, "Petari FXAA pass");
    source.texture = gFxaaTexture;
    source.view = gFxaaView;
    source.format = kIntermediateFormat;
  }
  const uint32_t width = std::max<uint32_t>(1, static_cast<uint32_t>(std::lround(viewWidth)));
  const uint32_t height = std::max<uint32_t>(1, static_cast<uint32_t>(std::lround(viewHeight)));
  const bool sameSize = width == source.size.width && height == source.size.height;
  const bool enlarge = !sameSize && viewWidth > static_cast<float>(source.size.width);
  const bool easu = enlarge && frame.upscaler == PETARI_PRESENT_UPSCALE_FSR1;
  const bool sharpen = frame.sharpness > 0.0f;
  const ImageFilter scaler = sameSize ? FilterBilinear
                             : enlarge ? (easu ? FilterEasu : frame.upscaler == PETARI_PRESENT_UPSCALE_BILINEAR ? FilterBilinear : FilterBicubic)
                                       : FilterArea;
  const float params[4] = {static_cast<float>(width), static_cast<float>(height), frame.sharpness, 0.0f};
  g_queue.WriteBuffer(gImageParams, 0, params, sizeof(params));

  if (!easu && !sharpen) {
    // Straight into the window.
    if (scaler == FilterBilinear) {
      gImageDraw.pipeline = g_CopyPipeline;
      gImageDraw.bindGroup = create_copy_bind_group(source);
    } else {
      const ImagePipelines& pipelines = imagePipelines(gSurfacePipelines, g_graphicsConfig.surfaceConfiguration.format);
      gImageDraw.pipeline = pipelines.filters[scaler];
      gImageDraw.bindGroup = imageBindGroup(pipelines, scaler, source.view);
    }
    return true;
  }
  // Scaled at the viewport's size first, then RCAS (or a copy) into the window.
  ensureTarget(gScaledTexture, gScaledView, width, height, "Petari scaled image");
  runFilter(encoder, scaler, source.view, gScaledView, easu ? "Petari FSR 1 EASU pass" : "Petari scale pass");
  if (sharpen) {
    const ImagePipelines& pipelines = imagePipelines(gSurfacePipelines, g_graphicsConfig.surfaceConfiguration.format);
    gImageDraw.pipeline = pipelines.filters[FilterRcas];
    gImageDraw.bindGroup = imageBindGroup(pipelines, FilterRcas, gScaledView);
  } else {
    gImageDraw.pipeline = g_CopyPipeline;
    gImageDraw.bindGroup = create_copy_bind_group(TextureWithSampler{.texture = gScaledTexture,
                                                                     .view = gScaledView,
                                                                     .size = {width, height, 1},
                                                                     .format = kIntermediateFormat,
                                                                     .sampler = present_source().sampler});
  }
  return true;
}

void draw_image(const wgpu::RenderPassEncoder& pass) noexcept {
  pass.SetPipeline(gImageDraw.pipeline);
  pass.SetBindGroup(0, gImageDraw.bindGroup, 0, nullptr);
  pass.Draw(3);
}

void draw_dim(const wgpu::RenderPassEncoder& pass, const Frame& frame) noexcept {
  using namespace aurora::webgpu;
  if (!gDimTexture) {
    const wgpu::TextureDescriptor descriptor{
        .label = "Petari VI dimming",
        .usage = wgpu::TextureUsage::TextureBinding | wgpu::TextureUsage::CopyDst,
        .dimension = wgpu::TextureDimension::e2D,
        .size = {1, 1, 1},
        .format = wgpu::TextureFormat::RGBA8Unorm,
    };
    gDimTexture = g_device.CreateTexture(&descriptor);
    gDimView = gDimTexture.CreateView();
    const uint8_t pixel[4] = {0, 0, 0, static_cast<uint8_t>(kDimOpacity * 255.0f + 0.5f)};
    const wgpu::TexelCopyTextureInfo destination{.texture = gDimTexture};
    const wgpu::TexelCopyBufferLayout layout{.bytesPerRow = 4, .rowsPerImage = 1};
    const wgpu::Extent3D size{1, 1, 1};
    g_queue.WriteTexture(&destination, pixel, sizeof(pixel), &layout, &size);
  }
  (void)frame;
  const TextureWithSampler source{
      .texture = gDimTexture,
      .view = gDimView,
      .size = {1, 1, 1},
      .format = wgpu::TextureFormat::RGBA8Unorm,
      .sampler = present_source().sampler,
  };
  pass.SetPipeline(g_CopyPremultipliedAlphaPipeline);
  pass.SetBindGroup(0, create_copy_bind_group(source), 0, nullptr);
  pass.Draw(3);
}

}  // namespace petari_present

extern "C" {

void petari_present_enable(void) {
  petari_present::gEnabled = true;
  if (!petari_present::gAspectEnabled.exchange(true)) {
    aurora::window::request_frame_buffer_resize();
  }
}

int petari_present_content_aspect(unsigned* width, unsigned* height) {
  if (!petari_present::gAspectEnabled.load()) {
    return 0;
  }
  *width = petari_present::gAspectWidth.load();
  *height = petari_present::gAspectHeight.load();
  return 1;
}

void petari_present_set_video(const PetariPresentVideo* video) {
  petari_present::gVideo = *video;
  petari_present::setContentAspect(video->aspectWidth, video->aspectHeight);
}

void petari_present_set_graphics(const PetariPresentGraphics* graphics) {
  petari_present::gRequestedHeight.store(graphics->renderHeight);
  petari_present::gUpscaler.store(graphics->upscaler);
  petari_present::gSharpness.store(graphics->sharpness > 0.0f ? std::min(graphics->sharpness, 1.0f) : 0.0f);
  petari_present::gFxaa.store(graphics->fxaa != 0);
}

unsigned petari_present_render_height(void) {
  return petari_present::gAspectEnabled.load() ? petari_present::gRenderHeight.load() : 0;
}

int petari_present_image_rect(float* x, float* y, float* width, float* height) {
  using namespace aurora::webgpu;
  const uint32_t surfaceWidth = g_graphicsConfig.surfaceConfiguration.width;
  const uint32_t surfaceHeight = g_graphicsConfig.surfaceConfiguration.height;
  const auto& video = petari_present::gVideo;
  const Viewport viewport = calculate_present_viewport(surfaceWidth, surfaceHeight,
                                                       video.aspectWidth != 0 ? video.aspectWidth : 4,
                                                       video.aspectHeight != 0 ? video.aspectHeight : 3);
  const AuroraWindowSize window = aurora::window::get_window_size();
  if (viewport.width <= 0.f || viewport.height <= 0.f || window.native_fb_width == 0 || window.native_fb_height == 0) {
    return 0;
  }
  // Surface pixels to window points.
  const float sx = static_cast<float>(window.width) / static_cast<float>(window.native_fb_width);
  const float sy = static_cast<float>(window.height) / static_cast<float>(window.native_fb_height);
  *x = viewport.left * sx;
  *y = viewport.top * sy;
  *width = viewport.width * sx;
  *height = viewport.height * sy;
  return 1;
}

}  // extern "C"
