"""Donkey Kong 64 (USA) ROM access: pointer tables (master @0x101C50) + gzip files + text format.

Text file (TABLE_12_TEXT, gzip): [u8 n_textbox] then per textbox [u8 n_block] then blocks:
  type & 1 : [u8 n] + n * (u32 pos, u16 size, u16 0)  -> string pieces in the data area
  type & 2 : [u8 n] + n * u32 (icon: (v >> 8) & 0xFF) (encoder writes 2,1,u16 icon,0,0)
  type & 4 : 4 extra bytes before the count
  then a 4-byte float (unk0)
After all textboxes: [u16 data size] + data (ASCII, no terminators).  (2dos/DK64-Randomizer base-hack/build/text_*.py)
"""
import struct, gzip, zlib

ROM_PATH = r'C:\claude\roms\n64\Donkey Kong 64 (USA).z64'
PT = 0x101C50
TEXT = 12


def load_rom(path=ROM_PATH):
    return open(path, 'rb').read()


def table(rom, t):
    base = PT + struct.unpack_from('>I', rom, PT + 4 * t)[0]
    n = struct.unpack_from('>I', rom, PT + 32 * 4 + 4 * t)[0]
    ents = [struct.unpack_from('>I', rom, base + 4 * j)[0] for j in range(n + 1)]
    return [(PT + (ents[j] & 0x7FFFFFFF), PT + (ents[j + 1] & 0x7FFFFFFF), ents[j] >> 31) for j in range(n)]


def file(rom, t, j):
    a, b, flag = table(rom, t)[j]
    d = rom[a:b]
    if d[:2] == b'\x1f\x8b':
        d = zlib.decompress(d, 15 + 32)
    return d


def parse_text(d):
    """-> list of textboxes; textbox = list of blocks; block = dict(kind, items, raw)"""
    p = 0
    n = d[p]; p += 1
    boxes = []
    for _ in range(n):
        nb = d[p]; p += 1
        blocks = []
        for _ in range(nb):
            t = d[p]; s0 = p; p += 1
            if t & 4:
                p += 4
            cnt = d[p]; p += 1
            items = []
            if t & 1:
                for _ in range(cnt):
                    pos, size, z = struct.unpack_from('>IHH', d, p); p += 8
                    items.append(('str', pos, size))
            elif t & 2:
                for _ in range(cnt):
                    v = struct.unpack_from('>I', d, p)[0]; p += 4
                    items.append(('icon', v))
            p += 4                                        # float unk0
            blocks.append(dict(kind=t, items=items, raw=d[s0:p]))
        boxes.append(blocks)
    size = struct.unpack_from('>H', d, p)[0]; p += 2
    data = d[p:p + size]
    return boxes, data, p + size


def strings(d):
    boxes, data, end = parse_text(d)
    out = []
    for bi, blocks in enumerate(boxes):
        for k, b in enumerate(blocks):
            parts = []
            for it in b['items']:
                if it[0] == 'str':
                    parts.append(data[it[1]:it[1] + it[2]].decode('latin-1'))
                else:
                    parts.append('{ICON%02X}' % (it[1] >> 16))
            out.append((bi, k, parts))
    return out, end, len(d)
