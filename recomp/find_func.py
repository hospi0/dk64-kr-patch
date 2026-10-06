"""map a DK64Recompiled.exe crash offset to the recompiled game function (function tables in .data)"""
import struct, sys
f = r'D:\hospi\GitHubLauncher\Apps\DK64Recompiled\DK64Recompiled.exe'
d = open(f, 'rb').read()
pe = struct.unpack_from('<I', d, 0x3C)[0]
nsec = struct.unpack_from('<H', d, pe + 6)[0]; opt = struct.unpack_from('<H', d, pe + 20)[0]
base = struct.unpack_from('<Q', d, pe + 24 + 24)[0]
secs = {}
for i in range(nsec):
    o = pe + 24 + opt + 40 * i
    secs[d[o:o + 8].rstrip(b'\0').decode()] = struct.unpack_from('<IIII', d, o + 8)
vs, va, rs, ra = secs['.data']
blk = d[ra:ra + rs]
target = base + int(sys.argv[1], 16)
best = None
for i in range(0, len(blk) - 16, 8):
    p, off, size = struct.unpack_from('<QII', blk, i)
    if p <= target and target - p < 0x40000 and 0 < size < 0x10000 and (best is None or p > best[0]):
        best = (p, off, size)
p, off, size = best
print(f'native +{target - p:#x}  section offset {off:#x} size {size:#x}  -> global_asm vram {0x805FB300 + off:#x}')
