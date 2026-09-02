# 현장 카드 — 보드가 COM 포트로 안 잡힐 때

> 2026-08-27 실측. **다음에 또 헤맨다.** 증상이 "케이블 불량"처럼 보이는데 아니다.

## 증상

보드를 4대 꽂았는데 Windows 가 CP210x 를 **1개만** 인식한다.
`arduino-cli upload` 는 `Check if the port is correct and ESP connected` 로 실패한다.

## ★ 원인 — 허브의 Quick Charging 구획에 꽂았다

USB 허브에 **Quick Charging 전용 구획**과 **USB 3.0 SuperSpeed 구획**이 나뉘어 있었다.
충전 구획은 **전원만 나가고 데이터선이 호스트까지 가지 않는다.**
보드 LED 는 켜지므로 "살아 있는데 인식이 안 된다"로 보이고, 케이블을 의심하게 된다.

**해결: SuperSpeed 구획으로 옮겨 꽂는다. 그러면 4대가 즉시 다 잡힌다.**

## 원인이 **아닌** 것 (배제 완료)

| 후보 | 왜 아닌가 |
|---|---|
| 케이블 불량 | **케이블 4개 전부 정상 데이터 케이블이었다.** 구획만 옮기니 그대로 다 잡혔다 |
| CP210x 시리얼 중복(`0001`) | 그거였다면 오류코드를 단 장치가 더 보여야 하는데 **장치 자체가 1개**였다 |
| 허브 불량 | 허브는 데이터 허브로 정상 인식돼 있었다(VID_05E3 Genesys) |
| 드라이버 | 잡힌 1개는 오류코드 0 으로 멀쩡했다 |

## 구분법 (30초)

```powershell
python -c "import serial.tools.list_ports as lp; [print(p.device, p.serial_number, p.hwid) for p in lp.comports()]"
```
- 꽂은 개수보다 **적게** 나오면 → 구획을 의심한다. 먼저 SuperSpeed 쪽으로 옮긴다.
- **0개**면 → 그때 케이블을 의심한다.

## 부수 발견 — COM 번호는 고정되지 않는다

```
COM3   serial=0001      LOCATION=1-1        <- 시리얼 보고함
COM6   serial=(없음)     LOCATION=1-3.4.2    <- USB 경로로 식별
COM7   serial=(없음)     LOCATION=1-3.4.3
COM8   serial=(없음)     LOCATION=1-3.4.4
```

시리얼을 보고하지 않는 개체는 **USB 포트 경로**로 식별된다.
⇒ **다른 구멍에 꽂으면 COM 번호가 바뀐다.**

그래서 게이트웨이는 COM 번호를 고정하지 않는다:
```bash
python gateway/gateway.py --port auto --fw --emit-dashboard
```
`auto` 는 포트를 순회하며 MESHID 배너를 읽고 `role=ROOT(bridge)` 인 포트를 채택한다.
못 찾으면 연결된 포트 목록과 함께 **명시적으로 실패**한다(조용히 빈 입력으로 돌지 않는다).

## 16보드 날 주의 — 시리얼 `0001` 중복

같은 USB 시리얼 두 개가 **동시에** 꽂히면 Windows 가 충돌로 하나를 안 잡는다.
2026-08-27 기준 4대 중 `0001` 은 **1개뿐**이라 안 터졌다. 16개 중 둘 이상이면 그날 터진다.

- `flash_all.py` 가 굽기 전에 세어보고, 중복이면 경고 후 **순차 굽기**로 전환한다.
- `flash_node.ps1` 이 굽을 때마다 `usb_serial` 을 `build_log.csv` 에 남긴다.
  16대를 굽고 나면 `0001` 이 몇 개인지 그날 전에 알 수 있다.
