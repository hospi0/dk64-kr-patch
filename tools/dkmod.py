"""DK64: Recompiled (Rekongpiled) Korean mod — data generator.

usage: python tools/dkmod.py <tsv folder or files...>
  -> recomp/mod/src/krblob.bin + recomp/mod/src/krblob.s (.incbin) + recomp/mod/src/krdata.h

The recompiled port only accepts the vanilla US ROM and runs pre-recompiled code, so the ROM patch
(tools/dkbuild.py) cannot be used there.  The mod (recomp/mod/src/kr.c) re-implements the same
hooks in C and takes its data from here:
  * text table 12 files: whole uncompressed files, handed to the game through the
    recomp_on_asset_file_load_override event (no ROM table changes, no size table).
  * glyph pages (served as table-14 files 256.. through the same event, so they live in the game heap
    like the original pages — RT64 cannot fetch textures straight from mod memory): style 6 = IA4 176x13, 12 cells (same as the ROM patch); style 1 = RGBA16 76x24 like
    the original menu pages, 3 cells of 22 px (no TLUT needed — the ROM patch used CI4 only to save RAM).
  * extended glyph tables / bounds for styles 1 and 6, voice captions, kong-name writes.
Same checks as the ROM builder (dkbuild.check_translations etc.); any error stops before writing.
"""
import os, sys, struct

sys.path.insert(0, os.path.dirname(__file__))
import dkrom, dkbuild as B, s1font

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'recomp', 'mod', 'src')

S1_W, S1_H = 76, 24                    # original style-1 page (RGBA16, LoadBlock 1823/108)
S1_PER = 3                             # 3 cells of 22 px (66 <= 76)
S1_BYTES = S1_W * S1_H * 2
# style 6: one IA4 strip 512x13 = 39 cells of 13 px (4056 B <= 4 KB TMEM, loaded with LoadTile).
# Every font page costs the renderer one pass (+ a PipeSync) per call, so fewer, wider pages.
P6_W, P6_H, P6_CELL = 512, 13, 13           # texture s beyond 512 px came out garbled (2026-10-06)
P6_PER = P6_W // P6_CELL
P6_BYTES = P6_W * P6_H // 2


def s6_pages(chars):
    """dialogue glyphs -> IA4 624x13 strips (glyph I7/A1 = 0xF, background I7/A0 = 0xE, like dkbuild)"""
    f = B.bdf.BdfFont(B.FONT)
    out = bytearray()
    for p0 in range(0, len(chars), P6_PER):
        px = bytearray(b'' * (P6_W * P6_H))
        for c, ch in enumerate(chars[p0:p0 + P6_PER]):
            gl = f.glyphs[ord(ch)]
            w, h, xo, yo = gl.bbx
            top = 12 - (h + yo)
            for y, row in enumerate(gl.bitmap()):
                for x, v in enumerate(row):
                    X, Y = x + xo, y + top
                    if v and 0 <= X < P6_CELL and 0 <= Y < P6_H:
                        px[Y * P6_W + c * P6_CELL + X] = 0x0F
        out += bytes((px[i] << 4) | px[i + 1] for i in range(0, len(px), 2))
    return bytes(out)


def s1_pages(chars):
    """menu-font glyphs -> RGBA16 76x24 pages, 3 per page (colours from s1font's palette)."""
    from PIL import ImageFont
    font = ImageFont.truetype(s1font.FONT, s1font.SIZE)
    pal = [s1font.rgba5551(c) for c in s1font.PAL]
    out = bytearray()
    for p0 in range(0, len(chars), S1_PER):
        grid = [[0] * S1_W for _ in range(S1_H)]
        for k, ch in enumerate(chars[p0:p0 + S1_PER]):
            g = s1font.glyph(ch, font)
            for j in range(S1_H):
                grid[j][k * s1font.CELL_W:(k + 1) * s1font.CELL_W] = g[j]
        for j in range(S1_H):
            for i in range(S1_W):
                out += pal[grid[j][i]].to_bytes(2, 'big')
    return bytes(out)


def s1_width(t, rd):
    """style-1 width as getCenterOfString measures it (Korean = Z 0 + D 20, kerning after each byte)"""
    desc = rd(B.DESC + 6, 6)
    tab = rd(struct.unpack('>I', rd(B.TABS + 4, 4))[0], 4 * B.S1_CHARS)
    sset = rd(0x80754A64, 57)
    w = 0
    for ch in t:
        if ch == ' ':
            w += desc[3] + desc[4]
        elif ord(ch) >= 0x80:
            w += 2 * desc[4] + s1font.QUAD_W
        else:
            w += tab[4 * sset.index(ch.encode()) + 2] + desc[4]
    return w


# the port's boot screen centres «PRESENTED IN» (text 0D:0) with a constant tuned to the English width
# (boot_logos_patches.c: x = (W - width) * 2 + 330, drawn at half size) -> pad the translation with
# spaces on both sides to the English width so it lands in the same place
CENTRE_LIKE_SOURCE = ('0D:0',)


def main():
    paths = sys.argv[1:]
    rom = bytearray(dkrom.load_rom())
    tr = B.check_translations(B.read_tsv(paths))
    rd = B.gdata(rom)
    for loc in CENTRE_LIKE_SOURCE:
        if loc in tr:
            src, ko = tr[loc]
            ko = ko.strip()
            n = max(0, (s1_width(src, rd) - s1_width(ko, rd)) // s1_width(' ', rd))
            tr[loc] = (src, ' ' * (n // 2) + ko + ' ' * (n - n // 2))
            print(f'{loc}: centred like the source ({n} spaces)')
    names = B.read_code_names()
    voices = B.read_voices()
    chars, n1 = B.order_glyphs(tr, [ko for _, _, _, ko, _ in names] + [v[1].split(':')[0] for v in voices if ':' in v[1]])
    for v in voices:
        for c in v[1]:
            if ord(c) >= 0x80 and c not in chars:
                chars.append(c)
    assert len(chars) <= B.NLEAD * B.NTRAIL
    cmap = {ch: i for i, ch in enumerate(chars)}

    # text files (uncompressed, whole file)
    by_file = {}
    for loc, (src, ko) in tr.items():
        f, b = loc.split(':')
        by_file.setdefault(int(f, 16), {})[int(b)] = (src, ko)
    texts, vbox = {}, None
    for j in sorted(set(by_file) | ({B.VOICE_FILE} if voices else set())):
        boxes, data, _ = dkrom.parse_text(dkrom.file(rom, dkrom.TEXT, j))
        new = {}
        for bi, (src, ko) in by_file.get(j, {}).items():
            new[bi] = [(k, [B.encode(p, cmap) for p in v]) if k == 'T' else (k, v) for k, v in B.split_box(ko)]
        extra = [B.encode(v[1], cmap) for v in voices] if j == B.VOICE_FILE else []
        if extra:
            vbox = len(boxes)
        nd = B.build_text(boxes, data, new, extra)
        dkrom.parse_text(nd)                                   # round trip
        texts[j] = nd + bytes(-len(nd) % 4)
    cpatch = B.code_patches(names, cmap, rd)
    tab1, bnd1, fc1, h1 = B.style_tables(rd, 1, B.S1_CHARS)
    tab6, bnd6, fc6, h6 = B.style_tables(rd, 6, B.S6_CHARS)
    pages6 = s6_pages(chars)
    pages1 = s1_pages(chars[:n1])
    # no per-string scan in the mod (hooks do not load in this port): every Korean page is a fixed
    # virtual page FC+1+r -> bounds = original FC+1 entries + one per Korean page
    np6, np1 = len(pages6) // P6_BYTES, len(pages1) // S1_BYTES
    bnd1 = bnd1[:fc1 + 1] + bytes((B.S1_CHARS,)) * np1
    bnd6 = bnd6[:fc6 + 1] + bytes((B.S6_CHARS,)) * np6

    blob, off = bytearray(), {}

    def put(name, b, align=16):
        blob.extend(bytes(-len(blob) % align))
        off[name] = len(blob)
        blob.extend(b)
    for j, d in texts.items():
        put(f'TEXT{j:02X}', d)
    put('TAB1', tab1)
    put('TAB6', tab6)
    put('BND1', bnd1)
    put('BND6', bnd6)
    put('PAGES6', pages6)
    put('PAGES1', pages1)
    blob.extend(bytes(-len(blob) % 16))

    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, 'krblob.bin'), 'wb').write(blob)
    open(os.path.join(OUT, 'krblob.s'), 'w', newline='\n').write(
        '.section .data\n.balign 16\n.global kr_blob\nkr_blob:\n.incbin "src/krblob.bin"\n')
    h = ['/* generated by tools/dkmod.py — do not edit */', '#pragma once', '',
         f'#define KR_LEAD0 {B.LEAD0}', f'#define KR_TRAIL0 {B.TRAIL0}', f'#define KR_NTRAIL {B.NTRAIL}',
         f'#define KR_ADV {B.KR_ADV}', f'#define KR_VMAX {B.VMAX}', '',
         f'#define KR_NTEXT {len(texts)}',
         'static const u16 kr_text_file[] = {' + ', '.join(f'0x{j:02X}' for j in texts) + '};',
         'static const u32 kr_text_off[] = {' + ', '.join(f'0x{off[f"TEXT{j:02X}"]:X}' for j in texts) + '};',
         'static const u32 kr_text_len[] = {' + ', '.join(str(len(d)) for d in texts.values()) + '};', '',
         '/* tab off, bnd off, glyphs, D, FC, per page, cell w, glyph w, pages off, page bytes, height set, height orig */',
         f'#define KR_P1_INIT {{0x{off["TAB1"]:X}, 0x{off["BND1"]:X}, {n1}, {B.S1_CHARS}, {fc1}, {S1_PER}, '
         f'{s1font.CELL_W}, {s1font.QUAD_W}, 0x{off["PAGES1"]:X}, {S1_BYTES}, 0, {h1}}}',
         f'#define KR_P6_INIT {{0x{off["TAB6"]:X}, 0x{off["BND6"]:X}, {len(chars)}, {B.S6_CHARS}, {fc6}, {P6_PER}, '
         f'{P6_CELL}, {B.KR_ADV}, 0x{off["PAGES6"]:X}, {P6_BYTES}, 13, {h6}}}', '',
         f'#define KR_NPAGES6 {len(pages6) // P6_BYTES}', f'#define KR_NPAGES1 {len(pages1) // S1_BYTES}', '',
         f'#define KR_NVOICE {len(voices)}',
         '/* sound id, caption box (text file 01), colour, frames */',
         'static const u16 kr_voice[][4] = {' + ', '.join(
             f'{{{sid}, {vbox + k}, {col}, {fr}}}' for k, (sid, _, col, fr) in enumerate(voices)) + '};' if voices
         else 'static const u16 kr_voice[1][4] = {{0xFFFF, 0, 0, 0}};', '',
         f'#define KR_NCODE {len(cpatch)}',
         'static const u32 kr_code[][2] = {' + ', '.join(f'{{0x{a:08X}, 0x{v:08X}}}' for a, v in cpatch) + '};', '']
    open(os.path.join(OUT, 'krdata.h'), 'w', encoding='utf-8', newline='\n').write('\n'.join(h))
    print(f'texts {len(texts)} files · glyphs {len(chars)} (menu {n1}) · pages6 {len(pages6) // P6_BYTES} '
          f'· pages1 {len(pages1) // S1_BYTES} · voices {len(voices)} · code words {len(cpatch)} · blob {len(blob)} B')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
