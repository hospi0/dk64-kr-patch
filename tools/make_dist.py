# -*- coding: utf-8 -*-
r"""배포 묶음 두 개
  dist/DK64_KR_v0.9/         N64 롬 패치 (xdelta + xdelta.exe + readme.txt + 패치적용.bat) → DK64_KR_v0.9.zip
  dist/DK64_KR_Recomp_v0.9/  리컴파일판(DK64 Rekongpiled) 모드 (dk64_korean.nrm + readme.txt) → DK64_KR_Recomp_v0.9.zip

  python tools/dkbuild.py "my files/dk_text_001.tsv" "my files/dk_text_002.tsv" work/text/dk_fix.tsv work/DK_KR_v0.9.z64
  python tools/dkmod.py ... && sh recomp/mod/build.sh      # 모드
  python tools/make_dist.py

규칙: 해시는 MD5 대문자 · 한국어 문서는 CP949(CRLF) · 버전은 v0.9 한 자리 · bat 의 if 블록 안 echo 에 괄호 금지.
"""
import hashlib, os, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)

VER = 'v0.9'
NAME = 'Donkey Kong 64 (USA).z64'
SRC = os.path.join(r'C:\claude\roms\n64', NAME)
SRC_MD5 = '9ec41abf2519fc386cadd0731f6e868c'
OUT = os.path.join(ROOT, 'work', 'DK_KR_' + VER + '.z64')
PKG = 'DK64_KR_' + VER
PKG_R = 'DK64_KR_Recomp_' + VER
DIST = os.path.join(ROOT, 'dist')
PATCH = PKG + '.xdelta'
NRM = os.path.join(ROOT, 'recomp', 'mod', 'bin', 'dk64_korean.nrm')
XDELTA = r'C:\claude\utils\xdelta.exe'


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


README = """동키콩 64 (N64 북미판) 한글 패치 {ver}
==========================================

{name} 에
패치하시면 됩니다.

원본md5 : {src}
패치md5 : {dst}

입니다.


[ 적용 방법 ]

1. 원본 {name} 을 이 패치 묶음과 한 폴더에 둡니다.
   (.z64 빅엔디언 · {srcsize:,} 바이트 · .n64/.v64 는 먼저 .z64 로 바꿔 주세요)
2. 「패치적용.bat」 을 실행합니다.
3. 배치가 원본 MD5 를 먼저 확인하고, 끝난 뒤 결과 MD5 까지 검사합니다.
   원본은 .bak 으로 남겨 둡니다.
4. 패치 후 롬 크기가 {dstsize:,} 바이트로 커집니다.


[ 꼭 필요한 것 ]

■ 확장팩(메모리 8MB)이 필요합니다(원래 게임도 확장팩 필수).


[ 바뀌는 것 ]

■ 대사 전부(말풍선·컷신 자막·화자 이름)
■ 메인 메뉴·일시정지 메뉴·콩 이름
■ 오프닝 음성 대사 자막(크룰과 졸개들)


[ 리컴파일판 ]

PC 리컴파일판(DK64 Rekongpiled)은 롬 패치가 아니라 모드로 따로 배포합니다
(DK64_KR_Recomp_{ver}.zip).
"""

README_R = """동키콩 64 리컴파일판(DK64 Rekongpiled) 한글 모드 {ver}
==========================================

만든 사람 : hospi

PC 리컴파일판 DK64 Rekongpiled(1.0 이상)용 한글 모드입니다.
리컴파일판은 원본 롬 그대로 실행하므로 롬 패치가 아니라 모드로 넣습니다.


[ 설치 방법 ]

1. dk64_korean.nrm 을
   %LOCALAPPDATA%\\DK64Recompiled\\mods\\
   폴더에 넣습니다. (mods 폴더가 없으면 만들어 주세요)
2. 게임을 켜고 모드 메뉴에서 「Korean Translation (한글 패치)」 가 켜져 있는지 확인합니다.
3. 게임 롬은 원본 북미판({name}, md5 {src})을 그대로 쓰면 됩니다.

모드 md5 : {nrm}


[ 바뀌는 것 ]

■ 대사 전부(말풍선·컷신 자막·화자 이름)
■ 메인 메뉴·일시정지 메뉴·콩 이름
■ 오프닝 음성 대사 자막(크룰과 졸개들)
"""

BAT = r"""@echo off
setlocal
set NAME={name}
set PATCH={patch}
set SRCMD5={src}
set DSTMD5={dst}

echo.
echo  ==============================================
echo    Donkey Kong 64 ^(N64 USA^) Korean Patch {ver}
echo  ==============================================
echo.

if not exist "%NAME%" (
  echo  [!] "%NAME%" 파일이 이 폴더에 없습니다.
  echo      원본 .z64 와 같은 폴더에 두고 실행하세요.
  goto END
)
if not exist "%~dp0xdelta.exe" (
  echo  [!] xdelta.exe 가 없습니다. 패치 묶음을 그대로 풀고 실행하세요.
  goto END
)

echo  [1/3] 원본 검사 중...
set HASH=
for /f "skip=1 tokens=* delims=" %%H in ('certutil -hashfile "%NAME%" MD5') do (
  if not defined HASH set HASH=%%H
)
set HASH=%HASH: =%

if /I "%HASH%"=="%DSTMD5%" (
  echo.
  echo  [!] 이미 이 버전의 한글 패치가 적용된 파일입니다.
  goto END
)
if /I not "%HASH%"=="%SRCMD5%" (
  echo.
  echo  [!] 원본 MD5 가 다릅니다. 패치하지 않고 중단합니다.
  echo      필요 : %SRCMD5%
  echo      현재 : %HASH%
  goto END
)

echo  [2/3] 패치 적용 중...
"%~dp0xdelta.exe" -d -f -s "%NAME%" "%~dp0%PATCH%" "%NAME%.kr"
if errorlevel 1 (
  echo  [!] 패치에 실패했습니다.
  if exist "%NAME%.kr" del "%NAME%.kr"
  goto END
)

echo  [3/3] 결과 검사 중...
set HASH2=
for /f "skip=1 tokens=* delims=" %%H in ('certutil -hashfile "%NAME%.kr" MD5') do (
  if not defined HASH2 set HASH2=%%H
)
set HASH2=%HASH2: =%

if /I not "%HASH2%"=="%DSTMD5%" (
  echo  [!] 결과 MD5 가 다릅니다. 원본은 그대로 두고 중단합니다.
  del "%NAME%.kr"
  goto END
)

move /y "%NAME%" "%NAME%.bak" >nul
move /y "%NAME%.kr" "%NAME%" >nul
echo.
echo  [OK] 한글 패치 완료. 원본은 "%NAME%.bak" 으로 남겨 두었습니다.

:END
echo.
pause
endlocal
"""


def write_cp949(path, text):
    data = text.replace('\r\n', '\n').replace('\n', '\r\n').encode('cp949')
    with open(path, 'wb') as f:
        f.write(data)


def zipdir(d, out):
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(d)):
            z.write(os.path.join(d, f), os.path.join(os.path.basename(d), f))


def main():
    src_md5, dst_md5 = md5(SRC), md5(OUT)
    assert src_md5 == SRC_MD5, src_md5
    # N64
    d = os.path.join(DIST, PKG)
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    patch = os.path.join(d, PATCH)
    subprocess.run([XDELTA, '-e', '-9', '-f', '-s', SRC, OUT, patch], check=True)
    shutil.copyfile(XDELTA, os.path.join(d, 'xdelta.exe'))
    chk = os.path.join(ROOT, 'work', 'dist_check.z64')
    subprocess.run([XDELTA, '-d', '-f', '-s', SRC, patch, chk], check=True)
    ok = md5(chk) == dst_md5
    os.remove(chk)
    if not ok:
        raise SystemExit('⛔ xdelta 되짚기 결과가 패치본과 다르다')
    v = dict(ver=VER, name=NAME, patch=PATCH, src=src_md5, dst=dst_md5,
             srcsize=os.path.getsize(SRC), dstsize=os.path.getsize(OUT))
    write_cp949(os.path.join(d, 'readme.txt'), README.format(**dict(v, src=src_md5.upper(), dst=dst_md5.upper())))
    write_cp949(os.path.join(d, '패치적용.bat'), BAT.format(**v))
    zipdir(d, os.path.join(DIST, PKG + '.zip'))
    # 리컴프
    r = os.path.join(DIST, PKG_R)
    if os.path.exists(r):
        shutil.rmtree(r)
    os.makedirs(r)
    shutil.copyfile(NRM, os.path.join(r, 'dk64_korean.nrm'))
    write_cp949(os.path.join(r, 'readme.txt'),
                README_R.format(ver=VER, name=NAME, src=src_md5.upper(), nrm=md5(NRM).upper()))
    zipdir(r, os.path.join(DIST, PKG_R + '.zip'))
    print('✅ %s.zip\n   xdelta %d B · 원본md5 %s · 패치md5 %s · 되짚기 일치\n✅ %s.zip  nrm md5 %s'
          % (PKG, os.path.getsize(patch), src_md5.upper(), dst_md5.upper(), PKG_R, md5(NRM).upper()))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
