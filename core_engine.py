import os
import sys
import re
import json
from datetime import datetime
import fitz
from PIL import Image, ImageDraw

# [핵심 패치] 일반 파이썬 실행과 EXE 실행 모두에서 현재 폴더 경로를 100% 정확히 인식
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RAW_DIR = os.path.join(BASE_DIR, "data_raw")
PROCESSED_DIR = os.path.join(BASE_DIR, "data_processed")
os.makedirs(PROCESSED_DIR, exist_ok=True)

MASTER_DB_PATH = os.path.join(PROCESSED_DIR, "master_db.json")
FAULT_HISTORY_PATH = os.path.join(PROCESSED_DIR, "fault_history.json")

CB_RELAY_MASTER_DICT = {
    "HCRN": {
        "kr_name": "선두차 제어 차단기 (HCR1~7)",
        "location": "전·후 운전실 배전반",
        "trip_symptom": "전부 차단: ACM·판토·MCB 불능 / 후부 차단: 판토 불능 및 비상제동 체결",
        "action": "차단 복귀 (후부 복귀불능 시 전부 EBCOS 취급 후 전후진 F/R 조작)"
    },
    "MCN": {
        "kr_name": "주간제어기 차단기",
        "location": "운전실 배전반",
        "trip_symptom": "주간제어기 전원 상실, 전체 MCB 투입 불능",
        "action": "운전실 배전반 MCN ON 복귀"
    },
    "MCB": {
        "kr_name": "주회로차단기 (MCBN1/2)",
        "location": "M2차 옥상 및 배전반 (2,4,8호차)",
        "trip_symptom": "해당 유니트 주회로 단전, TCMS MCB 'OFF' 현시",
        "action": "MCBCS 재투입 (불능 시 해당 M2차 MCBN1/2·ADAN·ADDN 확인)"
    },
    "MCBCS": {
        "kr_name": "MCB 투입스위치",
        "location": "운전실 제어대",
        "trip_symptom": "접점 불량 시 MCBHR 무여자로 전체 MCB 투입 불능 (코드 1049)",
        "action": "MCBCS 재취급 및 MCBHR 동작음 확인 (불능 시 후부 운전실 취급)"
    },
    "MCBHR": {
        "kr_name": "주회로차단기 유지계전기",
        "location": "운전실 배전반",
        "trip_symptom": "무여자 시 전체 주회로차단기(MCB) 투입 불능 (코드 1049)",
        "action": "MCBCS 취급 시 배전반 내 MCBHR 동작음 확인 및 MCN·HCRN 점검"
    },
    "ADAN": {
        "kr_name": "교류 피뢰기 차단기 (ADDN)",
        "location": "M2차 배전반 (2,4,8호차)",
        "trip_symptom": "차단 시 해당 M2차 주회로차단기(MCB) 투입 불능",
        "action": "일부 MCB 미투입 시 해당 M2차 배전반 ADAN, ADDN, MCBN1/2 확인 복귀"
    },
    "ADDN": {
        "kr_name": "직류 피뢰기 차단기",
        "location": "M2차 배전반 (2,4,8호차)",
        "trip_symptom": "차단 시 해당 M2차 주회로차단기(MCB) 투입 불능",
        "action": "해당 M2차 배전반 ADDN, ADAN, MCBN1/2 차단 확인 및 복귀"
    },
    "MTBMN": {
        "kr_name": "주변압기 송풍기 차단기 (MTOMN)",
        "location": "M2차 배전반 (2,4,8호차)",
        "trip_symptom": "차단 시 주변압기 냉각 불능으로 해당 M2차 MCB 투입 불능",
        "action": "일부 MCB 미투입 시 해당 M2차 배전반 MTBMN, MTOMN 차단 확인 및 복귀"
    },
    "MTOMN": {
        "kr_name": "주변압기 유펌프 차단기",
        "location": "M2차 배전반 (2,4,8호차)",
        "trip_symptom": "차단 시 주변압기 유순환 불능으로 해당 M2차 MCB 투입 불능",
        "action": "해당 M2차 배전반 MTOMN, MTBMN 차단 확인 및 복귀"
    },
    "ADS": {
        "kr_name": "교·직류 절환스위치 (ADSN)",
        "location": "운전실 제어대 / 배전반",
        "trip_symptom": "위치 오류·불량 시 MCB 투입/차단 불능 (코드 1095, 18000)",
        "action": "ADS 위치 확인, 절환 후 MCB 차단불능 시 즉시 EPanDS 취급(40km/h 이하)"
    },
    "EPanDS": {
        "kr_name": "비상 판토하강 스위치",
        "location": "전·후 운전실 제어대",
        "trip_symptom": "눌림 고착 시 전 차량 판토 하강 및 전체 MCB 차단",
        "action": "시계방향 돌려 복귀 (복귀불능 시 EBCOS 취급 후 회송)"
    },
    "PanUS": {
        "kr_name": "판토 상승 스위치",
        "location": "운전실 제어대",
        "trip_symptom": "불량 시 ACM 기동 및 전 차량 판토 상승 불능 (코드 1020)",
        "action": "전후진핸들 F/R 확인 후 재취급 (불능 시 후부 운전실 상승 시도)"
    },
    "PanDN": {
        "kr_name": "판토 하강 차단기 (PanDS)",
        "location": "운전실 배전반 / 제어대",
        "trip_symptom": "차단 시 PanDS 스위치로 판토 하강 불능 (코드 1021)",
        "action": "PanDN 복귀 후 PanDS 취급 (불능 시 EPanDS 취급으로 하강)"
    },
    "PANVN": {
        "kr_name": "판토 전자밸브 차단기",
        "location": "M2차 배전반 (2,4,8호차)",
        "trip_symptom": "해당 M2차 판토 상승 불능 및 SIV·CM 정지",
        "action": "해당 차 PANVN 및 공기코크 복귀 (불능 시 수동 연장급전)"
    },
    "ACMN": {
        "kr_name": "보조공기압축기 차단기 (ACMKN)",
        "location": "M2차 배전반 (2,4,8호차)",
        "trip_symptom": "제어 공기압 미형성으로 판토 상승 불능 (코드 1156)",
        "action": "해당 M2차 ACMN, ACMKN 복귀 (10분 이상 연속구동 시 차단)"
    },
    "MDS": {
        "kr_name": "주회로 단로기 (아이솔레이션 스위치)",
        "location": "M1, M2차 하부 기기함",
        "trip_symptom": "개방 위치 시 전 차량 판토 상승 불능 및 주회로 단전",
        "action": "하부 IVS 및 MDS 핸들 정상 투입 위치 확인"
    },
    "HSCB": {
        "kr_name": "고속도차단기 (LB1,2 / K1,2)",
        "location": "M1, M2차 하부",
        "trip_symptom": "개방 시 추진 불능 (3분 내 3회 시 중고장 CUT, 2량 이상 시 자동운전 불가)",
        "action": "전후진핸들 N→(6~10초)→F 재부팅 (코드 4016)"
    },
    "LB1": {
        "kr_name": "한류차단기 1, 2 (LB1, LB2)",
        "location": "M1, M2차 하부 LB BOX",
        "trip_symptom": "개방 시 해당 M차 주회로 차단 및 추진 불능 (코드 4016)",
        "action": "전후진핸들 N→(6~10초)→F 리셋 (불능 시 CIN OFF 후 30초 뒤 ON)"
    },
    "K1": {
        "kr_name": "주회로 접촉기 (K1, K2)",
        "location": "M1, M2차 C/I 기기함 내부",
        "trip_symptom": "개방 불량 시 해당 M차 추진 불능 및 HSCB 연동 차단",
        "action": "정차 후 전후진핸들 N→(6~10초)→F 리셋 (불능 시 CIN OFF 후 30초 뒤 ON)"
    },
    "CIN": {
        "kr_name": "추진전자제어 차단기 (CIN1,2)",
        "location": "M1, M2차 배전반",
        "trip_symptom": "해당 M차 C/I 전원 상실로 동력운전·회생제동 불능 (코드 4000~4025)",
        "action": "CIN OFF 후 반드시 30초 경과 뒤 ON (LGD/GDF 고장 시 취급 금지)"
    },
    "ENCN": {
        "kr_name": "엔코더 제어 차단기 (ENCN1,2)",
        "location": "전부 운전실 배전반",
        "trip_symptom": "P/B핸들 동력운전 및 상용제동 불능 (비상제동은 가능, 코드 19000)",
        "action": "ENCN 복귀, 불능 시 관제 협의 후 EROS 'EO' 모드 운전(35km/h 이하)"
    },
    "PBN": {
        "kr_name": "주차제동 차단기 (PBBS)",
        "location": "운전실 배전반",
        "trip_symptom": "주차제동 체결 및 역행(동력운전) 불능 (코드 1011)",
        "action": "PBN 복귀 또는 대차 PB코크 차단·수동완해 손잡이 당김(PBBS ON)"
    },
    "EROS": {
        "kr_name": "비상/구원 운전모드 스위치",
        "location": "전·후 운전실 배전반",
        "trip_symptom": "R1~R3 오위치 시 비상제동 체결 및 역행 불능",
        "action": "평시 'N' 복귀 / 비상시 'EO' 모드(상시 B7 제동, 35km/h 이하, 후진불가)"
    },
    "DSD": {
        "kr_name": "데드맨 스위치 (주간제어기)",
        "location": "운전실 주간제어기 핸들",
        "trip_symptom": "3km/h 이상 시 3초 후 동력차단, 5초 후 비상제동 정차 반복 (코드 1045)",
        "action": "정차 후 P/B핸들 B7 완해 ➔ 배전반 DSDBS '바이패스' 위치 취급"
    },
    "DSDBS": {
        "kr_name": "데드맨 바이패스 스위치",
        "location": "운전실 배전반",
        "trip_symptom": "DSD 불량으로 인한 운행 중 비상제동 체결 시 바이패스용",
        "action": "비상정차 후 B7 완해 ➔ 배전반 DSDBS '바이패스' 전환 후 정상 운행"
    },
    "EBS": {
        "kr_name": "비상제동 스위치 (좌·제어대·우)",
        "location": "전·후 운전실 제어대·벽면",
        "trip_symptom": "눌림 시 비상제동 루프 개방으로 전 차량 비상제동 체결 (코드 1007, 1008)",
        "action": "전·후부 EBS 복귀 확인 (복귀불능 시 관제 보고 후 EBCOS 취급)"
    },
    "MRPS": {
        "kr_name": "주공기 압력스위치 (MRPS)",
        "location": "운전실 하부 제동배관",
        "trip_symptom": "주공기압 부족(6.0kgf/cm² 이하) 시 비상제동 안전루프 개방으로 비상제동 체결",
        "action": "주공기압(6~7kgf/cm²) 확인 및 CM 구동 상태 확인 (불능 시 EBCOS 취급)"
    },
    "EBCOS": {
        "kr_name": "비상제동 개방 스위치",
        "location": "운전실 제어대 좌측 하부",
        "trip_symptom": "비상제동 루프 불량 시 강제 완해용 (취급 시 ATS/ATC 운전 불가)",
        "action": "관제 승인 후 취급 (BVN1,3 차단 시 구름 방지를 위해 가장 마지막에 취급)"
    },
    "BVN1": {
        "kr_name": "제동밸브 차단기 1,2,3 (BVN1~3)",
        "location": "전부 운전실 배전반",
        "trip_symptom": "차단 시 비상제동 체결 (BVN1,3 차단 시 상용·정차제동 동시 불능으로 구름 위험)",
        "action": "복귀불능 시 반드시 [P/B핸들 제동 ➔ EROS 'EO' ➔ 마지막 EBCOS] 순서 취급"
    },
    "BVN2": {
        "kr_name": "제동밸브 차단기 2 (비상제동 루프)",
        "location": "전부 운전실 배전반",
        "trip_symptom": "차단 시 비상제동 안전루프 개방으로 전 차량 비상제동 체결",
        "action": "복귀불능 시 [P/B핸들 제동위치 ➔ EROS 'EO' ➔ 마지막 EBCOS] 순서 취급"
    },
    "ScBN": {
        "kr_name": "보안제동 차단기 (ScBS)",
        "location": "전·후 운전실 배전반",
        "trip_symptom": "차단 시 비상제동 체결 / 보안제동 동작(코드 1012) 시 열차 기동 불능",
        "action": "비상제동 시 복귀(불능 시 EBCOS) / 보안제동 완해불능 시 ScBN OFF 및 SBR 코크 차단"
    },
    "BOUN": {
        "kr_name": "제동제어기 차단기 (ECUN / CPRS)",
        "location": "각 차량 배전반",
        "trip_symptom": "해당 차량 제동불완해(코드 1106, 5003) 또는 제동력 부족(코드 5001)",
        "action": "EB→B7→N 반복 및 강제완해(CPRS) ➔ BOUN·ECUN 30초 후 복귀(불능 시 BC코크 차단)"
    },
    "DILN": {
        "kr_name": "출입문 연동 표시등 차단기",
        "location": "전·후 운전실 배전반",
        "trip_symptom": "전부 OFF: DOOR등 소등(역행 가능) / 후부 OFF: DOOR등 소등(역행 불능)",
        "action": "전·후 운전실 DILN ON 복귀 (원인 불명 시 관제 승인 후 DBS ON 회송)"
    },
    "DOOR": {
        "kr_name": "운전실 출입문 표시등 (DOOR등)",
        "location": "운전실 제어대 표시등 패널",
        "trip_symptom": "전 차량 출입문 완전 폐문 시 점등 (소등 시 역행 불능)",
        "action": "불량 출입문 확인 및 전·후부 배전반 DILN 확인 (불능 시 관제 승인 후 DBS ON)"
    },
    "DRN": {
        "kr_name": "출입문 계전기 차단기",
        "location": "전·후 운전실 배전반",
        "trip_symptom": "차단 시 전 편성 출입문 열림/닫힘 불능 (코드 878)",
        "action": "전 편성 닫힘불능 시 DRN OFF/ON으로 판별 (닫혔다 열리면 DCS 고착→회송)"
    },
    "DCURN": {
        "kr_name": "우측 출입문 제어유닛 차단기 (DCURN)",
        "location": "각 차량 배전반 (상단부)",
        "trip_symptom": "해당 차량 우측 출입문(R1~R4) 열림/닫힘 불능 및 역행 불가 (코드 880, 954~977)",
        "action": "해당 호차 배전반 DCURN, DICRN, DCUSN 확인 복귀 (불능 시 회송)"
    },
    "DCULN": {
        "kr_name": "좌측 출입문 제어유닛 차단기 (DCULN)",
        "location": "각 차량 배전반 (하단부)",
        "trip_symptom": "해당 차량 좌측 출입문(L1~L4) 열림/닫힘 불능 및 역행 불가 (코드 880, 954~977)",
        "action": "해당 호차 배전반 DCULN, DICLN, DCUSN 확인 복귀 (불능 시 회송)"
    },
    "DICRN": {
        "kr_name": "우측 출입문 연동 제어 차단기",
        "location": "각 차량 배전반 (상단부)",
        "trip_symptom": "차단 시 해당 차량 우측 출입문 닫힘 연동 신호 불능",
        "action": "해당 호차 배전반 DCURN, DICRN, DCUSN 차단 확인 및 복귀"
    },
    "DICLN": {
        "kr_name": "좌측 출입문 연동 제어 차단기",
        "location": "각 차량 배전반 (하단부)",
        "trip_symptom": "차단 시 해당 차량 좌측 출입문 닫힘 연동 신호 불능",
        "action": "해당 호차 배전반 DCULN, DICLN, DCUSN 차단 확인 및 복귀"
    },
    "DCUSN": {
        "kr_name": "출입문 제어유닛 전원 차단기",
        "location": "각 차량 배전반",
        "trip_symptom": "차단 시 해당 차량 DCU 제어전원 상실로 출입문 개폐 불능",
        "action": "해당 호차 배전반 DCUSN, DCURN, DCULN 차단 확인 및 복귀"
    },
    "DOS": {
        "kr_name": "출입문 열림 스위치 (DOS1~4)",
        "location": "운전실 제어대 / 측벽",
        "trip_symptom": "접점 불량 시 전 편성 출입문 열림 불능 (코드 962~969)",
        "action": "DOS 연속 3회 열림 취급 후 DRN 확인 (ZVR 불량 시 DBS ON 취급)"
    },
    "DCS": {
        "kr_name": "출입문 닫힘 스위치 (DCS)",
        "location": "운전실 제어대",
        "trip_symptom": "접점 불량·고착 시 전 편성 출입문 닫힘 불능 (코드 878, 970~977)",
        "action": "DCS 연속 3회 취급 후 DRN OFF/ON으로 고착 판별 (닫혔다 열리면 DCS 고착→회송)"
    },
    "DROS": {
        "kr_name": "출입문 재개폐 스위치 (DROS)",
        "location": "운전실 제어대",
        "trip_symptom": "접점 고착 시 출입문 계속 열림 유지 및 닫힘 불능",
        "action": "DRN OFF(폐문) ➔ DOS 개문 ➔ DOS 폐문 ➔ DRN OFF/ON 반복 운전"
    },
    "ZVR": {
        "kr_name": "영속도 계전기 (ZVR1~3)",
        "location": "운전실 배전반",
        "trip_symptom": "불량 시 정차 중에도 열차 속도를 0km/h로 인식하지 못해 전 편성 출입문 열림 불능",
        "action": "전 편성 열림 불능(ZVR 불량) 시 운전실 배전반 DBS 'ON' 취급 후 개문"
    },
    "DBS": {
        "kr_name": "출입문 바이패스 스위치",
        "location": "운전실 배전반",
        "trip_symptom": "출입문 연동 불량으로 DOOR등 소등 및 역행 불가 시 비상 회송용",
        "action": "출입문 잠금 확인 및 관제 승인 후 DBS 'ON' 취급하여 회송"
    },
    "SIVCN": {
        "kr_name": "보조전원 제어 차단기 (SIVCN1,2)",
        "location": "0, 5, 9호차 배전반",
        "trip_symptom": "SIV 고장(코드 3000~3038) 시 해당 유니트 객실등·냉난방·CM 정지",
        "action": "자동 연장급전 불능 시 고장 차(0, 5, 9호차) SIVCN OFF로 수동 연장급전"
    },
    "TCMSPN": {
        "kr_name": "TCMS 전원 차단기 (TCMSPN1,2/VDUN)",
        "location": "운전실·각 차량 배전반",
        "trip_symptom": "통신 고장 시 VDU 정지 및 판토·MCB·냉난방 제어 불가 (코드 2000~2022)",
        "action": "관제 보고 후 TCMSPN1/2 OFF ➔ 10초 대기 후 ON (화면 불량 시 VDUN 재투입)"
    }
}

NINE_SCENARIO_MASTER = {
    "동력 운전 불능 시": {
        "search_query": "3.37 동력 운전 불능 시 16004 ENCN PBN EROS",
        "ref_manual": "응급처치요령(2) 95~96p [3.37 동력 운전 불능 시]",
        "fault_codes": ["16004", "4000", "19000", "1011"],
        "cbs": ["DOOR", "ENCN", "PBN", "EROS", "CIN", "DSD"],
        "steps": [
            "DOOR등 점등 여부 및 제동 체결(보안·비상·정차·주차) 상태 TCMS 확인",
            "축전지 전압(70V 이하) 및 전차선 전압(단전 또는 850V 이하) 확인",
            "전부 운전실 배전반 ENCN(엔코더), PBN(주차제동) 차단 확인 및 복귀",
            "전·후부 운전실 EROS 스위치 'N(정상)' 위치 확인 복귀",
            "C/I 고장 시: 정차 후 [전후진핸들 N ➔ 6초 대기 ➔ F] 리셋 (불능 시 CIN OFF 후 30초 뒤 ON)",
            "조치 불능(엔코더·DSD 고장 등) 시 관제 협의 후 EROS 'EO' 모드 응급운전(35km/h 이하 회송)"
        ]
    },
    "전 차량 비상제동 체결 시": {
        "search_query": "3.43 전 차량 비상 제동 체결 시 1007 1008 EBS EBCOS BVN1 ScBN",
        "ref_manual": "응급처치요령(2) 102~103p [3.43 전 차량 비상 제동 체결 시]",
        "fault_codes": ["1007", "1008", "1045"],
        "cbs": ["EBS", "MRPS", "EBCOS", "DSD", "DSDBS", "EROS", "HCRN", "ScBN", "BVN1", "BVN2"],
        "steps": [
            "전후진핸들 위치 확인 (전부 운전실 F 또는 R / 후부 운전실 N 위치)",
            "전·후부 EBS(좌·제어대·우) 눌림 및 주공기압(MRPS 6~7kgf/cm²) 확인 (복귀불능 시 EBCOS 취급)",
            "주간제어기 DSD 불량(3km/h 이상 정차 반복) 시 배전반 DSDBS 바이패스 취급",
            "전·후부 운전실 EROS 스위치 'N' 위치 복귀 및 배전반 HCRN, ScBN 차단 복귀",
            "★ BVN1, 2 차단 복귀불능 시(구름 방지): 반드시 [P/B핸들 제동위치 ➔ EROS 'EO' ➔ 마지막 EBCOS] 순서 취급",
            "위 조치 불능 시 후부 운전실 자력운전 시도 (불능 시 구원 연결 후 전 차량 SR 코크 차단)"
        ]
    },
    "전체 MCB 투입 불능 시": {
        "search_query": "3.11 전체 주회로차단기(MCB) 투입 불능 시 1049 MCBCS MCN HCRN ADS MCBHR",
        "ref_manual": "응급처치요령(1) 64p [3.11 전체 주회로차단기(MCB) 투입 불능 시]",
        "fault_codes": ["1049", "1095", "18000"],
        "cbs": ["EPanDS", "MCN", "HCRN", "ADS", "MCBCS", "MCBHR", "MCB", "ADAN", "ADDN", "MTBMN", "MTOMN"],
        "steps": [
            "전차선 전압 및 판토그래프 상승 상태 확인",
            "운전실 제어대 비상판토하강 스위치(EPanDS) 및 공기압력계 확인",
            "운전실 배전반 MCN, HCRN 차단 여부 및 제어대 ADS(교직절환) 위치 확인",
            "투입 스위치(MCBCS) 조작 시 배전반 내 MCBHR(유지계전기) 동작음 확인",
            "투입 불능 시 후부 운전실에서 취급 (일부 MCB 미투입 시 M2차 ADAN·ADDN·MCBN1/2·MTBMN·MTOMN 확인)"
        ]
    },
    "DOOR등 점등 불능 시": {
        "search_query": "3.26 DOOR등 점등 불능 시 DILN DBS 비상핸들",
        "ref_manual": "응급처치요령(2) 79~80p [3.26 DOOR등 점등 불능 시]",
        "fault_codes": ["878", "880", "978"],
        "cbs": ["DOS", "DILN", "DBS"],
        "steps": [
            "TCMS 불량 출입문 차호 확인 및 DOS 수회 개폐 취급",
            "해당 출입문 비상핸들(EH) 정상 위치 확인 및 도어엔진 차단기 OFF/ON 후 이물질 확인",
            "전·후부 운전실 배전반 DILN 확인 (전부 OFF: 역행 가능 / 후부 OFF: 역행 불능)",
            "원인 불명 시 관제사 승인 후 운전실 배전반 DBS(출입문바이패스) 'ON' 취급 회송",
            "※ 운행 중 DOOR등 소등 시: 즉시 비상정차 후 원인 제거하고 전도 운행"
        ]
    },
    "전 차량 HSCB 차단 시": {
        "search_query": "3.34 전 차량 HSCB 차단 시 4016 LB1 LB2 K1 K2 C/I",
        "ref_manual": "응급처치요령(2) 92~93p [3.34 전 차량 HSCB 차단 시 & 3.35 C/I 고장 시]",
        "fault_codes": ["4016", "4000", "4002"],
        "cbs": ["HSCB", "LB1", "K1", "CIN", "PANVN"],
        "steps": [
            "TCMS 고장 메시지(HSCB, LB1/2, K1/2 개방) 및 고장 차호 확인 (3분 내 3회 재발 시 중고장 CUT-OUT)",
            "C/I 2개 이하 고장 시: 정차 후 [전후진핸들 N ➔ 6~10초 후 C/I 정상 확인 ➔ F] 재부팅 (3개 이상 시 차량 재기동)",
            "재부팅 불능 시 해당 동력차 CIN OFF/ON 취급 (★ 반드시 30초 경과 후 조작 / LGD·GDF 검지 시 취급 금지)",
            "복귀 불능 시 CUT 상태 유지 운행 (주회로 불량 시 해당 M2차 PANVN 차단 후 수동 연장급전)"
        ]
    },
    "전체 출입문 열리지 않을 시": {
        "search_query": "3.27 출입문이 열리지 않을 시 962 969 DCURN DCULN DRN DBS",
        "ref_manual": "응급처치요령(2) 81~82p [3.27 출입문이 열리지 않을 시]",
        "fault_codes": ["962", "963", "964", "965", "966", "967", "968", "969"],
        "cbs": ["DOS", "DRN", "ZVR", "DBS", "DCURN", "DCULN", "DICRN", "DICLN", "DCUSN"],
        "steps": [
            "[전 편성 불능] 운전실 DOS(출입문 열림 스위치) 연속 3회 열림 취급 후 운전실 배전반 DRN 상태를 확인한다.",
            "[ZVR 불량 시] 운전실 배전반의 출입문 바이패스 스위치 DBS를 'ON' 위치로 취급하고 전·후부 운전실 DOS를 취급한다.",
            "[1량 불능] 불량 차호 확인 및 DOS 수회 개폐 ➔ 해당 차 배전반 DCURN, DCULN, DICRN, DICLN, DCUSN 확인 (불능 시 회송)",
            "[수동 개방] 차량 재기동 후에도 불능 시 각 차량 출입문 1개씩 수동 개방하여 여객 하차 유도 후 회송 조치한다."
        ]
    },
    "전체 출입문 닫히지 않을 시": {
        "search_query": "3.28 출입문이 닫히지 않을 시 878 970 977 DCURN DRN DROS DCS",
        "ref_manual": "응급처치요령(2) 83~84p [3.28 전편성 출입문이 닫히지 않을 때]",
        "fault_codes": ["878", "880", "970", "971", "972", "973", "974", "975", "976", "977"],
        "cbs": ["DCS", "DRN", "DROS", "DOS", "DCURN", "DCULN", "DICRN", "DICLN", "DCUSN"],
        "steps": [
            "[전 편성 불능] 운전실 DCS 연속 3회 취급 후 운전실 배전반의 DRN을 OFF/ON하여 스위치 고착 여부를 판별한다.",
            "[고착 판별] DRN OFF/ON 시 닫혔다 열리면 DCS 고착(관제 승인 회송) / 안 열리면 DROS 고착(DRN OFF 폐문·DOS 개문 반복 운행)",
            "[1량 불능] 불량 차호 확인 및 DCS 수회 개폐 ➔ 해당 차 배전반 DCURN, DCULN, DICRN, DICLN, DCUSN 확인 (불능 시 회송)",
            "[1개 불능] 비상핸들 '비상' 절환 후 이물질 제거·폐문 ➔ 상부 점검커버 차단봉 '차단(쇄정)' ➔ 비상핸들 원복·잠금 후 운행"
        ]
    },
    "데드맨 스위치 불량 시": {
        "search_query": "3.38 데드맨스위치 불량 시 1045 DSD DSDBS EBCOS",
        "ref_manual": "응급처치요령(2) 97p [3.38 데드맨스위치 불량 시]",
        "fault_codes": ["1045"],
        "cbs": ["DSDBS", "EBCOS"],
        "steps": [
            "비상정차 후 주간제어기 P/B핸들 B7 위치에서 비상제동 완해 취급",
            "운전실 배전반 내 DSDBS(데드맨 바이패스) 스위치를 '바이패스' 위치로 취급 후 운행",
            "비상제동 완해 불능 시 관제사 통보 후 비상제동개방 스위치(EBCOS) 취급"
        ]
    },
    "전체 판토 상승 불능 시": {
        "search_query": "3.7 전 차량 판토(PANTO) 상승 불능 시 1020 PanUS HCRN EPanDS ACM",
        "ref_manual": "응급처치요령(1) 59~60p [3.7 전 차량 판토 상승 불능 시]",
        "fault_codes": ["1020", "1156"],
        "cbs": ["PanUS", "HCRN", "EBCOS", "EPanDS", "ACMN", "MDS"],
        "steps": [
            "전후진 핸들 N 위치 시 F 또는 R 위치로 전환 후 PanUS 재취급",
            "전·후부 운전실 배전반 내 HCRN 차단 확인 및 복귀 (후부 복귀불능 시 전부 EBCOS 취급 후 F/R 위치로 상승 가능, 회송)",
            "전·후부 운전실 비상판토하강 스위치(EPanDS) 확인 복귀 (복귀불능 시 EBCOS 취급하여 판토 상승 후 회송)",
            "제어 공기압 부족 시 ACM 구동(ACMN, ACMKN) 확인, 불능 시 후부 운전실 상승 시도 및 하부 IVS·MDS 확인"
        ]
    }
}

NINE_SCENARIO_MASTER["출입문 열리지 않을 시 (1개/1량/전체)"] = NINE_SCENARIO_MASTER["전체 출입문 열리지 않을 시"]
NINE_SCENARIO_MASTER["출입문 닫히지 않을 시(1개, 1량, 전체)"] = NINE_SCENARIO_MASTER["전체 출입문 닫히지 않을 시"]

STANDARD_DEVICE_RULE = {
    "차상신호장치": "차상", "차상장치": "차상", "ATC/ATS": "차상", "ATC/ATO": "차상", "차상": "차상",
    "공기/제동장치": "제동", "제동장치": "제동", "공기장치": "제동", "비상제동": "제동", "제동": "제동",
}

_STRICT_SCAN_TERMS = sorted(
    set(list(CB_RELAY_MASTER_DICT.keys()) + [
        "MCBN1/2", "MCBN1", "MCBN2", "CIN1/2", "CIN1", "CIN2",
        "ENCN1/2", "ENCN1", "ENCN2", "BVN1~3", "BVN1, 2", "BVN1,2", "BVN1,3",
        "ACMKN", "LB1/2", "K1/2", "SIVCN1", "SIVCN2", "TCMSPN1/2", "TCMSPN1", "TCMSPN2"
    ]),
    key=len,
    reverse=True
)
_STRICT_SCAN_REGEX = re.compile(
    r'(?<![A-Za-z0-9])(' + '|'.join(re.escape(k) for k in _STRICT_SCAN_TERMS) + r')(?![A-Za-z0-9])'
)
_NORM_MAP = {
    "MCBN1/2": ["MCB"], "MCBN1": ["MCB"], "MCBN2": ["MCB"],
    "CIN1/2": ["CIN"], "CIN1": ["CIN"], "CIN2": ["CIN"],
    "ENCN1/2": ["ENCN"], "ENCN1": ["ENCN"], "ENCN2": ["ENCN"],
    "BVN1~3": ["BVN1", "BVN2"], "BVN1, 2": ["BVN1", "BVN2"], "BVN1,2": ["BVN1", "BVN2"], "BVN1,3": ["BVN1"],
    "ACMKN": ["ACMN"], "LB1/2": ["LB1"], "K1/2": ["K1"],
    "SIVCN1": ["SIVCN"], "SIVCN2": ["SIVCN"],
    "TCMSPN1/2": ["TCMSPN"], "TCMSPN1": ["TCMSPN"], "TCMSPN2": ["TCMSPN"]
}


class MetroAIEngine:
    def __init__(self):
        self.db = self._load_master_db()
        self.history = self._load_fault_history()

    def _load_master_db(self) -> dict:
        if not os.path.exists(MASTER_DB_PATH):
            return {"manuals": [], "schematics": []}
        with open(MASTER_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_fault_history(self) -> list:
        if not os.path.exists(FAULT_HISTORY_PATH):
            sample = [
                {"id": 1, "date": "2026-10-05 08:15", "train_no": "461", "car_no": "4", "raw_device": "공기/제동장치", "std_device": "제동", "symptom": "비상제동 완해 불능 (1007)", "action": "EBS 확인 및 복구", "repeat_count": 1, "remark": ""},
                {"id": 2, "date": "2026-10-09 14:22", "train_no": "461", "car_no": "4", "raw_device": "공기/제동장치", "std_device": "제동", "symptom": "4호차 제동불완해 (1106)", "action": "BOUN 재투입 및 코크 확인", "repeat_count": 2, "remark": ""},
                {"id": 3, "date": "2026-10-11 11:10", "train_no": "455", "car_no": "0", "raw_device": "차상신호장치", "std_device": "차상", "symptom": "ATC/ATS 통신 고장 (11000)", "action": "신호장치 리셋 및 관제 보고", "repeat_count": 1, "remark": ""},
                {"id": 4, "date": "2026-10-13 16:40", "train_no": "455", "car_no": "0", "raw_device": "차상신호장치", "std_device": "차상", "symptom": "ATC NO CODE 비상제동 (11000)", "action": "관제 승인 AFS 비상모드 운전", "repeat_count": 2, "remark": ""}
            ]
            with open(FAULT_HISTORY_PATH, "w", encoding="utf-8") as f:
                json.dump(sample, f, ensure_ascii=False, indent=2)
            return sample
        with open(FAULT_HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def reset_fault_history(self):
        self.history = []
        with open(FAULT_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

    def _extract_cbs_from_steps(self, steps: list, fallback_cbs: list) -> list:
        extracted = []
        for line in steps:
            clean_l = re.sub(r'<[^>]*>', '', line)
            for m in _STRICT_SCAN_REGEX.finditer(clean_l):
                raw_tok = m.group(0)
                for tok in _NORM_MAP.get(raw_tok, [raw_tok]):
                    for master_k in CB_RELAY_MASTER_DICT:
                        if tok.upper() == master_k.upper():
                            if master_k not in extracted:
                                extracted.append(master_k)
                            break
        return extracted if extracted else list(fallback_cbs)

    def _build_cb_table_rows(self, cb_keys: list) -> list:
        rows = []
        seen = set()
        for key in cb_keys:
            norm_key = key
            if key not in CB_RELAY_MASTER_DICT:
                for master_k in CB_RELAY_MASTER_DICT:
                    if key.upper() == master_k.upper():
                        norm_key = master_k
                        break
                if norm_key not in CB_RELAY_MASTER_DICT:
                    for master_k in CB_RELAY_MASTER_DICT:
                        if key.startswith(master_k) or master_k.startswith(key):
                            norm_key = master_k
                            break
            if norm_key in CB_RELAY_MASTER_DICT and norm_key not in seen:
                seen.add(norm_key)
                info = CB_RELAY_MASTER_DICT[norm_key]
                rows.append({
                    "기기 약어 및 명칭": f"{norm_key} ({info['kr_name']})",
                    "설치 위치": info["location"],
                    "트립(차단) 및 불량 시 증상": info["trip_symptom"],
                    "핵심 확인 및 조치요령": info["action"]
                })
        return rows

    def search_integrated(self, query: str, top_k: int = 6) -> dict:
        q_clean = query.strip()
        scenario = NINE_SCENARIO_MASTER.get(q_clean)
        actual_query = scenario["search_query"] if scenario else q_clean

        tokens = [t.strip() for t in re.split(r'[\s,./()~]+', actual_query) if len(t.strip()) >= 1]
        code_tokens = [t for t in tokens if t.isdigit() and 3 <= len(t) <= 5]

        manual_results = []
        for doc in self.db.get("manuals", []):
            score = 0
            title = doc.get("title", "")
            content = doc.get("content", "")
            doc_codes = doc.get("fault_codes", [])
            doc_cbs = doc.get("related_cbs", [])
            is_emerg = doc.get("is_emergency", False)
            doc_type = doc.get("doc_type", "")

            if "목차" in content[:100] or "Contents" in content[:100] or "장애유형 Page" in content:
                score -= 60

            for ct in code_tokens:
                if ct in doc_codes:
                    score += 180
                elif ct in content:
                    score += 70

            if q_clean in title:
                score += 90
            elif q_clean in content:
                score += 50

            for t in tokens:
                if len(t) < 2:
                    continue
                if t.lower() in title.lower():
                    score += 30
                if t in doc_cbs:
                    score += 25
                cnt = content.lower().count(t.lower())
                if cnt > 0:
                    score += min(cnt * 6, 30)

            if score > 0:
                if is_emerg and "Part 03" in content:
                    score += 100
                elif is_emerg:
                    score += 75
                elif doc_type == "FAULT_MANUAL" and code_tokens:
                    score += 65

            if score > 0:
                d_copy = dict(doc)
                d_copy["score"] = score
                manual_results.append(d_copy)

        manual_results.sort(key=lambda x: x["score"], reverse=True)
        top_manuals = manual_results[:top_k]

        if scenario:
            linked_cbs = self._extract_cbs_from_steps(scenario["steps"], scenario["cbs"])
        else:
            linked_cbs = []
            for m in top_manuals[:2]:
                for cb in m.get("related_cbs", []):
                    if cb not in linked_cbs:
                        linked_cbs.append(cb)

        return {
            "query": q_clean,
            "keywords": tokens,
            "code_tokens": code_tokens,
            "linked_cbs": linked_cbs,
            "manuals": top_manuals
        }

    def generate_ai_briefing(self, query: str, search_res: dict) -> dict:
        q_clean = query.strip()
        top_manuals = search_res.get("manuals", [])
        linked_cbs = search_res.get("linked_cbs", [])

        if q_clean in NINE_SCENARIO_MASTER:
            sc = NINE_SCENARIO_MASTER[q_clean]
            strict_cbs = self._extract_cbs_from_steps(sc["steps"], sc["cbs"])
            cb_rows = self._build_cb_table_rows(strict_cbs)
            return {
                "title": q_clean,
                "summary": f"📌 [매칭 기준] {sc['ref_manual']} | 고장코드: {', '.join(sc['fault_codes'])}",
                "cb_table": cb_rows,
                "checklist": sc["steps"],
                "cbs": strict_cbs
            }

        if not top_manuals:
            return {
                "title": q_clean,
                "summary": "일치하는 매뉴얼이 없습니다. 고장코드(예: 1049, 4001, 878) 또는 장치명(MCB, EBS)으로 검색하세요.",
                "cb_table": self._build_cb_table_rows(["MCB", "HCRN", "EBS", "DILN"]),
                "checklist": ["TCMS 고장코드 및 호차 확인", "전차선 전압·축전지 전압·주공기(MR) 압력 확인"],
                "cbs": ["MCB", "HCRN", "EBS", "DILN"]
            }

        best_doc = top_manuals[0]
        emerg_doc = next((m for m in top_manuals if m.get("is_emergency")), best_doc)

        target_content = emerg_doc["content"] + "\n" + (best_doc["content"] if best_doc["id"] != emerg_doc["id"] else "")
        raw_lines = target_content.split("\n")
        extracted_steps = []

        noise_patterns = re.compile(
            r'^(서울교통공사|Part\s*0[123]|고장코드|고장등급|고장분류|관리번호|차량위치|페이지|관련\s*사진|참고|플로우차트|'
            r'[0-9]+/[0-9]+|[0-9]{1,3}$|\*?\s*원인\s*및\s*조치|1\.\s*원\s*인|2\.\s*조치|점검\s*및\s*조치방법|고장조치\s*방법)'
        )

        for line in raw_lines:
            s = line.strip()
            if len(s) < 6 or noise_patterns.match(s):
                continue
            if re.match(r'^([0-9]{1,2}[\)\.]|[①-⑩])', s) or any(
                w in s for w in ["확인", "투입", "차단", "취급", "복귀", "운전", "개방", "조치", "스위치", "코크", "리셋", "Reset", "교체"]
            ):
                clean_s = re.sub(r'^([0-9]{1,2}[\)\.]|[①-⑩]|[-•▶▷※●])\s*', '', s).strip()
                if len(clean_s) >= 6 and clean_s not in extracted_steps:
                    extracted_steps.append(clean_s[:85])

        if not extracted_steps:
            extracted_steps = [l.strip()[:85] for l in raw_lines if len(l.strip()) > 8][:5]

        checklist_final = extracted_steps[:6]
        strict_cbs = self._extract_cbs_from_steps(checklist_final, linked_cbs)
        cb_rows = self._build_cb_table_rows(strict_cbs)
        if not cb_rows:
            fallback_cbs = ["BOUN", "EBS", "BVN1"] if "제동" in target_content else (
                ["DOS", "DILN", "DBS"] if "출입문" in target_content else ["TCMSPN", "HCRN", "MCB"]
            )
            cb_rows = self._build_cb_table_rows(fallback_cbs)
            strict_cbs = fallback_cbs

        codes_str = ", ".join(best_doc.get("fault_codes", [])[:5]) or "해당 없음"
        return {
            "title": best_doc["title"],
            "summary": f"📌 [1순위 매칭] {best_doc['source_file']} ({best_doc['page']}p) | 고장코드: {codes_str}",
            "cb_table": cb_rows[:8],
            "checklist": checklist_final,
            "cbs": strict_cbs[:8]
        }

    def evaluate_and_record_fault(self, train_no: str, car_no: str, raw_device: str, symptom: str, action: str) -> dict:
        train_no, car_no = str(train_no).strip(), str(car_no).strip()
        std_device = STANDARD_DEVICE_RULE.get(raw_device, raw_device)
        prev = [
            h for h in self.history
            if str(h.get("train_no")) == train_no and str(h.get("car_no")) == car_no and h.get("std_device") == std_device
        ]
        current_count = len(prev) + 1
        is_repeat = current_count >= 3
        remark_val = std_device if is_repeat else ""

        entry = {
            "id": len(self.history) + 1,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "train_no": train_no, "car_no": car_no, "raw_device": raw_device,
            "std_device": std_device, "symptom": symptom, "action": action,
            "repeat_count": current_count, "remark": remark_val
        }
        self.history.append(entry)
        with open(FAULT_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

        return {
            "is_repeat_alert": is_repeat,
            "alert_msg": (
                f"🚨 [반복고장 경보] {train_no}편성 {car_no}호차 '{std_device}' {current_count}회차! 비고란 '{remark_val}' 자동 표기"
                if is_repeat else
                f"✅ 등록 완료 ({train_no}편성 {car_no}호차 '{std_device}' 누적 {current_count}회차)"
            )
        }