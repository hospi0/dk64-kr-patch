"""Donkey Kong 64 (USA) sound banks -> WAV.

usage: python tools/dkaudio.py <out dir> [A|B ...]

Banks (boot gOverlayTable2, loaded by func_80600D50 with alBnkfNew(ctl, tbl)):
  A: ctl ROM 0x188AF20..0x1897860 (compressed), tbl 0x1897860..0x1A97280
  B: ctl ROM 0x1A97280..0x1ABCBF0 (compressed), tbl 0x1ABCBF0..0x1FED020
ctl compression = func_dk64_boot_80002790 (via func_8060B140 mode 2, arg 0xD): bit-level LZSS, MSB first;
  flag 1 -> 8-bit literal; flag 0 -> 13-bit position (0 = end) + 3-bit length (copy length+3);
  window 8 KB, write position starts at 1.
ctl = libultra ALBankFile (offsets from the file start); samples = VADPCM (type 0) or raw 16-bit (type 1).
"""
import os, sys, struct, wave

sys.path.insert(0, os.path.dirname(__file__))
import dkrom

BANKS = {'A': (0x188AF20, 0x1897860, 0x1897860), 'B': (0x1A97280, 0x1ABCBF0, 0x1ABCBF0)}


def lzss(d, ei=13):
    pos, mask, byte = 0, 0x80, 0
    n = 1 << ei
    win = bytearray(n)
    r = 1
    out = bytearray()

    def bits(cnt):
        nonlocal pos, mask, byte
        v = 0
        for _ in range(cnt):
            if mask == 0x80:
                byte = d[pos]
                pos += 1
            v = (v << 1) | (1 if byte & mask else 0)
            mask >>= 1
            if not mask:
                mask = 0x80
        return v
    while True:
        if bits(1):
            c = bits(8)
            out.append(c)
            win[r] = c
            r = (r + 1) & (n - 1)
        else:
            i = bits(ei)
            if i == 0:
                break
            j = bits(15 - ei + 1)
            for k in range(j + 3):
                c = win[(i + k) & (n - 1)]
                out.append(c)
                win[r] = c
                r = (r + 1) & (n - 1)
    return bytes(out)


def u8(d, o): return d[o]
def s16(d, o): return struct.unpack_from('>h', d, o)[0]
def u32(d, o): return struct.unpack_from('>I', d, o)[0]
def s32(d, o): return struct.unpack_from('>i', d, o)[0]


def parse_bank(ctl):
    """-> sample rate, list of (inst, sound, wavetable offset, keyBase, detune)"""
    assert ctl[:2] == b'B1', ctl[:4]
    nb = s16(ctl, 2)
    res = []
    for b in range(nb):
        bo = u32(ctl, 4 + 4 * b)
        ninst = s16(ctl, bo)
        rate = s32(ctl, bo + 4)
        perc = u32(ctl, bo + 8)
        insts = [u32(ctl, bo + 12 + 4 * i) for i in range(ninst)]
        if perc:
            insts.append(perc)
        for ii, io in enumerate(insts):
            if not io:
                continue
            nsnd = s16(ctl, io + 14)
            for si in range(nsnd):
                so = u32(ctl, io + 16 + 4 * si)
                km = u32(ctl, so + 4)
                wt = u32(ctl, so + 8)
                res.append((b, ii, si, wt, ctl[km + 4], struct.unpack_from('b', ctl, km + 5)[0]))
    return rate, res


def coef_table(book, order, npred):
    t = []
    for i in range(npred):
        tab = [[0] * (order + 8) for _ in range(8)]
        for j in range(order):
            for k in range(8):
                tab[k][j] = book[(i * order + j) * 8 + k]
        for k in range(1, 8):
            tab[k][order] = tab[k - 1][order - 1]
        tab[0][order] = 1 << 11
        for k in range(1, 8):
            for j in range(k):
                tab[j][k + order] = 0
            for j in range(k, 8):
                tab[j][k + order] = tab[j - k][order]
        t.append(tab)
    return t


def vadpcm(data, coefs, order):
    out = []
    state = [0] * 16
    for f in range(0, len(data) - 8, 9):
        h = data[f]
        scale = 1 << (h >> 4)
        tab = coefs[h & 0xF] if (h & 0xF) < len(coefs) else coefs[0]
        ix = []
        for b in data[f + 1:f + 9]:
            for nib in (b >> 4, b & 0xF):
                ix.append((nib - 16 if nib > 7 else nib) * scale)
        dec = [0] * 16
        for half in range(2):
            inv = (state[16 - order:] if half == 0 else dec[8 - order:8]) + [0] * 8
            for i in range(8):
                inv[order + i] = ix[half * 8 + i]
                row = tab[i]
                acc = 0
                for k in range(order + i + 1):
                    acc += row[k] * inv[k]
                v = acc >> 11                                   # floor division, as the reference decoder
                dec[half * 8 + i] = max(-32768, min(32767, v))
        state = dec
        out.extend(dec)
    return out


def wavetable(ctl, tbl, wt):
    base, ln, typ = u32(ctl, wt), s32(ctl, wt + 4), ctl[wt + 8]
    data = tbl[base:base + ln]
    if typ == 0:
        bo = u32(ctl, wt + 16)
        order, npred = s32(ctl, bo), s32(ctl, bo + 4)
        book = [s16(ctl, bo + 8 + 2 * i) for i in range(order * npred * 8)]
        return base, vadpcm(data, coef_table(book, order, npred), order)
    return base, list(struct.unpack('>%dh' % (len(data) // 2), data[:len(data) // 2 * 2]))


def main():
    out = sys.argv[1]
    which = sys.argv[2:] or list(BANKS)
    rom = dkrom.load_rom()
    for name in which:
        cs, ce, ts = BANKS[name]
        ctl = lzss(rom[cs:ce])
        rate, snds = parse_bank(ctl)
        tbl = rom[ts:]
        d = os.path.join(out, f'bank{name}')
        os.makedirs(d, exist_ok=True)
        seen = {}
        lines = []
        for b, ii, si, wt, kb, det in snds:
            base = u32(ctl, wt)
            if base in seen:
                lines.append(f'{ii:03d}_{si:02d}\t= {seen[base]}')
                continue
            _, pcm = wavetable(ctl, tbl, wt)
            fn = f'{ii:03d}_{si:02d}.wav'
            seen[base] = fn
            with wave.open(os.path.join(d, fn), 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(struct.pack('<%dh' % len(pcm), *pcm))
            lines.append(f'{fn}\tbase {base:#x}\t{len(pcm) / rate:.2f}s\tkeyBase {kb} detune {det}')
        open(os.path.join(d, 'index.tsv'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
        print(f'bank {name}: ctl {len(ctl)} B, rate {rate}, sounds {len(snds)}, wav {len(seen)}')


if __name__ == '__main__':
    main()
