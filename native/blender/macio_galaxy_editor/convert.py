"""Game space <-> Blender space.

The game is Y up in game units; Blender is Z up in metres, 1 m = 100 units (as the mods' Blender
models): (x, y, z) game -> (x, -z, y) / 100. An object's matrix in the game is
T(pos) . Rz(dir_z) . Ry(dir_y) . Rx(dir_x) . S(scale), degrees (Whitehole's AbstractObj, the game's
MR::makeMtxTR); a zone placed in its galaxy the same without scale. In Blender the rotation is the
same rotation seen in the other axes, and the scale (sx, sy, sz) becomes (sx, sz, sy).
"""
import math

from mathutils import Euler, Matrix, Vector

UNIT = 0.01  # metres per game unit
C = Matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0)))  # game axes -> Blender axes
CT = C.transposed()


def to_blender(point) -> Vector:
    return (C @ Vector(point)) * UNIT


def to_game(point) -> Vector:
    return (CT @ Vector(point)) / UNIT


def basis_from_game(pos, rot, scale=(1.0, 1.0, 1.0)) -> Matrix:
    """A Blender matrix from game pos, dir (degrees) and scale."""
    rotation = Euler([math.radians(a) for a in rot], "XYZ").to_matrix()
    linear = C @ rotation @ Matrix.Diagonal(Vector(scale)) @ CT
    matrix = linear.to_4x4()
    matrix.translation = to_blender(pos)
    return matrix


def game_from_basis(matrix: Matrix):
    """(pos, dir in degrees, scale) of a Blender matrix, rounded as the editor writes them."""
    location, rotation, scale = matrix.decompose()
    pos = to_game(location)
    euler = (CT @ rotation.to_matrix() @ C).to_euler("XYZ")
    rot = [math.degrees(a) for a in euler]
    return ([round(v, 3) for v in pos], [round(a, 4) + 0.0 for a in rot],
            [round(scale.x, 5), round(scale.z, 5), round(scale.y, 5)])


def same_matrix(a: Matrix, b: Matrix, tolerance=1e-5) -> bool:
    return all(abs(a[i][j] - b[i][j]) <= tolerance for i in range(4) for j in range(4))


def flat(matrix: Matrix):
    return [matrix[i][j] for i in range(4) for j in range(4)]


def unflat(values) -> Matrix:
    values = list(values)
    return Matrix([values[i * 4:i * 4 + 4] for i in range(4)])
