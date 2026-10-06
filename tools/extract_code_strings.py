"""On-screen strings inside the code overlays' .data -> my files/tsv/dk_code.tsv (minigames arcade/jetpac excluded:
하스피 «미니게임은 번역 ㄴ»; debug/error/GBI names excluded). 칸 = bytes up to the next non-zero byte (incl. NUL)."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICK = [
    ('global_asm', 0x10F18), ('global_asm', 0x12D28),
    ('global_asm', 0x14E00), ('global_asm', 0x14E08), ('global_asm', 0x14E10), ('global_asm', 0x14E18),
    ('global_asm', 0x14E20), ('global_asm', 0x14E28), ('global_asm', 0x14E30), ('global_asm', 0x14E38),
    ('global_asm', 0x15AD4),
    ('global_asm', 0x15FB0), ('global_asm', 0x15FB8), ('global_asm', 0x15FC0), ('global_asm', 0x15FC8),
    ('global_asm', 0x15FD0), ('global_asm', 0x15FD8), ('global_asm', 0x15FE4), ('global_asm', 0x15FEC),
    ('global_asm', 0x15FF4),
    ('global_asm', 0x176D0), ('global_asm', 0x176D8), ('global_asm', 0x1A17C),
    ('multiplayer', 0xD4),
    ('bonus', 0x450), ('bonus', 0x660), ('bonus', 0x668), ('bonus', 0x674), ('bonus', 0x67C),
    ('critter', 0x9A0), ('critter', 0x9AC),
    ('boss', 0x6E0),
]


def main():
    out = ['ID\t위치\t구분\t원문\t번역\t칸']
    for n, (seg, off) in enumerate(PICK, 1):
        d = open(os.path.join(ROOT, 'work', 'code', f'{seg}_data.bin'), 'rb').read()
        end = d.index(b'\0', off)
        s = d[off:end].decode('ascii')
        slot = end + 1
        while slot < len(d) and d[slot] == 0:
            slot += 1
        out.append(f'C{n:03d}\t{seg}:{off:X}\t코드\t{s}\t\t{slot - off}')
    open(os.path.join(ROOT, 'my files', 'tsv', 'dk_code.tsv'), 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
