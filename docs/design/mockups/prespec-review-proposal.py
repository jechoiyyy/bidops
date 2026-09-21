#!/usr/bin/env python3
"""Standalone visual proposal for the BidOps pre-spec review list and report.

The generator deliberately has no application or network dependency.  It reads the
installed Astryx reset/core CSS and the checked-in BidOps theme, then writes one
self-contained file that can be opened with ``file://``.
"""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRONTEND_ROOT = Path(os.environ.get("BIDOPS_FRONTEND_ROOT", HERE.parents[2] / "web" / "frontend"))
OUTPUT = HERE / "_preview" / "prespec-review-proposal.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Keep the component recipes in step with the classes extracted from the installed
# Astryx build.  The proposal owns layout CSS, while buttons, inputs, badges and
# typography use these real class strings.
ASTRYX_CLASSES = json.loads(_read(HERE / "astryx-classes.json"))
CORE_CSS = _read(FRONTEND_ROOT / "node_modules" / "@astryxdesign" / "core" / "dist" / "astryx.css")
DISABLED_ATOMS = {
    match.group(1)
    for match in re.finditer(
        r"\.(x[0-9a-z]+)(?::not\(#\\#\))+\{([^}]*)\}", CORE_CSS
    )
    if "opacity:.5" in match.group(2).replace(" ", "")
    or "pointer-events:none" in match.group(2).replace(" ", "")
}


def astryx_class(component: str, *parts: str, enabled: bool = True) -> str:
    candidates = [classes for _tag, classes in ASTRYX_CLASSES[component]]
    matches = [classes for classes in candidates if all(part in classes.split() for part in parts)]
    if enabled:
        active_matches = [
            classes for classes in matches if not (set(classes.split()) & DISABLED_ATOMS)
        ]
        matches = active_matches or matches
    if not matches:
        raise KeyError(f"No Astryx class recipe for {component} {parts}")
    return min(matches, key=lambda classes: len(classes.split()))


CLS = {
    "buttonPrimary": astryx_class("astryx-button", "primary", "sm", enabled=True),
    "buttonSecondary": astryx_class("astryx-button", "secondary", "sm", enabled=True),
    "badgeWarning": astryx_class("astryx-badge", "warning"),
    "badgeNeutral": astryx_class("astryx-badge", "neutral"),
    "badgeInfo": astryx_class("astryx-badge", "info"),
    "badgeSuccess": astryx_class("astryx-badge", "success"),
    "textBody": astryx_class("astryx-text", "body", "primary"),
    "textSecondary": astryx_class("astryx-text", "body", "secondary"),
    "textLabel": astryx_class("astryx-text", "label", "secondary"),
    "textSupporting": astryx_class("astryx-text", "supporting", "secondary"),
    "heading3": astryx_class("astryx-heading", "level-3"),
    "heading4": astryx_class("astryx-heading", "level-4"),
    "textInput": astryx_class("astryx-text-input", "sm"),
    "selector": astryx_class("astryx-selector", "input", "sm"),
    "statusDot": astryx_class("astryx-status-dot"),
}

DATA = [
    {
        "id": "notice-001",
        "title": "2026년 공공데이터 개방·활용 확산을 위한 통합 플랫폼 구축 및 운영 고도화 사업",
        "agency": "가상 행정안전부",
        "number": "PS-26-001",
        "budget": "9억 8,000만 원",
        "schedule": "2026.11 ~ 2027.10",
        "deadline": "2026.09.25",
        "category": "SW사업대상",
        "grade": "우선 검토",
        "tracking": "미선택",
        "summary": "분산된 공공데이터를 한 곳에서 검색·개방하고 이용 현황을 관리하는 통합 플랫폼을 구축합니다.",
        "caution": "기존 데이터 표준과 연계 대상 시스템의 범위가 원문에서 추가 확인 필요",
        "tasks": [
            "데이터 카탈로그·검색·개방 포털 구축",
            "기관별 연계 API와 품질 모니터링",
            "운영자 권한·통계 대시보드 제공",
        ],
        "participation": ["유사 플랫폼 구축 실적 제출", "개인정보 보호 및 보안 계획", "상주 운영 인력 계획"],
        "fit": ["내부 역량 자료 대조 전", "공공데이터 표준 경험은 별도 확인"],
        "risks": ["연계 API 목록과 데이터 이관량 미확인", "운영 전환 일정의 승인 조건 미확인"],
        "evidence": ["사업 개요 2쪽 · 데이터 개방 범위", "제안요청 안내 5쪽 · 연계 요구"],
        "attachments": ["사전규격서.pdf · 18쪽", "연계 대상 목록.xlsx · 4쪽"],
        "history": ["2026.09.12 · 수집 · 합성 레코드 생성", "2026.09.13 · 개요 검토 대기"],
    },
    {
        "id": "notice-002",
        "title": "지역 공공시설 안전관리 통합관제 고도화",
        "agency": "가상 부산광역시 시설관리공단",
        "number": "PS-26-002",
        "budget": "4억 2,000만 원",
        "schedule": "2026.10 ~ 2027.03",
        "deadline": "2026.09.19",
        "category": "일반용역",
        "grade": "검토 권장",
        "tracking": "계속 추적",
        "summary": "시설 센서와 점검 이력을 통합해 안전 이상을 조기에 확인하는 관제 화면을 개선합니다.",
        "caution": "센서 설치 위치와 현장 통신 품질의 확인이 필요합니다",
        "tasks": ["센서 이벤트 수집·정규화", "위험도별 관제 화면", "점검 이력과 조치 보고서"],
        "participation": ["시설 안전 분야 인력", "24시간 장애 대응 체계"],
        "fit": ["운영 인력 배치 계획 확인 전", "유사 실적 제출 형식 확인 전"],
        "risks": ["현장 네트워크 장애 대응 범위 미확인"],
        "evidence": ["사업 개요 1쪽 · 관제 목표", "요구사항 8쪽 · 장애 대응"],
        "attachments": ["사전규격서.pdf · 12쪽"],
        "history": ["2026.09.10 · 수집 · 합성 레코드 생성", "2026.09.11 · 추적 시작(시안)"],
    },
    {
        "id": "notice-003",
        "title": "교육행정 데이터 품질관리 체계 개선",
        "agency": "가상 국가교육데이터센터",
        "number": "PS-26-003",
        "budget": "1억 6,000만 원",
        "schedule": "2026.11 ~ 2027.04",
        "deadline": "2026.09.30",
        "category": "SW사업대상",
        "grade": "관찰 대상",
        "tracking": "미선택",
        "summary": "교육행정 데이터의 오류를 찾아 정정 이력을 남기는 품질관리 체계를 정비합니다.",
        "caution": "품질 기준과 측정 지표가 초안 상태인지 확인해야 합니다",
        "tasks": ["품질 규칙 관리", "오류 탐지·정정 이력", "부서별 품질 리포트"],
        "participation": ["데이터 품질관리 경험", "개인정보 처리 절차"],
        "fit": ["회사 역량 검증 전 · 내부 자료 대조 필요"],
        "risks": ["원천 시스템별 데이터 정의 차이"],
        "evidence": ["품질관리 초안 3쪽 · 측정 지표"],
        "attachments": ["사전규격서.pdf · 9쪽", "데이터 사전.csv · 1개"],
        "history": ["2026.09.12 · 수집 · 합성 레코드 생성"],
    },
    {
        "id": "notice-004",
        "title": "지방세 모바일 고지 서비스 운영지원",
        "agency": "가상 전라북도",
        "number": "PS-26-004",
        "budget": None,
        "schedule": None,
        "deadline": "2026.09.18",
        "category": "일반용역",
        "grade": "검토 권장",
        "tracking": "미선택",
        "summary": "모바일 고지 서비스의 운영지원과 장애 대응 절차를 정리합니다.",
        "caution": "예산과 사업 기간이 공개되지 않아 참여 규모를 판단할 수 없습니다",
        "tasks": ["운영 모니터링", "장애 접수·복구", "월간 운영 보고"],
        "participation": ["운영지원 인력과 연락 체계"],
        "fit": ["회사 역량 확인 전 · 자격 미확인"],
        "risks": ["예산·기간·서비스 수준 미확인"],
        "evidence": ["사전규격 안내 1쪽 · 운영지원 범위"],
        "attachments": ["사전규격서.pdf · 7쪽"],
        "history": ["2026.09.13 · 수집 · 합성 레코드 생성"],
    },
    {
        "id": "notice-005",
        "title": "공공기관 내부 업무포털 접근성 개선 컨설팅",
        "agency": "가상 국가기록원",
        "number": "PS-26-005",
        "budget": "7,500만 원",
        "schedule": "2026.10 ~ 2026.12",
        "deadline": None,
        "category": "컨설팅",
        "grade": "관찰 대상",
        "tracking": "보류",
        "summary": "내부 업무포털의 접근성 진단과 개선 우선순위를 도출합니다.",
        "caution": "의견등록 마감일이 확인되지 않아 일정 확인이 필요합니다",
        "tasks": ["접근성 현황 진단", "사용자 여정별 개선안", "개선 우선순위 보고"],
        "participation": ["웹 접근성 진단 경험", "진단 방법론 제시"],
        "fit": ["내부 역량 자료 대조 전"],
        "risks": ["마감 일시 미확인"],
        "evidence": ["과업 초안 2쪽 · 진단 대상"],
        "attachments": ["과업지시서.pdf · 6쪽"],
        "history": ["2026.09.09 · 수집 · 합성 레코드 생성"],
    },
    {
        "id": "notice-006",
        "title": "도시재생 사업 성과관리 시스템 유지관리",
        "agency": "가상 대전광역시",
        "number": "PS-26-006",
        "budget": "2억 1,000만 원",
        "schedule": "2026.12 ~ 2027.11",
        "deadline": "2026.10.02",
        "category": "SW사업대상",
        "grade": "우선 검토",
        "tracking": "미선택",
        "summary": "도시재생 사업별 성과지표와 증빙 자료를 관리하는 시스템을 유지보수합니다.",
        "caution": "기존 운영사 인수인계 방식과 소스 접근 권한을 확인해야 합니다",
        "tasks": ["성과지표 관리", "증빙 자료 등록", "운영·장애 지원"],
        "participation": ["유지관리 인력 상주 계획", "보안서약 및 접근통제"],
        "fit": ["유지관리 실적 확인 전"],
        "risks": ["소스 저장소·인수인계 범위 미확인"],
        "evidence": ["과업지시서 4쪽 · 유지관리 범위"],
        "attachments": ["사전규격서.pdf · 14쪽"],
        "history": ["2026.09.12 · 수집 · 합성 레코드 생성"],
    },
    {
        "id": "notice-007",
        "title": "공공도서관 지능형 자료검색 시범사업",
        "agency": "가상 서울특별시 도서관사업소",
        "number": "PS-26-007",
        "budget": None,
        "schedule": "2026.11 ~ 2027.02",
        "deadline": "2026.09.27",
        "category": "SW사업대상",
        "grade": "검토 권장",
        "tracking": "미선택",
        "summary": "도서관 자료 메타데이터를 활용한 검색·추천 기능의 시범 적용을 검토합니다.",
        "caution": "예산 정보가 없어 시범 범위와 비용 구조를 확인해야 합니다",
        "tasks": ["메타데이터 정비", "검색·추천 시범 기능", "이용자 피드백 분석"],
        "participation": ["검색 서비스 구축 경험", "시범 운영 계획"],
        "fit": ["회사 역량 확인 전"],
        "risks": ["예산·대상 도서관 수 미확인"],
        "evidence": ["사업 개요 2쪽 · 시범 범위"],
        "attachments": ["사전규격서.pdf · 10쪽"],
        "history": ["2026.09.08 · 수집 · 합성 레코드 생성"],
    },
    {
        "id": "notice-008",
        "title": "재난문자 발송 이력 분석 및 대시보드 구축",
        "agency": "가상 광주광역시",
        "number": "PS-26-008",
        "budget": "3억 4,000만 원",
        "schedule": "2026.10 ~ 2027.05",
        "deadline": "2026.09.21",
        "category": "SW사업대상",
        "grade": "우선 검토",
        "tracking": "계속 추적",
        "summary": "재난문자 발송 데이터를 분석해 지역별 도달 현황과 개선 지표를 제공합니다.",
        "caution": "개인정보 비식별 처리 기준과 보존 기간을 확인해야 합니다",
        "tasks": ["발송 이력 적재", "지역별 분석 화면", "비식별·보존 정책"],
        "participation": ["데이터 분석·시각화 경험", "개인정보 보호 조치"],
        "fit": ["내부 역량 자료 대조 전"],
        "risks": ["원천 데이터 보존 기간 미확인"],
        "evidence": ["요구사항 6쪽 · 분석 지표"],
        "attachments": ["사전규격서.pdf · 11쪽"],
        "history": ["2026.09.11 · 수집 · 합성 레코드 생성", "2026.09.12 · 추적 시작(시안)"],
    },
    {
        "id": "notice-009",
        "title": "지역문화 행사 통합예약 시스템 개선",
        "agency": "가상 제주특별자치도",
        "number": "PS-26-009",
        "budget": "8,800만 원",
        "schedule": None,
        "deadline": "2026.09.29",
        "category": "일반용역",
        "grade": "관찰 대상",
        "tracking": "미선택",
        "summary": "지역문화 행사 검색과 예약 흐름을 한 화면에서 이용하도록 개선합니다.",
        "caution": "사업 기간이 미확인이라 운영 전환 일정을 확인해야 합니다",
        "tasks": ["행사 검색·필터", "예약·결제 연계", "운영자 관리 화면"],
        "participation": ["예약 서비스 운영 경험"],
        "fit": ["회사 역량 확인 전"],
        "risks": ["기존 결제 연계와 사업 기간 미확인"],
        "evidence": ["과업 초안 1쪽 · 서비스 개선"],
        "attachments": ["사전규격서.pdf · 8쪽"],
        "history": ["2026.09.13 · 수집 · 합성 레코드 생성"],
    },
]

CUSTOM_CSS = r"""
/* Proposal-owned layout. Every color comes from the BidOps theme scope. */
html, body { width: 100%; height: 100%; min-width: 1280px; overflow: hidden; }
body { margin: 0; background: var(--color-background-body); color: var(--color-text-primary); font-family: var(--font-family-body); }
button, input, select, textarea { font: inherit; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; }
.pr-app { width: 100%; height: 100vh; min-width: 1280px; overflow: hidden; background: var(--color-background-body); }
.pr-shell { display: grid; grid-template-columns: 232px minmax(0, 1fr); width: 100%; height: 100%; min-height: 0; }
.pr-sidebar { display: flex; flex-direction: column; min-height: 0; padding: var(--spacing-6) var(--spacing-4) var(--spacing-4); background: var(--color-background-inverted); color: var(--color-on-dark); }
.pr-brand { display: flex; align-items: center; gap: var(--spacing-2); padding: 0 var(--spacing-2) var(--spacing-6); }
.pr-brand-mark { display: grid; place-items: center; width: 32px; height: 32px; border-radius: var(--radius-inner); background: var(--color-accent); color: var(--color-on-accent); font-weight: var(--font-weight-bold); }
.pr-brand-copy { display: grid; gap: var(--spacing-0-5); }
.pr-brand-name { color: var(--color-on-dark); font-size: var(--bo-type-body); font-weight: var(--font-weight-bold); }
.pr-brand-sub { color: var(--color-on-dark); opacity: .72; font-size: var(--bo-type-caption); }
.pr-nav { display: grid; gap: var(--spacing-5); }
.pr-nav-group { display: grid; gap: var(--spacing-1); }
.pr-nav-label { padding: 0 var(--spacing-2); color: var(--color-on-dark); opacity: .58; font-size: var(--bo-type-caption); font-weight: var(--font-weight-semibold); letter-spacing: .02em; }
.pr-nav-item { display: flex; align-items: center; gap: var(--spacing-2); min-height: 34px; padding: 0 var(--spacing-2); border-radius: var(--radius-inner); color: var(--color-on-dark); opacity: .82; font-size: var(--bo-type-caption); }
.pr-nav-item.is-active { background: color-mix(in srgb, var(--color-on-dark) 13%, transparent); opacity: 1; font-weight: var(--font-weight-semibold); }
.pr-nav-dot { width: 6px; height: 6px; border-radius: var(--radius-full); background: currentColor; opacity: .65; }
.pr-nav-item.is-active .pr-nav-dot { background: var(--color-accent); opacity: 1; }
.pr-sidebar-foot { margin-top: auto; padding: var(--spacing-3) var(--spacing-2) 0; border-top: 1px solid color-mix(in srgb, var(--color-on-dark) 20%, transparent); color: var(--color-on-dark); opacity: .66; font-size: var(--bo-type-caption); line-height: 1.6; }
.pr-main { display: flex; width: 100%; min-width: 0; height: 100%; min-height: 0; flex-direction: column; overflow: hidden; }
.pr-topbar { display: flex; align-items: center; gap: var(--spacing-4); min-height: 72px; padding: 0 var(--spacing-6); border-bottom: 1px solid var(--color-border); background: var(--color-background-surface); }
.pr-topbar-main { display: grid; gap: var(--spacing-1); min-width: 0; }
.pr-breadcrumb { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-page-title { margin: 0; font-size: var(--bo-type-page-title); line-height: var(--bo-type-page-title-leading); font-weight: var(--font-weight-semibold); }
.pr-sample-indicator { margin-left: auto; padding: var(--spacing-1) var(--spacing-2); border: 1px solid var(--color-border); border-radius: var(--radius-full); color: var(--color-text-secondary); background: var(--color-background-muted); font-size: var(--bo-type-caption); white-space: nowrap; }
.pr-view { flex: 1; min-height: 0; }
.pr-list-view { display: grid; grid-template-rows: auto auto minmax(0, 1fr); gap: var(--spacing-3); height: 100%; min-height: 0; padding: var(--spacing-4) var(--spacing-6) var(--spacing-5); overflow: hidden; }
.pr-list-heading { display: flex; align-items: end; justify-content: space-between; gap: var(--spacing-4); }
.pr-heading-block { display: grid; gap: var(--spacing-1); }
.pr-heading-block h2 { margin: 0; font-size: var(--bo-type-section-title); line-height: var(--bo-type-section-title-leading); }
.pr-heading-support { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-toolbar { display: flex; align-items: end; gap: var(--spacing-2); padding: var(--spacing-3); border: 1px solid var(--color-border); border-radius: var(--radius-container); background: var(--color-background-surface); }
.pr-field { display: grid; gap: var(--spacing-1); }
.pr-field label { color: var(--color-text-secondary); font-size: var(--bo-type-caption); font-weight: var(--font-weight-semibold); }
.pr-search-field { width: 340px; }
.pr-filter-field { width: 160px; }
.pr-toolbar .astryx-text-input, .pr-toolbar .astryx-selector { min-height: 32px; width: 100%; }
.pr-toolbar input, .pr-toolbar select { width: 100%; min-height: 32px; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; }
.pr-toolbar input { padding: var(--spacing-1) var(--spacing-2); }
.pr-toolbar select { padding: var(--spacing-1) var(--spacing-2); }
.pr-bulk-actions { display: flex; align-items: center; gap: var(--spacing-1); margin-left: auto; }
.pr-bulk-actions .astryx-button { white-space: nowrap; }
.pr-list-layout { display: grid; grid-template-columns: minmax(0, 1fr) 440px; min-height: 0; border: 1px solid var(--color-border); border-radius: var(--radius-container); background: var(--color-background-surface); overflow: hidden; }
.pr-list-column { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; min-width: 0; min-height: 0; }
.pr-list-meta { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-3); min-height: 40px; padding: 0 var(--spacing-4); border-bottom: 1px solid var(--color-border); }
.pr-result-count { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-result-count strong { color: var(--color-text-primary); font-weight: var(--font-weight-semibold); }
.pr-list-note { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-rows { min-height: 0; overflow: auto; }
.pr-row { display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; gap: var(--spacing-2); align-items: start; padding: var(--spacing-3) var(--spacing-4); border-bottom: 1px solid var(--color-border); outline: 0; }
.pr-row:hover, .pr-row:focus-visible { background: var(--color-overlay-hover); }
.pr-row.is-active { box-shadow: inset 3px 0 0 var(--color-accent); background: var(--color-accent-muted); }
.pr-row-check { display: grid; place-items: start center; padding-top: 2px; }
.pr-row-check input { width: 16px; height: 16px; accent-color: var(--color-accent); }
.pr-row-main { display: grid; gap: var(--spacing-1); min-width: 0; }
.pr-row-title { color: var(--color-text-primary); font-size: var(--bo-type-body); line-height: var(--bo-type-body-leading); font-weight: var(--font-weight-semibold); }
.pr-row-agency { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-row-meta { display: flex; flex-wrap: wrap; gap: var(--spacing-1) var(--spacing-2); align-items: center; color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-row-meta span + span { position: relative; }
.pr-row-meta span + span::before { content: "·"; position: absolute; left: calc(-1 * var(--spacing-2)); color: var(--color-border-emphasized); }
.pr-row-aside { display: grid; justify-items: end; gap: var(--spacing-2); min-width: 126px; }
.pr-row-status { display: flex; align-items: center; gap: var(--spacing-1); color: var(--color-text-secondary); font-size: var(--bo-type-caption); white-space: nowrap; }
.pr-row-status .pr-status-dot { width: 7px; height: 7px; }
.pr-grade { display: inline-flex; align-items: center; min-height: 22px; padding: 0 var(--spacing-2); border: 1px solid var(--color-border); border-radius: var(--radius-full); color: var(--color-text-primary); font-size: var(--bo-type-caption); font-weight: var(--font-weight-semibold); }
.pr-grade.is-g1 { border-color: var(--color-accent); background: var(--color-accent); color: var(--color-on-accent); }
.pr-grade.is-g2 { border-color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 22%, var(--color-background-surface)); }
.pr-grade.is-g3 { background: var(--color-background-muted); }
.pr-row-open { padding: 0; border: 0; color: var(--color-text-accent); background: transparent; font-size: var(--bo-type-caption); text-decoration: underline; text-underline-offset: 3px; }
.pr-list-footer { display: flex; align-items: center; justify-content: space-between; min-height: 48px; padding: 0 var(--spacing-4); border-top: 1px solid var(--color-border); }
.pr-page-controls { display: flex; align-items: center; gap: var(--spacing-1); }
.pr-page-controls .astryx-button { min-width: 32px; }
.pr-page-indicator { min-width: 72px; color: var(--color-text-secondary); font-size: var(--bo-type-caption); text-align: center; }
.pr-panel { display: flex; min-width: 0; min-height: 0; flex-direction: column; border-left: 1px solid var(--color-border); background: var(--color-background-card); }
.pr-panel-head { display: grid; gap: var(--spacing-1); padding: var(--spacing-4); border-bottom: 1px solid var(--color-border); }
.pr-panel-kicker { color: var(--color-text-accent); font-size: var(--bo-type-caption); font-weight: var(--font-weight-semibold); }
.pr-panel-title { margin: 0; font-size: var(--bo-type-body); line-height: var(--bo-type-body-leading); }
.pr-panel-agency { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-panel-body { display: grid; gap: var(--spacing-3); padding: var(--spacing-4); }
.pr-panel-section { display: grid; gap: var(--spacing-1); }
.pr-panel-section h3 { margin: 0; font-size: var(--bo-type-section-title); font-weight: var(--font-weight-semibold); }
.pr-panel-summary { margin: 0; color: var(--color-text-secondary); font-size: var(--bo-type-caption); line-height: var(--bo-type-caption-leading); }
.pr-task-list { display: grid; gap: var(--spacing-1); margin: 0; padding: 0; list-style: none; }
.pr-task-list li { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: var(--spacing-1); color: var(--color-text-primary); font-size: var(--bo-type-caption); line-height: var(--bo-type-caption-leading); }
.pr-task-list li::before { content: attr(data-index); color: var(--color-text-accent); font-weight: var(--font-weight-semibold); }
.pr-facts { display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-2); margin: 0; }
.pr-fact { display: grid; gap: var(--spacing-0-5); }
.pr-fact dt { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-fact dd { margin: 0; color: var(--color-text-primary); font-size: var(--bo-type-caption); font-weight: var(--font-weight-semibold); }
.pr-caution { display: grid; gap: var(--spacing-1); padding: var(--spacing-2); border: 1px solid var(--color-warning); border-radius: var(--radius-inner); background: var(--color-warning-muted); }
.pr-caution-head { display: flex; align-items: center; gap: var(--spacing-1); color: var(--color-warning); font-size: var(--bo-type-section-title); font-weight: var(--font-weight-semibold); }
.pr-status-dot { display: inline-block; width: 8px; height: 8px; flex: 0 0 auto; border-radius: var(--radius-full); background: var(--color-warning); }
.pr-status-dot.is-success { background: var(--color-success); }
.pr-caution p { margin: 0; color: var(--color-text-primary); font-size: var(--bo-type-caption); line-height: var(--bo-type-caption-leading); }
.pr-panel-foot { display: flex; align-items: center; gap: var(--spacing-2); margin-top: auto; padding: var(--spacing-4); border-top: 1px solid var(--color-border); }
.pr-panel-foot .astryx-button { flex: 1; }
.pr-empty { display: grid; place-items: center; min-height: 240px; color: var(--color-text-secondary); font-size: var(--bo-type-body); }
.pr-detail-view { min-height: 0; overflow: auto; padding: var(--spacing-6) max(var(--spacing-6), 5vw) var(--spacing-10); }
.pr-detail-wrap { width: min(1080px, 100%); margin: 0 auto; }
.pr-detail-top { display: flex; align-items: start; justify-content: space-between; gap: var(--spacing-5); margin-bottom: var(--spacing-5); }
.pr-detail-top-main { display: grid; gap: var(--spacing-2); min-width: 0; }
.pr-detail-breadcrumb { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-detail-title { margin: 0; font-size: var(--bo-type-page-title); line-height: var(--bo-type-page-title-leading); font-weight: var(--font-weight-semibold); }
.pr-detail-agency { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-detail-actions { display: flex; align-items: center; gap: var(--spacing-2); flex: 0 0 auto; }
.pr-detail-nav { display: flex; gap: var(--spacing-1); }
.pr-detail-section { display: grid; gap: var(--spacing-4); margin-top: var(--spacing-5); padding-top: var(--spacing-5); border-top: 1px solid var(--color-border); }
.pr-detail-section:first-of-type { margin-top: 0; padding-top: 0; border-top: 0; }
.pr-section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: var(--spacing-3); }
.pr-section-heading h2 { margin: 0; font-size: var(--bo-type-section-title); line-height: var(--bo-type-section-title-leading); }
.pr-section-heading p { margin: 0; color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-summary-grid { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(280px, .9fr); gap: var(--spacing-5); }
.pr-summary-copy { display: grid; gap: var(--spacing-3); }
.pr-summary-copy p { margin: 0; color: var(--color-text-secondary); font-size: var(--bo-type-body); line-height: var(--bo-type-body-leading); }
.pr-identity { display: flex; flex-wrap: wrap; gap: var(--spacing-2); align-items: center; }
.pr-identity span { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-detail-facts { align-self: start; }
.pr-tracking-bar { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-4); padding: var(--spacing-3); border: 1px solid var(--color-border); border-radius: var(--radius-container); background: var(--color-background-muted); }
.pr-tracking-copy { display: grid; gap: var(--spacing-1); }
.pr-tracking-copy strong { font-size: var(--bo-type-body); }
.pr-tracking-copy span { color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-report-list { display: grid; gap: var(--spacing-2); margin: 0; padding: 0; list-style: none; }
.pr-report-list li { display: grid; grid-template-columns: 28px minmax(0, 1fr); gap: var(--spacing-2); align-items: start; padding: var(--spacing-2) 0; border-bottom: 1px solid var(--color-border); font-size: var(--bo-type-body); line-height: var(--bo-type-body-leading); }
.pr-report-list li:last-child { border-bottom: 0; }
.pr-report-index { display: grid; place-items: center; width: 24px; height: 24px; border-radius: var(--radius-full); background: var(--color-accent-muted); color: var(--color-text-accent); font-size: var(--bo-type-caption); font-weight: var(--font-weight-semibold); }
.pr-columns-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--spacing-4); }
.pr-report-subsection { display: grid; gap: var(--spacing-2); align-content: start; }
.pr-report-subsection h3 { margin: 0; font-size: var(--bo-type-body); }
.pr-report-subsection ul { display: grid; gap: var(--spacing-1); margin: 0; padding-left: var(--spacing-4); color: var(--color-text-secondary); font-size: var(--bo-type-caption); line-height: var(--bo-type-caption-leading); }
.pr-report-subsection.is-risk { padding: var(--spacing-3); border: 1px solid var(--color-warning); border-radius: var(--radius-inner); background: var(--color-warning-muted); }
.pr-report-subsection.is-risk ul { color: var(--color-text-primary); }
.pr-evidence-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-5); }
.pr-evidence-list { display: grid; gap: var(--spacing-1); margin: 0; padding: 0; list-style: none; }
.pr-evidence-list li { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-2); padding: var(--spacing-2) 0; border-bottom: 1px solid var(--color-border); color: var(--color-text-secondary); font-size: var(--bo-type-caption); }
.pr-evidence-list li:last-child { border-bottom: 0; }
.pr-disabled-note { color: var(--color-text-secondary); font-size: var(--bo-type-caption); line-height: var(--bo-type-caption-leading); }
.pr-history { display: grid; gap: var(--spacing-2); }
.pr-history-item { display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: var(--spacing-3); align-items: baseline; padding: var(--spacing-2) 0; border-bottom: 1px solid var(--color-border); font-size: var(--bo-type-caption); }
.pr-history-item time { color: var(--color-text-secondary); }
.pr-report-actions { display: flex; flex-wrap: wrap; gap: var(--spacing-2); }
.pr-report-actions .astryx-button:disabled { opacity: .55; }
.pr-dialog { width: 480px; max-width: calc(100vw - var(--spacing-8)); padding: 0; border: 1px solid var(--color-border-emphasized); border-radius: var(--radius-container); background: var(--color-background-surface); color: var(--color-text-primary); box-shadow: var(--shadow-high); }
.pr-dialog::backdrop { background: var(--color-overlay); }
.pr-dialog-inner { display: grid; gap: var(--spacing-4); padding: var(--spacing-5); }
.pr-dialog-head { display: grid; gap: var(--spacing-1); }
.pr-dialog-head h2 { margin: 0; font-size: var(--bo-type-section-title); }
.pr-dialog-head p { margin: 0; color: var(--color-text-secondary); font-size: var(--bo-type-caption); line-height: var(--bo-type-caption-leading); }
.pr-dialog-form { display: grid; gap: var(--spacing-3); }
.pr-dialog-field { display: grid; gap: var(--spacing-1); }
.pr-dialog-field label { color: var(--color-text-secondary); font-size: var(--bo-type-caption); font-weight: var(--font-weight-semibold); }
.pr-dialog-field input, .pr-dialog-field textarea { width: 100%; padding: var(--spacing-2); border: 1px solid var(--color-border); border-radius: var(--radius-inner); background: var(--color-background-surface); color: var(--color-text-primary); }
.pr-dialog-field textarea { min-height: 86px; resize: vertical; }
.pr-dialog-message { min-height: 20px; margin: 0; color: var(--color-warning); font-size: var(--bo-type-caption); line-height: var(--bo-type-caption-leading); }
.pr-dialog-actions { display: flex; justify-content: end; gap: var(--spacing-2); }
.pr-dialog-confirmation { padding: var(--spacing-2); border-radius: var(--radius-inner); background: var(--color-success-muted); color: var(--color-text-primary); font-size: var(--bo-type-caption); font-weight: var(--font-weight-semibold); }
.is-hidden { display: none !important; }
:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
@media (min-width: 1600px) {
  .pr-list-layout { grid-template-columns: minmax(0, 1fr) 460px; }
}
"""

BODY = r"""
<div class="pr-app" data-astryx-theme="bidops" data-theme="light">
  <div class="pr-shell">
    <aside class="pr-sidebar" aria-label="BidOps 주 메뉴">
      <div class="pr-brand">
        <span class="pr-brand-mark" aria-hidden="true">B</span>
        <span class="pr-brand-copy"><span class="pr-brand-name">BidOps</span><span class="pr-brand-sub">ROOTLAB · 사업기회</span></span>
      </div>
      <nav class="pr-nav">
        <div class="pr-nav-group">
          <span class="pr-nav-label">오늘의 업무</span>
          <span class="pr-nav-item"><span class="pr-nav-dot" aria-hidden="true"></span>대시보드</span>
          <span class="pr-nav-item"><span class="pr-nav-dot" aria-hidden="true"></span>공고 판정 이력</span>
        </div>
        <div class="pr-nav-group">
          <span class="pr-nav-label">탐색과 추적</span>
          <span class="pr-nav-item"><span class="pr-nav-dot" aria-hidden="true"></span>발주계획 C-2</span>
          <span class="pr-nav-item is-active" aria-current="page"><span class="pr-nav-dot" aria-hidden="true"></span>사전규격</span>
          <span class="pr-nav-item"><span class="pr-nav-dot" aria-hidden="true"></span>사업 추적</span>
          <span class="pr-nav-item"><span class="pr-nav-dot" aria-hidden="true"></span>최종 Go/No-Go</span>
        </div>
        <div class="pr-nav-group">
          <span class="pr-nav-label">기준과 운영</span>
          <span class="pr-nav-item"><span class="pr-nav-dot" aria-hidden="true"></span>판정 기준</span>
          <span class="pr-nav-item"><span class="pr-nav-dot" aria-hidden="true"></span>실행 상태</span>
        </div>
      </nav>
      <div class="pr-sidebar-foot">기획부 · 사업기획<br>관리자 화면 · 데스크톱 전용</div>
    </aside>

    <main class="pr-main">
      <header class="pr-topbar">
        <div class="pr-topbar-main">
          <div class="pr-breadcrumb">탐색과 추적 <span aria-hidden="true">/</span> 사전규격</div>
          <h1 class="pr-page-title">사전규격 검토</h1>
        </div>
        <span class="pr-sample-indicator" data-testid="proposal-indicator">디자인 시안 · 가상 예시 · 실제 저장/실행 없음</span>
      </header>

      <section id="list-view" class="pr-view pr-list-view" aria-labelledby="list-title">
        <div class="pr-list-heading">
          <div class="pr-heading-block">
            <h2 id="list-title">사전규격 목록</h2>
            <span class="pr-heading-support">수집된 합성 예시를 검토하고 필요한 사업만 추적합니다.</span>
          </div>
        </div>
        <div class="pr-toolbar" aria-label="사전규격 검색과 필터">
          <div class="pr-field pr-search-field">
            <label for="search-input">검색</label>
            <div class="__TEXT_INPUT__" data-size="sm"><input id="search-input" type="search" placeholder="공고명·기관·번호 검색" autocomplete="off" /></div>
          </div>
          <div class="pr-field pr-filter-field">
            <label for="status-filter">추적 상태</label>
            <select id="status-filter" class="__SELECTOR__" data-size="sm">
              <option value="all">전체 상태</option>
              <option value="미선택">미선택</option>
              <option value="계속 추적">계속 추적</option>
              <option value="보류">보류</option>
            </select>
          </div>
          <div class="pr-bulk-actions">
            <button id="select-page" type="button" class="__BUTTON_SECONDARY__" data-testid="select-visible-page">전체 선택</button>
            <button id="clear-selection" type="button" class="__BUTTON_SECONDARY__" data-testid="clear-selection">전체 해제</button>
          </div>
        </div>

        <div class="pr-list-layout">
          <section class="pr-list-column" aria-label="사전규격 행 목록">
            <div class="pr-list-meta">
              <span id="result-count" class="pr-result-count" data-testid="visible-count"></span>
              <span id="selection-count" class="pr-list-note" data-testid="selected-count"></span>
            </div>
            <div id="rows" class="pr-rows" role="list" aria-label="사전규격 목록"></div>
            <footer class="pr-list-footer">
              <span class="pr-list-note">페이지 선택은 현재 보이는 페이지에만 적용됩니다.</span>
              <div class="pr-page-controls" data-testid="page-controls">
                <button id="page-prev" type="button" class="__BUTTON_SECONDARY__" aria-label="이전 페이지" data-testid="page-prev">‹</button>
                <span id="page-indicator" class="pr-page-indicator" data-testid="page-indicator"></span>
                <button id="page-next" type="button" class="__BUTTON_SECONDARY__" aria-label="다음 페이지" data-testid="page-next">›</button>
              </div>
            </footer>
          </section>
          <aside id="right-panel" class="pr-panel" data-testid="right-panel" aria-label="선택한 사전규격 요약"></aside>
        </div>
      </section>

      <section id="detail-view" class="pr-view pr-detail-view is-hidden" aria-labelledby="detail-title" aria-hidden="true">
        <div id="detail-content" class="pr-detail-wrap" data-testid="detail-screen"></div>
      </section>
    </main>
  </div>
</div>

<dialog id="tracking-dialog" class="pr-dialog" data-testid="tracking-dialog" aria-labelledby="tracking-dialog-title">
  <div class="pr-dialog-inner">
    <div class="pr-dialog-head">
      <h2 id="tracking-dialog-title">추적 시작 · 시안 입력</h2>
      <p>실제 저장·실행 없이, 담당자와 사유를 입력하는 흐름만 확인합니다.</p>
    </div>
    <form id="tracking-form" class="pr-dialog-form">
      <div class="pr-dialog-field">
        <label for="actor-input">담당자 이름</label>
        <input id="actor-input" name="actor" type="text" autocomplete="off" required />
      </div>
      <div class="pr-dialog-field">
        <label for="reason-input">추적 사유</label>
        <textarea id="reason-input" name="reason" required></textarea>
      </div>
      <p id="dialog-message" class="pr-dialog-message" role="status" aria-live="polite"></p>
      <p id="tracking-confirmation" class="pr-dialog-confirmation is-hidden" data-testid="tracking-confirmation"></p>
      <div class="pr-dialog-actions">
        <button id="tracking-cancel" type="button" class="__BUTTON_SECONDARY__">취소</button>
        <button id="tracking-submit" type="submit" class="__BUTTON_PRIMARY__">시안에서만 반영</button>
      </div>
    </form>
  </div>
</dialog>
"""

SCRIPT = r"""
(() => {
  "use strict";
  const DATA = __DATA__;
  const CLS = __CLS__;
  const pageSize = 5;
  let currentPage = 0;
  let activeId = DATA[0].id;
  const selectedIds = new Set();
  let detailId = null;
  let detailSnapshot = [];
  let trackingTargetId = null;
  let dialogDirty = false;
  let dialogWarningAcknowledged = false;

  const $ = (id) => document.getElementById(id);
  const listView = $("list-view");
  const detailView = $("detail-view");
  const rowsNode = $("rows");
  const rightPanel = $("right-panel");
  const searchInput = $("search-input");
  const statusFilter = $("status-filter");
  const dialog = $("tracking-dialog");
  const trackingForm = $("tracking-form");
  const actorInput = $("actor-input");
  const reasonInput = $("reason-input");
  const dialogMessage = $("dialog-message");
  const trackingConfirmation = $("tracking-confirmation");
  const cancelButton = $("tracking-cancel");
  const submitButton = $("tracking-submit");

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[character]));
  }
  function display(value) { return value === null || value === undefined || value === "" ? "미확인" : escapeHtml(value); }
  function gradeClass(value) {
    return value === "우선 검토" ? "is-g1" : value === "검토 권장" ? "is-g2" : "is-g3";
  }
  function filteredRows() {
    const query = searchInput.value.trim().toLowerCase();
    const tracking = statusFilter.value;
    return DATA.filter((item) => {
      const haystack = [item.title, item.agency, item.number, item.category].join(" ").toLowerCase();
      return (!query || haystack.includes(query)) && (tracking === "all" || item.tracking === tracking);
    });
  }
  function pageRows() {
    const rows = filteredRows();
    const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
    if (currentPage >= pageCount) currentPage = pageCount - 1;
    return rows.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  }
  function taskMarkup(tasks, className = "pr-task-list") {
    return `<ol class="${className}">${tasks.map((task, index) => `<li data-index="${index + 1}">${escapeHtml(task)}</li>`).join("")}</ol>`;
  }
  function gradeMarkup(item) { return `<span class="pr-grade ${gradeClass(item.grade)}">${escapeHtml(item.grade)}</span>`; }
  function statusMarkup(item) {
    const dotClass = item.tracking === "계속 추적" ? "pr-status-dot is-success" : "pr-status-dot";
    return `<span class="pr-row-status"><span class="${dotClass}" aria-hidden="true"></span>${escapeHtml(item.tracking)}</span>`;
  }
  function renderList() {
    const focused = document.activeElement;
    const focusedId = focused?.dataset?.id || focused?.closest?.("[data-id]")?.dataset?.id;
    const focusedCheckbox = focused?.classList?.contains("row-checkbox");
    const rows = pageRows();
    const matches = filteredRows();
    const pageCount = Math.max(1, Math.ceil(matches.length / pageSize));
    $("result-count").innerHTML = `<strong>${matches.length}건</strong> 표시 · 전체 ${DATA.length}건`;
    $("selection-count").textContent = `선택 ${selectedIds.size}건`;
    $("page-indicator").textContent = `${currentPage + 1} / ${pageCount} 페이지`;
    $("page-prev").disabled = currentPage === 0;
    $("page-next").disabled = currentPage >= pageCount - 1;
    if (!rows.length) {
      rowsNode.innerHTML = `<div class="pr-empty" role="status">검색 조건에 맞는 사전규격이 없습니다.</div>`;
    } else {
      rowsNode.innerHTML = rows.map((item) => {
        const checked = selectedIds.has(item.id) ? " checked" : "";
        const active = activeId === item.id ? " is-active" : "";
        return `<article class="pr-row${active}" role="listitem" tabindex="0" data-id="${escapeHtml(item.id)}" data-testid="notice-row-${escapeHtml(item.id)}" aria-label="${escapeHtml(item.title)}">
          <label class="pr-row-check" aria-label="${escapeHtml(item.title)} 선택"><input class="row-checkbox" type="checkbox" data-id="${escapeHtml(item.id)}"${checked} /></label>
          <div class="pr-row-main"><span class="pr-row-title">${escapeHtml(item.title)}</span><span class="pr-row-agency">${escapeHtml(item.agency)}</span><span class="pr-row-meta"><span>${display(item.budget)}</span><span>${display(item.schedule)}</span><span>${escapeHtml(item.category)}</span></span></div>
          <div class="pr-row-aside">${gradeMarkup(item)}${statusMarkup(item)}<button type="button" class="pr-row-open" data-open-detail="${escapeHtml(item.id)}">상세 보기</button></div>
        </article>`;
      }).join("");
      rowsNode.querySelectorAll(".pr-row").forEach((row) => {
        const id = row.dataset.id;
        row.addEventListener("click", () => { activeId = id; renderList(); renderRightPanel(); });
        row.addEventListener("keydown", (event) => {
          if (event.target !== row) return;
          if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          if (event.repeat) return;
          activeId = id;
          if (event.key === " ") {
            if (selectedIds.has(id)) selectedIds.delete(id); else selectedIds.add(id);
          }
          renderList();
          renderRightPanel();
        });
      });
      rowsNode.querySelectorAll(".row-checkbox").forEach((checkbox) => {
        checkbox.addEventListener("click", (event) => event.stopPropagation());
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) selectedIds.add(checkbox.dataset.id); else selectedIds.delete(checkbox.dataset.id);
          renderList();
        });
      });
      rowsNode.querySelectorAll("[data-open-detail]").forEach((button) => {
        button.addEventListener("click", (event) => { event.stopPropagation(); openDetail(button.dataset.openDetail); });
      });
    }
    if (focusedId) {
      const candidates = rowsNode.querySelectorAll(focusedCheckbox ? ".row-checkbox" : ".pr-row");
      Array.from(candidates).find((candidate) => candidate.dataset.id === focusedId)?.focus();
    }
  }
  function renderRightPanel() {
    const item = DATA.find((candidate) => candidate.id === activeId);
    if (!item) {
      rightPanel.innerHTML = `<div class="pr-empty" role="status">선택한 사전규격이 없습니다.</div>`;
      return;
    }
    const canTrack = item.tracking === "미선택";
    const trackingControl = canTrack
      ? `<button type="button" class="${CLS.buttonPrimary}" data-testid="panel-track-button" id="panel-track-button">추적 시작</button>`
      : `<span class="pr-disabled-note">추적 상태 · ${escapeHtml(item.tracking)}</span>`;
    rightPanel.innerHTML = `<div class="pr-panel-head"><span class="pr-panel-kicker">선택한 사전규격</span><h2 class="pr-panel-title" data-testid="selected-title">${escapeHtml(item.title)}</h2><span class="pr-panel-agency" data-testid="selected-agency">${escapeHtml(item.agency)} · ${escapeHtml(item.number)}</span></div>
      <div class="pr-panel-body"><section class="pr-panel-section"><h3>사업 설명</h3><p class="pr-panel-summary">${escapeHtml(item.summary)}</p></section><section class="pr-panel-section"><h3>주요 과업</h3>${taskMarkup(item.tasks)}</section><dl class="pr-facts"><div class="pr-fact"><dt>예산</dt><dd data-testid="selected-budget">${display(item.budget)}</dd></div><div class="pr-fact"><dt>일정</dt><dd data-testid="selected-schedule">${display(item.schedule)}</dd></div></dl><section class="pr-caution" data-testid="panel-caution"><div class="pr-caution-head"><span class="pr-status-dot" aria-hidden="true"></span>주의 필요 · 확인 전</div><p>${escapeHtml(item.caution)}</p></section></div>
      <div class="pr-panel-foot">${trackingControl}<button type="button" class="${CLS.buttonSecondary}" data-testid="panel-detail-button" id="panel-detail-button">상세 보기</button></div>`;
    if (canTrack) $("panel-track-button").addEventListener("click", openTrackingDialog);
    $("panel-detail-button").addEventListener("click", () => openDetail(item.id));
  }
  function summaryFacts(item) {
    return `<dl class="pr-facts pr-detail-facts"><div class="pr-fact"><dt>사업 예산</dt><dd>${display(item.budget)}</dd></div><div class="pr-fact"><dt>사업 일정</dt><dd>${display(item.schedule)}</dd></div><div class="pr-fact"><dt>의견등록 마감</dt><dd>${display(item.deadline)}</dd></div><div class="pr-fact"><dt>구분</dt><dd>${escapeHtml(item.category)}</dd></div></dl>`;
  }
  function reportList(items, numbered = false) {
    return `<ul class="${numbered ? "pr-report-list" : "pr-report-list"}">${items.map((value, index) => `<li>${numbered ? `<span class="pr-report-index">${index + 1}</span>` : "<span class=\"pr-report-index\">·</span>"}<span>${escapeHtml(value)}</span></li>`).join("")}</ul>`;
  }
  function renderDetail(item) {
    const ordered = detailSnapshot.length
      ? detailSnapshot.map((id) => DATA.find((candidate) => candidate.id === id)).filter(Boolean)
      : [item];
    const index = Math.max(0, ordered.findIndex((candidate) => candidate.id === item.id));
    const previous = ordered[index - 1];
    const next = ordered[index + 1];
    const canNavigate = detailSnapshot.length > 1;
    const trackingControl = item.tracking === "미선택"
      ? `<button type="button" class="${CLS.buttonPrimary}" data-testid="detail-track-button" id="detail-track-button">추적 시작</button>`
      : `<span class="pr-disabled-note">추적 상태 · ${escapeHtml(item.tracking)}</span>`;
    $("detail-content").innerHTML = `<div class="pr-detail-top"><div class="pr-detail-top-main"><span class="pr-detail-breadcrumb">탐색과 추적 / 사전규격 / 보고서</span><div class="pr-identity">${gradeMarkup(item)}<span>${escapeHtml(item.category)}</span><span>추적 상태 · ${escapeHtml(item.tracking)}</span><span data-testid="detail-position">선택 항목 ${index + 1} / ${ordered.length}</span></div><h1 id="detail-title" class="pr-detail-title">${escapeHtml(item.title)}</h1><span class="pr-detail-agency">${escapeHtml(item.agency)} · ${escapeHtml(item.number)}</span></div><div class="pr-detail-actions"><div class="pr-detail-nav"><button type="button" class="${CLS.buttonSecondary}" data-testid="detail-prev" id="detail-prev" ${canNavigate && previous ? "" : "disabled"}>이전</button><button type="button" class="${CLS.buttonSecondary}" data-testid="detail-next" id="detail-next" ${canNavigate && next ? "" : "disabled"}>다음</button></div><button type="button" class="${CLS.buttonSecondary}" data-testid="detail-back" id="detail-back">목록으로 돌아가기</button></div></div>
      <section class="pr-detail-section" aria-labelledby="summary-heading"><div class="pr-section-heading"><h2 id="summary-heading">사업 설명</h2><p>합성 예시 · 원문 확인 전</p></div><div class="pr-summary-grid"><div class="pr-summary-copy"><p>${escapeHtml(item.summary)}</p><p class="pr-disabled-note">이 문장은 시안용 사업 요약입니다. 공고 사실이나 회사 역량을 확인한 결과가 아닙니다.</p></div>${summaryFacts(item)}</div><div class="pr-caution" data-testid="detail-caution"><div class="pr-caution-head"><span class="pr-status-dot" aria-hidden="true"></span>주의 필요 · 확인 전</div><p>${escapeHtml(item.caution)}</p></div></section>
      <div class="pr-tracking-bar"><div class="pr-tracking-copy"><strong>추적 결정 · ${escapeHtml(item.tracking)}</strong><span>추적은 후속 공고와 일정 확인을 이어가는 결정이며, 최종 입찰 Go/No-Go와 다릅니다.</span></div>${trackingControl}</div>
      <section class="pr-detail-section" aria-labelledby="tasks-heading"><div class="pr-section-heading"><h2 id="tasks-heading">주요 과업과 범위</h2><p>핵심 확인 단위 3건</p></div>${reportList(item.tasks, true)}</section>
      <section class="pr-detail-section" aria-labelledby="conditions-heading"><div class="pr-section-heading"><h2 id="conditions-heading">참여 조건 · 회사 부합 · 위험</h2><p>확인 전 상태를 분리해 표시</p></div><div class="pr-columns-3"><section class="pr-report-subsection"><h3>참여 조건</h3><ul>${item.participation.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section><section class="pr-report-subsection"><h3>회사 업무 부합 여부</h3><ul><li>판정 보류 · 정보 부족</li>${item.fit.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul><span class="pr-disabled-note">확인된 회사 자격·실적 없음 · 내부 자료 대조 필요</span></section><section class="pr-report-subsection is-risk"><h3>위험 · 미확인</h3><ul>${item.risks.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section></div></section>
      <section class="pr-detail-section" aria-labelledby="evidence-heading"><div class="pr-section-heading"><h2 id="evidence-heading">근거 · 첨부 문서</h2><p>다운로드·실행 없음</p></div><div class="pr-evidence-grid"><section class="pr-report-subsection"><h3>원문 근거</h3><ul class="pr-evidence-list">${item.evidence.map((value) => `<li><span>${escapeHtml(value)}</span><button type="button" class="${CLS.buttonSecondary}" disabled aria-disabled="true">페이지 보기</button></li>`).join("")}</ul></section><section class="pr-report-subsection"><h3>첨부 목록</h3><ul class="pr-evidence-list">${item.attachments.map((value) => `<li><span>${escapeHtml(value)}</span><button type="button" class="${CLS.buttonSecondary}" disabled aria-disabled="true">다운로드</button></li>`).join("")}</ul><span class="pr-disabled-note">첨부 파일은 시안에 포함되지 않았습니다. 실제 저장소나 원문을 호출하지 않습니다.</span></section></div></section>
      <section class="pr-detail-section" aria-labelledby="history-heading"><div class="pr-section-heading"><h2 id="history-heading">처리 이력 · 문서 준비 · 검토 실행</h2><p>운영 정보는 보존하되 시안에서는 비활성</p></div><div class="pr-history">${item.history.map((entry) => { const pieces = entry.split(" · "); return `<div class="pr-history-item"><time>${escapeHtml(pieces.shift())}</time><span>${escapeHtml(pieces.join(" · "))}</span></div>`; }).join("")}</div><div class="pr-report-actions"><button type="button" class="${CLS.buttonSecondary}" disabled aria-disabled="true">문서 준비 열기</button><button type="button" class="${CLS.buttonSecondary}" disabled aria-disabled="true">개요 검토 실행</button><button type="button" class="${CLS.buttonSecondary}" disabled aria-disabled="true">검토 결과 저장</button></div><span class="pr-disabled-note">문서 준비·심층 검토·저장은 실제 동작하지 않습니다. 추적 결정, 적합성 등급, 최종 Go/No-Go는 서로 다른 업무 결정입니다.</span></section>`;
    $("detail-back").addEventListener("click", closeDetail);
    if (item.tracking === "미선택") $("detail-track-button").addEventListener("click", openTrackingDialog);
    if (previous) $("detail-prev").addEventListener("click", () => openDetail(previous.id));
    if (next) $("detail-next").addEventListener("click", () => openDetail(next.id));
  }
  function openDetail(id) {
    const item = DATA.find((candidate) => candidate.id === id);
    if (!item) return;
    if (detailId === null) {
      detailSnapshot = selectedIds.has(id) ? Array.from(selectedIds) : [];
    }
    activeId = id;
    detailId = id;
    renderDetail(item);
    listView.classList.add("is-hidden");
    listView.setAttribute("aria-hidden", "true");
    detailView.classList.remove("is-hidden");
    detailView.setAttribute("aria-hidden", "false");
    detailView.scrollTop = 0;
    detailView.focus({ preventScroll: true });
  }
  function closeDetail() {
    detailId = null;
    detailSnapshot = [];
    detailView.classList.add("is-hidden");
    detailView.setAttribute("aria-hidden", "true");
    listView.classList.remove("is-hidden");
    listView.setAttribute("aria-hidden", "false");
    renderList();
    renderRightPanel();
  }
  function openTrackingDialog() {
    trackingTargetId = detailId || activeId;
    const target = DATA.find((item) => item.id === trackingTargetId);
    if (!target || target.tracking !== "미선택") return;
    actorInput.value = "";
    reasonInput.value = "";
    dialogDirty = false;
    dialogWarningAcknowledged = false;
    dialogMessage.textContent = "";
    trackingConfirmation.textContent = "";
    trackingConfirmation.classList.add("is-hidden");
    cancelButton.textContent = "취소";
    submitButton.disabled = false;
    dialog.showModal();
    actorInput.focus();
  }
  function requestDialogClose() {
    if (dialogDirty && !dialogWarningAcknowledged) {
      dialogWarningAcknowledged = true;
      dialogMessage.textContent = "입력 내용이 저장되지 않았습니다. 다시 취소하면 입력을 버리고 닫습니다.";
      cancelButton.textContent = "변경 취소";
      return;
    }
    dialog.close();
  }
  function resetListContext() {
    currentPage = 0;
    selectedIds.clear();
    const matches = filteredRows();
    activeId = matches[0]?.id || null;
    renderList();
    renderRightPanel();
  }
  searchInput.addEventListener("input", resetListContext);
  statusFilter.addEventListener("change", resetListContext);
  $("select-page").addEventListener("click", () => { pageRows().forEach((item) => selectedIds.add(item.id)); renderList(); });
  $("clear-selection").addEventListener("click", () => { selectedIds.clear(); renderList(); });
  $("page-prev").addEventListener("click", () => { if (currentPage > 0) { currentPage -= 1; renderList(); } });
  $("page-next").addEventListener("click", () => { const pageCount = Math.max(1, Math.ceil(filteredRows().length / pageSize)); if (currentPage < pageCount - 1) { currentPage += 1; renderList(); } });
  actorInput.addEventListener("input", () => { dialogDirty = true; dialogWarningAcknowledged = false; });
  reasonInput.addEventListener("input", () => { dialogDirty = true; dialogWarningAcknowledged = false; });
  cancelButton.addEventListener("click", requestDialogClose);
  dialog.addEventListener("cancel", (event) => { if (dialogDirty && !dialogWarningAcknowledged) { event.preventDefault(); dialogWarningAcknowledged = true; dialogMessage.textContent = "입력 내용이 저장되지 않았습니다. Escape를 다시 누르면 입력을 버리고 닫습니다."; cancelButton.textContent = "변경 취소"; } });
  trackingForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const actor = actorInput.value.trim();
    const reason = reasonInput.value.trim();
    if (!actor || !reason) { dialogMessage.textContent = "담당자 이름과 추적 사유를 입력해 주세요."; return; }
    const target = DATA.find((item) => item.id === trackingTargetId);
    if (!target || target.tracking !== "미선택") return;
    target.tracking = "계속 추적";
    dialogDirty = false;
    dialogWarningAcknowledged = true;
    dialogMessage.textContent = "";
    trackingConfirmation.textContent = `시안에서만 반영 · ${actor} · 사유 ${reason}`;
    trackingConfirmation.classList.remove("is-hidden");
    activeId = target.id;
    renderList();
    renderRightPanel();
    if (detailId === target.id) renderDetail(target);
    submitButton.disabled = true;
    cancelButton.textContent = "닫기";
  });

  renderList();
  renderRightPanel();
})();
"""


def build() -> Path:
    css_paths = [
        FRONTEND_ROOT / "node_modules" / "@astryxdesign" / "core" / "src" / "reset.css",
        FRONTEND_ROOT / "node_modules" / "@astryxdesign" / "core" / "dist" / "astryx.css",
        FRONTEND_ROOT / "src" / "themes" / "bidops" / "bidops.css",
        FRONTEND_ROOT / "src" / "styles" / "typography.css",
    ]
    missing = [str(path) for path in css_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Astryx/BidOps CSS not found: " + ", ".join(missing))
    astryx_css = "\n".join(_read(path) for path in css_paths)
    body = BODY
    replacements = {
        "__TEXT_INPUT__": CLS["textInput"],
        "__SELECTOR__": CLS["selector"],
        "__BUTTON_SECONDARY__": CLS["buttonSecondary"],
        "__BUTTON_PRIMARY__": CLS["buttonPrimary"],
    }
    for marker, value in replacements.items():
        body = body.replace(marker, html.escape(value, quote=True))
    script = SCRIPT.replace("__DATA__", json.dumps(DATA, ensure_ascii=False, separators=(",", ":")))
    script = script.replace("__CLS__", json.dumps(CLS, ensure_ascii=False, separators=(",", ":")))
    document = """<!doctype html>
<html lang="ko" data-theme="light" data-astryx-theme="bidops">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=1280">
  <title>BidOps · 사전규격 검토 시안</title>
  <style>
%s
%s
  </style>
</head>
<body>
%s
<script>
%s
</script>
</body>
</html>
""" % (astryx_css, CUSTOM_CSS, body, script)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(document, encoding="utf-8")
    return OUTPUT


if __name__ == "__main__":
    print(build().resolve())
