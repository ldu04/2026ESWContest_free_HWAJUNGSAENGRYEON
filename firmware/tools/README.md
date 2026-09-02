# firmware/tools — 보드 굽기 도구

> **★ 이 디렉터리가 원본이다.** 실행은 영문 경로에서 하지만(한글 경로가 GNU 툴체인을 깨뜨린다,
> `firmware/BUILD.md` 함정 ④), **원본은 반드시 여기에 있어야 한다.**
> 2026-08-27 에 이 스크립트들이 저장소 밖(`C:\Users\Public\esp32\`)에만 있어서
> 그날 잡은 버그 세 개가 **어디에도 백업되지 않은 상태**였다.

## 사용

```powershell
# 실행 위치로 복사 (영문 경로)
Copy-Item firmware\tools\flash_node.ps1, firmware\tools\flash_queue.ps1 C:\Users\Public\esp32\

# 한 대 굽기 — 인덱스/역할/임계를 배너로 대조하고 build_log.csv 에 기록
.\flash_node.ps1 -Index 99 -Port COM3                 # 브리지(BRIDGE_INDEX)
.\flash_node.ps1 -Index 1  -Port COM6                 # 격자 노드
.\flash_node.ps1 -Index 1  -Port COM6 -Threshold 40   # 시험용 낮은 임계(빌드 플래그로만)

# 보드를 갈아 끼우면 자동 감지해서 순서대로 굽기(데이터 포트가 하나뿐일 때)
.\flash_queue.ps1 -Indices "1,2,3" -Port COM3 -KnownMids "219922329"
```

## PASS 판정에 들어가는 것

배너 `{"type":"MESHID", ...}` 를 읽어 **네 가지를 대조**한다. 하나라도 어긋나면 FAIL.

| 검사 | 왜 |
|---|---|
| `index` == 요청값 | 16번 반복하면 눈으로는 반드시 틀린다 |
| `is_root` == (index == bridge_index) | **브리지인데 루트가 아니면 시리얼 중계가 통째로 멈춘다.** 보드는 멀쩡히 돌아 침묵으로 실패한다 |
| `death_threshold_c` == 80.0 (플래그 없을 때) | 시험용 임시 임계 40 을 그대로 데모에 들고 가는 사고 방지 |
| `usb_serial` 기록 | 같은 시리얼 둘이 동시에 꽂히면 Windows 가 하나를 안 잡는다. 16개 중 `0001` 이 몇 개인지 그날 전에 알아야 한다 |

## ★ 2026-08-27 에 잡은 버그 세 개 (같은 실수 반복 금지)

### ① `build.extra_flags` 는 플랫폼 기본 플래그를 덮어쓴다
```
error: 'AsyncClient' does not name a type      <- painlessMesh 가 통째로 깨진다
```
플래그 **없이** 빌드하면 멀쩡해서 라이브러리 문제로 오인하기 쉽다.
사용자 `-D` 매크로는 반드시 **`compiler.cpp.extra_flags`** 로 준다.
`firmware/flash_all.py` 도 같은 버그가 있었다(16보드 굽기가 통째로 실패했을 것).

### ② `powershell -File script.ps1 -Indices 1,2,3` 은 배열이 안 된다
`"1,2,3"` 이 **하나의 값**으로 넘어가 `[int[]]` 캐스팅이 **`123`** 이 된다.
실제로 `NODE_ID=123` 으로 구울 뻔했고, 그 보드는 격자에도 브리지에도 없어
`unknown_ids` 로 **조용히 버려졌을** 것이다.
→ 문자열로 받아 스크립트 안에서 쪼갠다.

### ③ `[double]40` 은 `"40"` 으로 렌더링된다
```
" -DTEMP_THRESHOLD_C=$($Threshold)f"   ->   -DTEMP_THRESHOLD_C=40f
error: unable to find numeric literal operator 'operator""f'
```
C++ 리터럴은 `40.0f` 여야 한다.
→ `("{0:0.0#####}f" -f $Threshold)` 로 소수점을 강제한다.

## build_log.csv

굽을 때마다 한 줄씩 쌓인다. **스티커가 떨어져도 `mesh_id` 로 보드를 역추적**할 수 있다
(painlessMesh nodeId 는 칩 MAC 에서 나와 보드마다 고유하다. CP2102 USB 시리얼과 달리 겹치지 않는다).

```
date, requested_index, banner_index, is_root, role, port,
usb_serial, usb_path, death_threshold_c, mesh_id, result, note
```
