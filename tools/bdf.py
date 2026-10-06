"""BDF 비트맵 폰트 파서.

TTF 래스터화와 달리 픽셀이 원본 그대로다. 갈무리 배포본에 BDF 가 함께 들어 있다.
"""
import os
import re


class BdfGlyph:
    __slots__ = ('code', 'name', 'dwidth', 'bbx', 'rows')

    def __init__(self, code, name, dwidth, bbx, rows):
        self.code, self.name = code, name
        self.dwidth = dwidth              # (dx, dy) 진행폭
        self.bbx = bbx                    # (w, h, xoff, yoff)  BDF 좌표(원점 = baseline 왼쪽)
        self.rows = rows                  # [int] 각 행의 비트, 상단부터

    def bitmap(self):
        """[[0/1]] 로 펼친다."""
        w, h, _x, _y = self.bbx
        out = []
        pad = (w + 7) // 8 * 8
        for r in self.rows:
            out.append([(r >> (pad - 1 - i)) & 1 for i in range(w)])
        return out

    def __repr__(self):
        return '<BdfGlyph U+%04X %dx%d off=(%d,%d) dw=%d>' % (
            self.code, self.bbx[0], self.bbx[1], self.bbx[2], self.bbx[3], self.dwidth[0])


class BdfFont:
    def __init__(self, path):
        self.path = path
        self.props = {}
        self.glyphs = {}
        self._parse()

    def _parse(self):
        with open(self.path, 'r', encoding='latin1') as f:
            cur = None
            code = None
            name = None
            dwidth = None
            bbx = None
            rows = None
            inbits = False
            for line in f:
                line = line.rstrip('\n').rstrip('\r')
                if inbits:
                    if line.startswith('ENDCHAR'):
                        inbits = False
                        if code is not None and bbx:
                            self.glyphs[code] = BdfGlyph(code, name, dwidth, bbx, rows)
                        code = name = dwidth = bbx = rows = None
                    else:
                        rows.append(int(line.strip() or '0', 16))
                    continue
                if line.startswith('STARTCHAR'):
                    name = line.split(None, 1)[1] if ' ' in line else ''
                elif line.startswith('ENCODING'):
                    code = int(line.split()[1])
                elif line.startswith('DWIDTH'):
                    p = line.split()
                    dwidth = (int(p[1]), int(p[2]))
                elif line.startswith('BBX'):
                    p = line.split()
                    bbx = (int(p[1]), int(p[2]), int(p[3]), int(p[4]))
                elif line.startswith('BITMAP'):
                    inbits = True
                    rows = []
                elif line.startswith('FONTBOUNDINGBOX'):
                    p = line.split()
                    self.props['fbbx'] = tuple(int(x) for x in p[1:5])
                elif line.startswith('PIXEL_SIZE'):
                    self.props['pixel_size'] = int(line.split()[1])
                elif line.startswith('FONT_ASCENT'):
                    self.props['ascent'] = int(line.split()[1])
                elif line.startswith('FONT_DESCENT'):
                    self.props['descent'] = int(line.split()[1])

    def has(self, cp):
        return cp in self.glyphs

    def count_in(self, lo, hi):
        return sum(1 for c in self.glyphs if lo <= c <= hi)


BLOCKS = [
    ('한글자모 U+1100-11FF', 0x1100, 0x11FF),
    ('호환자모 U+3130-318F', 0x3130, 0x318F),
    ('한글음절 U+AC00-D7A3', 0xAC00, 0xD7A3),
    ('ASCII    U+0020-007E', 0x20, 0x7E),
]


def summarize(path):
    f = BdfFont(path)
    name = os.path.basename(path)
    print('%-34s glyphs=%-6d pixel=%s fbbx=%s asc/desc=%s/%s'
          % (name, len(f.glyphs), f.props.get('pixel_size'), f.props.get('fbbx'),
             f.props.get('ascent'), f.props.get('descent')))
    for lab, lo, hi in BLOCKS:
        n = f.count_in(lo, hi)
        if n:
            print('    %-22s %5d / %d' % (lab, n, hi - lo + 1))
    return f


if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        summarize(p)
        print()
