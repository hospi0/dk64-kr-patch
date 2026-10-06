"""Tiny two-pass MIPS assembler for the few instructions the hooks need."""
import struct

R = {n: i for i, n in enumerate(
    'zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra'.split())}

I_OPS = {'addiu': 9, 'slti': 0x0A, 'sltiu': 0x0B, 'andi': 0x0C, 'ori': 0x0D, 'lui': 0x0F,
         'lb': 0x20, 'lh': 0x21, 'lw': 0x23, 'lbu': 0x24, 'lhu': 0x25, 'sb': 0x28, 'sh': 0x29, 'sw': 0x2B}
R_OPS = {'addu': 0x21, 'subu': 0x23, 'and': 0x24, 'or': 0x25, 'slt': 0x2A, 'sltu': 0x2B}
SH_OPS = {'sll': 0, 'srl': 2, 'sra': 3}


def hi(v):
    return ((v + 0x8000) >> 16) & 0xFFFF


def lo(v):
    return v & 0xFFFF


class Asm:
    """prog: list of str lines; 'label:' defines labels; operands may use labels / %hi(x) / %lo(x)."""

    def __init__(self, base, syms=None):
        self.base = base
        self.syms = dict(syms or {})

    def _val(self, s):
        s = s.strip()
        if s.startswith('%hi(') or s.startswith('%lo('):
            v = self._val(s[4:-1])
            return hi(v) if s[1] == 'h' else lo(v)
        if s in self.syms:
            return self.syms[s]
        return int(s, 0)

    def assemble(self, prog):
        lines = []
        pc = self.base
        for ln in prog:
            ln = ln.split('#')[0].strip()
            if not ln:
                continue
            if ln.endswith(':'):
                self.syms[ln[:-1]] = pc
                continue
            lines.append((pc, ln))
            pc += 4
        out = b''
        for pc, ln in lines:
            out += struct.pack('>I', self._enc(pc, ln))
        return out

    def _enc(self, pc, ln):
        op, _, rest = ln.partition(' ')
        a = [x.strip() for x in rest.split(',')] if rest else []
        if op == 'nop':
            return 0
        if op in ('j', 'jal'):
            return ((2 if op == 'j' else 3) << 26) | ((self._val(a[0]) >> 2) & 0x3FFFFFF)
        if op == 'mfc1':                                     # mfc1 rt, fN
            return (0x11 << 26) | (R[a[0]] << 16) | (int(a[1][1:]) << 11)
        if op in ('blez', 'bgtz'):
            off = (self._val(a[1]) - (pc + 4)) >> 2
            return ((6 if op == 'blez' else 7) << 26) | (R[a[0]] << 21) | (off & 0xFFFF)
        if op in ('bltz', 'bgez'):
            off = (self._val(a[1]) - (pc + 4)) >> 2
            return (1 << 26) | (R[a[0]] << 21) | ((0 if op == 'bltz' else 1) << 16) | (off & 0xFFFF)
        if op in ('multu', 'mult', 'divu', 'div'):
            f = {'mult': 0x18, 'multu': 0x19, 'div': 0x1A, 'divu': 0x1B}[op]
            return (R[a[0]] << 21) | (R[a[1]] << 16) | f
        if op in ('mflo', 'mfhi'):
            return (R[a[0]] << 11) | (0x12 if op == 'mflo' else 0x10)
        if op == 'jr':
            return (R[a[0]] << 21) | 8
        if op == 'jalr':                                     # jalr rs  (rd = ra)
            return (R[a[0]] << 21) | (31 << 11) | 9
        if op in ('beq', 'bne'):
            off = (self._val(a[2]) - (pc + 4)) >> 2
            assert -0x8000 <= off < 0x8000
            return ((4 if op == 'beq' else 5) << 26) | (R[a[0]] << 21) | (R[a[1]] << 16) | (off & 0xFFFF)
        if op in ('beqz', 'bnez'):
            return self._enc(pc, '%s %s, zero, %s' % (op[:3], a[0], a[1]))
        if op == 'b':
            return self._enc(pc, 'beq zero, zero, %s' % a[0])
        if op == 'move':
            return self._enc(pc, 'addu %s, %s, zero' % (a[0], a[1]))
        if op == 'li':                                       # 0x8000..0xFFFF: ori (addiu would sign-extend)
            v = self._val(a[1])
            assert -0x8000 <= v <= 0xFFFF, ln
            return self._enc(pc, '%s %s, zero, %s' % ('ori' if v >= 0x8000 else 'addiu', a[0], a[1]))
        if op in R_OPS:
            return (R[a[1]] << 21) | (R[a[2]] << 16) | (R[a[0]] << 11) | R_OPS[op]
        if op in SH_OPS:
            return (R[a[1]] << 16) | (R[a[0]] << 11) | ((self._val(a[2]) & 31) << 6) | SH_OPS[op]
        if op == 'lui':
            return (0x0F << 26) | (R[a[0]] << 16) | (self._val(a[1]) & 0xFFFF)
        if op in I_OPS:
            if '(' in a[1]:                                    # load/store: rt, imm(rs)
                imm, rs = a[1][:-1].split('(')
                return (I_OPS[op] << 26) | (R[rs] << 21) | (R[a[0]] << 16) | (self._val(imm or '0') & 0xFFFF)
            return (I_OPS[op] << 26) | (R[a[1]] << 21) | (R[a[0]] << 16) | (self._val(a[2]) & 0xFFFF)
        raise ValueError(ln)
