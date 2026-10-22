"""The opening camera flight of a galaxy: camera/StartScenario1.canm, a keyframed CKAN
animation as CameraAnim.cpp reads it (native/CUSTOM_GALAXY.md, "Your own planet").

Layout: a 0x20 header ('ANDO' 'CKAN', s32 1, 0, 1, 4 as on the disc, u32 frames, u32 size
of the track table = 96); 8 tracks of {u32 count, u32 first value, u32 type} (PosX, PosY,
PosZ, WatchX, WatchY, WatchZ, Twist, Fovy); then u32 byte size of the values and the
big-endian f32 values. A type 0 key is (frame, value, slope), the slope in units per
second (the game divides by 30); a track of count 1 is one constant value. Positions are
in world coordinates.
"""
import math
import struct


def keys_with_slopes(frames, values):
    """Keys through the values, smooth (Catmull-Rom slopes), easing in and out at the ends."""
    keys = []
    for i, (frame, value) in enumerate(zip(frames, values)):
        if i == 0 or i == len(frames) - 1:
            slope = 0.0
        else:
            slope = (values[i + 1] - values[i - 1]) / (frames[i + 1] - frames[i - 1])
        keys.append((frame, value, slope * 30.0))
    return keys


def build(frames, tracks):
    """tracks: 8 lists of (frame, value, slope per second) keys, or [value] for a constant."""
    infos, values = [], []
    for track in tracks:
        if len(track) == 1 and not isinstance(track[0], tuple):
            infos.append((1, len(values), 0))
            values.append(float(track[0]))
        else:
            infos.append((len(track), len(values), 0))
            for key in track:
                values.extend(key)
    table = b"".join(struct.pack(">3I", *info) for info in infos)
    data = struct.pack(">4s4s4i2I", b"ANDO", b"CKAN", 1, 0, 1, 4, frames, len(table)) + table
    data += struct.pack(">I", 4 * len(values)) + struct.pack(f">{len(values)}f", *values)
    return data + bytes(-len(data) % 16)


def orbit(center, radius, height, mario, frames_orbit=240, hold=60):
    """Five-sixths of a turn round the planet, rising, then down behind Mario's landing place,
    looking at him; held there for `hold` frames."""
    cx, cy, cz = center
    frames, eye, watch = [], [], []
    for i in range(6):
        angle = math.radians(-60 * i)
        frames.append(i * frames_orbit // 5)
        eye.append((cx + radius * math.sin(angle), cy + height + 300 * i, cz + radius * math.cos(angle)))
        watch.append(center)
    mx, my, mz = mario
    frames.append(frames_orbit + 90)
    eye.append((mx, my + 900, mz + 1600))
    watch.append((mx, my + 150, mz))
    total = frames[-1] + hold
    # The last key sits at the last frame, as on the disc: keys are sampled only below it.
    frames.append(total)
    eye.append(eye[-1])
    watch.append(watch[-1])
    tracks = [keys_with_slopes(frames, [p[axis] for p in eye]) for axis in range(3)]
    tracks += [keys_with_slopes(frames, [w[axis] for w in watch]) for axis in range(3)]
    tracks += [[0.0], [45.0]]  # twist (degrees), field of view
    return build(total, tracks)
