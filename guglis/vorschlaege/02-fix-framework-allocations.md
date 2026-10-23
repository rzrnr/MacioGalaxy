With AirPods as the Mac's sound output, the game crashed at the first sound: SIGSEGV in `OSLockMutex`, called from `JKRExpHeap::do_free`, called from `operator delete`, on a CoreAudio thread. Core Animation's fence transactions crashed the same way on a dispatch queue.

## Cause

The allocation-site check (`native/src/host_allocation.cpp`) decides on a game thread whether an allocation belongs to the game's JKR heaps or to the host. It classifies the call chain by its first frame outside the allocator and the C++ library. A C++ name with `::` counted as game code.

macOS frameworks are C++ too. CoreAudio's `HALObject::AddPropertyListener` and Core Animation's `CA::Render::Fence::Transaction` read as game classes, so the containers they grew on a game thread came from the JKR heaps. When they were freed on the frameworks' own threads, which have no OS thread for the heap's mutex, the game crashed. With AirPods, macOS sets up its audio session that way at the first sound (smart routing), so every run crashed there.

## Change

A frame outside the main executable now counts as host code, whatever its name. "Outside" means `dladdr`'s image base differs from `_dyld_get_image_header(0)`. This applies to the allocation routing and to `classifyCode`.

## Testing

- All 84 ctest programs pass.
- The EggStarGalaxy stage smoke now passes with AirPods as the default output device. Before the change it crashed on the first sound.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
