"""RetroArch Mupen64Plus-Next save state -> RDRAM + thread PCs (crash analysis).

usage: python tools/dkstate.py <file.state> [rdram_out.bin]

.state = RZIP (#RZIPv\\x01#, u32 chunk size, u64 total, then [u32 len][zlib] chunks) -> M64+SAVE;
RDRAM at +0x1CC as little-endian 32-bit words.  libultra thread list = 0x800100EC (os active queue);
OSThread: +0 next, +4 priority, +0x14 state(u16), +0x20 context (GPRs as u64: at=+0x20 ... ra), pc at +0x11C.
"""
import sys, struct, zlib

RDRAM_OFF, RDRAM_SIZE = 0x1CC, 0x800000


def unrzip(b):
    assert b[:8] == b'#RZIPv\x01#', b[:8]
    total = struct.unpack_from('<Q', b, 12)[0]
    p, out = 20, bytearray()
    while len(out) < total:
        n = struct.unpack_from('<I', b, p)[0]
        out += zlib.decompress(b[p + 4:p + 4 + n])
        p += 4 + n
    return bytes(out)


def rdram(state):
    raw = state[RDRAM_OFF:RDRAM_OFF + RDRAM_SIZE]
    return b''.join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))


REGS = 'at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 gp sp s8 ra'.split()


def main():
    st = unrzip(open(sys.argv[1], 'rb').read())
    ram = rdram(st)
    if len(sys.argv) > 2:
        open(sys.argv[2], 'wb').write(ram)
    r32 = lambda a: struct.unpack_from('>I', ram, a & 0x7FFFFF)[0]
    seen = set()
    for head in (0x800100EC, 0x800100E8, 0x800100F0):
        t = r32(head)
        while t and 0x80000000 <= t < 0x80800000 and t not in seen:
            seen.add(t)
            ctx = (t & 0x7FFFFF) + 0x20
            regs = {n: struct.unpack_from('>Q', ram, ctx + 8 * i)[0] & 0xFFFFFFFF for i, n in enumerate(REGS)}
            pc = r32(t + 0x11C)
            cause, badv = r32(t + 0x120), r32(t + 0x124)
            print(f'thread {t:#x} id {r32(t + 0x14) & 0xFFFF} pri {r32(t + 4)} pc {pc:#x} cause {cause:#x} badvaddr {badv:#x} ra {regs["ra"]:#x} sp {regs["sp"]:#x}')
            print('   ' + ' '.join(f'{n}={regs[n]:08x}' for n in REGS))
            t = r32(t + 0xC)


if __name__ == '__main__':
    main()
