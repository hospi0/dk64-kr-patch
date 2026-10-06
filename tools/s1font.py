"""Style-1 (menu font) Korean glyphs: yellow->green gradient, dark outline, drop shadow — like the
original RGBA16 76x24 pages (table 14 files 6..18).  Output = CI4 pages (PAGE_W x 24) + 16-colour TLUT.

colours sampled from the original pages (5-bit RGB per row):
  fill rows 3-4 orange, 5-12 yellow, 13-17 green · outline (17,0,10) top -> (3,0,0) bottom · shadow (2,2,2)
"""
from PIL import Image, ImageDraw, ImageFont

FONT = r'C:\claude\utils\font\nanum-gothic\NanumGothicExtraBold.ttf'
SIZE = 17                   # px -> body about rows 2..18, width <= 16
CELL_W, H = 22, 24
PAGE_W = 160                # 4b LoadBlock: 10 words/row, dxt error stays < 1 word over 24 rows
PER_PAGE = PAGE_W // CELL_W  # 7
QUAD_W = 20                 # drawn width of a glyph (table entry width); advance = 1 (lead) + 20 + 1 = 22
PAGE_BYTES = PAGE_W * H // 2
TOP = 2                     # first body row

# palette: 0 transparent, 1..10 fill gradient, 11..13 outline, 14 shadow
FILL = [(31, 14, 0), (31, 21, 0), (31, 25, 0), (31, 31, 0), (31, 31, 4), (31, 31, 2),
        (29, 31, 0), (24, 31, 0), (19, 31, 0), (17, 31, 0)]
OUTL = [(17, 0, 10), (10, 0, 5), (3, 0, 0)]
SHADOW = (2, 2, 2)
PAL = [None] + FILL + OUTL + [SHADOW, SHADOW]


def rgba5551(c):
    if c is None:
        return 0
    r, g, b = c
    return (r << 11) | (g << 6) | (b << 1) | 1


def tlut():
    return b''.join(rgba5551(c).to_bytes(2, 'big') for c in PAL)


def fill_index(y):
    # body rows TOP..TOP+15 -> gradient 1..10
    t = min(max(y - TOP, 0), 15) / 15
    return 1 + min(9, int(t * 10))


def outline_index(y):
    return 11 if y < 8 else 12 if y < 15 else 13


def glyph(ch, font=None):
    """-> list of rows (CELL_W) of palette indices"""
    font = font or ImageFont.truetype(FONT, SIZE)
    im = Image.new('L', (CELL_W, H), 0)
    d = ImageDraw.Draw(im)
    l, t, r, b = d.textbbox((0, 0), ch, font=font)
    x = 1 + max(0, (16 - (r - l)) // 2) - l          # outline 1 left; embolden+outline+shadow 3 right -> x < 20
    y = TOP - t + max(0, (16 - (b - t)) // 2)
    d.text((x, y), ch, font=font, fill=255)
    px = im.load()
    body = {(i, j) for j in range(H) for i in range(CELL_W) if px[i, j] >= 110}
    body |= {(i + 1, j) for i, j in body if i + 1 < CELL_W}          # embolden: strokes +1 px
    dil = {(i + di, j + dj) for i, j in body for di in (-1, 0, 1) for dj in (-1, 0, 1)}
    sh = {(i + 1, j + 2) for i, j in dil} | {(i + 1, j + 3) for i, j in dil}
    out = [[0] * CELL_W for _ in range(H)]
    for j in range(H):
        for i in range(CELL_W):
            p = (i, j)
            if p in body:
                out[j][i] = fill_index(j)
            elif p in dil:
                out[j][i] = outline_index(j)
            elif p in sh:
                out[j][i] = 14
    for row in out:                                                  # the quad shows x < QUAD_W only
        row[QUAD_W:] = [0] * (CELL_W - QUAD_W)
    return out


def pages(chars):
    """chars -> list of CI4 page bytes (PAGE_W x H, 2 px per byte, high nibble first)"""
    font = ImageFont.truetype(FONT, SIZE)
    res = []
    for p0 in range(0, len(chars), PER_PAGE):
        grid = [[0] * PAGE_W for _ in range(H)]
        for k, ch in enumerate(chars[p0:p0 + PER_PAGE]):
            g = glyph(ch, font)
            for j in range(H):
                grid[j][k * CELL_W:(k + 1) * CELL_W] = g[j]
        res.append(bytes((grid[j][i] << 4) | grid[j][i + 1] for j in range(H) for i in range(0, PAGE_W, 2)))
    return res


def preview(text, scale=3):
    """render a string (Hangul + spaces) the way the game would, as RGBA image"""
    font = ImageFont.truetype(FONT, SIZE)
    w = sum(7 if c == ' ' else QUAD_W + 2 for c in text) + 4
    im = Image.new('RGBA', (w, H), (40, 40, 90, 255))
    x = 2
    for c in text:
        if c == ' ':
            x += 7
            continue
        g = glyph(c, font)
        for j in range(H):
            for i in range(CELL_W):
                v = g[j][i]
                if v:
                    r, gg, b = PAL[v]
                    if 0 <= x + i < w:
                        im.putpixel((x + i, j), (r * 255 // 31, gg * 255 // 31, b * 255 // 31, 255))
        x += QUAD_W + 2
    return im.resize((im.width * scale, H * scale), Image.NEAREST)
