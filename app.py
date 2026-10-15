import os
import sys
import re
import json
import time
import socket
import fitz
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from core_engine import MetroAIEngine, NINE_SCENARIO_MASTER, CB_RELAY_MASTER_DICT, FAULT_HISTORY_PATH

# [핵심 패치] 일반 파이썬 실행과 EXE 실행 모두에서 현재 폴더 경로를 100% 정확히 인식
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RAW_DIR = os.path.join(BASE_DIR, "data_raw")
SCHEMATIC_PDF_NAME = "(4호선 210칸) 회로도면집.pdf"

st.set_page_config(
    page_title="서울교통공사 제1관제센터 | 4호선 210칸 AI 통합 관제 시스템",
    page_icon="🚇",
    layout="wide",
    initial_sidebar_state="expanded"
)

def get_current_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

EXTRA_CB_SPECS = {
    "DCULN": {
        "kr_name": "좌측 출입문 제어유닛 차단기",
        "location": "각 차량 배전반 (하단부)",
        "trip_symptom": "해당 차량 좌측 출입문(L1~L4) 열림/닫힘 불능 및 역행 불가",
        "action": "해당 호차 배전반 DCULN, DICLN 확인 및 복귀 (불능 시 회송)"
    },
    "DOS": {
        "kr_name": "출입문 열림 스위치 (DOS1~4)",
        "location": "운전실 제어대 / 측벽",
        "trip_symptom": "접점 불량 시 출입문 개폐 불량 및 DOOR등 점등 불능",
        "action": "운전실 DOS 수회 개폐 취급 후 표시등 및 출입문 상태 확인"
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
    "BVN2": {
        "kr_name": "제동밸브 차단기 2 (비상제동 루프)",
        "location": "전부 운전실 배전반",
        "trip_symptom": "차단 시 비상제동 안전루프 개방으로 전 차량 비상제동 체결",
        "action": "복귀불능 시 [P/B핸들 제동위치 ➔ EROS 'EO' ➔ 마지막 EBCOS] 순서 취급"
    },
    "DSDBS": {
        "kr_name": "데드맨 바이패스 스위치",
        "location": "운전실 배전반",
        "trip_symptom": "주간제어기 데드맨(DSD) 불량 시 비상제동 완해 및 바이패스용",
        "action": "정차 후 P/B핸들 B7 완해 ➔ 배전반 DSDBS '바이패스' 위치 취급"
    },
    "MCBHR": {
        "kr_name": "주회로차단기 유지계전기",
        "location": "운전실 배전반",
        "trip_symptom": "무여자 시 전체 주회로차단기(MCB) 투입 불능 (코드 1049)",
        "action": "MCBCS 조작 시 배전반 내 MCBHR 동작음 확인"
    }
}
for _k, _v in EXTRA_CB_SPECS.items():
    if _k not in CB_RELAY_MASTER_DICT:
        CB_RELAY_MASTER_DICT[_k] = _v

CUSTOM_CSS = """
<style>
.block-container {
    padding-top: 1.0rem !important;
    padding-bottom: 2.5rem !important;
    max-width: 98% !important;
}
section[data-testid="stSidebar"] {
    min-width: 330px !important;
    max-width: 350px !important;
}
section[data-testid="stSidebar"] .block-container {
    padding-top: 1.0rem !important;
    padding-left: 0.9rem !important;
    padding-right: 0.9rem !important;
}
.main-header {
    background: linear-gradient(90deg, #090d16 0%, #1e3a8a 55%, #0369a1 100%);
    color: #ffffff;
    padding: 18px 26px;
    border-radius: 14px;
    border: 3px solid #38bdf8;
    margin-bottom: 12px;
    box-shadow: 0 6px 16px rgba(0,0,0,0.25);
}
.main-header h2 {
    margin: 0;
    font-size: 2.1rem !important;
    font-weight: 900 !important;
    color: #ffffff !important;
    letter-spacing: -0.5px;
}
.main-header p {
    margin: 6px 0 0 0;
    font-size: 1.25rem !important;
    color: #fde047 !important;
    font-weight: 900 !important;
}
.car-box-ok {
    background: #f0f9ff;
    border: 3px solid #0284c7;
    border-radius: 12px;
    padding: 8px 4px;
    text-align: center;
    box-sizing: border-box;
    width: 100%;
}
.car-box-ok .c-num { font-size: 1.35rem; font-weight: 900; color: #0f172a; }
.car-box-ok .c-type { font-size: 0.92rem; font-weight: 900; color: #334155; }
.car-box-ok .c-st { font-size: 1.15rem; font-weight: 900; color: #0369a1; margin-top: 2px; }
.car-box-err {
    background: #fef2f2;
    border: 4px solid #dc2626;
    border-radius: 12px;
    padding: 8px 4px;
    text-align: center;
    box-sizing: border-box;
    width: 100%;
    box-shadow: 0 0 14px rgba(220,38,38,0.45);
}
.car-box-err .c-num { font-size: 1.4rem; font-weight: 900; color: #991b1b; }
.car-box-err .c-type { font-size: 0.92rem; font-weight: 900; color: #7f1d1d; }
.car-box-err .c-st { font-size: 1.2rem; font-weight: 900; color: #dc2626; margin-top: 2px; }
.target-banner {
    background: #fffbeb;
    border-left: 12px solid #d97706;
    border-top: 3px solid #f59e0b;
    border-right: 3px solid #f59e0b;
    border-bottom: 3px solid #f59e0b;
    border-radius: 12px;
    padding: 12px 18px;
    margin: 10px 0;
    font-size: 1.35rem;
    font-weight: 900;
    color: #0f172a;
    line-height: 1.4;
    word-break: keep-all;
    box-sizing: border-box;
}
.search-banner-box {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
    color: #fde047;
    font-size: 1.15rem;
    font-weight: 900;
    padding: 10px 8px;
    border-radius: 10px 10px 0 0;
    border: 3px solid #0f172a;
    border-bottom: none;
    margin-top: 6px;
    text-align: center;
    line-height: 1.35;
    word-break: keep-all;
    overflow: hidden;
    width: 100%;
    box-sizing: border-box;
}
.sidebar-field-label {
    font-size: 1.35rem !important;
    font-weight: 900 !important;
    color: #0f172a !important;
    background: #e0f2fe;
    border-left: 8px solid #0284c7;
    padding: 8px 12px;
    border-radius: 6px;
    margin-top: 12px;
    margin-bottom: 6px;
    box-sizing: border-box;
}
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
    min-height: 54px !important;
    background-color: #ffffff !important;
    border: 3px solid #0284c7 !important;
    border-radius: 10px !important;
    padding: 4px 10px !important;
    box-sizing: border-box !important;
}
div[data-testid="stSelectbox"] div[data-baseweb="select"] span,
div[data-testid="stSelectbox"] div[data-baseweb="select"] div {
    font-size: 1.28rem !important;
    font-weight: 900 !important;
    color: #0f172a !important;
    line-height: 1.3 !important;
}
ul[role="listbox"] li {
    font-size: 1.22rem !important;
    font-weight: 900 !important;
    color: #0f172a !important;
}
.stButton > button[kind="secondary"] {
    height: auto !important;
    min-height: 56px !important;
    padding: 12px 14px !important;
    border: 3px solid #475569 !important;
    border-radius: 12px !important;
    background-color: #ffffff !important;
    box-sizing: border-box !important;
    box-shadow: 0 2px 5px rgba(0,0,0,0.08) !important;
}
.stButton > button[kind="secondary"]:hover {
    border-color: #dc2626 !important;
    background-color: #fef2f2 !important;
    transform: translateY(-1px);
}
.stButton > button[kind="secondary"] p {
    font-size: 1.32rem !important;
    font-weight: 900 !important;
    color: #0f172a !important;
    line-height: 1.3 !important;
    word-break: keep-all !important;
    white-space: normal !important;
    margin: 0 !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="secondary"] {
    height: 54px !important;
    min-height: 54px !important;
    max-height: 54px !important;
    width: 100% !important;
    padding: 4px 6px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    border: 3px solid #334155 !important;
    border-radius: 10px !important;
    box-sizing: border-box !important;
    overflow: hidden !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="secondary"] p {
    font-size: 1.12rem !important;
    font-weight: 900 !important;
    color: #0f172a !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    line-height: 1.2 !important;
    margin: 0 !important;
}
div[data-testid="stHorizontalBlock"]:has(button[kind="primary"]) button[kind="secondary"] {
    background: linear-gradient(145deg, #090d16 0%, #0f172a 100%) !important;
    border: 3px solid #f59e0b !important;
    border-radius: 14px !important;
    height: 98px !important;
    min-height: 98px !important;
    padding: 10px 6px !important;
    box-shadow: 0 6px 14px rgba(0,0,0,0.28) !important;
}
div[data-testid="stHorizontalBlock"]:has(button[kind="primary"]) button[kind="secondary"] p {
    color: #fde047 !important;
    font-size: 1.32rem !important;
    font-weight: 900 !important;
    line-height: 1.35 !important;
    white-space: pre-line !important;
    word-break: keep-all !important;
    text-align: center !important;
}
div[data-testid="stHorizontalBlock"]:has(button[kind="primary"]) button[kind="secondary"]:hover {
    border-color: #38bdf8 !important;
    background: #1e293b !important;
}
div[data-testid="stHorizontalBlock"]:has(button[kind="primary"]) button[kind="primary"] {
    background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%) !important;
    border: 4px solid #fde047 !important;
    border-bottom: 9px solid #fde047 !important;
    border-radius: 14px !important;
    height: 98px !important;
    min-height: 98px !important;
    padding: 10px 6px !important;
    box-shadow: 0 6px 18px rgba(220, 38, 38, 0.55) !important;
}
div[data-testid="stHorizontalBlock"]:has(button[kind="primary"]) button[kind="primary"] p {
    color: #ffffff !important;
    font-size: 1.35rem !important;
    font-weight: 900 !important;
    line-height: 1.35 !important;
    white-space: pre-line !important;
    word-break: keep-all !important;
    text-align: center !important;
}
section[data-testid="stSidebar"] .stTextInput input {
    font-size: 1.08rem !important;
    font-weight: 900 !important;
    color: #991b1b !important;
    background-color: #fef9c3 !important;
    padding: 10px 6px !important;
    border: 3px solid #dc2626 !important;
    border-radius: 0 0 10px 10px !important;
    text-align: center !important;
    box-sizing: border-box !important;
    box-shadow: 0 4px 10px rgba(220,38,38,0.18) !important;
}
.stTextInput input {
    font-size: 1.35rem !important;
    font-weight: 900 !important;
    color: #991b1b !important;
    background-color: #fef9c3 !important;
    padding: 12px 14px !important;
    border: 3px solid #dc2626 !important;
    border-radius: 10px !important;
}
.section-title {
    font-size: 1.75rem;
    font-weight: 900;
    color: #0f172a;
    margin: 14px 0 12px 0;
    padding-bottom: 6px;
    border-bottom: 4px solid #1e3a8a;
}
.step-card {
    background: #ffffff;
    border-left: 14px solid #dc2626;
    border-top: 3px solid #0f172a;
    border-right: 3px solid #0f172a;
    border-bottom: 3px solid #0f172a;
    border-radius: 12px;
    padding: 16px 22px;
    margin-bottom: 12px;
    font-size: 1.52rem !important;
    font-weight: 900 !important;
    color: #0f172a;
    line-height: 1.48;
    word-break: keep-all;
    overflow-wrap: break-word;
    box-sizing: border-box;
    width: 100%;
    box-shadow: 0 3px 6px rgba(0,0,0,0.06);
}
.step-num-badge {
    display: inline-block;
    background: #dc2626;
    color: #ffffff;
    font-weight: 900;
    font-size: 1.4rem;
    padding: 4px 16px;
    border-radius: 8px;
    margin-right: 14px;
    vertical-align: middle;
}
.cb-master-table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    margin: 10px 0 22px 0;
    background: #ffffff;
    border: 4px solid #0f172a;
}
.cb-master-table th {
    background-color: #0f172a !important;
    color: #fde047 !important;
    font-weight: 900 !important;
    font-size: 1.42rem !important;
    padding: 16px 12px;
    text-align: center;
    border: 2px solid #475569;
    word-break: keep-all;
}
.cb-master-table td {
    padding: 16px 14px;
    border: 2px solid #475569;
    vertical-align: middle;
    line-height: 1.45;
    color: #0f172a;
    font-size: 1.35rem !important;
    font-weight: 900 !important;
    word-break: keep-all;
    overflow-wrap: break-word;
    box-sizing: border-box;
}
.cb-master-table tr:nth-child(even) { background-color: #f8fafc; }
.loc-badge {
    display: block;
    width: 100%;
    box-sizing: border-box;
    background: #e0f2fe;
    color: #0f172a;
    font-weight: 900;
    font-size: 1.28rem;
    padding: 12px 8px;
    border-radius: 10px;
    border: 3px solid #0284c7;
    text-align: center;
    line-height: 1.35;
    word-break: keep-all;
}
.symptom-text { display: block; color: #b91c1c; font-weight: 900; font-size: 1.35rem; line-height: 1.45; word-break: keep-all; }
.action-text { display: block; color: #0f172a; font-weight: 900; font-size: 1.35rem; line-height: 1.45; word-break: keep-all; }
.hl-tag-bar {
    background: #0f172a;
    border: 4px solid #f59e0b;
    border-radius: 12px;
    padding: 16px 20px;
    margin: 10px 0 16px 0;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    box-sizing: border-box;
}
.hl-tag-title { color: #fde047; font-size: 1.45rem; font-weight: 900; margin-right: 10px; }
.hl-chip {
    background: #dc2626;
    color: #ffffff;
    border: 3px solid #fde047;
    border-radius: 30px;
    padding: 8px 20px;
    font-size: 1.42rem;
    font-weight: 900;
}
.report-table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    font-size: 1.28rem;
    font-weight: 900;
    text-align: center;
    background: white;
    color: #0f172a;
    border: 4px solid #0f172a;
}
.report-table th, .report-table td {
    border: 2px solid #475569;
    padding: 14px 10px;
    word-break: keep-all;
    box-sizing: border-box;
}
.report-table th { background-color: #0f172a; font-size: 1.32rem; font-weight: 900; color: #fde047; }
.badge-repeat {
    display: inline-block;
    background: #dc2626;
    color: white;
    padding: 8px 14px;
    border-radius: 8px;
    font-size: 1.22rem;
    font-weight: 900;
}
.roi-card {
    background: linear-gradient(145deg, #090d16 0%, #0f172a 100%);
    border: 4px solid #f59e0b;
    border-radius: 14px;
    padding: 22px 16px;
    text-align: center;
    box-shadow: 0 6px 14px rgba(0,0,0,0.25);
    box-sizing: border-box;
}
.roi-val { font-size: 2.35rem; font-weight: 900; color: #fde047; margin: 10px 0; word-break: keep-all; }
.roi-lbl { font-size: 1.35rem; font-weight: 900; color: #38bdf8; word-break: keep-all; }

/* 📱 스마트폰(모바일 앱) 화면 자동 최적화 미디어 쿼리 */
@media screen and (max-width: 768px) {
    .block-container {
        padding-top: 0.5rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
        max-width: 100% !important;
    }
    .main-header { padding: 12px 14px !important; }
    .main-header h2 { font-size: 1.35rem !important; line-height: 1.3 !important; }
    .main-header p { font-size: 0.95rem !important; line-height: 1.3 !important; }
    .step-card { font-size: 1.2rem !important; padding: 12px 14px !important; }
    .step-num-badge { font-size: 1.1rem !important; padding: 3px 10px !important; }
    .cb-master-table, .report-table {
        display: block !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
    }
    .cb-master-table th, .cb-master-table td,
    .report-table th, .report-table td {
        font-size: 1.05rem !important;
        padding: 10px 8px !important;
        min-width: 110px !important;
    }
    div[data-testid="stHorizontalBlock"]:has(button[kind="primary"]) button {
        height: 76px !important;
        min-height: 76px !important;
        margin-bottom: 4px !important;
    }
    div[data-testid="stHorizontalBlock"]:has(button[kind="primary"]) button p {
        font-size: 1.12rem !important;
    }
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

CUSTOM_NINE_SCENARIOS = {
    "동력 운전 불능 시": "동력 운전 불능 시",
    "전 차량 비상제동 체결 시": "전 차량 비상제동 체결 시",
    "전체 MCB 투입 불능 시": "전체 MCB 투입 불능 시",
    "DOOR등 점등 불능 시": "DOOR등 점등 불능 시",
    "전 차량 HSCB 차단 시": "전 차량 HSCB 차단 시",
    "전체 출입문 열리지 않을 시": "전체 출입문 열리지 않을 시",
    "전체 출입문 닫히지 않을 시": "전체 출입문 닫히지 않을 시",
    "데드맨 스위치 불량 시": "데드맨 스위치 불량 시",
    "전체 판토 상승 불능 시": "전체 판토 상승 불능 시"
}

STRICT_CB_RELAY_SWITCH_TERMS = sorted(
    set(list(CB_RELAY_MASTER_DICT.keys()) + [
        "MCBN1/2", "MCBN1", "MCBN2", "MCBHR", "MCBOS", "MCBCS",
        "ADAN", "ADDN", "MTBMN", "MTOMN", "ACMKN", "ACMN",
        "CIN1/2", "CIN1", "CIN2", "ENCN1/2", "ENCN1", "ENCN2",
        "BVN1~3", "BVN1, 2", "BVN1,2", "BVN1,3", "BVN1", "BVN2", "BVN3",
        "DSDBS", "DSD", "EBCOS", "HBCOS", "PBBS", "PBRS", "PBN",
        "ScBN", "ScBS", "BOUN", "ECUN", "CPRS", "SBR", "MRPS",
        "DCURN", "DCULN", "DICRN", "DICLN", "DCUSN", "DILN", "DRN",
        "DROS", "DCS", "DOS", "DBS", "LOS", "DIR1", "ZVR",
        "SIVCN1", "SIVCN2", "SIVCN", "TCMSPN1/2", "TCMSPN1", "TCMSPN2", "VDUN",
        "EPanDS", "PanUS", "PanDS", "PANVN", "EROS", "EBS", "HSCB", "LB1", "LB2", "K1", "K2"
    ]),
    key=len,
    reverse=True
)

_CB_REGEX_PATTERN = re.compile(
    r'(?<![A-Za-z0-9])(' + '|'.join(re.escape(k) for k in STRICT_CB_RELAY_SWITCH_TERMS) + r')(?![A-Za-z0-9])'
)

def emphasize_keywords_html(text: str, font_size: str = "1.45rem") -> str:
    clean_text = re.sub(r'<[^>]*>', '', text)
    return _CB_REGEX_PATTERN.sub(
        lambda m: f'<span style="color: #dc2626; font-size: {font_size}; font-weight: 900; text-decoration: underline;">{m.group(0)}</span>',
        clean_text
    )

_NORM_TOKEN_MAP = {
    "MCBN1/2": ["MCB"], "MCBN1": ["MCB"], "MCBN2": ["MCB"],
    "CIN1/2": ["CIN"], "CIN1": ["CIN"], "CIN2": ["CIN"],
    "ENCN1/2": ["ENCN"], "ENCN1": ["ENCN"], "ENCN2": ["ENCN"],
    "BVN1~3": ["BVN1", "BVN2"], "BVN1, 2": ["BVN1", "BVN2"], "BVN1,2": ["BVN1", "BVN2"], "BVN1,3": ["BVN1"],
    "ACMKN": ["ACMN"], "SIVCN1": ["SIVCN"], "SIVCN2": ["SIVCN"],
    "TCMSPN1/2": ["TCMSPN"], "TCMSPN1": ["TCMSPN"], "TCMSPN2": ["TCMSPN"]
}

def extract_strict_cbs_from_checklist(checklist_lines: list, fallback_cbs: list) -> list:
    extracted = []
    for line in checklist_lines:
        clean_l = re.sub(r'<[^>]*>', '', line)
        for m in _CB_REGEX_PATTERN.finditer(clean_l):
            raw_tok = m.group(0)
            mapped_list = _NORM_TOKEN_MAP.get(raw_tok, [raw_tok])
            for tok in mapped_list:
                for master_k in CB_RELAY_MASTER_DICT:
                    if tok.upper() == master_k.upper():
                        if master_k not in extracted:
                            extracted.append(master_k)
                        break
    return extracted if extracted else list(fallback_cbs)

def build_complete_cb_rows(cb_keys: list) -> list:
    rows = []
    seen = set()
    for key in cb_keys:
        norm_key = key
        if key not in CB_RELAY_MASTER_DICT:
            for master_k in CB_RELAY_MASTER_DICT:
                if key.upper() == master_k.upper():
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

PRECISION_MANUAL_DB = {
    "4001": {
        "title": "C/I 배터리 제어전원 이상 (고장코드 4001)",
        "summary": "📌 [매칭 기준] 고장조치매뉴얼(1) 3~5p [1.1 C/I 배터리 제어전원 이상] | 고장코드: 4001",
        "cbs": ["CIN", "HSCB"],
        "checklist": [
            "TCMS 화면 하단부 고장 메시지(4001) 및 고장 발생 동력차(M차) 호차를 확인한다.",
            "고장 차호 일반배전반의 추진전자제어 차단기(CIN) 또는 인버터 내부 OPER S/W를 OFF/ON 하여 리셋한다.",
            "정상 복귀 시 자동 복귀된 것으로 정상 운행하고, 3분 내 3회 이상 재발 시 중고장 CUT-OUT 처리한다.",
            "M차 2량 이상 CUT-OUT 시 자동운전 불가하므로 수동운전으로 전환하여 운행한다."
        ]
    },
    "878": {
        "title": "전체 출입문 닫히지 않음 / 공기질 개선장치 점등 안됨 (고장코드 878)",
        "summary": "📌 [매칭 기준] 고장조치매뉴얼(2) 391~393p [7.1 전체 출입문 닫히지 않음] | 고장코드: 878",
        "cbs": ["DRN", "DILN", "DOS", "DBS"],
        "checklist": [
            "TCMS 화면에서 출입문 닫힘 상태를 확인하고, 운전실 일반배전반 출입문 계전기 차단기(DRN) 및 DILN 상태를 확인한다.",
            "재개폐 명령(DOS)을 부여하여 정상 닫힘 여부를 확인하고, 이물질 유무를 철저히 점검한다.",
            "비상핸들 복귀 상태 및 도어 바이패스 스위치 DBS가 '자동' 위치에 있는지 확인한다.",
            "지속적인 불량 발생 시 수동으로 도어를 락킹(쇄정)한 후 DBS를 '수동' 위치로 전환하고 계속 운행한다."
        ]
    },
    "전체 출입문 닫히지 않을 시": {
        "title": "전체 출입문 닫히지 않음 조치 (응급처치요령 83~84p)",
        "summary": "📌 [매칭 기준] 응급처치요령(2) 83~84p [3.28 출입문이 닫히지 않을 시] | 고장코드: 878, 970~977",
        "cbs": ["DCS", "DRN", "DROS", "DOS", "DCURN", "DCULN"],
        "checklist": [
            "[전 편성 불능] 운전실 DCS 연속 3회 취급 후 운전실 배전반의 DRN을 OFF/ON하여 스위치 고착 여부를 판별한다.",
            "[고착 판별] DRN OFF/ON 시 닫혔다 열리면 DCS 고착(관제 승인 회송) / 안 열리면 DROS 고착(DRN OFF 폐문·DOS 개문 반복 운행)",
            "[1량 불능] 불량 차호 확인 및 DCS 수회 개폐 ➔ 해당 차 배전반 DCURN, DCULN, DICRN, DICLN, DCUSN 확인 (불능 시 회송)",
            "[1개 불능] 비상핸들 '비상' 절환 후 이물질 제거·폐문 ➔ 상부 점검커버 차단봉 '차단(쇄정)' ➔ 비상핸들 원복·잠금 후 운행"
        ]
    },
    "전체 출입문 열리지 않을 시": {
        "title": "전체 출입문 열리지 않음 조치 (응급처치요령 81~82p)",
        "summary": "📌 [매칭 기준] 응급처치요령(2) 81~82p [3.27 출입문이 열리지 않을 시] | 고장코드: 962~969",
        "cbs": ["DOS", "DRN", "DBS", "DCURN", "DCULN"],
        "checklist": [
            "[전 편성 불능] 운전실 DOS(출입문 열림 스위치) 연속 3회 열림 취급 후 운전실 배전반 DRN 상태를 확인한다.",
            "[ZVR 불량 시] 운전실 배전반의 출입문 바이패스 스위치 DBS를 'ON' 위치로 취급하고 전·후부 운전실 DOS를 취급한다.",
            "[1량 불능] 불량 차호 확인 및 DOS 수회 개폐 ➔ 해당 차 배전반 DCURN, DCULN, DICRN, DICLN, DCUSN 확인 (불능 시 회송)",
            "[수동 개방] 차량 재기동 후에도 불능 시 각 차량 출입문 1개씩 수동 개방하여 여객 하차 유도 후 회송 조치한다."
        ]
    }
}

DIRECT_CODE_AND_CB_MAP = {
    "4001": "4001", "878": "878",
    "전체 출입문 닫히지 않을 시": "전체 출입문 닫히지 않을 시",
    "전체 출입문 열리지 않을 시": "전체 출입문 열리지 않을 시",
    "1049": "전체 MCB 투입 불능 시", "MCB": "전체 MCB 투입 불능 시",
    "MCBCS": "전체 MCB 투입 불능 시", "MCBHR": "전체 MCB 투입 불능 시",
    "MCN": "전체 MCB 투입 불능 시", "ADS": "전체 MCB 투입 불능 시",
    "16004": "동력 운전 불능 시", "ENCN": "동력 운전 불능 시",
    "PBN": "동력 운전 불능 시", "EROS": "동력 운전 불능 시",
    "1007": "전 차량 비상제동 체결 시", "1008": "전 차량 비상제동 체결 시",
    "EBS": "전 차량 비상제동 체결 시", "EBCOS": "전 차량 비상제동 체결 시",
    "BVN1": "전 차량 비상제동 체결 시", "BVN2": "전 차량 비상제동 체결 시", "SCBN": "전 차량 비상제동 체결 시",
    "DILN": "DOOR등 점등 불능 시", "DRN": "전체 출입문 열리지 않을 시", "DBS": "DOOR등 점등 불능 시",
    "DCURN": "전체 출입문 열리지 않을 시", "DCULN": "전체 출입문 열리지 않을 시",
    "DOS": "전체 출입문 열리지 않을 시", "DCS": "전체 출입문 닫히지 않을 시", "DROS": "전체 출입문 닫히지 않을 시",
    "4016": "전 차량 HSCB 차단 시", "HSCB": "전 차량 HSCB 차단 시", "CIN": "전 차량 HSCB 차단 시",
    "1045": "데드맨 스위치 불량 시", "DSD": "데드맨 스위치 불량 시", "DSDBS": "데드맨 스위치 불량 시",
    "1020": "전체 판토 상승 불능 시", "PANUS": "전체 판토 상승 불능 시",
    "EPANDS": "전체 판토 상승 불능 시", "HCRN": "전체 판토 상승 불능 시",
    "PANVN": "전체 판토 상승 불능 시", "ACMN": "전체 판토 상승 불능 시"
}

RADIO_INSTRUCTION_MASTER = {
    "4001": {
        "display": "1. TCMS 고장 메시지(4001) 확인 ➔ 2. 해당 호차 배전반 CIN 차단기 OFF/ON 리셋 ➔ 3. 3회 재발 시 CUT-OUT 후 수동운전",
        "speech": "추진제어장치 배터리 제어전원 이상 고장코드 4001번 조치입니다. 해당 호차 배전반의 추진전자제어 차단기를 오프 후 30초 뒤 온으로 복귀하십시오."
    },
    "전체 출입문 닫히지 않을 시": {
        "display": "1. DCS 연속 3회 취급 및 배전반 DRN OFF/ON 고착 판별 ➔ 2. 1량 불능 시 DCURN·DCULN 확인 ➔ 3. 불능 시 관제 승인 회송",
        "speech": "전체 출입문 닫히지 않을 시 조치입니다. 디씨에스 연속 삼회 취급 후 출입문 계전기 차단기 디알엔과 디씨유알엔, 디씨유엘엔을 확인하십시오."
    },
    "전체 출입문 열리지 않을 시": {
        "display": "1. 운전실 DOS 연속 3회 열림 취급 ➔ 2. 배전반 DRN 및 DCURN·DCULN 확인 ➔ 3. ZVR 불량 시 DBS 'ON' 취급 및 수동 개방",
        "speech": "전체 출입문 열리지 않을 시 조치입니다. 디오에스 연속 삼회 취급 후 출입문 차단기 디알엔, 디씨유알엔, 디씨유엘엔을 확인하고 도어 바이패스 스위치를 온 하십시오."
    },
    "전체 MCB 투입 불능 시": {
        "display": "1. 전차선 전압 및 판토 상승 확인 ➔ 2. 제어대 EPanDS 복귀 및 배전반 MCN, HCRN, ADS 위치 확인 ➔ 3. MCBCS 재투입 및 MCBHR 동작음 확인",
        "speech": "주회로차단기 투입 불능 시 조치입니다. 전차선 전압과 판토 상승을 확인하고 비상판토하강 스위치 복귀 및 배전반 차단기를 점검하십시오."
    },
    "동력 운전 불능 시": {
        "display": "1. DOOR등 점등 및 제동 완해 확인 ➔ 2. 배전반 ENCN, PBN, EROS 'N' 위치 확인 ➔ 3. C/I 재부팅 (불능 시 EO모드 35km/h 이하 회송)",
        "speech": "동력 운전 불능 시 조치입니다. 도어등과 제동 완해를 확인하고, 엔코더 및 주차제동 차단기를 점검한 뒤, 주변환장치 리셋을 시행하십시오."
    },
    "전 차량 비상제동 체결 시": {
        "display": "1. 전후진핸들 및 전·후부 EBS, 주공기압 확인 ➔ 2. DSDBS 바이패스 및 HCRN·ScBN 확인 ➔ 3. BVN1,2 복귀 불능 시 [제동 → EROS 'EO' → EBCOS]",
        "speech": "전 차량 비상제동 체결 시 조치입니다. 전후진 핸들과 비상제동 스위치를 확인하고, 데드맨 바이패스 및 제동밸브 차단기 복귀 불능 시 비상제동개방 스위치를 취급하십시오."
    },
    "DOOR등 점등 불능 시": {
        "display": "1. TCMS 불량 호차 확인 및 DOS 수회 개폐 ➔ 2. 비상핸들 복귀 및 이물질 제거 ➔ 3. 운전실 배전반 DILN 확인 (불능 시 DBS 'ON' 회송)",
        "speech": "도어등 점등 불능 시 조치입니다. 티씨엠에스 확인 후 출입문 계전기 차단기 디아이엘엔을 확인하고, 불능 시 출입문 바이패스를 취급하십시오."
    },
    "전 차량 HSCB 차단 시": {
        "display": "1. C/I 2개 이하 고장 시 정차 후 [전후진핸들 N → 6~10초 → F] 리셋 ➔ 2. C/I 3개 이상 고장 시 차량 재기동 ➔ 3. CIN OFF 후 30초 뒤 ON 복귀",
        "speech": "전 차량 에이치에스씨비 차단 시 조치입니다. 주변환장치 리셋을 시행하고, 불능 시 추진전자제어 차단기를 오프 후 온으로 복귀하십시오."
    },
    "데드맨 스위치 불량 시": {
        "display": "1. 비상정차 후 주간제어기 B7 위치에서 제동 완해 ➔ 2. 운전실 배전반 DSDBS '바이패스' 전환 ➔ 3. 완해 불능 시 EBCOS 취급",
        "speech": "데드맨 스위치 불량 시 조치입니다. 제동 7단 위치에서 비상제동을 완해하고 데드맨 바이패스 스위치를 취급하십시오."
    },
    "전체 판토 상승 불능 시": {
        "display": "1. 전후진 핸들 F/R 전환 후 PanUS 재취급 ➔ 2. HCRN 및 EPanDS 확인 ➔ 3. M2차 ACMN, PANVN 확인",
        "speech": "전체 판토 상승 불능 시 조치입니다. 핸들 조작 후 선두차 제어 차단기와 비상판토하강 스위치를 확인하고, 공기압축기 차단기를 점검하십시오."
    }
}

PRONUNCIATION_MAP = {
    "MCBCS": "엠씨비 투입 스위치", "MCBHR": "엠씨비 유지계전기", "MCBN1/2": "엠씨비 차단기 1, 2",
    "MCBN1": "엠씨비 차단기 1", "MCB": "주회로차단기 엠씨비", "MCN": "주간제어기 차단기 엠씨엔",
    "HCRN": "선두차 제어 차단기 에이치씨알엔", "EPanDS": "비상판토하강 스위치", "PanUS": "판토상승 스위치",
    "PANVN": "판토 전자밸브 차단기", "ACMN": "보조공기압축기 차단기", "HSCB": "고속도차단기",
    "CIN": "추진전자제어 차단기 씨아이엔", "ENCN": "엔코더 차단기 이엔씨엔", "PBN": "주차제동 차단기 피비엔",
    "EROS": "비상구원운전 스위치", "DSDBS": "데드맨 바이패스 스위치", "DSD": "데드맨 스위치",
    "EBCOS": "비상제동개방 스위치", "EBS": "비상제동 스위치", "BVN1": "제동밸브 차단기 비브이엔 1",
    "ScBN": "보안제동 차단기", "BOUN": "제동제어기 차단기", "DILN": "출입문 표시등 차단기 디아이엘엔",
    "DRN": "출입문 계전기 차단기 디알엔", "DCURN": "출입문 제어 차단기 디씨유알엔",
    "DCULN": "출입문 제어 차단기 디씨유엘엔", "DBS": "출입문 바이패스 스위치",
    "SIVCN": "보조전원 제어 차단기", "TCMSPN": "티씨엠에스 전원 차단기", "TCMS": "티씨엠에스",
    "C/I": "주변환장치", "P/B핸들": "주간제어기 핸들", "OFF/ON": "오프 후 온", "OFF": "오프", "ON": "온", "km/h": "킬로미터"
}

def get_radio_display_and_speech(train_no: str, car_no: str, raw_query: str, briefing: dict) -> tuple:
    q_clean = raw_query.strip().upper()
    lookup_key = DIRECT_CODE_AND_CB_MAP.get(q_clean, raw_query.strip())
    if isinstance(lookup_key, str) and lookup_key in PRECISION_MANUAL_DB:
        lookup_key = q_clean

    for k in (lookup_key, q_clean):
        if k in RADIO_INSTRUCTION_MASTER:
            item = RADIO_INSTRUCTION_MASTER[k]
            disp = f"[{train_no}편성 {car_no}호차 핵심조치] {item['display']}"
            spch = f"제1관제센터에서 {train_no}편성 {car_no}호차에 지시합니다. {item['speech']} 이상."
            return disp, spch

    steps = briefing.get("checklist", [])[:3]
    disp_joined = " ➔ ".join([f"{idx}. {re.sub(r'<[^>]*>', '', st_txt)}" for idx, st_txt in enumerate(steps, 1)])
    disp = f"[{train_no}편성 {car_no}호차 핵심조치] {disp_joined}"

    cleaned_sentences = []
    for idx, st_txt in enumerate(steps, 1):
        s = re.sub(r'<[^>]*>', '', st_txt)
        s = re.sub(r'\([^)]*\)', '', s)
        s = s.replace("➔", ", ").replace("→", ", ").replace("★", "").replace("※", "").strip()
        for eng_k, kor_v in sorted(PRONUNCIATION_MAP.items(), key=lambda x: len(x[0]), reverse=True):
            s = s.replace(eng_k, kor_v)
        cleaned_sentences.append(f"{idx}번, {s}.")

    spch = f"제1관제센터에서 {train_no}편성 {car_no}호차에 핵심 응급조치를 지시합니다. {' '.join(cleaned_sentences)} 이상."
    return disp, spch

SCHEMATIC_PAGE_CATALOG = {
    10: {"title": "EC-005 주회로도 (1/3) [Tc1-M1-M2]", "dwg": "REC10001A03", "comps": ["PANTOGRAPH", "MCB", "ADCg", "MTr", "HSCB", "LB1", "LB2", "C/I", "EGS", "ACArr", "DCArr"]},
    13: {"title": "EC-008 주회로제어회로도 (1/4) [BatK/MCB/ACB]", "dwg": "REC10002A03", "comps": ["BatKN1", "BatKN2", "BatN1", "EBON", "BVR", "BLVR", "MCBN1", "MCBN2", "ADAN", "ADDN", "MCB", "HSCB", "LB1"]},
    17: {"title": "EC-012 선두차제어회로도 [HCR/ACM]", "dwg": "REC10003A03", "comps": ["HCRN", "HCR1", "HCR2", "HCR3", "HCR4", "TCR1", "ACM", "ACMN", "ACMCN", "ACMK", "ACMKR", "ACMG", "BMCN"]},
    18: {"title": "EC-013 SIV제어회로도 (1/2)", "dwg": "REC10004A03", "comps": ["SIV", "CHK", "LK", "SIVK", "IVS", "GDU", "3ACPT"]},
    19: {"title": "EC-014 SIV제어회로도 (2/2) [SIV TR]", "dwg": "REC10004A03", "comps": ["SIV", "IVS", "SIVK", "SSK", "BCRM"]},
    20: {"title": "EC-015 교류/직류절환스위치(ADS) 제어회로도", "dwg": "REC10005A03", "comps": ["ADS", "ADSN", "DSSRR", "ACR", "DCR", "TCR3", "HCR1"]},
    21: {"title": "EC-016 표시등제어회로도 [DOOR등/비상제동등]", "dwg": "REC10006A03", "comps": ["LPTSN", "PLPN", "EBR1", "SIVFR", "CIFR", "PanFR", "ACOCRR", "DOOR"]},
    22: {"title": "EC-017 저압보조회로도 (1/6) [판토/MCB 제어(Tc1)]", "dwg": "REC10007A03", "comps": ["PanUS", "PanDS", "EPanDS", "IPanDS1", "MCBCS", "MCBOS", "MCBHR", "EPanDR", "MCN", "PanDN", "IPanDN", "ADS", "HCR3"]},
    23: {"title": "EC-018 저압보조회로도 (2/6) [판토/MCB 제어(M2-1)]", "dwg": "REC10007A03", "comps": ["PANVN", "PanVN", "EGCN", "MPUN", "MCB", "PanR", "PanPSR", "PanPS1", "PanPS2", "IMCR", "ADAR3", "ADDR2", "LB1"]},
    28: {"title": "EC-023 속도제어회로도 (Tc) [주간제어기/엔코더]", "dwg": "REC20001A03", "comps": ["ENCN", "ENCN1", "ENCN2", "ENCORDER", "EROS", "EROSR", "EROHDR", "DBS2", "DIR1", "DIR3", "EBR1", "ZVR1", "PAR", "PBBS", "PIR", "BCRR", "NRBDR"]},
    29: {"title": "EC-024 속도제어회로도 (M1) [C/I TCU 제어]", "dwg": "REC20002A03", "comps": ["CIN", "CIN1", "CIN2", "MCBOR", "HSCB", "HB", "LB1", "LB2", "K1", "K2", "MDS", "CONTROL UNIT"]},
    30: {"title": "EC-025 속도제어회로도 (M2) [C/I TCU 제어]", "dwg": "REC20003A03", "comps": ["CIN", "CIN1", "CIN2", "MCBOR", "HSCB", "HB", "LB1", "LB2", "K1", "K2", "MDS", "CONTROL UNIT"]},
    31: {"title": "EC-026 제동제어회로도 (1/2) [비상/보안/주차/데드맨]", "dwg": "REC30001A03", "comps": ["BVN1", "BVN2", "BVN3", "EBCOS", "EBS", "EBS1", "EBS2", "EBS3", "EBR1", "EBR2", "EMR1", "EMR2", "DSD", "DSDBS", "DMR", "DMTR", "EROS", "ScBN", "ScBS", "CPRN", "CPRS", "PBN", "PBA", "PBR", "HBCOS", "ZVR1", "ZVR3", "MRPS"]},
    32: {"title": "EC-027 제동제어회로도 (2/2) [제동 릴레이 접점]", "dwg": "REC30001A03", "comps": ["ATCSBR1", "BER", "DMR", "DMTR", "EBR1", "EBR2", "EBRSR", "ELBR", "EMR1", "EMR2", "HBR", "MRPSAR", "NRBDR", "PAR", "ZVR1", "ZVR2", "ZVR3"]},
    33: {"title": "EC-028 제동제어회로도 (Tc) [BOU/ECU/공기코크]", "dwg": "REC30002A03", "comps": ["BOU", "ECU", "BOUN", "BHEN", "ADYN", "BCCS1", "BCCS2", "ASCS1", "SCBMV", "CPRMV", "SBV", "EBV"]},
    38: {"title": "EC-033 CMSB(공기압축기) 제어회로도", "dwg": "REC30007A03", "comps": ["CMSB", "CMCN", "CMIVN", "CMN", "BCMK", "CMK", "ACLVR", "EOCR"]},
    39: {"title": "EC-034 구원운전제어회로도 [BTU/EROS]", "dwg": "REC30008A03", "comps": ["BTU", "BTD", "BTUN", "EROS", "EROSR", "EROHDR", "ROR1", "ROR2", "ROR3"]},
    40: {"title": "EC-035 고압보조회로도 (1/3) [SIV/주변압기 MTr]", "dwg": "REC40001A03", "comps": ["SIVCN", "SIVCN1", "SIVCN2", "SIVSRN", "MTOMN", "MTBMN", "MTRCCN", "MTN", "MTOPR", "MTOFR", "MTTHRR1"]},
    43: {"title": "EC-038 연장급전회로도 [ESK]", "dwg": "REC40002A03", "comps": ["ESK", "ESKN", "ESKR", "TES01", "TESC01"]},
    44: {"title": "EC-039 차단기트립제어회로도 (1/2) [배전반 NFB]", "dwg": "REC40003A03", "comps": ["BOUN", "DCULN", "DCURN", "ESWN1", "ESWN2", "ATCN1", "ATCN2", "CIN", "CIN1", "CIN2", "CMCN", "ACMN", "ADSN", "PANVN", "EBON", "FDRUN", "TRN1"]},
    49: {"title": "EC-044 캠스위치결선도 (Tc) [마스콘/EROS/DBS]", "dwg": "REC40007A03", "comps": ["MASTER CONTROLLER", "EROS", "DBS", "CHCS", "CACS", "HLPCS", "DSD"]},
    50: {"title": "EC-045 등제어회로도 (Tc) [객실등 LpCN]", "dwg": "REC50001A03", "comps": ["LpCN", "RALPN", "RDLPN", "ALCS", "DLCS", "RALPR1", "RDLPR", "HLPN"]},
    54: {"title": "EC-049 객실냉난방제어회로도 (1/2) [HVAC]", "dwg": "REC50005A03", "comps": ["ACUN1", "ACUN2", "ACINVN1", "ACINVN2", "EOCRN", "CMK1", "EFK1", "MICOM"]},
    62: {"title": "EC-057 도어제어회로도 (Tc) [DRN/DILN/DCU/DBS]", "dwg": "REC60001A03", "comps": ["DRN", "DILN", "DICRN", "DICLN", "DCURN", "DCULN", "DCUSN", "DIR1", "DIR2", "DIR3", "DIR4", "DR1", "DR2", "DROS", "DCS", "DOS", "DBS", "DOOR CONTROL UNIT"]},
    63: {"title": "EC-058 도어제어회로도 (M,T) [DCU 외부단자/LOS]", "dwg": "REC60002A03", "comps": ["DCURN", "DCULN", "DCUSN", "DICRN", "DICLN", "DOOR CONTROL UNIT", "DLS1", "DCS1", "DCS2", "LOS", "EAD", "EED"]},
    86: {"title": "EC-081 Tc인터페이스회로도 (1/4) [TCMSPN]", "dwg": "REC80002A03", "comps": ["TCMSPN", "TCMSPN1", "TCMSPN2", "LIU1", "LIU2", "ETHERNET"]},
    93: {"title": "EC-088 ATS/ATC제어회로도 [신호/비상제동]", "dwg": "REC80005A03", "comps": ["ATCN1", "ATCN2", "ADUN1", "CBTCN", "ADU", "HCR6", "DBS5", "DBS6", "ZVR2", "EMR1"]}
}

PDF_EXACT_TOKEN_CANDIDATES = {
    "DILN": ["DILN(3A)", "DILN"],
    "DRN": ["DRN(10A)", "DRN"],
    "DCURN": ["DCURN(16A)", "DCURN"],
    "DCULN": ["DCULN(16A)", "DCULN"],
    "DICRN": ["DICRN(6A)", "DICRN"],
    "DICLN": ["DICLN(6A)", "DICLN"],
    "DCUSN": ["DCUSN(3A)", "DCUSN"],
    "DBS": ["DBS3,4", "DBS2", "DBS1", "DBS5", "DBS"],
    "DOS": ["DOS1(S)", "DOS2(S)", "DOS"],
    "DCS": ["DCS(C)", "LDCS(S)", "DCS1", "DCS"],
    "DROS": ["DROS(C)", "LDROS(S)", "RDROS(S)", "DROS"],
    "ENCN": ["ENCN1(3A)", "ENCN1", "ENCN2(3A)", "ENCN2", "ENCN"],
    "CIN": ["CIN1(10A)", "CIN1", "CIN2(10A)", "CIN2", "CIN"],
    "BVN1": ["BVN1(10A)", "BVN1"],
    "BVN2": ["BVN2(10A)", "BVN2"],
    "EBS": ["EBS1", "EBS2", "EBS3", "EBS"],
    "EBCOS": ["EBCOS"],
    "DSDBS": ["DSDBS"],
    "DSD": ["DSD"],
    "ScBN": ["ScBN(3A)", "ScBN", "ScBS"],
    "PBN": ["PBN(3A)", "PBN", "PBBS"],
    "EROS": ["EROS2(N)", "EROS1", "EROS", "EROHDR"],
    "HCRN": ["HCRN(6A)", "HCRN", "HCR1", "HCR3"],
    "MCN": ["MCN(20A)", "MCN"],
    "MCBCS": ["MCBCS"],
    "MCBHR": ["MCBHR"],
    "EPanDS": ["EPanDS"],
    "PanUS": ["PanUS"],
    "PanDN": ["PanDN(3A)", "PanDN", "PanDS"],
    "PANVN": ["PanVN(6A)", "PanVN", "PANVN"],
    "ACMN": ["ACMN(10A)", "ACMCN(3A)", "ACMN"],
    "ADS": ["ADSN(3A)", "ADS", "ADSN"],
    "HSCB": ["HSCB", "HB"],
    "LB1": ["LB1", "LB2"],
    "MCB": ["MCBN1(6A)", "MCBN1", "MCB"]
}

FALLBACK_SCHEMATIC_POINTS = {
    62: {
        "DILN": (0.072, 0.098),
        "DRN": (0.128, 0.098),
        "DBS": (0.141, 0.328),
        "DOS": (0.214, 0.440),
        "DCS": (0.245, 0.415),
        "DROS": (0.312, 0.525),
        "DCURN": (0.528, 0.142),
        "DCULN": (0.528, 0.762)
    },
    28: {
        "ENCN": (0.438, 0.082),
        "EROS": (0.665, 0.440),
        "EBR1": (0.348, 0.142),
        "DIR1": (0.250, 0.275)
    },
    31: {
        "BVN2": (0.082, 0.082),
        "EBCOS": (0.210, 0.162),
        "EBS": (0.475, 0.075),
        "BVN1": (0.082, 0.342),
        "DSD": (0.745, 0.395),
        "DSDBS": (0.745, 0.345),
        "EROS": (0.695, 0.535),
        "ScBN": (0.558, 0.635),
        "PBN": (0.520, 0.785)
    },
    22: {
        "PanUS": (0.035, 0.085),
        "EPanDS": (0.395, 0.315),
        "MCBCS": (0.365, 0.555),
        "MCBHR": (0.405, 0.680),
        "MCN": (0.530, 0.115),
        "ADS": (0.640, 0.135)
    }
}

SCENARIO_PAGE_ORDER = {
    "동력 운전 불능 시": [28, 31, 29, 49, 13],
    "전 차량 비상제동 체결 시": [31, 32, 17, 33, 93],
    "전체 MCB 투입 불능 시": [22, 13, 23, 17, 20],
    "DOOR등 점등 불능 시": [62, 21, 28, 63, 44],
    "전 차량 HSCB 차단 시": [29, 30, 10, 13, 23],
    "전체 출입문 열리지 않을 시": [62, 63, 44, 21],
    "전체 출입문 닫히지 않을 시": [62, 63, 44, 21],
    "데드맨 스위치 불량 시": [31, 49, 32, 28],
    "전체 판토 상승 불능 시": [22, 23, 17, 10, 44]
}

def get_smart_schematics_for_query(q_clean: str, search_res: dict) -> list:
    def make_item(p_num: int) -> dict:
        cat = SCHEMATIC_PAGE_CATALOG.get(p_num, {"title": f"회로도 {p_num}p", "dwg": "", "comps": []})
        return {
            "source_file": SCHEMATIC_PDF_NAME,
            "page": p_num,
            "title": f"{cat['title']} ({cat['dwg']})",
            "components": cat["comps"]
        }

    mapped_q = DIRECT_CODE_AND_CB_MAP.get(q_clean.upper(), q_clean)
    if isinstance(mapped_q, str) and mapped_q in SCENARIO_PAGE_ORDER:
        return [make_item(p) for p in SCENARIO_PAGE_ORDER[mapped_q]]

    tokens = [t.upper() for t in search_res.get("keywords", []) if len(t) >= 2]
    cbs = [c.upper() for c in search_res.get("linked_cbs", [])]
    pool = set(tokens + cbs)

    scored = []
    for p_num, cat in SCHEMATIC_PAGE_CATALOG.items():
        sc = 0
        t_up = cat["title"].upper()
        c_up = [c.upper() for c in cat["comps"]]
        for term in pool:
            if term in c_up:
                sc += 80
            elif any(term in c or c in term for c in c_up):
                sc += 45
            if term in t_up:
                sc += 60
        if ("제동" in q_clean or "비상" in q_clean) and p_num in (31, 32, 33):
            sc += 90
        if ("출입문" in q_clean or "도어" in q_clean or "DOOR" in q_clean.upper()) and p_num in (62, 63, 21):
            sc += 90
        if ("판토" in q_clean or "MCB" in q_clean.upper()) and p_num in (22, 23, 13, 10):
            sc += 90
        if ("동력" in q_clean or "인버터" in q_clean or "HSCB" in q_clean.upper()) and p_num in (28, 29, 30, 10):
            sc += 90
        if sc > 0:
            scored.append((sc, p_num))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        scored = [(100, 22), (90, 31), (80, 28), (70, 62), (60, 17)]
    return [make_item(p) for _, p in scored[:6]]

def _find_exact_point_on_page(page, page_num: int, term: str, W: int, H: int):
    t_clean = term.strip()
    if not t_clean:
        return None
    t_up = t_clean.upper()

    pw = page.rect.width
    ph = page.rect.height
    candidates = PDF_EXACT_TOKEN_CANDIDATES.get(t_up, [t_clean, t_up])

    def _is_valid_drawing_area(rx: float, ry: float) -> bool:
        if rx < 0.03 or rx > 0.96 or ry < 0.04 or ry > 0.84:
            return False
        if ry > 0.76 and rx > 0.70:
            return False
        if page_num == 62 and (0.04 <= rx <= 0.13 and 0.44 <= ry <= 0.65):
            return False
        return True

    words = page.get_text("words")
    for cand in candidates:
        cand_up = cand.upper()
        matched_rects = []
        for w in words:
            x0, y0, x1, y1, w_text = w[0], w[1], w[2], w[3], w[4].strip().upper()
            if w_text == cand_up or w_text.startswith(cand_up + "(") or w_text.startswith(cand_up + ","):
                rx = ((x0 + x1) / 2.0) / pw
                ry = ((y0 + y1) / 2.0) / ph
                if _is_valid_drawing_area(rx, ry):
                    matched_rects.append((rx, ry))
        if matched_rects:
            if page_num == 62 and t_up == "DOS":
                matched_rects.sort(key=lambda pt: pt[0])
            best_rx, best_ry = matched_rects[0]
            return int(best_rx * W), int(best_ry * H)

    for cand in candidates:
        rects = page.search_for(cand)
        valid_r = []
        for r in rects:
            rx = ((r.x0 + r.x1) / 2.0) / pw
            ry = ((r.y0 + r.y1) / 2.0) / ph
            if _is_valid_drawing_area(rx, ry):
                valid_r.append((rx, ry))
        if valid_r:
            if page_num == 62 and t_up == "DOS":
                valid_r.sort(key=lambda pt: pt[0])
            best_rx, best_ry = valid_r[0]
            return int(best_rx * W), int(best_ry * H)

    fb_pts = FALLBACK_SCHEMATIC_POINTS.get(page_num, {})
    for k_name, (rx, ry) in fb_pts.items():
        if t_up == k_name.upper():
            return int(rx * W), int(ry * H)

    return None

def render_highlighted_schematic_circle(schematic_item: dict, highlight_terms: list) -> tuple:
    pdf_path = os.path.join(RAW_DIR, schematic_item.get("source_file", SCHEMATIC_PDF_NAME))
    page_num = schematic_item.get("page", 31)

    if not os.path.exists(pdf_path):
        return None, 0, []

    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    zoom_factor = 2.6
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom_factor, zoom_factor), alpha=False)
    base_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("RGBA")
    W, H = base_img.width, base_img.height

    hit_points = []
    used_centers = []

    for term in highlight_terms:
        pt = _find_exact_point_on_page(page, page_num, term, W, H)
        if pt is not None:
            cx, cy = pt
            if not any(abs(cx - ux) < 32 and abs(cy - uy) < 32 for ux, uy in used_centers):
                used_centers.append((cx, cy))
                hit_points.append((term.strip().upper(), cx, cy))

    doc.close()

    circle_layer = Image.new("RGBA", base_img.size, (255, 255, 255, 0))
    label_layer = Image.new("RGBA", base_img.size, (255, 255, 255, 0))
    draw_circle = ImageDraw.Draw(circle_layer)
    draw_label = ImageDraw.Draw(label_layer)

    try:
        font = ImageFont.truetype("malgunbd.ttf", 42)
    except Exception:
        font = ImageFont.load_default()

    FIXED_RADIUS = int(min(W, H) * 0.042)
    circle_bboxes = []

    for idx, (term, cx, cy) in enumerate(hit_points, 1):
        ex0 = max(10, cx - FIXED_RADIUS)
        ey0 = max(10, cy - FIXED_RADIUS)
        ex1 = min(W - 10, cx + FIXED_RADIUS)
        ey1 = min(H - 10, cy + FIXED_RADIUS)
        circle_bboxes.append((ex0 - 12, ey0 - 12, ex1 + 12, ey1 + 12))

        draw_circle.ellipse([ex0 - 12, ey0 - 12, ex1 + 12, ey1 + 12], fill=(255, 255, 0, 125), outline=(245, 158, 11, 255), width=8)
        draw_circle.ellipse([ex0, ey0, ex1, ey1], fill=(254, 240, 138, 95), outline=(220, 38, 38, 255), width=9)

        cross_len = 18
        draw_circle.line([(cx - cross_len, cy), (cx + cross_len, cy)], fill=(220, 38, 38, 255), width=4)
        draw_circle.line([(cx, cy - cross_len), (cx, cy + cross_len)], fill=(220, 38, 38, 255), width=4)
        draw_circle.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(220, 38, 38, 255), outline=(255, 255, 255, 255), width=2)

    placed_label_boxes = []

    def _is_overlapping(boxA, boxB):
        return not (boxA[2] < boxB[0] or boxA[0] > boxB[2] or boxA[3] < boxB[1] or boxA[1] > boxB[3])

    for idx, (term, cx, cy) in enumerate(hit_points, 1):
        ex0 = max(10, cx - FIXED_RADIUS)
        ey0 = max(10, cy - FIXED_RADIUS)
        ex1 = min(W - 10, cx + FIXED_RADIUS)
        ey1 = min(H - 10, cy + FIXED_RADIUS)

        label_text = f"★ {idx}. {term}"
        bbox = draw_label.textbbox((0, 0), label_text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        pad_x = 28
        pad_y = 14
        lbl_w = text_w + pad_x * 2
        lbl_h = text_h + pad_y * 2

        candidate_positions = [
            (cx - lbl_w // 2, ey0 - lbl_h - 18),
            (cx - lbl_w // 2, ey1 + 18),
            (ex0 - lbl_w - 18, cy - lbl_h // 2),
            (ex1 + 18, cy - lbl_h // 2),
            (ex0 - lbl_w - 14, ey0 - lbl_h - 14),
            (ex1 + 14, ey0 - lbl_h - 14),
            (ex0 - lbl_w - 14, ey1 + 14),
            (ex1 + 14, ey1 + 14),
        ]

        best_box = None
        for cand_x, cand_y in candidate_positions:
            cx0 = max(12, min(W - lbl_w - 12, cand_x))
            cy0 = max(12, min(H - lbl_h - 12, cand_y))
            c_box = (cx0, cy0, cx0 + lbl_w, cy0 + lbl_h)

            if any(_is_overlapping(c_box, p_box) for p_box in placed_label_boxes):
                continue
            if any(_is_overlapping(c_box, cir_box) for cir_box in circle_bboxes):
                continue
            best_box = c_box
            break

        if best_box is None:
            for cand_x, cand_y in candidate_positions:
                cx0 = max(12, min(W - lbl_w - 12, cand_x))
                cy0 = max(12, min(H - lbl_h - 12, cand_y))
                c_box = (cx0, cy0, cx0 + lbl_w, cy0 + lbl_h)
                if not any(_is_overlapping(c_box, p_box) for p_box in placed_label_boxes):
                    best_box = c_box
                    break

        if best_box is None:
            cx0 = max(12, min(W - lbl_w - 12, cx - lbl_w // 2))
            cy0 = max(12, min(H - lbl_h - 12, ey0 - lbl_h - 18))
            best_box = (cx0, cy0, cx0 + lbl_w, cy0 + lbl_h)

        lbl_x0, lbl_y0, lbl_x1, lbl_y1 = best_box
        placed_label_boxes.append(best_box)

        draw_label.rounded_rectangle([lbl_x0 - 4, lbl_y0 - 4, lbl_x1 + 4, lbl_y1 + 4], radius=14, fill=(254, 240, 138, 255))
        draw_label.rounded_rectangle([lbl_x0, lbl_y0, lbl_x1, lbl_y1], radius=12, fill=(220, 38, 38, 255), outline=(255, 255, 255, 255), width=4)

        text_x = lbl_x0 + (lbl_w - text_w) // 2
        text_y = lbl_y0 + (lbl_h - text_h) // 2 - 3
        draw_label.text((text_x, text_y), label_text, fill=(255, 255, 255, 255), font=font)

    composited = Image.alpha_composite(base_img, circle_layer)
    composited_rgb = Image.alpha_composite(composited, label_layer).convert("RGB")
    matched_names = [f"{i}. {name}" for i, (name, _, _) in enumerate(hit_points, 1)]
    return composited_rgb, len(hit_points), matched_names

@st.cache_resource
def get_engine():
    return MetroAIEngine()

engine = get_engine()

CAR_SPEC_MAP = {
    "0": {"short": "TC1", "type": "TC1 (운전실)", "equip": "ATC/ATS, SIV, CM, 축전지, 운전실 배전반", "key_cb": "MCN, HCRN, ENCN, BVN1~3, DILN, DRN, SIVCN1"},
    "1": {"short": "M1", "type": "M1 (동력차)", "equip": "주변환장치(C/I), HSCB/LB", "key_cb": "CIN1/2, BOUN, DCURN/DCULN"},
    "2": {"short": "M2-1", "type": "M2-1 (집전/동력)", "equip": "판토(PT), MCB, 주변압기(MTr), ACM", "key_cb": "PANVN, MCBN1/2, ADAN, ADDN, ACMN, MTBMN, MTOMN"},
    "3": {"short": "T1", "type": "T1 (부수차)", "equip": "연장급전접촉기(ESK), 제동제어기(BOU)", "key_cb": "ESKN, BOUN, DCURN/DCULN"},
    "4": {"short": "M2-2", "type": "M2-2 (집전/동력)", "equip": "판토(PT), MCB, 주변압기(MTr), ACM", "key_cb": "PANVN, MCBN1/2, ADAN, ADDN, ACMN, MTBMN, MTOMN"},
    "5": {"short": "T2", "type": "T2 (부수차)", "equip": "보조전원(SIV), 주공기압축기(CM), 축전지", "key_cb": "SIVCN, CMCN, BOUN"},
    "6": {"short": "T1'", "type": "T1' (부수차)", "equip": "연장급전접촉기(ESK), 제동제어기(BOU)", "key_cb": "ESKN, BOUN, DCURN/DCULN"},
    "7": {"short": "M1", "type": "M1 (동력차)", "equip": "주변환장치(C/I), HSCB/LB", "key_cb": "CIN1/2, BOUN, DCURN/DCULN"},
    "8": {"short": "M2-3", "type": "M2-3 (집전/동력)", "equip": "판토(PT), MCB, 주변압기(MTr), ACM", "key_cb": "PANVN, MCBN1/2, ADAN, ADDN, ACMN, MTBMN, MTOMN"},
    "9": {"short": "TC2", "type": "TC2 (운전실)", "equip": "ATC/ATS, SIV, CM, 축전지, 후부 배전반", "key_cb": "MCN, HCRN, ENCN, BVN1~3, DILN, DRN, SIVCN1"},
}

if "timer_state" not in st.session_state:
    st.session_state.timer_state = "idle"
if "timer_start_ts" not in st.session_state:
    st.session_state.timer_start_ts = None
if "timer_elapsed_sec" not in st.session_state:
    st.session_state.timer_elapsed_sec = 0
if "quick_query" not in st.session_state:
    st.session_state.quick_query = "DOOR등 점등 불능 시"
if "active_nav_tab" not in st.session_state:
    st.session_state.active_nav_tab = 0

st.markdown(
    '<div class="main-header">'
    '<h2>🚇 서울교통공사 제1관제센터 | 4호선 210칸 전동차 AI 응급조치 통합 관제 시스템</h2>'
    '<p>【METRO AI-THON 자유과제형】 1. 응급조치매뉴얼 · 2. 고장관련 차단기 · 3. 회로도 노란 동그라미 핀포인트 · 4. 3회 반복고장 판정</p>'
    '</div>',
    unsafe_allow_html=True
)

with st.sidebar:
    st.markdown("### 🚨 제1관제센터 검수관제 상황판")
    st.markdown("#### ⏱️ 5분 골든타임 타이머")
    
    tb1, tb2 = st.columns(2)
    with tb1:
        if st.button("▶️ 시작", use_container_width=True):
            st.session_state.timer_state = "running"
            st.session_state.timer_start_ts = time.time()
            st.session_state.timer_elapsed_sec = 0
    with tb2:
        if st.button("🔄 초기화", use_container_width=True):
            st.session_state.timer_state = "idle"
            st.session_state.timer_start_ts = None
            st.session_state.timer_elapsed_sec = 0

    if st.button("⏹️ 종료 (소요시간 확인)", use_container_width=True):
        if st.session_state.timer_state == "running" and st.session_state.timer_start_ts is not None:
            st.session_state.timer_elapsed_sec = max(1, int(time.time() - st.session_state.timer_start_ts))
            st.session_state.timer_state = "stopped"
        elif st.session_state.timer_state == "idle":
            st.session_state.timer_elapsed_sec = 0
            st.session_state.timer_state = "stopped"

    t_state = st.session_state.timer_state
    start_ts_ms = int((st.session_state.timer_start_ts or time.time()) * 1000)
    elapsed_sec = int(st.session_state.timer_elapsed_sec)
    rem_sec = max(0, 300 - elapsed_sec)
    rem_m, rem_s = divmod(rem_sec, 60)
    el_m, el_s = divmod(elapsed_sec, 60)

    if t_state == "running":
        border_col = "#ef4444"
        status_title = "🔥 골든타임 진행 중!"
        init_clock = "05:00"
        clock_col = "#f87171"
        sub_html = '<div id="elapsed_box" style="font-size:15px; font-weight:900; color:#38bdf8; margin-top:4px;">실시간 경과: 00분 00초</div>'
    elif t_state == "stopped":
        border_col = "#22c55e"
        status_title = "✅ 응급조치 완료!"
        init_clock = f"{rem_m:02d}:{rem_s:02d}"
        clock_col = "#4ade80"
        sub_html = (
            f'<div style="background:#14532d; border:2px solid #fde047; border-radius:8px; padding:6px 4px; margin-top:6px; '
            f'font-size:14px; font-weight:900; color:#fde047; word-break:keep-all;">'
            f'⏱️ 총 소요시간: {el_m:02d}분 {el_s:02d}초 ({elapsed_sec}초)'
            f'</div>'
        )
    else:
        border_col = "#38bdf8"
        status_title = "⏳ 골든타임 대기 중"
        init_clock = "05:00"
        clock_col = "#38bdf8"
        sub_html = '<div style="font-size:13px; font-weight:900; color:#cbd5e1; margin-top:4px;">시작 버튼을 누르면 측정됩니다</div>'

    components.html(f"""
    <div style="background:#0f172a; border:3px solid {border_col}; border-radius:10px; padding:10px 6px; text-align:center; color:white; font-family:'Malgun Gothic', monospace; box-sizing:border-box;">
        <div style="font-size:15px; font-weight:900; color:#fde047;">{status_title}</div>
        <div id="clock" style="font-size:32px; font-weight:900; color:{clock_col}; line-height:1.15; margin-top:2px;">{init_clock}</div>
        {sub_html}
    </div>
    <script>
        const state = "{t_state}";
        const startTs = {start_ts_ms};
        const clockEl = document.getElementById("clock");
        const elapsedEl = document.getElementById("elapsed_box");
        if (state === "running") {{
            function updateTimer() {{
                const now = Date.now();
                const elapsed = Math.max(0, Math.floor((now - startTs) / 1000));
                const rem = Math.max(0, 300 - elapsed);
                const rm = String(Math.floor(rem / 60)).padStart(2, '0');
                const rs = String(rem % 60).padStart(2, '0');
                const em = String(Math.floor(elapsed / 60)).padStart(2, '0');
                const es = String(elapsed % 60).padStart(2, '0');
                if (clockEl) clockEl.innerText = rm + ":" + rs;
                if (elapsedEl) elapsedEl.innerText = "실시간 경과: " + em + "분 " + es + "초";
            }}
            updateTimer();
            setInterval(updateTimer, 500);
        }}
    </script>
    """, height=142)

    st.markdown(
        '<div class="search-banner-box">'
        '🔍 고장코드 · 고장내용<br>즉시검색'
        '</div>',
        unsafe_allow_html=True
    )
    search_query = st.text_input(
        "검색어 입력",
        value=st.session_state.quick_query,
        label_visibility="collapsed"
    )

    st.markdown('<div class="sidebar-field-label">🚆 편성 번호</div>', unsafe_allow_html=True)
    selected_train = st.selectbox(
        "편성 번호",
        options=[str(i) for i in range(450, 471)],
        index=11,
        label_visibility="collapsed"
    )

    st.markdown('<div class="sidebar-field-label">🚨 고장 호차</div>', unsafe_allow_html=True)
    selected_car = st.selectbox(
        "고장 호차",
        options=list(CAR_SPEC_MAP.keys()),
        index=0,
        format_func=lambda x: f"{x}호차 - {CAR_SPEC_MAP[x]['type']}",
        label_visibility="collapsed"
    )

    cur_ip = get_current_local_ip()
    st.markdown(
        f'<div style="background:#0f172a; border:3px solid #38bdf8; border-radius:10px; padding:10px 8px; margin-top:14px; text-align:center; color:#ffffff; box-sizing:border-box;">'
        f'<div style="font-size:1.05rem; font-weight:900; color:#fde047;">📱 스마트폰 앱 접속 주소</div>'
        f'<div style="font-size:1.15rem; font-weight:900; color:#38bdf8; margin:4px 0; word-break:break-all;">http://{cur_ip}:8501</div>'
        f'<div style="font-size:0.88rem; font-weight:900; color:#e2e8f0; line-height:1.3;">동일 Wi-Fi/핫스팟 연결 후 접속<br>(홈 화면에 추가 시 전용 앱 설치)</div>'
        f'</div>',
        unsafe_allow_html=True
    )

car_cols = st.columns(10)
for car_idx, spec in CAR_SPEC_MAP.items():
    with car_cols[int(car_idx)]:
        if car_idx == selected_car:
            st.markdown(
                f'<div class="car-box-err"><div class="c-num">{car_idx}호차</div>'
                f'<div class="c-type">{spec["short"]}</div><div class="c-st">🚨 고장</div></div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div class="car-box-ok"><div class="c-num">{car_idx}호차</div>'
                f'<div class="c-type">{spec["short"]}</div><div class="c-st">정상</div></div>',
                unsafe_allow_html=True
            )

cur_spec = CAR_SPEC_MAP[selected_car]
st.markdown(
    f'<div class="target-banner">'
    f'🎯 <b>[{selected_train}편성 {selected_car}호차 ({cur_spec["type"]})]</b> &nbsp;|&nbsp; '
    f'<b>주요 기기:</b> {cur_spec["equip"]} &nbsp;|&nbsp; '
    f'<b>차량 핵심 CB:</b> <span style="color:#dc2626; text-decoration:underline;">{cur_spec["key_cb"]}</span>'
    f'</div>',
    unsafe_allow_html=True
)

st.markdown('<div style="font-size:1.45rem; font-weight:900; color:#0f172a; margin:8px 0;">💡 현장 다빈도 고장 9대 원클릭 시연 버튼</div>', unsafe_allow_html=True)
btn_labels = list(CUSTOM_NINE_SCENARIOS.keys())
for row in range(3):
    r_cols = st.columns(3)
    for col_idx in range(3):
        idx = row * 3 + col_idx
        if idx < len(btn_labels):
            lbl = btn_labels[idx]
            display_lbl = CUSTOM_NINE_SCENARIOS[lbl]
            if r_cols[col_idx].button(f"🚨 {display_lbl}", use_container_width=True):
                st.session_state.quick_query = lbl
                st.session_state.timer_state = "running"
                st.session_state.timer_start_ts = time.time()
                st.session_state.timer_elapsed_sec = 0
                st.rerun()

q_raw_clean = search_query.strip()
mapped_key = DIRECT_CODE_AND_CB_MAP.get(q_raw_clean.upper(), q_raw_clean)
if isinstance(mapped_key, str) and mapped_key in PRECISION_MANUAL_DB:
    pass
elif q_raw_clean in PRECISION_MANUAL_DB:
    mapped_key = q_raw_clean

if mapped_key in PRECISION_MANUAL_DB:
    p_data = PRECISION_MANUAL_DB[mapped_key]
    strict_cbs = extract_strict_cbs_from_checklist(p_data["checklist"], p_data["cbs"])
    briefing = {
        "title": p_data["title"],
        "summary": p_data["summary"],
        "cb_table": build_complete_cb_rows(strict_cbs),
        "checklist": p_data["checklist"],
        "cbs": strict_cbs
    }
    effective_query_for_sch = mapped_key
else:
    effective_query_for_sch = DIRECT_CODE_AND_CB_MAP.get(q_raw_clean.upper(), q_raw_clean)
    search_res = engine.search_integrated(effective_query_for_sch, top_k=6)
    briefing = engine.generate_ai_briefing(effective_query_for_sch, search_res)
    cleaned_list = []
    for line in briefing.get("checklist", []):
        if any(bad in line for bad in ["고장코드", "시 동작", "상태 이상 시", "불량 시", "위치오류", "차단상태 시"]):
            continue
        cleaned_list.append(line)
    if cleaned_list:
        briefing["checklist"] = cleaned_list

    strict_cbs = extract_strict_cbs_from_checklist(briefing["checklist"], briefing.get("cbs", []))
    briefing["cbs"] = strict_cbs
    briefing["cb_table"] = build_complete_cb_rows(strict_cbs)

smart_schematics = get_smart_schematics_for_query(effective_query_for_sch, {"keywords": [q_raw_clean], "linked_cbs": briefing["cbs"]})

st.markdown('<div style="margin-top: 14px;"></div>', unsafe_allow_html=True)
nav_titles = [
    "⚡ 1. 응급조치매뉴얼 &\n2. 고장관련 차단기",
    "📐 회로도면 핀포인트 뷰어\n(노란 동그라미 마킹)",
    "📋 3회 반복고장 판정 &\n공식 보고서",
    "🚀 AI 도입성과(ROI) &\n전 노선 확산"
]
nav_cols = st.columns(4)
for idx, n_title in enumerate(nav_titles):
    btn_type = "primary" if st.session_state.active_nav_tab == idx else "secondary"
    if nav_cols[idx].button(n_title, key=f"big_nav_box_{idx}", use_container_width=True, type=btn_type):
        st.session_state.active_nav_tab = idx
        st.rerun()

st.markdown('<div style="margin-bottom: 12px;"></div>', unsafe_allow_html=True)

if st.session_state.active_nav_tab == 0:
    radio_display_text, radio_speech_text = get_radio_display_and_speech(
        selected_train, selected_car, q_raw_clean, briefing
    )
    radio_js_str = json.dumps(radio_speech_text, ensure_ascii=False)

    components.html(f"""
    <div style="background:linear-gradient(90deg, #090d16 0%, #1e3a8a 100%); border:4px solid #fde047; border-radius:14px; padding:18px 24px; display:flex; align-items:center; justify-content:space-between; gap:18px; font-family:'Malgun Gothic', sans-serif; box-sizing:border-box; box-shadow:0 6px 14px rgba(0,0,0,0.25);">
        <div style="flex:1; color:#ffffff; font-size:21px; font-weight:900; line-height:1.5; word-break:keep-all;">
            <span style="background:#dc2626; color:#fde047; border:2px solid #fde047; padding:5px 14px; border-radius:8px; font-size:18px; margin-right:10px; display:inline-block; margin-bottom:6px;">📻 AI 남성 관제사 핵심 응급조치 무전</span><br>
            {radio_display_text}
        </div>
        <div style="display:flex; gap:10px;">
            <button onclick='
                window.speechSynthesis.cancel();
                function speakClearMale() {{
                    let u = new SpeechSynthesisUtterance({radio_js_str});
                    u.lang = "ko-KR";
                    let voices = window.speechSynthesis.getVoices();
                    let korVoices = voices.filter(v => v.lang.includes("ko") || v.lang.includes("KR"));
                    let maleVoice = korVoices.find(v =>
                        v.name.toLowerCase().includes("injoon") ||
                        v.name.toLowerCase().includes("hyunsu") ||
                        v.name.toLowerCase().includes("male") ||
                        v.name.includes("남성") ||
                        v.name.toLowerCase().includes("bongjin")
                    );
                    if (maleVoice) {{
                        u.voice = maleVoice; u.pitch = 0.85; u.rate = 0.95;
                    }} else {{
                        if (korVoices.length > 0) u.voice = korVoices[0];
                        u.pitch = 0.62; u.rate = 0.93;
                    }}
                    window.speechSynthesis.speak(u);
                }}
                if (window.speechSynthesis.getVoices().length === 0) {{
                    window.speechSynthesis.onvoiceschanged = speakClearMale;
                }} else {{
                    speakClearMale();
                }}
            ' style="background:#dc2626; color:#ffffff; border:3px solid #fde047; border-radius:12px; padding:16px 22px; font-size:19px; font-weight:900; cursor:pointer; white-space:nowrap; box-shadow:0 4px 10px rgba(0,0,0,0.3);">
                🔊 남성 관제 음성 송출
            </button>
            <button onclick='window.speechSynthesis.cancel();'
                    style="background:#334155; color:#ffffff; border:2px solid #cbd5e1; border-radius:12px; padding:16px 18px; font-size:18px; font-weight:900; cursor:pointer; white-space:nowrap;">
                ⏹️ 정지
            </button>
        </div>
    </div>
    """, height=145)

    st.markdown(f'<div class="section-title">📞 1. 응급조치매뉴얼 ({briefing["summary"]})</div>', unsafe_allow_html=True)
    for i, step_text in enumerate(briefing["checklist"], 1):
        formatted_step = emphasize_keywords_html(step_text, font_size="1.58rem")
        st.markdown(
            f'<div class="step-card"><span class="step-num-badge">조치 {i}</span>{formatted_step}</div>',
            unsafe_allow_html=True
        )

    st.markdown('<div class="section-title">📊 2. 고장관련 차단기 및 스위치 일람표</div>', unsafe_allow_html=True)
    cb_rows_html = []
    for row in briefing["cb_table"]:
        cb_name_black = f'<span style="color: #0f172a; font-size: 1.42rem; font-weight: 900;">{row["기기 약어 및 명칭"]}</span>'
        cb_rows_html.append(
            f'<tr>'
            f'<td>{cb_name_black}</td>'
            f'<td><span class="loc-badge">{row["설치 위치"]}</span></td>'
            f'<td><span class="symptom-text">⚡ {row["트립(차단) 및 불량 시 증상"]}</span></td>'
            f'<td><span class="action-text">✅ {emphasize_keywords_html(row["핵심 확인 및 조치요령"], font_size="1.40rem")}</span></td>'
            f'</tr>'
        )

    cb_table_full_html = (
        '<table class="cb-master-table">'
        '<thead><tr>'
        '<th style="width:23%;">차단기 / 계전기 명칭</th>'
        '<th style="width:16%;">설치 위치</th>'
        '<th style="width:30%;">트립(차단) 시 증상</th>'
        '<th style="width:31%;">핵심 조치요령</th>'
        '</tr></thead>'
        '<tbody>' + "".join(cb_rows_html) + '</tbody></table>'
    )
    st.markdown(cb_table_full_html, unsafe_allow_html=True)

elif st.session_state.active_nav_tab == 1:
    st.markdown('<div class="section-title">📐 주요도면집(회로도면집) 고해상도 노란 동그라미 핀포인트 뷰어</div>', unsafe_allow_html=True)

    all_page_nums = sorted(SCHEMATIC_PAGE_CATALOG.keys())
    smart_page_nums = [s["page"] for s in smart_schematics]
    ordered_pages = smart_page_nums + [p for p in all_page_nums if p not in smart_page_nums]

    ctrl_c1, ctrl_c2 = st.columns([1.25, 1.0])
    with ctrl_c1:
        selected_page_num = st.selectbox(
            "📂 회로도면 선택 (상단: AI 고장직결 추천 도면 / 하단: 27개 전체 도면):",
            options=ordered_pages,
            format_func=lambda p: (
                f"★ AI추천 {smart_page_nums.index(p)+1}순위 | {SCHEMATIC_PAGE_CATALOG[p]['title']} ({p}p)"
                if p in smart_page_nums else
                f"📄 전체도면 | {SCHEMATIC_PAGE_CATALOG[p]['title']} ({p}p)"
            )
        )

    cat_info = SCHEMATIC_PAGE_CATALOG[selected_page_num]
    current_sch = {
        "source_file": SCHEMATIC_PDF_NAME,
        "page": selected_page_num,
        "title": f"{cat_info['title']} ({cat_info['dwg']})",
        "components": cat_info["comps"]
    }

    page_comps = [c.upper() for c in cat_info["comps"]]
    scenario_targets = briefing.get("cbs", [])
    matched_default = [
        t for t in scenario_targets
        if any(t.upper() == c or t.upper() in c or c in t.upper() for c in page_comps)
    ]
    if not matched_default:
        matched_default = scenario_targets

    with ctrl_c2:
        custom_highlight = st.text_input(
            "🎯 하이라이트 기기명 (응급조치매뉴얼 본문 직결 기기만 자동 표시):",
            value=", ".join(matched_default),
            key=f"hl_input_{effective_query_for_sch}_{selected_page_num}"
        )

    highlight_terms = [t.strip() for t in custom_highlight.split(",") if t.strip()]
    highlighted_img, hit_count, matched_names = render_highlighted_schematic_circle(current_sch, highlight_terms)

    chips_html = "".join([f'<span class="hl-chip">🎯 {m_name}</span>' for m_name in matched_names])
    st.markdown(
        f'<div class="hl-tag-bar">'
        f'<span class="hl-tag-title">🟡 현재 도면 핀포인트 타겟 ({hit_count}개소 정밀 마킹):</span>'
        f'{chips_html}'
        f'</div>',
        unsafe_allow_html=True
    )

    if highlighted_img:
        st.image(highlighted_img, use_container_width=True)

elif st.session_state.active_nav_tab == 2:
    st.markdown('<div class="section-title">📋 동일 호차 3회 반복고장 자동 판정 및 공식 보고서</div>', unsafe_allow_html=True)
    reg_col1, reg_col2 = st.columns([1.05, 1.95])
    with reg_col1:
        with st.form("fault_form"):
            f_train = st.text_input("편성 번호", value=selected_train)
            f_car = st.text_input("호차 번호", value=selected_car)
            f_device = st.selectbox("고장 장치", options=["공기/제동장치", "차상신호장치", "출입문장치", "주변환장치(CI)", "보조전원장치(SIV)"])
            f_symptom = st.text_input("고장 현상", value=f"{selected_car}호차 {briefing['title']}")
            f_action = st.text_input("조치 내용", value="응급조치매뉴얼에 의거 관련 CB 복구")

            reg_btn_col1, reg_btn_col2 = st.columns(2)
            with reg_btn_col1:
                submit_reg = st.form_submit_button("🚨 고장 이력 등록", use_container_width=True)
            with reg_btn_col2:
                submit_reset = st.form_submit_button("🔄 이력 초기화", use_container_width=True)

            if submit_reg:
                res = engine.evaluate_and_record_fault(f_train, f_car, f_device, f_symptom, f_action)
                if res["is_repeat_alert"]:
                    st.error(res["alert_msg"])
                else:
                    st.success(res["alert_msg"])
                st.rerun()

            if submit_reset:
                engine.reset_fault_history()
                st.success("✅ 고장 이력이 완전히 초기화되었습니다.")
                st.rerun()

    with reg_col2:
        history_data = engine.history
        if history_data:
            df_export = pd.DataFrame(history_data)
            df_export = df_export.rename(columns={
                "date": "발생일시", "train_no": "편성", "car_no": "호차",
                "raw_device": "장치명", "symptom": "고장현상", "action": "조치내용",
                "repeat_count": "누적횟수", "remark": "비고(3회이상_중정비이관)"
            })
            csv_bytes = df_export[["발생일시", "편성", "호차", "장치명", "고장현상", "조치내용", "누적횟수", "비고(3회이상_중정비이관)"]].to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                label="📥 제1관제센터 일일 고장보고서 엑셀(CSV) 즉시 다운로드",
                data=csv_bytes,
                file_name=f"제1관제센터_4호선210칸_고장보고서_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )

        total_rows = len(history_data)
        if total_rows == 0:
            st.info("ℹ️ 등록된 고장 이력이 없습니다. (이력이 깨끗하게 초기화되었습니다)")
        else:
            rep_rows = []
            for idx, item in enumerate(history_data):
                rem = f'<span class="badge-repeat">{item["remark"]} (기지이관)</span>' if item.get("remark") else "-"
                first_col = f'<td rowspan="{total_rows}" style="font-weight:900; background:#f8fafc; font-size:1.3rem;">4호선<br>(210칸)</td>' if idx == 0 else ""
                rep_rows.append(
                    f'<tr>{first_col}<td>{item["date"]}</td><td><b>{item["train_no"]}</b></td><td><b>{item["car_no"]}</b></td>'
                    f'<td>{item["raw_device"]}</td><td style="text-align:left;"><b>[현상]</b> {item["symptom"]}<br><b>[조치]</b> {item["action"]}</td>'
                    f'<td><b>{item["repeat_count"]}회</b></td><td>{rem}</td></tr>'
                )

            table_html = (
                '<table class="report-table"><thead><tr>'
                '<th style="width:11%;">호선 구분</th>'
                '<th style="width:15%;">발생일시</th><th style="width:8%;">편성</th><th style="width:7%;">호차</th>'
                '<th style="width:13%;">장치명</th><th style="width:27%;">현상 및 조치</th><th style="width:8%;">횟수</th><th style="width:11%;">비고(3회↑)</th>'
                '</tr></thead><tbody>' + "".join(rep_rows) + '</tbody></table>'
            )
            st.markdown(table_html, unsafe_allow_html=True)

elif st.session_state.active_nav_tab == 3:
    st.markdown('<div class="section-title">🚀 『METRO AI-THON』 기대효과 및 1~8호선 전 노선 확산 로드맵</div>', unsafe_allow_html=True)
    r1, r2, r3, r4 = st.columns(4)
    with r1:
        st.markdown('<div class="roi-card"><div class="roi-lbl">⏱️ 매뉴얼·도면 탐색 시간</div><div class="roi-val">180초 ➔ 3초</div><div style="font-size:1.2rem; font-weight:900; color:#ffffff;">98.3% 단축 (골든타임 확보)</div></div>', unsafe_allow_html=True)
    with r2:
        st.markdown('<div class="roi-card"><div class="roi-lbl">📚 통합 데이터 범위</div><div class="roi-val">총 1,220 페이지</div><div style="font-size:1.2rem; font-weight:900; color:#ffffff;">고장매뉴얼·응급요령·도면 6종</div></div>', unsafe_allow_html=True)
    with r3:
        st.markdown('<div class="roi-card"><div class="roi-lbl">🔒 보안 및 망분리 적합성</div><div class="roi-val">100% 로컬 구동</div><div style="font-size:1.2rem; font-weight:900; color:#ffffff;">외부 API 비용 0원 · 사내망 즉시적용</div></div>', unsafe_allow_html=True)
    with r4:
        st.markdown('<div class="roi-card"><div class="roi-lbl">🚇 타 호선 확장성</div><div class="roi-val">1~8호선 즉시호환</div><div style="font-size:1.2rem; font-weight:900; color:#ffffff;">PDF 교체만으로 전 차종 적용</div></div>', unsafe_allow_html=True)

    st.divider()
    st.markdown(
        '<div class="step-card" style="border-left-color:#1e3a8a;">'
        '<span class="step-num-badge" style="background:#1e3a8a;">확산 1단계</span>'
        '<b>제1관제센터 (1~4호선) 표준화:</b> 4호선 다원시스 210칸(450~470편성) 운영 실증 후 1·2·3호선 신조차 매뉴얼 DB 즉시 탑재'
        '</div>'
        '<div class="step-card" style="border-left-color:#0284c7;">'
        '<span class="step-num-badge" style="background:#0284c7;">확산 2단계</span>'
        '<b>제2관제센터 (5~8호선) 및 차량기지 연동:</b> 3회 이상 반복고장 판정 데이터를 해당 차량기지와 실시간 공유하여 예방정비 실현'
        '</div>',
        unsafe_allow_html=True
    )