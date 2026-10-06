"""N64 header CRC (CIC-6102/6103 family). BK uses 6103."""
import struct

SEEDS = {6101: 0xF8CA4DDC, 6102: 0xF8CA4DDC, 6103: 0xA3886759, 6105: 0xDF26F436, 6106: 0x1FEA617A}
M = 0xFFFFFFFF


def rol(v, n):
    n &= 31
    return ((v << n) | (v >> (32 - n))) & M


def calc(rom, cic=6103):
    t1 = t2 = t3 = t4 = t5 = t6 = SEEDS[cic]
    for i in range(0x1000, 0x101000, 4):
        d = struct.unpack_from('>I', rom, i)[0]
        if (t6 + d) & M < t6:
            t4 = (t4 + 1) & M
        t6 = (t6 + d) & M
        t3 ^= d
        r = rol(d, d & 0x1F)
        t5 = (t5 + r) & M
        t2 = t2 ^ r if t2 > d else t2 ^ (t6 ^ d)
        if cic == 6105:
            t1 = (t1 + (struct.unpack_from('>I', rom, 0x0750 + (i & 0xFF))[0] ^ d)) & M
        else:
            t1 = (t1 + (t5 ^ d)) & M
    if cic == 6103:
        return (t6 ^ t4) + t3 & M, (t5 ^ t2) + t1 & M
    if cic == 6106:
        return (t6 * t4 + t3) & M, (t5 * t2 + t1) & M
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


def fix(rom, cic=6103):
    c1, c2 = calc(rom, cic)
    rom[0x10:0x18] = struct.pack('>II', c1, c2)
    return c1, c2
