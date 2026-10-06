# 동키콩 64 한글 패치 (N64 북미판 · PC 리컴파일판)

**최신 v0.9** — [릴리즈](https://github.com/hospi0/dk64-kr-patch/releases/latest)에서 내려받으세요.

- `DK64_KR_v0.9.zip` — N64 롬 패치(xdelta + 적용 배치). 원본 `Donkey Kong 64 (USA).z64` (MD5 `9EC41ABF2519FC386CADD0731F6E868C`) → 패치본 MD5 `2574A06FB8D3710154B17256D53ED150`. 확장팩 필요(원래 게임도 필수).
- `DK64_KR_Recomp_v0.9.zip` — PC 리컴파일판 [DK64 Rekongpiled](https://github.com/Rainchus/DK64Recomp) 한글 모드 `dk64_korean.nrm`(만든 사람 hospi). `%LOCALAPPDATA%\DK64Recompiled\mods\` 에 넣으면 됩니다.

## 바뀌는 것
- 대사 전부(말풍선·컷신 자막·화자 이름)
- 메인 메뉴·일시정지 메뉴·콩 이름
- 오프닝 음성 대사 자막(크룰과 졸개들)

## 구성
- `tools/dkbuild.py` — N64 롬 빌더(글꼴 페이지·훅·대사 파일 재배치)
- `tools/dkmod.py` + `recomp/mod/` — 리컴파일판 모드(N64Recomp .nrm, `zig clang` 으로 빌드)
- `docs/00_이어하기.md` — 구조 분석·작업 기록
