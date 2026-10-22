#!/usr/bin/env python3
"""Read and write whole RARC archives with their folders (stage archives: StageData/<Zone>.arc).

stage_edit.Archive replaces the contents of files an archive already has; rarc_write.make_rarc
writes one flat folder. A stage editor also adds and removes files (a new path's point table,
jmp/path/commonpathpointinfo.<n>), so this reads the folder tree and writes it back:

    tree = read_tree(raw)            # raw: Yaz0 or plain RARC
    tree.files["jmp/path/commonpathpointinfo.3"] = data   # add, replace, or del tree.files[...]
    plain = write_tree(tree)         # plain RARC; stage_edit.yaz0_compress for Yaz0

Paths are below the root folder, as on the disc (lower case in stage archives); folders keep their
order and new files go at the end of their folder. The layout is the disc's: a 0x20 header, the
info block, the folder nodes (type = the name's first four letters upper case,
ROOT for the root; depth first), each folder's entries (sub-folders and files in order, then "." and ".."),
the string table, the file data (32-byte aligned). File IDs count the files in entry order;
files are preloaded to main memory (flags 0x11) unless the source said otherwise.

    rarc_tree.py selftest   rewrites every disc stage archive and compares it with the original
"""
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_pipeline_seed_inputs import decompress  # noqa: E402
from rarc_write import align, name_hash  # noqa: E402


@dataclass
class Tree:
    root: str
    folders: list = field(default_factory=list)  # folder paths below the root, in order ("" not listed)
    files: dict = field(default_factory=dict)    # path -> bytes, in order
    flags: dict = field(default_factory=dict)    # path -> entry flags of files read from an archive
    sync: int = 0                                # the info block's "IDs are synchronised" byte


def read_tree(raw: bytes) -> Tree:
    data = decompress(raw)
    if data[:4] != b"RARC":
        raise ValueError("not a RARC archive")
    header, data_offset = struct.unpack_from(">II", data, 8)
    payload = header + data_offset
    nodes, node_offset, _, entry_offset, _, string_offset, _, sync, _ = struct.unpack_from(">6IHBB", data, header)

    def string(offset):
        start = header + string_offset + offset
        return data[start:data.index(b"\0", start)].decode("latin-1")

    def node(index):
        _, name, _, count, first = struct.unpack_from(">4sIHHI", data, header + node_offset + index * 16)
        return string(name), count, first

    tree = Tree(root=node(0)[0], sync=sync)
    queue = [(0, "")]
    while queue:
        index, prefix = queue.pop(0)
        _, count, first = node(index)
        for i in range(first, first + count):
            _, _, flags, _, name_offset, value, size = struct.unpack_from(">HHBBHII", data, header + entry_offset + i * 20)
            name = string(name_offset)
            if name in (".", ".."):
                continue
            path = prefix + name
            if flags & 2:
                tree.folders.append(path)
                queue.append((value, path + "/"))
            else:
                tree.files[path] = bytes(data[payload + value:payload + value + size])
                tree.flags[path] = flags
    return tree


def write_tree(tree: Tree) -> bytes:
    # Folders: every folder a file needs, then the order read or added.
    folders = list(tree.folders)
    for path in tree.files:
        parts = path.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            folder = "/".join(parts[:depth])
            if folder not in folders:
                folders.append(folder)

    def parent(path):
        return path.rpartition("/")[0]

    # Depth first from the root (as on the disc), children in the order listed.
    ordered = []

    def visit(path):
        ordered.append(path)
        for child in folders:
            if parent(child) == path:
                visit(child)

    visit("")
    node_index = {path: i for i, path in enumerate(ordered)}

    # Strings as on the disc: ".", "..", then each folder's name followed by its files' names, depth
    # first (a folder's node and its entry in the parent share the name).
    strings = bytearray(b".\0..\0")
    name_at = {}

    def add(key, name):
        name_at[key] = len(strings)
        strings.extend(name.encode("latin-1") + b"\0")

    for path in ordered:
        add(path, tree.root if path == "" else path.rpartition("/")[2])
        for child in tree.files:
            if parent(child) == path:
                add(child, child.rpartition("/")[2])

    entries = []    # (id, name offset, name, flags, value, size, file path or None)
    node_records = []
    file_id = 0
    for path in ordered:
        name = tree.root if path == "" else path.rpartition("/")[2]
        first = len(entries)
        for child in (f for f in folders if parent(f) == path):
            entries.append((0xFFFF, name_at[child], child.rpartition("/")[2], 0x02, node_index[child], 0x10, None))
        for child in (p for p in tree.files if parent(p) == path):
            entries.append((file_id, name_at[child], child.rpartition("/")[2], tree.flags.get(child, 0x11), 0,
                            len(tree.files[child]), child))
            file_id += 1
        entries.append((0xFFFF, 0, ".", 0x02, node_index[path], 0x10, None))
        entries.append((0xFFFF, 2, "..", 0x02, 0xFFFFFFFF if path == "" else node_index[parent(path)], 0x10, None))
        kind = b"ROOT" if path == "" else name.upper().encode("latin-1")[:4].ljust(4, b" ")
        node_records.append((kind, name_at[path], name_hash(name), len(entries) - first, first))
    strings.extend(bytes(align(len(strings)) - len(strings)))

    body = bytearray()
    offsets = {}
    for path, content in tree.files.items():
        offsets[path] = len(body)
        body += content
        body += bytes(align(len(body)) - len(body))

    node_offset = 0x20
    entry_offset = node_offset + align(len(ordered) * 16)
    string_offset = entry_offset + align(len(entries) * 20)
    data_offset = string_offset + len(strings)

    info = struct.pack(">6IHBB", len(ordered), node_offset, len(entries), entry_offset, len(strings), string_offset,
                       file_id, tree.sync, 0)
    info += bytes(node_offset - len(info))
    node_bytes = b"".join(struct.pack(">4sIHHI", *record) for record in node_records)
    node_bytes += bytes(align(len(node_bytes)) - len(node_bytes))
    entry_bytes = bytearray()
    for fid, name_offset, name, flags, value, size, path in entries:
        if path is not None:
            value = offsets[path]
        entry_bytes += struct.pack(">HHBBHIII", fid, name_hash(name), flags, 0, name_offset, value, size, 0)
    entry_bytes += bytes(align(len(entry_bytes)) - len(entry_bytes))
    block = info + node_bytes + bytes(entry_bytes) + bytes(strings)
    assert len(block) == data_offset
    total = 0x20 + data_offset + len(body)
    head = struct.pack(">4s7I", b"RARC", total, 0x20, data_offset, len(body), len(body), 0, 0)
    return head + block + bytes(body)


def selftest() -> int:
    disc = Path.home() / "Library/Application Support/Petari/Disc/RMGE01/files/StageData"
    count = 0
    for path in sorted(disc.glob("*.arc")):
        raw = path.read_bytes()
        tree = read_tree(raw)
        again = read_tree(write_tree(tree))
        if (again.root, again.folders, again.files, again.flags) != (tree.root, tree.folders, tree.files, tree.flags):
            print(f"FAIL {path.name}")
            return 1
        count += 1
    print(f"rarc_tree selftest: {count} stage archives rewritten and read back unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if sys.argv[1:] == ["selftest"] else (print(__doc__) or 2))
