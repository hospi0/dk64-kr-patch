#!/bin/sh
# test builds dk64_kr_s1..s4 (KR_STAGE 1..4) -> bin/stage/
set -e
cd "$(dirname "$0")"
ZIG=/c/claude/utils/zig-x86_64-windows-0.17.0/zig.exe
CFLAGS="-target mips -mips2 -mabi=32 -O2 -fno-jump-tables -G0 -mno-abicalls -mno-odd-spreg -mno-check-zero-division -fomit-frame-pointer -ffast-math -fno-unsafe-math-optimizations -fno-builtin-memset -Wall -Wno-unused-parameter -Wno-unknown-pragmas -Wno-unused-variable -Wno-unused-function -Wno-missing-braces -Wno-unsupported-floating-point-opt -Werror=section"
CPPFLAGS="-nostdinc -D_LANGUAGE_C -DMIPS -DF3DEX_GBI -I include -I include/dummy_headers -I dk64_decomp/include -I dk64_decomp/include/2.0L"
mkdir -p build/st bin/stage
$ZIG clang -target mips -mips2 -mabi=32 -mno-abicalls -c src/krblob.s -o build/st/krblob.o
for n in 1 2 3 4; do
  $ZIG clang $CFLAGS $CPPFLAGS -DKR_STAGE=$n -c src/kr.c -o build/st/kr$n.o
  $ZIG ld.lld build/st/kr$n.o build/st/krblob.o -nostdlib -T mod.ld --unresolved-symbols=ignore-all --emit-relocs -e 0 --no-nmagic -o build/st/mod$n.elf
  sed -e "s/^id = .*/id = \"dk64_kr_s$n\"/" -e "s/^display_name = .*/display_name = \"KR test $n\"/" \
      -e "s#^elf_path = .*#elf_path = \"build/st/mod$n.elf\"#" -e "s/^mod_filename = .*/mod_filename = \"dk64_kr_s$n\"/" mod.toml > mod_s$n.toml
  ../tools/RecompModTool.exe mod_s$n.toml bin/stage
  rm mod_s$n.toml
done
ls -l bin/stage/*.nrm
