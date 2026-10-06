#!/bin/sh
# build the Korean mod: run  python tools/dkmod.py <tsv...>  first (writes src/krdata.h, src/krblob.*)
set -e
cd "$(dirname "$0")"
# "zig clang" = plain clang with every target (the official Windows LLVM ships without MIPS)
ZIG=/c/claude/utils/zig-x86_64-windows-0.17.0/zig.exe
CFLAGS="-target mips -mips2 -mabi=32 -O2 -fno-jump-tables -G0 -mno-abicalls -mno-odd-spreg -mno-check-zero-division -fomit-frame-pointer -ffast-math -fno-unsafe-math-optimizations -fno-builtin-memset -Wall -Wextra -Wno-incompatible-library-redeclaration -Wno-unused-parameter -Wno-unknown-pragmas -Wno-unused-variable -Wno-missing-braces -Wno-unsupported-floating-point-opt -Werror=section"
CPPFLAGS="-nostdinc -D_LANGUAGE_C -DMIPS -DF3DEX_GBI -I include -I include/dummy_headers -I dk64_decomp/include -I dk64_decomp/include/2.0L"
mkdir -p build/src bin
$ZIG clang $CFLAGS $CPPFLAGS -c src/kr.c -o build/src/kr.o
# bubble.c = a copy of the port's own F3DEX2 code -> F3DEX2 GBI (kr.c only emits RDP commands, same in both)
$ZIG clang $CFLAGS $(echo "$CPPFLAGS" | sed 's/-DF3DEX_GBI /-DF3DEX_GBI_2 /') -c src/bubble.c -o build/src/bubble.o
$ZIG clang -target mips -mips2 -mabi=32 -G0 -mno-abicalls -c src/krblob.s -o build/src/krblob.o
$ZIG ld.lld build/src/kr.o build/src/bubble.o build/src/krblob.o -nostdlib -T mod.ld -Map build/mod.map --unresolved-symbols=ignore-all --emit-relocs -e 0 --no-nmagic -o build/mod.elf
../tools/RecompModTool.exe mod.toml bin
ls -l bin/dk64_korean.nrm
