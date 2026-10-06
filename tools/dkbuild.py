"""Donkey Kong 64 (USA) Korean builder.

usage: python tools/dkbuild.py <tsv folder or files...> <out.z64>

Design (docs/00_이어하기.md):
  * Korean = 2 bytes: lead 0x80..0x8F x trail 0x90..0xFE (111) — text never uses bytes >= 0x80.
    glyph id g = (lead-0x80)*111 + (trail-0x90); ids 0..N1-1 = glyphs that also exist in the menu font.
  * RAM below the heap: heap end constant (0x80610510/18: 0x805FAE00) lowered by RESERVE.
    boot hook 0x80000764 DMAs the blob (ROM 0x2000000) there and jumps to RESUME, which writes the
    hooks straight into the inflated global_asm, flushes caches and replays the displaced boot code.
  * every text renderer (printStyledText 0x806FC530, 806FCC88, 806FD094) works page by page: one pass
    per font page, drawing the chars whose index (806FB914) falls in that page's bounds.  Korean:
      - 806FB914 hook (styles 1 and 6): lead -> remembers the bank, returns Z (zero width, never drawn);
        trail -> writes the glyph's cell into spare table entry D and rewrites the bounds so D falls in
        the «virtual page» FC+1+v holding the glyph's real page, returns D.
      - renderer entry wrappers pre-scan the string: v = 0..V-1 for the distinct Korean pages it uses,
        file_count := FC+V for the call (style 6: quad height 12 -> 13), restored afterwards.
      - 806FBEF0 hook: a virtual page loads our page (style 1 = CI4 160x24 + TLUT, style 6 = IA4 176x13)
        and turns the TLUT back off before any original page / after the renderer.
    style tables/bounds = our extended copies (pointer arrays D_80754A18 / D_807549FC re-pointed).
  * dialogue (func_806A370C draws node by node): 0x806A3B4C jal printStyledText -> KR_DRAW: a lead node
    draws [lead, trail] (trail from the next node), a trail node draws nothing; widths 0x806FD7A8 hook
    (style 6: lead -> KR_ADV, trail -> 0).
  * text table 12 rebuilt after the blob; uncompressed sizes = table 26 file 12 (raw, patched in place).
"""
import os, sys, struct, csv, glob, gzip, zlib, collections

sys.path.insert(0, os.path.dirname(__file__))
import dkrom, bdf, n64crc, s1font
from mips import Asm, hi, lo

LEAD0, NLEAD = 0x80, 16
TRAIL0, NTRAIL = 0x90, 111
KR_ADV = 12                        # style-6 Hangul advance (kerning_character = 0)
# style 6 (dialogue / captions): IA4 176x13 pages, 13 cells of 13 px (4b LoadBlock: 11 words/row, no dxt slip)
CELL = 13
PAGE_W, PAGE_H = 176, 13
PER_PAGE = 13
PAGE_BYTES = PAGE_W * PAGE_H // 2  # 1144
VMAX = 32                          # Korean pages one string may use (per style)

RESERVE = 0x30000
KR_RAM = 0x805FAE00 - RESERVE      # 0x805CAE00
BLOB_ROM = 0x2000000
BOOT_HOOK = 0x80000764
BOOT_ROM = 0x1000 - 0x80000400     # boot segment: ROM = VRAM + this
FONT = r'C:\claude\utils\font\Galmuri-v2.40.3\Galmuri11-Bold.bdf'

GDATA_ROM, GDATA_VRAM = 0xC29D4, 0x80744460      # global_asm .data (gzip)
DESC = 0x80754A34                  # 8 x 6 B: first_tex, file_count, height, kerning_space, kerning_char, kerning_anim
TABS, BNDS = 0x80754A18, 0x807549FC
S1_CHARS, S6_CHARS = 59, 48        # table entries = last bound (style 1: strchr set 57 + 2 icon glyphs)
# files drawn with the menu font (style 1): menus, HUD/popups, level/kong/move names, race, bonus names
S1_FILES = {0x02, 0x0C, 0x0D, 0x1A, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2A}


# --- translations ---------------------------------------------------------------------
def read_tsv(paths):
    files = []
    for p in paths:
        files += sorted(glob.glob(os.path.join(p, '*.tsv'))) if os.path.isdir(p) else [p]
    rows = {}
    for p in files:
        with open(p, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f, delimiter='\t', quoting=csv.QUOTE_NONE):
                if (r.get('번역') or '').strip():
                    rows[r['위치']] = (r['ID'], r['원문'], r['번역'].strip())
    return rows


PUNCT = ',.!?:;)\'"'
STYLE6 = "ABCDEFGHIJKLMNOPQRTUVWXYZ.,!?:;'S-x1234567890()%"     # style-6 glyphs (D_80754AA0)
ALLOWED = set(STYLE6) | set(' ~@')
TOKEN = r'\{/\}|\{ICON[0-9A-F]{2}\}|\{BLK\}|~|@'


def normalize(t):
    """received-translation clean-up: ＿ used as a space (translation tool), full-width parens."""
    return t.replace('＿', ' ').replace('（', '(').replace('）', ')')


def restore_tokens(rid, src, ko):
    """token sequence must equal the source.  Auto-restore: a {/} missing right before an {ICON}
    (translator moved the «PRESS» piece's verb after the icon) -> put it back.  Anything else -> None."""
    import re
    want, got = re.findall(TOKEN, src), re.findall(TOKEN, ko)
    if want == got:
        return ko
    parts = re.split('(' + TOKEN + ')', ko)
    toks = parts[1::2]
    i = 0
    while i < len(want):
        if i < len(toks) and toks[i] == want[i]:
            i += 1
            continue
        if want[i] == '{/}' and i < len(toks) and toks[i].startswith('{ICON') and want[i + 1:i + 2] == [toks[i]]:
            toks.insert(i, '{/}')
            parts[2 * i + 1:2 * i + 1] = ['{/}', '']
            print(f'  {rid}: {{/}} 복원 (앞 {toks[i + 1]})')
            i += 1
            continue
        return None
    return ''.join(parts) if toks == want else None


def check_translations(tr):
    """«쓰는 순간» 검사 — 하나라도 걸리면 빌드 안 함.  ★DK64 예외: 부호 뒤 공백은 지우지 않는다
    (엔진이 공백에서만 줄을 바꾸므로, 지우면 한 줄보다 긴 덩어리가 생겨 말풍선 밖으로 넘친다)."""
    import re
    out, bad = {}, []
    for loc, (rid, src, ko) in tr.items():
        ko = restore_tokens(rid, src, normalize(ko))
        if ko is None:
            bad.append(f'{rid} {loc}: 토큰 불일치 {re.findall(TOKEN, src)} / {re.findall(TOKEN, tr[loc][2])}')
            continue
        body = re.sub(TOKEN, '', ko)
        odd = sorted({c for c in body if c not in ALLOWED and not '가' <= c <= '힣'})
        if odd:
            bad.append(f'{rid} {loc}: 글꼴에 없는 글자 {odd}')
            continue
        out[loc] = (src, ko)
    if bad:
        print('\n'.join(bad))
        sys.exit(f'번역 검사 실패 {len(bad)}건, 빌드 안 함')
    return out


def squeeze(t):
    out = []
    for i, ch in enumerate(t):
        if ch == ' ' and i and t[i - 1] in PUNCT and t[i + 1:i + 2] != ' ':
            continue
        out.append(ch)
    return ''.join(out)


def encode(t, cmap):
    out = bytearray()
    for ch in t:
        if ord(ch) < 0x80:
            out.append(ord(ch))
        else:
            g = cmap[ch]
            out += bytes((LEAD0 + g // NTRAIL, TRAIL0 + g % NTRAIL))
    return bytes(out)


def split_box(t):
    """'A{/}B{ICON6E}C' -> [('T', ['A', 'B']), ('I', 0x6E), ('T', ['C'])]"""
    import re
    out = []
    for tok in re.split(r'(\{ICON[0-9A-F]{2}\}|\{BLK\})', t):
        if tok.startswith('{ICON'):
            out.append(('I', int(tok[5:7], 16)))
        elif tok == '{BLK}' or tok == '':
            continue
        else:
            out.append(('T', tok.split('{/}')))
    return out


# --- text file (de)serialise ----------------------------------------------------------------
def box_pieces(blocks, data):
    out = []
    for b in blocks:
        if b['kind'] & 1:
            out.append(('T', [data[i[1]:i[1] + i[2]] for i in b['items']]))
        else:
            out.append(('I', b['raw']))
    return out


def build_text(boxes, data, new_boxes, extra=()):
    """boxes/data = parsed original; new_boxes = {box index: [('T', [bytes...]) | ('I', icon)]};
    extra = text pieces appended as new one-block boxes (voice captions)."""
    assert len(boxes) + len(extra) < 256
    out = bytearray((len(boxes) + len(extra),))
    blob = bytearray()
    for bi, blocks in enumerate(boxes):
        repl = new_boxes.get(bi)
        kinds = ['T' if b['kind'] & 1 else 'I' for b in blocks]
        if repl is not None and kinds != [k for k, _ in repl]:
            # the translation reorders text and icons («PRESS{A}TO…» -> «{A}을 눌러…»): build the blocks in
            # the translation's order.  heads = the box's first text / icon block; trailing float = 0 except
            # the last block, which keeps the original last block's value.
            tt = next(b for b in blocks if b['kind'] & 1)
            it = next((b for b in blocks if not b['kind'] & 1), None)
            out.append(len(repl))
            for k, (kind, v) in enumerate(repl):
                fl = blocks[-1]['raw'][-4:] if k == len(repl) - 1 else bytes(4)
                if kind == 'T':
                    out += tt['raw'][:1 + (4 if tt['kind'] & 4 else 0)] + bytes((len(v),))
                    for pc in v:
                        out += struct.pack('>IHH', len(blob), len(pc), 0)
                        blob += pc
                else:
                    assert it is not None and len(it['items']) == 1, bi
                    out += it['raw'][:1 + (4 if it['kind'] & 4 else 0)] + b'\x01' + struct.pack('>HH', v, 0)
                out += fl
            continue
        out.append(len(blocks))
        for k, b in enumerate(blocks):
            if not b['kind'] & 1:
                raw = b['raw']
                if repl is not None and len(b['items']) == 1 and b['items'][0][1] >> 16 != repl[k][1]:
                    n0 = 1 + (4 if b['kind'] & 4 else 0)
                    raw = raw[:n0 + 1] + struct.pack('>HH', repl[k][1], 0) + raw[-4:]
                out += raw
                continue
            pieces = repl[k][1] if repl is not None else [data[i[1]:i[1] + i[2]] for i in b['items']]
            raw = b['raw']
            head = raw[:1 + (4 if b['kind'] & 4 else 0)]
            out += head + bytes((len(pieces),))
            for pc in pieces:
                out += struct.pack('>IHH', len(blob), len(pc), 0)
                blob += pc
            out += raw[-4:]                                   # float unk0
    if extra:
        tt = next(b for bl in boxes for b in bl if b['kind'] & 1)
        fl = boxes[0][-1]['raw'][-4:]
        for pc in extra:
            out += bytes((1,)) + tt['raw'][:1 + (4 if tt['kind'] & 4 else 0)] + bytes((1,))
            out += struct.pack('>IHH', len(blob), len(pc), 0) + fl
            blob += pc
    out += struct.pack('>H', len(blob)) + blob
    return bytes(out)


# --- glyph pages -----------------------------------------------------------------------------
def render_pages(chars):
    """style 6: IA4 176x13, 13 cells; glyph = I7/A1 (0xF), background I7/A0 (0xE) like the original IA8 pages."""
    f = bdf.BdfFont(FONT)
    npages = (len(chars) + PER_PAGE - 1) // PER_PAGE
    px = [bytearray(b'\x0E' * (PAGE_W * PAGE_H)) for _ in range(npages)]
    for g, ch in enumerate(chars):
        p, c = divmod(g, PER_PAGE)
        gl = f.glyphs[ord(ch)]
        w, h, xo, yo = gl.bbx
        top = 12 - (h + yo)                          # Hangul rows 1..11; the draw quad is 13 rows (P6 height)
        for y, row in enumerate(gl.bitmap()):
            for x, v in enumerate(row):
                X, Y = x + xo, y + top
                if v and 0 <= X < CELL and 0 <= Y < PAGE_H:
                    px[p][Y * PAGE_W + c * CELL + X] = 0x0F
    return b''.join(bytes((q[i] << 4) | q[i + 1] for i in range(0, len(q), 2)) for q in px)


# --- display-list templates (F3DEX2) ---------------------------------------------------------
def _cmd(w0, w1=0):
    return struct.pack('>II', w0 & 0xFFFFFFFF, w1 & 0xFFFFFFFF)


def _settimg(fmt, siz, addr):
    return _cmd(0xFD000000 | fmt << 21 | siz << 19, addr)


def _settile(fmt, siz, line, tmem, tile, pal=0, cms=2, cmt=2):
    return _cmd(0xF5000000 | fmt << 21 | siz << 19 | line << 9 | tmem, tile << 24 | pal << 20 | cmt << 18 | cms << 8)


LOADSYNC, PIPESYNC, TILESYNC = _cmd(0xE6000000), _cmd(0xE7000000), _cmd(0xE8000000)
TT_NONE, TT_RGBA16 = _cmd(0xE3001001, 0), _cmd(0xE3001001, 0x8000)


def _load4b(fmt, w, h, addr, pal=0):
    words = max(1, w // 16)
    dxt = (2048 + words - 1) // words
    assert dxt * words * h < 2048 * h + dxt, 'dxt slip'
    return (_settimg(fmt, 2, addr) + _settile(fmt, 2, 0, 0, 7) + LOADSYNC +
            _cmd(0xF3000000, 7 << 24 | ((w * h + 3) // 4 - 1) << 12 | dxt) + PIPESYNC +
            _settile(fmt, 0, ((w >> 1) + 7) >> 3, 0, 0, pal) +
            _cmd(0xF2000000, ((w - 1) << 2) << 12 | ((h - 1) << 2)))


def tpl_ci(tlut_phys):
    """CI4 page + 16-colour TLUT.  page address = word at -52 from the end (patched at run time)."""
    t = (TT_RGBA16 + _settimg(0, 2, tlut_phys) + TILESYNC + _settile(0, 0, 0, 256, 7, cms=0, cmt=0) + LOADSYNC +
         _cmd(0xF0000000, 7 << 24 | 15 << 14) + PIPESYNC + _load4b(2, s1font.PAGE_W, s1font.H, 0))
    assert len(t) == 112 and t[60:64] == bytes(4)
    return t


def tpl_ia():
    t = _load4b(3, PAGE_W, PAGE_H, 0)
    assert len(t) == 56 and t[4:8] == bytes(4)
    return t


# --- hook code -------------------------------------------------------------------------------
HOOK_ASM = """
RESUME:
    lui t0, %hi(PATCHTAB)
    addiu t0, t0, %lo(PATCHTAB)
PLOOP:
    lw t1, 0(t0)
    beqz t1, PDONE
    lw t2, 4(t0)
    sw t2, 0(t1)
    b PLOOP
    addiu t0, t0, 8
PDONE:
    jal 0x800052E0              # osWritebackDCacheAll
    nop
    lui a0, 0x805F
    ori a0, a0, 0xB300
    jal 0x80005260              # osInvalICache(global_asm, 0x150000)
    lui a1, 0x0015
    lui v0, 0x8001              # displaced boot instructions 0x80000764..0x80000780
    addiu v0, v0, -0x233C
    lui t3, 0
    lui t4, 1
    lui t5, 1
    lui t9, 0xD
    lui t8, 0xD
    lui t6, 0xD
    j 0x80000784
    nop

KR_WIDTH:                       # func_806FD7A8(a0 style, a1 char)
    andi t0, a0, 0xFFFF
    li t1, 6
    bne t0, t1, W_ORIG
    andi t2, a1, 0xFF
    sltiu at, t2, LEAD0
    bnez at, W_ORIG
    nop
    sltiu at, t2, TRAIL0
    beqz at, W_TRAIL
    nop
    jr ra
    li v0, KR_ADV
W_TRAIL:
    sltiu at, t2, 0xFF
    beqz at, W_ORIG
    nop
    jr ra
    move v0, zero
W_ORIG:
    sll a2, a0, 0x10
    j 0x806FD7B0
    sra t6, a2, 0x10

KR_DRAW:                        # replaces jal printStyledText at 0x806A3B4C; s1 = node+0x10, string = 0x10(sp)
    lw t0, 0x10(sp)
    lbu t1, 0(t0)
    sltiu at, t1, LEAD0
    bnez at, D_PLAIN
    nop
    sltiu at, t1, TRAIL0
    beqz at, D_NONE
    nop
    lw t2, 0x90(s1)
    beqz t2, D_NONE
    nop
    lbu t3, 0x12(t2)
    sltiu at, t3, TRAIL0
    bnez at, D_NONE
    nop
    lui t4, %hi(KR_STR)
    addiu t4, t4, %lo(KR_STR)
    sb t1, 0(t4)
    sb t3, 1(t4)
    sb zero, 2(t4)
    sw t4, 0x10(sp)
D_PLAIN:
    j KR_PST
    nop
D_NONE:
    jr ra
    move v0, a0

KR_LOOKUP:                      # func_806FB914(a0 style, a1 &char) -> v0, *a1 = glyph index
    andi t0, a0, 0xFF
    li t1, 1
    beq t0, t1, LK_1
    li t1, 6
    beq t0, t1, LK_6
    nop
LK_ORIG:
    addiu sp, sp, -0xE0
    j 0x806FB91C
    sll t6, a0, 0x10
LK_1:
    lui t2, %hi(P1)
    b LK_GO
    addiu t2, t2, %lo(P1)
LK_6:
    lui t2, %hi(P6)
    addiu t2, t2, %lo(P6)
LK_GO:
    lbu t3, 0(a1)
    sltiu at, t3, LEAD0
    bnez at, LK_ORIG
    nop
    sll t6, t0, 2
    lui t5, 0x8075
    addu t5, t5, t6
    lw t4, 0(t2)
    sw t4, 0x4A18(t5)
    lw t4, 4(t2)
    sw t4, 0x49FC(t5)
    lui t9, %hi(VSTATE)
    addiu t9, t9, %lo(VSTATE)
    sltiu at, t3, TRAIL0
    beqz at, LK_TRAIL
    nop
    addiu t3, t3, -LEAD0
    sb t3, 3(t9)
LK_Z:
    lbu t3, 10(t2)
    addiu t3, t3, 1
    sb t3, 0(a1)
    jr ra
    move v0, zero
LK_TRAIL:
    sltiu at, t3, 0xFF
    beqz at, LK_ORIG
    nop
    lbu t4, 3(t9)
    li t5, NTRAIL
    multu t4, t5
    mflo t4
    addiu t3, t3, -TRAIL0
    addu t3, t3, t4
    lhu t4, 8(t2)
    sltu at, t3, t4
    beqz at, LK_Z
    nop
    lbu t4, 12(t2)
    divu t3, t4
    mflo t5
    mfhi t6
    lbu t7, 13(t2)
    multu t6, t7
    mflo t6
    lw t7, 0(t2)
    lbu t8, 10(t2)
    sll t4, t8, 2
    addu t7, t7, t4
    sh t6, 0(t7)
    lbu t4, 14(t2)
    sb t4, 2(t7)
    li v1, 0xFF
    lbu t4, 0(t9)
    bne t4, t0, LK_B
    lbu t6, 1(t9)
    move t4, zero
LK_F:
    beq t4, t6, LK_B
    addu t7, t9, t4
    lbu t7, 4(t7)
    beq t7, t5, LK_FOUND
    nop
    b LK_F
    addiu t4, t4, 1
LK_FOUND:
    move v1, t4
LK_B:                           # B[FC+1+j] = D (j < v) / D+1 (j >= v);  v = 0xFF -> D never drawn
    lw t7, 4(t2)
    lbu t4, 11(t2)
    addu t7, t7, t4
    move t4, zero
    addiu t6, t8, 1
LK_BL:
    sltu at, t4, v1
    beqz at, LK_BW
    move t5, t6
    move t5, t8
LK_BW:
    addu t3, t7, t4
    sb t5, 1(t3)
    addiu t4, t4, 1
    sltiu at, t4, VMAX
    bnez at, LK_BL
    nop
    sb t8, 0(a1)
    jr ra
    move v0, zero

KR_SCAN:                        # a0 string, a1 style, a2 P -> v0 = V, VSTATE.VMAP
    lui t9, %hi(VSTATE)
    addiu t9, t9, %lo(VSTATE)
    sb a1, 0(t9)
    move v0, zero
SC_L:
    lbu t0, 0(a0)
    beqz t0, SC_END
    addiu a0, a0, 1
    sltiu at, t0, LEAD0
    bnez at, SC_L
    sltiu at, t0, TRAIL0
    beqz at, SC_L
    nop
    lbu t1, 0(a0)
    sltiu at, t1, TRAIL0
    bnez at, SC_L
    sltiu at, t1, 0xFF
    beqz at, SC_L
    addiu a0, a0, 1
    addiu t0, t0, -LEAD0
    li t2, NTRAIL
    multu t0, t2
    mflo t0
    addiu t1, t1, -TRAIL0
    addu t0, t0, t1
    lhu t2, 8(a2)
    sltu at, t0, t2
    beqz at, SC_L
    lbu t2, 12(a2)
    divu t0, t2
    mflo t0
    move t3, zero
SC_F:
    beq t3, v0, SC_ADD
    addu t4, t9, t3
    lbu t4, 4(t4)
    beq t4, t0, SC_L
    nop
    b SC_F
    addiu t3, t3, 1
SC_ADD:
    sltiu at, v0, VMAX
    beqz at, SC_L
    addu t4, t9, v0
    sb t0, 4(t4)
    b SC_L
    addiu v0, v0, 1
SC_END:
    jr ra
    sb v0, 1(t9)

KR_SET:                         # t0 style, t2 P, v0 V: file_count += V, height override
    sll t3, t0, 1
    addu t3, t3, t0
    sll t3, t3, 1
    lui t4, 0x8075
    addu t4, t4, t3
    lbu t5, 11(t2)
    addu t5, t5, v0
    sb t5, 0x4A35(t4)
    lbu t5, 22(t2)
    beqz t5, KS_R
    nop
    sb t5, 0x4A36(t4)
KS_R:
    jr ra
    nop

KR_DONE:                        # v0 = dl: restore file_count/height, VCOUNT = 0, TLUT off if left on
    lui t9, %hi(VSTATE)
    addiu t9, t9, %lo(VSTATE)
    lbu t0, 0(t9)
    sb zero, 1(t9)
    li t1, 1
    beq t0, t1, KD_1
    nop
    lui t2, %hi(P6)
    b KD_GO
    addiu t2, t2, %lo(P6)
KD_1:
    lui t2, %hi(P1)
    addiu t2, t2, %lo(P1)
KD_GO:
    sll t3, t0, 1
    addu t3, t3, t0
    sll t3, t3, 1
    lui t4, 0x8075
    addu t4, t4, t3
    lbu t5, 11(t2)
    sb t5, 0x4A35(t4)
    lbu t5, 23(t2)
    sb t5, 0x4A36(t4)
    lbu t5, 2(t9)
    beqz t5, KD_R
    nop
    sb zero, 2(t9)
    lui t5, 0xE300
    ori t5, t5, 0x1001
    sw t5, 0(v0)
    sw zero, 4(v0)
    addiu v0, v0, 8
KD_R:
    jr ra
    nop

KR_PST:                         # printStyledText(a0 dl, a1 style, a2 x, a3 y, 0x10 string, 0x14 flags)
    andi t0, a1, 0x7F
    li t1, 1
    beq t0, t1, PS_1
    li t1, 6
    beq t0, t1, PS_6
    nop
PS_T:
    addiu sp, sp, -0xC8
    j 0x806FC538
    sw s0, 0x18(sp)
PS_1:
    lui t2, %hi(P1)
    b PS_GO
    addiu t2, t2, %lo(P1)
PS_6:
    lui t2, %hi(P6)
    addiu t2, t2, %lo(P6)
PS_GO:
    addiu sp, sp, -0x48
    sw ra, 0x44(sp)
    sw a0, 0x20(sp)
    sw a1, 0x24(sp)
    sw a2, 0x28(sp)
    sw a3, 0x2C(sp)
    sw t2, 0x30(sp)
    sw t0, 0x34(sp)
    lw a0, 0x58(sp)
    move a1, t0
    jal KR_SCAN
    move a2, t2
    lw t2, 0x30(sp)
    beqz v0, PS_PLAIN
    lw t0, 0x34(sp)
    jal KR_SET
    nop
    lw a0, 0x20(sp)
    lw a1, 0x24(sp)
    lw a2, 0x28(sp)
    lw a3, 0x2C(sp)
    lw t3, 0x58(sp)
    sw t3, 0x10(sp)
    lw t3, 0x5C(sp)
    jal PS_T
    sw t3, 0x14(sp)
    jal KR_DONE
    nop
    lw ra, 0x44(sp)
    jr ra
    addiu sp, sp, 0x48
PS_PLAIN:
    lw a0, 0x20(sp)
    lw a1, 0x24(sp)
    lw a2, 0x28(sp)
    lw a3, 0x2C(sp)
    lw ra, 0x44(sp)
    b PS_T
    addiu sp, sp, 0x48

KR_FX1:                         # func_806FCC88(a0 dl, a1 text: +4 string, +0xC style)
    lui t8, %hi(CC_T)
    b KR_FX
    addiu t8, t8, %lo(CC_T)
KR_FX2:                         # func_806FD094 (same arguments)
    lui t8, %hi(FD_T)
    addiu t8, t8, %lo(FD_T)
KR_FX:
    lbu t0, 0xC(a1)
    andi t0, t0, 0x7F
    li t1, 1
    beq t0, t1, FX_1
    li t1, 6
    beq t0, t1, FX_6
    nop
    jr t8
    nop
FX_1:
    lui t2, %hi(P1)
    b FX_GO
    addiu t2, t2, %lo(P1)
FX_6:
    lui t2, %hi(P6)
    addiu t2, t2, %lo(P6)
FX_GO:
    addiu sp, sp, -0x30
    sw ra, 0x2C(sp)
    sw a0, 0x20(sp)
    sw a1, 0x24(sp)
    sw t8, 0x28(sp)
    sw t2, 0x18(sp)
    sw t0, 0x1C(sp)
    lw a0, 4(a1)
    move a1, t0
    jal KR_SCAN
    move a2, t2
    lw t2, 0x18(sp)
    lw t0, 0x1C(sp)
    lw t8, 0x28(sp)
    lw a0, 0x20(sp)
    beqz v0, FX_PLAIN
    lw a1, 0x24(sp)
    jal KR_SET
    nop
    lw t8, 0x28(sp)
    lw a0, 0x20(sp)
    jalr t8
    lw a1, 0x24(sp)
    jal KR_DONE
    nop
    lw ra, 0x2C(sp)
    jr ra
    addiu sp, sp, 0x30
FX_PLAIN:
    lw ra, 0x2C(sp)
    jr t8
    addiu sp, sp, 0x30
CC_T:
    addiu sp, sp, -0xC8
    j 0x806FCC90
    sw s1, 0x3C(sp)
FD_T:
    addiu sp, sp, -0xC8
    j 0x806FD09C
    sw s1, 0x34(sp)

KR_VOICE:                       # cutscene command 13/20 (play sound) in func_80627F04: s0 = p0, 0x46(sp) = sound
    lh t1, 0x46(sp)
    lui t2, %hi(VOICES)
    addiu t2, t2, %lo(VOICES)
VO_L:
    lhu t3, 0(t2)
    ori t4, zero, 0xFFFF
    beq t3, t4, VO_GO
    nop
    bne t3, t1, VO_L
    addiu t2, t2, 8
    lui t5, 0x8080              # a new voiced line: drop the caption overlays still on screen
    lh t6, -0x3C10(t5)          # actor_count  0x807FC3F0
    addiu t7, t5, -0x4010       # actor_list   0x807FBFF0
VC_L:
    blez t6, VC_D
    nop
    lw t8, 0(t7)
    addiu t7, t7, 4
    beqz t8, VC_L
    addiu t6, t6, -1
    lw t9, 0x58(t8)             # actor type
    li t3, 0xE8                 # ACTOR_TEXT_OVERLAY
    bne t9, t3, VC_L
    nop
    lh t9, 0xEE(t8)             # 0 = plain popup (not the animated HUD text)
    bnez t9, VC_L
    nop
    li t9, 1
    sb t9, 0x154(t8)            # control_state 1
    li t9, 3
    b VC_L
    sb t9, 0x155(t8)            # progress 3 = free + despawn on its next update
VC_D:
    lbu a0, -6(t2)              # caption = text file 01 box
    lhu a1, -4(t2)              # frames
    jal 0x80627C5C              # func_80627C5C(text, frames, colour)
    lbu a2, -5(t2)
VO_GO:
    lui t0, 0x8080
    addiu t0, t0, -0x44B4
    bltz s0, VO_NEG
    lw t4, 0x44(sp)
    j 0x8062898C
    nop
VO_NEG:
    j 0x80628AA4
    nop

KR_TRIG:                        # func_80627F04 entry (cutscene command 13): a voiced line started by an actor animation,
    andi t1, a0, 0xFF           # not by a sound command -> caption on the animation command itself.
    ori t2, zero, 4             # Helm_IntroStory cutscene 12 frame 255: sub 4, actor 7 (Klump) animation 0x33
    bne t1, t2, TR_GO           # = «Oh, your excellency, we've already taken care of business» (sound 843)
    lui t3, 0x0007
    ori t3, t3, 0x0002
    bne a1, t3, TR_GO
    lui t3, 0x0033
    bne a2, t3, TR_GO
    lui t3, 0x8077
    lw t3, -0x5F58(t3)          # current_map 0x8076A0A8
    ori t2, zero, 0x98
    bne t3, t2, TR_GO
    nop
    addiu sp, sp, -0x20
    sw ra, 0x10(sp)
    sw a0, 0x14(sp)
    sw a1, 0x18(sp)
    sw a2, 0x1C(sp)
    jal VO_SHOW
    ori a0, zero, 843
    lw ra, 0x10(sp)
    lw a0, 0x14(sp)
    lw a1, 0x18(sp)
    lw a2, 0x1C(sp)
    addiu sp, sp, 0x20
TR_GO:
    addiu sp, sp, -0xA8         # the two entry instructions the hook replaced
    j 0x80627F0C
    lui t0, 0x8080

VO_SHOW:                        # a0 = sound id: caption from VOICES (same as KR_VOICE)
    addiu sp, sp, -0x18
    sw ra, 0x14(sp)
    lui t2, %hi(VOICES)
    addiu t2, t2, %lo(VOICES)
VS_L:
    lhu t3, 0(t2)
    ori t4, zero, 0xFFFF
    beq t3, t4, VS_END
    nop
    bne t3, a0, VS_L
    addiu t2, t2, 8
    lui t5, 0x8080
    lh t6, -0x3C10(t5)          # actor_count  0x807FC3F0
    addiu t7, t5, -0x4010       # actor_list   0x807FBFF0
VS_K:
    blez t6, VS_D
    nop
    lw t8, 0(t7)
    addiu t7, t7, 4
    beqz t8, VS_K
    addiu t6, t6, -1
    lw t9, 0x58(t8)
    li t3, 0xE8
    bne t9, t3, VS_K
    nop
    lh t9, 0xEE(t8)
    bnez t9, VS_K
    nop
    li t9, 1
    sb t9, 0x154(t8)
    li t9, 3
    b VS_K
    sb t9, 0x155(t8)
VS_D:
    lbu a0, -6(t2)
    lhu a1, -4(t2)
    jal 0x80627C5C
    lbu a2, -5(t2)
VS_END:
    lw ra, 0x14(sp)
    jr ra
    addiu sp, sp, 0x18

KR_TEX:                         # func_806FBEF0(a0 dl, a1 style, a2 page): load one font page
    andi t0, a1, 0xFF
    li t1, 1
    beq t0, t1, TX_1
    li t1, 6
    beq t0, t1, TX_6
    nop
TX_ORIG:
    lui t9, %hi(VSTATE)
    addiu t9, t9, %lo(VSTATE)
    lbu t1, 2(t9)
    beqz t1, TX_T
    nop
    sb zero, 2(t9)
    lui t1, 0xE300
    ori t1, t1, 0x1001
    sw t1, 0(a0)
    sw zero, 4(a0)
    addiu a0, a0, 8
TX_T:
    addiu sp, sp, -0x20
    j 0x806FBEF8
    sw a1, 0x24(sp)
TX_1:
    lui t2, %hi(P1)
    b TX_GO
    addiu t2, t2, %lo(P1)
TX_6:
    lui t2, %hi(P6)
    addiu t2, t2, %lo(P6)
TX_GO:
    lbu t1, 11(t2)
    slt at, t1, a2
    beqz at, TX_ORIG
    nop
    subu t3, a2, t1
    addiu t3, t3, -1
    lui t9, %hi(VSTATE)
    addiu t9, t9, %lo(VSTATE)
    addu t4, t9, t3
    lbu t4, 4(t4)
    lhu t5, 20(t2)
    multu t4, t5
    mflo t4
    lw t5, 16(t2)
    addu t4, t4, t5
    lui t5, 0x1FFF
    ori t5, t5, 0xFFFF
    and t4, t4, t5
    lbu t5, 15(t2)
    beqz t5, TX_IA
    nop
    lui t6, %hi(TPL_CI)
    addiu t6, t6, %lo(TPL_CI)
    li t7, 28
TX_C1:
    lw t8, 0(t6)
    sw t8, 0(a0)
    addiu t6, t6, 4
    addiu t7, t7, -1
    bnez t7, TX_C1
    addiu a0, a0, 4
    sw t4, -52(a0)
    li t8, 1
    sb t8, 2(t9)
    jr ra
    move v0, a0
TX_IA:
    lbu t1, 2(t9)
    beqz t1, TX_I0
    nop
    sb zero, 2(t9)
    lui t1, 0xE300
    ori t1, t1, 0x1001
    sw t1, 0(a0)
    sw zero, 4(a0)
    addiu a0, a0, 8
TX_I0:
    lui t6, %hi(TPL_IA)
    addiu t6, t6, %lo(TPL_IA)
    li t7, 14
TX_I1:
    lw t8, 0(t6)
    sw t8, 0(a0)
    addiu t6, t6, 4
    addiu t7, t7, -1
    bnez t7, TX_I1
    addiu a0, a0, 4
    sw t4, -52(a0)
    jr ra
    move v0, a0
"""

DATA_SYMS = ('PATCHTAB', 'KR_STR', 'VSTATE', 'P1', 'P6', 'TPL_CI', 'TPL_IA', 'VOICES')
HOOKS = [  # (address, target label, kind)  j + nop at a function entry, or a jal replacing a call
    (0x806FD7A8, 'KR_WIDTH', 'j'), (0x806A3B4C, 'KR_DRAW', 'jal'), (0x806FB914, 'KR_LOOKUP', 'j'),
    (0x806FBEF0, 'KR_TEX', 'j'), (0x806FC530, 'KR_PST', 'j'), (0x806FCC88, 'KR_FX1', 'j'),
    (0x806FD094, 'KR_FX2', 'j'), (0x80628984, 'KR_VOICE', 'j'), (0x80627F04, 'KR_TRIG', 'j'),
]


def hook_asm():
    t = HOOK_ASM
    for k, v in (('PAGE_BYTES', PAGE_BYTES), ('PER_PAGE', PER_PAGE), ('LEAD0', LEAD0), ('TRAIL0', TRAIL0),
                 ('NTRAIL', NTRAIL), ('KR_ADV', KR_ADV), ('VMAX', VMAX)):
        t = t.replace(k, str(v))
    return t.splitlines()


def gdata(rom):
    """global_asm .data as it sits in RAM (VRAM 0x80744460)."""
    d = zlib.decompressobj(-15).decompress(bytes(rom[GDATA_ROM + 10:GDATA_ROM + 0x40000]))
    return lambda adr, n: d[adr - GDATA_VRAM:adr - GDATA_VRAM + n]


def style_tables(rd, style, nchars):
    """our extended copies: table = original entries + D (dynamic glyph) + Z (lead byte, width 0);
    bounds = original FC+1 bytes + VMAX for the virtual pages."""
    tab_adr = struct.unpack('>I', rd(TABS + 4 * style, 4))[0]
    bnd_adr = struct.unpack('>I', rd(BNDS + 4 * style, 4))[0]
    fc = rd(DESC + 6 * style + 1, 1)[0]
    tab = bytearray(rd(tab_adr, 4 * nchars)) + bytes(8)
    bnd = bytearray(rd(bnd_adr, fc + 1))
    assert bnd[fc] == nchars, (style, list(bnd))
    bnd += bytes((nchars,)) * VMAX
    return tab, bnd, fc, rd(DESC + 6 * style + 2, 1)[0]


def build_blob(rom, pages6, n6, pages1, n1, extra_patches=(), voices=()):
    rd = gdata(rom)
    assert rd(0x80754A64, 57) == b"ABCDEFGH,.rIJKLMNO:PQRSgTUVWXYlZ!-'?q%&bz0123456789enwsco"
    tab1, bnd1, fc1, h1 = style_tables(rd, 1, S1_CHARS)
    tab6, bnd6, fc6, h6 = style_tables(rd, 6, S6_CHARS)
    asm = hook_asm()
    size = len(Asm(KR_RAM, {k: 0 for k in DATA_SYMS}).assemble(asm))
    # data layout after the code
    lay, pos = {}, KR_RAM + size

    def put(name, n, align=4):
        nonlocal pos
        pos = (pos + align - 1) & ~(align - 1)
        lay[name] = pos
        pos += n
    patches = [(0x80610510, 0x3C0D0000 | (KR_RAM >> 16)),          # lui t5, hi(KR_RAM)   (heap end)
               (0x80610518, 0x35AD0000 | (KR_RAM & 0xFFFF))]       # ori t5, t5, lo(KR_RAM)
    patches += list(extra_patches)                                  # .data strings (kong names)
    npatch = len(patches) + sum(2 if k == 'j' else 1 for _, _, k in HOOKS)
    put('KR_STR', 4)
    put('PATCHTAB', 8 * (npatch + 1))
    put('VSTATE', 4 + VMAX)
    put('P1', 24)
    put('P6', 24)
    put('TAB1', len(tab1))
    put('TAB6', len(tab6))
    put('BND1', len(bnd1))
    put('BND6', len(bnd6))
    put('TLUT', 32, 8)
    put('TPL_CI', 112, 8)
    put('TPL_IA', 56, 8)
    put('VOICES', 8 * len(voices) + 8)
    put('PAGES6', len(pages6), 16)
    put('PAGES1', len(pages1), 16)
    a = Asm(KR_RAM, {k: lay[k] for k in DATA_SYMS})
    code = a.assemble(asm)
    assert len(code) == size
    s = dict(a.syms, **lay)
    j = lambda t: (2 << 26) | ((t >> 2) & 0x3FFFFFF)
    jal = lambda t: (3 << 26) | ((t >> 2) & 0x3FFFFFF)
    for adr, lab, kind in HOOKS:
        if kind == 'j':
            patches += [(adr, j(s[lab])), (adr + 4, 0)]
        else:
            patches.append((adr, jal(s[lab])))
    assert len(patches) == npatch

    def pblock(tab, bnd, ng, d, fc, per, cw, wd, kind, pg, pbytes, hset, horig):
        return struct.pack('>IIHBBBBBBIHBB', tab, bnd, ng, d, fc, per, cw, wd, kind, pg, pbytes, hset, horig)
    phys = lambda v: v & 0x1FFFFFFF
    blob = bytearray(pos - KR_RAM)
    w = lambda name, b: blob.__setitem__(slice(lay[name] - KR_RAM, lay[name] - KR_RAM + len(b)), b)
    blob[:size] = code
    w('KR_STR', b'A\0\0\0')
    w('PATCHTAB', b''.join(struct.pack('>II', adr, v) for adr, v in patches) + bytes(8))
    w('P1', pblock(lay['TAB1'], lay['BND1'], n1, S1_CHARS, fc1, s1font.PER_PAGE, s1font.CELL_W, s1font.QUAD_W,
                   1, lay['PAGES1'], s1font.PAGE_BYTES, 0, h1))
    w('P6', pblock(lay['TAB6'], lay['BND6'], n6, S6_CHARS, fc6, PER_PAGE, CELL, KR_ADV,
                   0, lay['PAGES6'], PAGE_BYTES, 13, h6))
    w('TAB1', tab1)
    w('TAB6', tab6)
    w('BND1', bnd1)
    w('BND6', bnd6)
    w('TLUT', s1font.tlut())
    w('TPL_CI', tpl_ci(phys(lay['TLUT'])))
    w('TPL_IA', tpl_ia())
    w('VOICES', b''.join(struct.pack('>HBBHH', sid, box, col, fr, 0) for sid, box, col, fr in voices) + b'\xff\xff' + bytes(6))
    w('PAGES6', pages6)
    w('PAGES1', pages1)
    blob += bytes(-len(blob) % 16)
    assert len(blob) <= RESERVE, hex(len(blob))
    return bytes(blob), s


def boot_hook(syms, blob_len):
    b = Asm(BOOT_HOOK).assemble([
        f'lui a0, {BLOB_ROM >> 16:#x}',
        f'lui a1, {hi(BLOB_ROM + blob_len)}',
        f'addiu a1, a1, {lo(BLOB_ROM + blob_len)}',
        f'lui a2, {hi(KR_RAM)}',
        'jal 0x80000450',
        f'addiu a2, a2, {lo(KR_RAM)}',
        f'j {syms["RESUME"]:#x}',
        'nop'])
    assert len(b) == 32 and BLOB_ROM & 0xFFFF == 0
    return b


def s1_text(loc, ko):
    """the part of a row the menu font (style 1) may draw: whole row of a menu file, the speaker name of a
    cutscene caption (file 01 'NAME:'), short one-piece popups of file 00."""
    f = int(loc.split(':')[0], 16)
    if f in S1_FILES:
        return ko
    if f == 0x01 and ':' in ko:
        return ko.split(':')[0]
    if f == 0x00 and '{' not in ko and len(ko) <= 16:
        return ko
    return ''


CODE_TSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'my files', 'tsv', 'dk_code.tsv')


def read_code_names(path=CODE_TSV):
    """translated strings inside global_asm .data (kong names ...) -> [(id, RAM address, src, ko, slot)].
    checked like the text rows: glyphs, and the encoded name + NUL must fit the slot (column 칸)."""
    out, bad = [], []
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f, delimiter='\t', quoting=csv.QUOTE_NONE):
            ko = normalize((r.get('번역') or '').strip())
            if not ko:
                continue
            seg, off = r['위치'].split(':')
            if seg != 'global_asm':
                bad.append(f"{r['ID']}: {seg} 는 아직 적재 안 함")
                continue
            odd = sorted({c for c in ko if c not in ALLOWED and not '가' <= c <= '힣'})
            if odd:
                bad.append(f"{r['ID']}: 글꼴에 없는 글자 {odd}")
            out.append((r['ID'], GDATA_VRAM + int(off, 16), r['원문'], ko, int(r['칸'])))
    if bad:
        print('\n'.join(bad))
        sys.exit(f'코드 문자열 검사 실패 {len(bad)}건, 빌드 안 함')
    return out


def code_patches(names, cmap, rd):
    """word writes for RESUME's patch table: name + NUL, zero-filled over the old string too."""
    pts = []
    for rid, adr, src, ko, slot in names:
        old = rd(adr, slot)
        assert old.split(b'\0')[0] == src.encode(), (rid, old)
        new = encode(ko, cmap) + b'\0'
        if len(new) > slot:
            sys.exit(f'{rid}: {ko} {len(new)} B > 칸 {slot} B, 빌드 안 함')
        n = (max(len(new), len(src) + 1) + 3) & ~3
        assert adr % 4 == 0 and n <= slot and not any(old[len(src):n]), rid
        buf = new + bytes(n - len(new))
        pts += [(adr + i, struct.unpack('>I', buf[i:i + 4])[0]) for i in range(0, n, 4)]
    return pts


VOICE_TSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'work', 'text', 'dk_voice.tsv')
VOICE_FILE = 0x01                  # captions go to the cutscene text file (func_80627C5C reads file 01)
FPS = 30


def read_voices(path=VOICE_TSV):
    """voiced cutscene lines -> [(sound id, caption, colour, frames)]; caption shown by func_80627C5C"""
    out, bad = [], []
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f, delimiter='\t', quoting=csv.QUOTE_NONE):
            ko = normalize((r.get('번역') or '').strip())
            if not ko:
                continue
            # '：' (U+FF1A) = a glyph, so func_80627C5C does not split off a speaker label at ':'
            assert ':' not in ko, f"voice {r['소리번호']}: 화자는 '：'(전각)으로 — ':' 는 이름표로 떨어져 나감"
            odd = sorted({c for c in ko if c not in ALLOWED and c != '：' and not '가' <= c <= '힣'})
            if odd:
                bad.append(f"voice {r['소리번호']}: 글꼴에 없는 글자 {odd}")
            out.append((int(r['소리번호']), ko, int(r['색']), int(float(r['길이(초)']) * FPS + 15)))
    if bad:
        print('\n'.join(bad))
        sys.exit(f'음성 자막 검사 실패 {len(bad)}건, 빌드 안 함')
    return out


def order_glyphs(tr, extra=()):
    """glyph ids: menu-font glyphs first in order of appearance (a string's glyphs share few pages),
    then the rest by frequency (common ones cluster on the first dialogue pages).
    extra = strings drawn by both fonts (kong names)."""
    hang = lambda t: [c for c in t if ord(c) >= 0x80]
    s1 = []
    for t in extra:
        for c in hang(t):
            if c not in s1:
                s1.append(c)
    for loc in sorted(tr, key=lambda l: (int(l.split(':')[0], 16), int(l.split(':')[1]))):
        for c in hang(s1_text(loc, tr[loc][1])):
            if c not in s1:
                s1.append(c)
    freq = collections.Counter(c for _, k in tr.values() for c in hang(k))
    freq.update(c for t in extra for c in hang(t))
    rest = sorted((c for c in freq if c not in s1), key=lambda c: (-freq[c], c))
    return s1 + rest, len(s1)


def main():
    *paths, out = sys.argv[1:]
    rom = bytearray(dkrom.load_rom())
    orig_boot = bytes(rom[BOOT_HOOK + BOOT_ROM:BOOT_HOOK + BOOT_ROM + 32])
    assert orig_boot[:4] == bytes.fromhex('3c028001'), orig_boot.hex()
    tr = read_tsv(paths)
    tr = check_translations(tr)            # DK64: no squeeze (see check_translations)
    names = read_code_names()
    voices = read_voices()
    chars, n1 = order_glyphs(tr, [ko for _, _, _, ko, _ in names] + [v[1].split(':')[0] for v in voices if ':' in v[1]])
    for v in voices:                                   # caption body glyphs (dialogue font) must exist too
        for c in v[1]:
            if ord(c) >= 0x80 and c not in chars:
                chars.append(c)
    assert len(chars) <= NLEAD * NTRAIL
    cmap = {ch: i for i, ch in enumerate(chars)}

    # text files
    t12 = dkrom.table(rom, dkrom.TEXT)
    by_file = {}
    for loc, (src, ko) in tr.items():
        f, b = loc.split(':')
        by_file.setdefault(int(f, 16), {})[int(b)] = (src, ko)
    files = []
    usizes = {}
    for j in range(len(t12)):
        a, e, flag = t12[j]
        if j not in by_file:
            files.append(bytes(rom[a:e]))
            continue
        d = dkrom.file(rom, dkrom.TEXT, j)
        boxes, data, _ = dkrom.parse_text(d)
        new = {}
        for bi, (src, ko) in by_file[j].items():
            parts = split_box(ko)
            new[bi] = [(k, [encode(p, cmap) for p in v]) if k == 'T' else (k, v) for k, v in parts]
        extra = [encode(v[1], cmap) for v in voices] if j == VOICE_FILE else []
        if extra:
            vbox = len(boxes)
        nd = build_text(boxes, data, new, extra)
        usizes[j] = len(nd)
        z = gzip.compress(nd, compresslevel=9, mtime=0)
        files.append(z)
        print(f'text file {j:02X}: {len(by_file[j])} boxes, {len(d)} -> {len(nd)} B')

    pages6 = render_pages(chars)
    pages1 = b''.join(s1font.pages(chars[:n1]))
    cpatch = code_patches(names, cmap, gdata(rom))
    print(f'code names: {len(names)} ({len(cpatch)} words)')
    vt = [(sid, vbox + k, col, fr) for k, (sid, _, col, fr) in enumerate(voices)]
    print(f'voice captions: {len(vt)} (text file {VOICE_FILE:02X} boxes {vbox}..)' if vt else 'voice captions: 0')
    blob, syms = build_blob(rom, pages6, len(chars), pages1, n1, cpatch, vt)
    print(f'glyphs: dialogue {len(chars)} ({len(pages6) // PAGE_BYTES} pages) / menu font {n1} '
          f'({len(pages1) // s1font.PAGE_BYTES} pages)')
    # ★the game sizes a table's entry array as (entry[0] - table start) (func_8066B5F4) -> the entry list
    #  must move together with the files: [entries (n+1)][files...], master[12] -> new table start.
    text_rom = (BLOB_ROM + len(blob) + 0xFFF) & ~0xFFF
    base_old = dkrom.PT + struct.unpack_from('>I', rom, dkrom.PT + 4 * dkrom.TEXT)[0]
    flags = [struct.unpack_from('>I', rom, base_old + 4 * k)[0] & 0x80000000 for k in range(len(files) + 1)]
    assert not any(flags)
    head = 4 * (len(files) + 1)
    region = bytearray(head)
    offs = []
    for z in files:
        offs.append(text_rom + len(region))
        region += z
        region += bytes(-len(region) % 4)
    offs.append(text_rom + len(region))
    for k, o in enumerate(offs):
        struct.pack_into('>I', region, 4 * k, o - dkrom.PT)
    end = text_rom + len(region)
    size = (end + 0x3FFFFF) & ~0x3FFFFF
    rom += b'\xFF' * (size - len(rom))
    rom[BLOB_ROM:BLOB_ROM + len(blob)] = blob
    rom[text_rom:end] = region
    struct.pack_into('>I', rom, dkrom.PT + 4 * dkrom.TEXT, text_rom - dkrom.PT)
    # uncompressed sizes (table 26 file 12, raw)
    a26, e26, _ = dkrom.table(rom, 26)[dkrom.TEXT]
    for j, n in usizes.items():
        struct.pack_into('>I', rom, a26 + 4 * j, (n + 1) & ~1)
    # boot hook
    rom[BOOT_HOOK + BOOT_ROM:BOOT_HOOK + BOOT_ROM + 32] = boot_hook(syms, len(blob))
    # verify text round trip through the new table
    for j in by_file:
        d = dkrom.file(rom, dkrom.TEXT, j)
        dkrom.parse_text(d)
    n64crc.fix(rom, 6105)
    open(out, 'wb').write(rom)
    import hashlib
    print(f'glyphs {len(chars)}  blob {len(blob)} B @ROM {BLOB_ROM:#x} -> RAM {KR_RAM:#x}  text @ {text_rom:#x}  rom {size:#x}')
    print(out, hashlib.md5(rom).hexdigest())


if __name__ == '__main__':
    main()
