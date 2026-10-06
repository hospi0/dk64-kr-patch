"""Word-by-word MIPS disassembly of DK64 overlays (work/code). usage: dkdis.py global_asm 0x806FB490 0x806FB714"""
import capstone, sys
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_BIG_ENDIAN)
VRAM = {'global_asm': 0x805FB300}


def image(seg):
    c = open(f'work/code/{seg}_code.bin', 'rb').read()
    d = open(f'work/code/{seg}_data.bin', 'rb').read()
    return c + d, VRAM[seg]


def dis(b, base, lo, hi):
    out = []
    for a in range(lo, hi, 4):
        w = b[a - base:a - base + 4]
        ins = next(md.disasm(w, a), None)
        out.append(f'{a:08x}: {w.hex()}  ' + (f'{ins.mnemonic} {ins.op_str}' if ins else '.word'))
    return '\n'.join(out)


if __name__ == '__main__':
    b, base = image(sys.argv[1])
    print(dis(b, base, int(sys.argv[2], 16), int(sys.argv[3], 16)))
