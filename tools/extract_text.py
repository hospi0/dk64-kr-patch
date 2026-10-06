"""DK64 text -> TSV (one row per textbox).

columns: ID / 위치 (file:box, hex file) / 구분 / 원문 / 번역
  {/}       = boundary between string pieces of the same block (the game draws pieces as separate runs/lines)
  {ICONxx}  = button/sprite icon block (xx = icon id)
  {BLK}     = boundary between two text blocks with no icon between them (rare)
out: work/text/dk_text.tsv (+ 29 KB split copies in my files/tsv/)
"""
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
import dkrom

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def box_text(blocks, data):
    out = []
    prev_text = False
    for b in blocks:
        if b['kind'] & 1:
            if prev_text:
                out.append('{BLK}')
            out.append('{/}'.join(data[i[1]:i[1] + i[2]].decode('ascii') for i in b['items']))
            prev_text = True
        else:
            out.append(''.join('{ICON%02X}' % (i[1] >> 16) for i in b['items']))
            prev_text = False
    return ''.join(out)


def rows(rom):
    n = 0
    for j in range(len(dkrom.table(rom, dkrom.TEXT))):
        d = dkrom.file(rom, dkrom.TEXT, j)
        boxes, data, _ = dkrom.parse_text(d)
        for bi, blocks in enumerate(boxes):
            t = box_text(blocks, data)
            n += 1
            yield f'{n:05d}', f'{j:02X}:{bi}', '대사', t


def main():
    rom = dkrom.load_rom()
    out = ['ID\t위치\t구분\t원문\t번역']
    for r in rows(rom):
        out.append('\t'.join(r) + '\t')
    text = '\n'.join(out) + '\n'
    os.makedirs(os.path.join(ROOT, 'my files', 'tsv'), exist_ok=True)
    open(os.path.join(ROOT, 'work', 'text', 'dk_text.tsv'), 'w', encoding='utf-8').write(text)
    # split copies for the translator: ~29 KB each, remainder merged into the last one
    head, body = out[0], out[1:]
    parts, cur = [], []
    for ln in body:
        if cur and len(('\n'.join([head] + cur + [ln]) + '\n').encode('utf-8')) > 29 * 1024:
            parts.append(cur); cur = []
        cur.append(ln)
    if cur:
        if parts and len(('\n'.join([head] + parts[-1] + cur) + '\n').encode('utf-8')) <= 29 * 1024 * 1.5:
            parts[-1] += cur
        else:
            parts.append(cur)
    for k, p in enumerate(parts, 1):
        open(os.path.join(ROOT, 'my files', 'tsv', f'dk_text_{k:03d}.tsv'), 'w',
             encoding='utf-8').write('\n'.join([head] + p) + '\n')
    print(f'{len(body)} rows -> work/text/dk_text.tsv, {len(parts)} split files')


if __name__ == '__main__':
    main()
