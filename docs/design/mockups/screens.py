#!/usr/bin/env python3
"""8개 화면 아트보드를 생성한다. `python3 screens.py`"""
from build import (
    artboard, badge, button, cls, divider, grade_tag, heading, link, screen,
    segmented, selector, stack, status_dot, table, text, text_input, topbar,
)

W, H = 1440, 940
NARROW = 1180


def row(title, badges, meta, selected=False, deadline=None, tone=None):
    sel = " is-selected" if selected else ""
    if tone:
        sel += f" is-{tone}"
    dl = f'<span class="bo-row-deadline">{deadline}</span>' if deadline else ""
    return (
        f'<span class="bo-row{sel}">'
        f'<span class="bo-row-line">{text(title, "body", "primary")}{dl}</span>'
        f'<span class="bo-row-badges">{"".join(badges)}</span>'
        f'{text(meta, "supporting", "secondary")}</span>'
    )


def fact(label, value):
    return (
        '<li style="display:flex;gap:10px;padding:7px 0;border-bottom:1px solid var(--color-border)">'
        f'<span style="flex:0 0 132px">{text(label, "supporting", "secondary")}</span>'
        f'<span style="flex:1;min-width:0">{value}</span></li>'
    )


# ─────────────────────────────────────────── 1단계 · 발주계획 C-2 검토
def main_screen():
    filters = (
        '<section class="bo-filters">'
        f'<span class="bo-filter-field">{text("저장된 뷰", "label", "secondary")}'
        f'{segmented(["검토 대상", "전체", "BM25 탈락", "실패·거부"], 0)}</span>'
        f'<span class="bo-filter-field">{text("Qwen relevance", "label", "secondary")}{selector("relevant · uncertain")}</span>'
        f'<span class="bo-filter-field">{text("BM25 stage1", "label", "secondary")}{selector("선정")}</span>'
        f'<span class="bo-filter-field">{text("사람 피드백", "label", "secondary")}{selector("전체")}</span>'
        f'{text_input("제목·계획번호 검색")}'
        f"{button('필터 초기화')}"
        "</section>"
    )

    rows = "".join([
        row("인공지능 기반 공공데이터 통합·분석 플랫폼 구축 및 운영 지원 사업",
            [badge("BM25 선정 · 1", "success"), badge("relevant", "info"), badge("피드백 rev 2", "neutral")],
            "서울특별시 디지털정책관 · 1.25억 · 2026년 11월", selected=True),
        row("지방공기업 업무혁신 및 데이터 연계 체계 고도화",
            [badge("BM25 선정 · 3", "success"), badge("uncertain", "info")],
            "경기도청 · 1.83억 · 2027년 03월"),
        row("차세대 지방재정관리시스템 유지관리 용역",
            [badge("filtered_out", "neutral"), badge("null · 미적용", "neutral")],
            "행정안전부 · null (미제공) · 2026년 12월"),
        row("스마트도시 통합플랫폼 연계 표준 적용 사업",
            [badge("BM25 선정 · 7", "success"), badge("not_relevant", "neutral")],
            "부산광역시 · 0.94억 · 2027년 01월"),
        row("공공 마이데이터 유통 기반 구축 2단계",
            [badge("failed · timeout", "error"), badge("null · 결과 없음", "neutral")],
            "한국지능정보사회진흥원 · 2.10억 · 2026년 10월"),
        row("지역 데이터 허브 고도화 및 운영",
            [badge("rejected · binding", "error"), badge("null · 미시도", "neutral")],
            "충청남도청 · null (미제공) · 2027년 02월"),
    ])

    list_pane = (
        '<aside class="bo-list-pane">'
        '<header class="bo-list-head">'
        f'{stack([text("검토 목록", "label", "primary"), text("현재 필터 결과 42건 · 1 / 9 페이지", "supporting", "secondary")], gap=1)}'
        "</header>"
        '<div class="bo-list-scroll">'
        '<span class="bo-group">'
        f'<span class="bo-group-head"><span class="bo-group-swatch"></span>{text("사람 피드백 없음 · 38", "label", "secondary")}</span>'
        f"{rows}</span></div>"
        f'<div class="bo-pager">{button("이전")}{text("1 / 9", "supporting", "secondary")}{button("다음")}</div>'
        "</aside>"
    )

    tabs = segmented(["판정", "신호 세부", "운영 텔레메트리"], 0)

    # 판정에 필요한 사실만 둔다. source run·관측 시각·신호 수치는 다른 탭이 맡는다.
    facts = "".join([
        fact("발주계획 번호", text("OP-2026-00101", "body", "primary")),
        fact("기관", text("서울특별시 디지털정책관", "body", "primary")),
        fact("사업 분야", text("정보화 · IT · 구축·운영", "body", "primary")),
        fact("예산", text("125,000,000", "body", "primary")),
        fact("계획 시기", text("2026년 11월", "body", "primary")),
    ])

    feedback = (
        '<div class="bo-section">'
        f'<div class="bo-section-head">{text("사람 피드백", "label", "primary")}'
        f'{text("이 입력은 적합성 등급·참여 준비 상태·심층 추적 승인·최종 Go/No-Go를 채우거나 대신하지 않습니다.", "supporting", "secondary")}</div>'
        f'{stack([
            stack([text("relevance", "label", "secondary"), segmented(["relevant", "uncertain", "not_relevant"], 0)], gap=1),
            stack([text("priority", "label", "secondary"), segmented(["high", "normal", "null · 미지정"], 1)], gap=1),
            stack([text("memo", "label", "secondary"),
                   f'<div class="{cls("astryx-text-area")}" style="min-height:64px;padding:9px 11px">'
                   + text("공공데이터 플랫폼 구축·운영으로 회사 역량과 맞음", "body", "secondary") + "</div>"], gap=1),
        ], gap=3)}'
        "</div>"
    )

    # 결정 액션은 상세 pane 바닥에 고정한다. 스크롤 위치와 무관하게 첫 화면에서 보인다.
    actions = (
        '<div style="margin-top:auto;display:flex;align-items:center;gap:10px;'
        'padding:14px 20px;border-top:1px solid var(--color-border);'
        'background:var(--color-background-card)">'
        f'{button("저장", "primary")}{button("저장 후 다음 →")}'
        f'<span style="margin-left:auto">{text("1 / 42", "supporting", "secondary")}</span></div>'
    )

    detail = (
        '<section class="bo-detail-pane">'
        '<header class="bo-detail-head">'
        f'{stack([text("발주계획 OP-2026-00101 · 계획 ID 101", "supporting", "secondary"), heading("인공지능 기반 공공데이터 통합·분석 플랫폼 구축 및 운영 지원 사업", 4)], gap=1)}'
        f"{tabs}</header>"
        '<div class="bo-detail-scroll">'
        f'<div class="bo-section"><ul class="bo-facts">{facts}</ul></div>'
        f"{feedback}</div>{actions}</section>"
    )

    content = (
        '<main class="bo-canvas"><div class="bo-queue">'
        f'{filters}<div class="bo-workspace">{list_pane}{detail}</div>'
        "</div></main>"
    )

    tb = topbar(
        "발주계획 C-2 검토",
        f'{text("누적 데이터 · 회차 선택기 없음", "supporting", "secondary")}{button("실행 상세")}',
        f'<span class="bo-topbar-status">{status_dot("부분 성공", "warning")}&nbsp;부분 성공 · a2f4d7c1 · 09-01 11:05</span>',
    )
    return screen("발주계획 C-2", tb, content)


# ─────────────────────────────────────────── 2단계 · 사이드바 정보구조
def navigation_screen():
    def old_group(label, items):
        rows = "".join(
            f'<span class="bo-nav-item"><span class="bo-nav-dot"></span>{n}'
            + (f'<span class="bo-nav-pending">{p}</span>' if p else "")
            + "</span>"
            for n, p in items
        )
        return f'<div class="bo-nav-group"><span class="bo-nav-group-label">{label}</span>{rows}</div>'

    old = (
        '<aside class="bo-sidebar" style="flex:0 0 248px">'
        '<div class="bo-brand"><span class="bo-brand-mark">B</span>'
        '<span class="bo-brand-text"><strong>BidOps</strong><span>현재 · 16항목</span></span></div>'
        '<nav class="bo-nav">'
        + old_group("모니터링", [("대시보드", None), ("검토 대기열", None), ("마감 추적", "리다이렉트"), ("사업기회", None), ("발주계획 C-2", None), ("사전규격", None)])
        + old_group("판정", [("공고 판정 이력", None), ("담당자 리뷰 기록", "준비 중")])
        + old_group("기준", [("회사 프로필", None), ("판정 정책", None), ("품질 게이트", None), ("검증 지표", None)])
        + old_group("운영", [("수집 실행", None), ("첨부 확보", None), ("상시 운영", None), ("산출물 감사 로그", "리다이렉트")])
        + "</nav></aside>"
    )

    new = (
        '<aside class="bo-sidebar" style="flex:0 0 248px">'
        '<div class="bo-brand"><span class="bo-brand-mark">B</span>'
        '<span class="bo-brand-text"><strong>BidOps</strong><span>이후 · 8항목</span></span></div>'
        '<nav class="bo-nav">'
        + old_group("회차 검토", [("대시보드", None), ("검토 대기열", None)])
        + old_group("누적 추적", [("발주계획 C-2", None), ("사전규격", None), ("사업기회", None), ("최종 Go/No-Go", None)])
        + old_group("기준과 운영", [("판정 기준", None), ("실행 상태", None)])
        + "</nav></aside>"
    )

    absorb = [
        ("마감 추적", "검토 대기열의 저장된 뷰"),
        ("공고 판정 이력 · 담당자 리뷰 기록", "검토 대기열의 탭"),
        ("회사 프로필 · 판정 정책 · 품질 게이트 · 검증 지표", "판정 기준의 탭 4개"),
        ("수집 실행 · 첨부 확보 · 상시 운영 · 산출물 감사 로그", "실행 상태 한 화면"),
        ("입찰 변경 비교 (메뉴 없음)", "최종 Go/No-Go 최상위 항목"),
        ("심층 검토 보고서 (메뉴 없음)", "사업기회 화면의 명시적 진입점"),
    ]
    absorb_rows = [[text(a, "body", "secondary"), text(b, "body", "primary")] for a, b in absorb]

    body = (
        '<div class="xjp7ctv x1tgivj0 x9ynric x19aimcq" data-astryx-theme="neutral" data-theme="light">'
        '<section class="bo-shell" style="min-height:0">'
        '<div class="bo-content" style="padding:20px">'
        + stack([
            heading("사이드바 정보구조 — 16항목에서 8항목으로", 3),
            text("1차 분류를 회차 검토와 누적 추적으로 나눕니다. 회차 선택기 표시 여부가 1차 분류만 보고 예측됩니다.", "body", "secondary"),
            f'<div style="display:flex;gap:20px;align-items:flex-start">{old}{new}'
            '<div class="bo-panel" style="flex:1">'
            f'<div class="bo-panel-head">{text("흡수 관계", "label", "primary")}'
            f'{badge("기존 경로 23개 모두 유지", "success")}</div>'
            f'<div class="bo-panel-body">{table([("현재", None), ("이후", None)], absorb_rows, min_width=460)}'
            f'<div style="padding-top:10px">{text("리다이렉트 항목과 미구현 안내 항목을 두지 않습니다. 기존 링크는 새 뷰로 연결되고 404를 내지 않습니다.", "supporting", "secondary")}</div>'
            "</div></div></div>",
        ], gap=3)
        + "</div></section></div>"
    )
    return body


# ─────────────────────────────────────────── 2단계 · 최종 Go/No-Go
def gonogo_screen():
    rows = "".join([
        row("차세대 통합 데이터 분석 플랫폼 구축",
            [grade_tag("우선 검토"), badge("부분 확인 필요", "warning"), badge("delta 6건", "neutral")],
            "서울특별시 · OPP-2026-0043", selected=True, deadline="D-2"),
        row("지방재정 데이터 표준화 용역",
            [grade_tag("검토 권장"), badge("확인 완료", "success"), badge("delta 2건", "neutral")],
            "행정안전부 · OPP-2026-0051", deadline="D-5"),
        row("공공 마이데이터 유통 기반 2단계",
            [grade_tag("관찰 대상"), badge("unknown · 확인 대기", "warning"), badge("delta null", "neutral")],
            "한국지능정보사회진흥원 · OPP-2026-0057", deadline="D-8"),
        row("스마트도시 통합플랫폼 연계 표준",
            [grade_tag("제외"), badge("참여 불가 확인", "error"), badge("delta 1건", "neutral")],
            "부산광역시 · OPP-2026-0060", deadline="D-13"),
    ])

    list_pane = (
        '<aside class="bo-list-pane">'
        f'<header class="bo-list-head">{stack([text("결정 대기 사업기회", "label", "primary"), text("4건 · 과거 기록을 덮어쓰지 않는 결정", "supporting", "secondary")], gap=1)}</header>'
        f'<div class="bo-list-scroll">{rows}</div></aside>'
    )

    delta_rows = [
        [text("추정가격", "body", "secondary"), text("1,180,000,000", "body", "primary"), badge("1,050,000,000", "warning"), link("공고문 p.3")],
        [text("참가자격", "body", "secondary"), text("SW사업자 신고", "body", "primary"), badge("SW사업자 + 정보보호 인증", "warning"), link("공고문 p.7")],
        [text("과업 기간", "body", "secondary"), text("12개월", "body", "primary"), text("12개월", "body", "primary"), link("공고문 p.4")],
        [text("실적요건", "body", "secondary"), text("null · 사전규격 미기재", "body", "secondary"), badge("동종 실적 3건 이상", "warning"), link("공고문 p.9")],
        [text("배점 기준", "body", "secondary"), text("null · 사전규격 미기재", "body", "secondary"), text("기술 90 / 가격 10", "body", "primary"), link("공고문 p.11")],
        [text("제출 마감", "body", "secondary"), text("2026-09-15", "body", "primary"), badge("2026-09-08", "warning"), link("공고문 p.1")],
    ]

    detail = (
        '<section class="bo-detail-pane">'
        '<header class="bo-detail-head">'
        f'{stack([text("사업기회 OPP-2026-0043 · 공고 20260901-004", "supporting", "secondary"), heading("차세대 통합 데이터 분석 플랫폼 구축", 4)], gap=1)}'
        f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        f'{badge("등급 우선 검토", "info")}{badge("준비 부분 확인 필요", "warning")}{badge("추적 승인됨", "neutral")}'
        f'<span style="margin-left:auto;display:flex;gap:8px">{button("변경 비교 열기", "primary")}{button("결정 이력")}</span></div>'
        "</header>"
        '<div class="bo-detail-scroll"><div class="bo-section">'
        f'<div class="bo-section-head">{text("공고 변경 항목 6건", "label", "primary")}'
        f'{text("사전규격 대비 달라진 값입니다. 근거 위치가 없는 항목은 근거 없음으로 표시하고 숨기지 않습니다.", "supporting", "secondary")}</div>'
        + table([("항목", "96px"), ("사전규격", None), ("입찰공고", None), ("근거", "92px")], delta_rows, min_width=620)
        + "</div></div></section>"
    )

    content = f'<main class="bo-canvas"><div class="bo-workspace">{list_pane}{detail}</div></main>'
    tb = topbar(
        "최종 Go/No-Go",
        f'{text("누적 데이터 · 회차 선택기 없음", "supporting", "secondary")}',
        f'<span class="bo-topbar-status">결정 대기 4 · Go 12 · No-Go 7</span>',
    )
    return screen("최종 Go/No-Go", tb, content)


# ─────────────────────────────────────────── 3단계 · 사전규격 접이식 그룹
def prespecs_screen():
    def group(title, count, variant, open_rows=None, note=None):
        head = (
            f'<span class="bo-group-head">{status_dot(title, variant)}'
            f'{text(title, "label", "primary")}{badge(str(count), "neutral")}'
            + (f'<span style="margin-left:auto">{text(note, "supporting", "secondary")}</span>' if note else "")
            + "</span>"
        )
        return f'<span class="bo-group">{head}{open_rows or ""}</span>'

    need_rows = "".join([
        row("차세대 통합 데이터 분석 플랫폼 구축",
            [badge("결과 null · 검증 대기", "warning"), badge("SW사업대상", "neutral")],
            "서울특별시 · 20260901-004", selected=True, deadline="D-2"),
        row("지방재정 데이터 표준화 용역",
            [badge("모델 제안 · 조건부 추진", "warning"), badge("검증 대기", "warning")],
            "행정안전부 · 20260901-011", deadline="D-6"),
        row("공공 마이데이터 유통 기반 2단계",
            [badge("null · 개요 결과 없음", "neutral")],
            "한국지능정보사회진흥원 · 20260901-023", deadline="D-9"),
    ])
    fail_rows = "".join([
        row("국가물류통합정보센터 시스템 개선",
            [badge("모델 오류", "error")], "국토교통부 · 20260901-047", deadline="D-13"),
        row("스마트도시 통합플랫폼 연계 표준", [badge("변환 실패", "error")],
            "부산광역시 · 20260901-052", deadline="D-17"),
    ])

    groups = (
        group("needs_human_review · 사람 검토 필요", 9, "warning", need_rows, "기본 펼침")
        + group("failed · 실패", 3, "error", fail_rows, "기본 펼침")
        + group("completed · 완료", 84, "success", None, "기본 접힘")
        + group("queued · 대기", 11, "info", None, "기본 접힘")
        + group("running · 실행 중", 4, "info", None, "기본 접힘")
        + group("preparing · 준비 중", 6, "info", None, "기본 접힘")
        + group("awaiting_model · 모델 대기", 3, "info", None, "기본 접힘")
        + group("awaiting_document · 문서 대기", 5, "info", None, "기본 접힘")
        + group("awaiting_structure · 구조 대기", 2, "info", None, "기본 접힘")
        + group("cancelled · 취소", 1, "neutral", None, "기본 접힘")
    )

    list_pane = (
        '<aside class="bo-list-pane" style="flex:0 0 min(520px,44%);width:min(520px,44%)">'
        f'<header class="bo-list-head">{stack([text("개요 검토 상태별 그룹", "label", "primary"), text("상태 10값이 모두 그룹으로 나타납니다. 0건 그룹도 숨기지 않습니다.", "supporting", "secondary")], gap=1)}</header>'
        f'<div class="bo-list-scroll">{groups}</div></aside>'
    )

    detail = (
        '<section class="bo-detail-pane">'
        '<header class="bo-detail-head">'
        f'{stack([text("사전규격 20260901-004 · 서울특별시", "supporting", "secondary"), heading("차세대 통합 데이터 분석 플랫폼 구축", 4)], gap=1)}'
        f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        f'{badge("개요 needs_human_review", "warning")}{badge("결과 null · 검증 대기", "neutral")}{badge("의견등록 마감 D-2", "error")}'
        f'<span style="margin-left:auto;display:flex;gap:8px">{button("검증 항목 확인", "primary")}{button("사람 검토 열기")}</span></div>'
        "</header>"
        '<div class="bo-detail-scroll"><div class="bo-section">'
        f'<div class="bo-section-head">{text("개요 검토 결과", "label", "primary")}'
        f'{text("제안요청서 앞부분만 읽은 저비용 단계입니다. 참가자격·배점·제출물·실적요건은 보지 못합니다.", "supporting", "secondary")}</div>'
        f'<ul class="bo-facts">{fact("결과", text("null · 검증 미완료", "body", "secondary"))}'
        f'{fact("모델 제안", badge("추진 검토 · 미검증", "warning"))}'
        f'{fact("조건", text("null · 조건 없음", "body", "secondary"))}'
        f'{fact("확인 기한", text("null · 해당 없음", "body", "secondary"))}'
        f'{fact("모델", text("qwen3.8:27b · prompt-v3", "body", "primary"))}</ul></div>'
        '<div class="bo-section" style="border-bottom:0">'
        f'{text("이 결과는 적합성 등급, 참여 준비 상태, 심층 검토 추적 선택, 최종 입찰 Go/No-Go를 채우거나 대신하지 않습니다.", "supporting", "secondary")}</div>'
        "</div></section>"
    )

    content = f'<main class="bo-canvas"><div class="bo-workspace">{list_pane}{detail}</div></main>'
    tb = topbar(
        "사전규격",
        f'{text("누적 데이터 · 회차 선택기 없음", "supporting", "secondary")}{selector("게시 최신순", "130px")}',
        '<span class="bo-topbar-status">전체 128건 · 사람 손 필요 12건</span>',
    )
    return screen("사전규격", tb, content)


# ─────────────────────────────────────────── 3단계 · 대시보드 할 일 스트립
def dashboard_screen():
    def action(kicker, count, label, arrow_to, alert=False):
        mod = " is-alert" if alert else ""
        return (
            f'<div class="bo-action-item{mod}" style="flex:1;min-width:0">'
            f'<span class="bo-action-text">{text(kicker, "supporting", "secondary")}'
            f'<span style="display:flex;align-items:baseline;gap:6px;white-space:nowrap">'
            f'{heading(count, 5)}{text(label, "body", "primary")}</span>'
            f'<span style="padding-top:4px">{link(arrow_to)}</span></span></div>'
        )

    strip = (
        '<section class="bo-action-strip">'
        f'<span class="bo-action-title">{text("지금 처리할 일", "label", "primary")}</span>'
        + action("결정 1 · 발주계획 후보 선별", "42", "건 검토 대기", "발주계획 C-2 →")
        + action("결정 2 · 심층 추적 승인", "9", "건 사람 검토 필요", "사전규격 →")
        + action("결정 3 · 공고 1차 판정", "17", "건 판정 대기", "검토 대기열 →")
        + action("결정 4 · 최종 Go/No-Go", "4", "건 결정 대기", "최종 Go/No-Go →", alert=True)
        + "</section>"
    )

    def kpi(label, value, unit, note):
        value_row = (
            '<span class="bo-kpi-value">'
            + heading(value, 2)
            + text(unit, "body", "secondary")
            + "</span>"
        )
        inner = stack(
            [
                text(label, "label", "secondary"),
                value_row,
                text(note, "supporting", "secondary"),
            ],
            gap=2,
        )
        return '<div class="bo-kpi">' + inner + "</div>"

    kpis = (
        '<section class="bo-kpi-grid">'
        + kpi("수집 건수", "2,014", "건", "수집 산출물 기준 · 용역 본공고")
        + kpi("분석 표본", "120", "건", "전체 수집의 6.0%")
        + kpi("우선 검토", "14", "건", "분석 표본 120건의 11.7%")
        + kpi("검증 실패", "4", "건", "사람 검토로 보냅니다 · 자동 보정하지 않음")
        + "</section>"
    )

    funnel = "".join(
        f'<div class="bo-funnel-row"><span style="flex:0 0 108px">{text(n, "supporting", "secondary")}</span>'
        f'<span class="bo-funnel-track"><span class="bo-funnel-fill" style="width:{p}%"></span></span>'
        f'<span class="bo-funnel-pct">{v}</span></div>'
        for n, p, v in [("수집", 100, "2,014건"), ("표본 선정", 100, "120건"), ("1차 판정", 86, "103건"), ("담당자 리뷰", 41, "49건")]
    )

    # 등급 4값은 심각도가 아니라 우선순위 순서다. 의미색(error/warning/success)에 실으면
    # "제외"가 위험으로, "우선 검토"가 성공으로 읽힌다. accent 농도 4단 전용 스케일을 쓴다.
    grades = [("우선 검토", 14, "is-g1"), ("검토 권장", 31, "is-g2"),
              ("관찰 대상", 44, "is-g3"), ("제외", 28, "is-g4")]
    grade_segs = "".join(
        f'<span class="bo-grade-seg {mod}" style="flex:{c}">'
        f'<span class="bo-grade-seg-count">{c}</span></span>'
        for _n, c, mod in grades
    )
    legend = "".join(
        f'<span class="bo-grade-legend-item"><span class="bo-grade-swatch {mod}"></span>'
        + text(f"{n} {c}", "supporting", "secondary")
        + "</span>"
        for n, c, mod in grades
    ) + '<span class="bo-grade-legend-item">' + text("unknown 3 · 확인 대기", "supporting", "secondary") + "</span>"

    verify = "".join(
        f'<li style="display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid var(--color-border)">'
        f'{status_dot(n, v)}<span style="flex:1">{text(n, "body", "primary")}</span>{text(val, "supporting", "secondary")}</li>'
        for n, v, val in [("근거 위치 연결", "success", "103 / 103"), ("수치 검증 실패", "warning", "4건 사람 검토로"),
                          ("첨부 미확보", "neutral", "7건"), ("평가 수치", "neutral", "계산 불가")]
    )

    panels = (
        '<section class="bo-review-grid">'
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("회차 진행", "label", "primary")}{text("20260901-weekly", "supporting", "secondary")}</div>'
        f'<div class="bo-panel-body">{funnel}'
        f'<div style="padding-top:14px">{text("적합성 등급 분포", "label", "primary")}'
        f'<div class="bo-grade-bar" style="margin-top:8px">{grade_segs}</div>'
        f'<div class="bo-grade-legend" style="margin-top:8px">{legend}</div></div></div></div>'
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("검증 상태", "label", "primary")}</div>'
        f'<div class="bo-panel-body"><ul class="bo-verify-list" style="list-style:none;margin:0;padding:0">{verify}</ul>'
        f'<div style="padding-top:10px">{text("계산 불가를 0/10으로 바꾸지 않습니다. 값 없음·미확인·계산 불가·0을 구분해 표시합니다.", "supporting", "secondary")}</div>'
        "</div></div></section>"
    )

    content = f'<main class="bo-canvas">{stack([strip, kpis, panels], gap=3)}</main>'
    tb = topbar(
        "대시보드",
        f'{text("실행 회차", "supporting", "secondary")}{selector("20260901-weekly", "180px")}{button("산출 근거")}',
        '<span class="bo-topbar-status">회차 데이터 · 읽기 전용</span>',
    )
    return screen("대시보드", tb, content)


# ─────────────────────────────────────────── 2단계 · 판정 기준 탭 통합
def criteria_screen():
    cap_rows = [
        [text("공공데이터 플랫폼", "body", "primary"), text("2024 서울시 데이터허브 · 2025 NIA 유통기반", "body", "secondary"), badge("확인 완료", "success")],
        [text("AI 분석 모델", "body", "primary"), text("2025 지자체 수요예측 PoC", "body", "secondary"), badge("부분 확인 필요", "warning")],
        [text("정보보호 인증", "body", "primary"), text("unknown · 확인 대기", "body", "secondary"), badge("unknown", "warning")],
        [text("물류 도메인", "body", "primary"), text("null · 실적 없음", "body", "secondary"), badge("해당 없음", "neutral")],
    ]

    left = (
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("회사 역량 프로필", "label", "primary")}'
        f'<span style="display:flex;gap:8px">{badge("profile-v1", "neutral")}{badge("기준선 검증 통과", "success")}</span></div>'
        f'<div class="bo-panel-body">'
        + table([("역량", "132px"), ("근거", None), ("확인 상태", "116px")], cap_rows, min_width=400)
        + f'<div style="padding-top:12px">{text("확인되지 않은 회사 역량·자격·실적은 추정하지 않습니다. unknown은 확인 대기, null은 값 없음으로 그대로 둡니다.", "supporting", "secondary")}</div>'
        "</div></div>"
    )

    right = stack([
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("이 화면이 정하지 않는 것", "label", "primary")}</div>'
        f'<div class="bo-panel-body">{stack([
            text("· 적합성 등급 4값", "body", "secondary"),
            text("· 참여 준비 상태 4값", "body", "secondary"),
            text("· 심층 검토 추적 승인", "body", "secondary"),
            text("· 최종 입찰 Go/No-Go", "body", "secondary"),
            text("네 판단은 각각 별도 조작으로 남습니다. 기준 편집이 판정을 소급해 바꾸지 않습니다.", "supporting", "secondary"),
        ], gap=1)}</div></div>',
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("활성화 대기 판정 정책", "label", "primary")}{badge("차단됨", "warning")}</div>'
        f'<div class="bo-panel-body">{stack([
            text("c2-policy-v1", "body", "primary"),
            text("현재 blocked · BM25 Top 300 → Qwen relevance. 승인 gold와 품질 게이트를 통과하기 전에는 활성화하지 않습니다.", "supporting", "secondary"),
        ], gap=1)}</div></div>',
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("품질 게이트 미충족", "label", "primary")}{badge("1건", "warning")}</div>'
        f'<div class="bo-panel-body">{stack([
            text("근거 위치 연결률이 임계값 아래입니다.", "body", "primary"),
            text("실패 결과는 사람 검토로 보내며 자동 보정하지 않습니다.", "supporting", "secondary"),
            link("품질 게이트 탭으로 →"),
        ], gap=1)}</div></div>',
    ], gap=3)

    content = (
        '<main class="bo-canvas">'
        + stack([
            segmented(["회사 프로필", "판정 정책", "품질 게이트", "검증 지표"], 0),
            f'<section class="bo-facts-grid">{left}{right}</section>',
        ], gap=3)
        + "</main>"
    )
    tb = topbar(
        "판정 기준",
        f'{text("누적 기준 · 회차 선택기 없음", "supporting", "secondary")}',
        '<span class="bo-topbar-status">기준 4화면을 탭으로 통합</span>',
    )
    return screen("판정 기준", tb, content)


# ─────────────────────────────────────────── 2단계 · 실행 상태 통합
def runstatus_screen():
    run_rows = [
        [badge("실행 중", "info"), text("a2f4d7c1…010301", "body", "primary"), text("91d8c2e4…0101", "body", "secondary"), text("09-01 13:01", "body", "primary"), text("진행 중", "body", "secondary"), text("null", "body", "secondary")],
        [badge("부분 성공", "warning"), text("a2f4d7c1…010101", "body", "primary"), text("91d8c2e4…0101", "body", "secondary"), text("09-01 11:05", "body", "primary"), text("4,800 ms", "body", "primary"), badge("부분", "warning")],
        [badge("실패", "error"), text("a2f4d7c1…009902", "body", "primary"), text("91d8c2e4…0098", "body", "secondary"), text("08-31 22:14", "body", "primary"), text("120,000 ms", "body", "primary"), text("없음", "body", "secondary")],
        [badge("성공", "success"), text("a2f4d7c1…009801", "body", "primary"), text("91d8c2e4…0098", "body", "secondary"), text("08-31 09:02", "body", "primary"), text("5,120 ms", "body", "primary"), badge("완전", "success")],
    ]

    telemetry = (
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("선택한 실행의 운영 텔레메트리", "label", "primary")}{badge("a2f4d7c1…010101", "neutral")}</div>'
        f'<div class="bo-panel-body"><ul class="bo-facts">'
        f'{fact("model_digest", text("sha256:4e2b…a91f", "body", "primary"))}'
        f'{fact("tokens 입력/캐시/출력", text("620 / 120 / 700", "body", "primary"))}'
        f'{fact("duration_ms", text("4,800", "body", "primary"))}'
        f'{fact("error code", text("batch_schema_violation", "body", "primary"))}</ul>'
        f'<div style="padding-top:10px">{text("판정 화면의 기본 표시에서 뺐지만 삭제하지 않았습니다. 감사 목적으로 여기서 확인합니다.", "supporting", "secondary")}</div>'
        "</div></div>"
    )

    always_on_body = stack([
        text("승인 조합 불일치 상태에서는 켤 수 없습니다.", "body", "primary"),
        text("켜기는 대화상자에서 조합·담당자·결과 ID를 재확인합니다.", "supporting", "secondary"),
        text("앱 startup은 migration·seed·정책 활성화·모델 호출을 수행하지 않습니다.", "supporting", "secondary"),
    ], gap=1)
    always_on = (
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("상시 운영", "label", "primary")}{badge("꺼짐", "error")}</div>'
        f'<div class="bo-panel-body">{always_on_body}</div></div>'
    )

    content = (
        '<main class="bo-canvas">'
        + stack([
            segmented(["실행", "첨부 확보", "상시 운영", "산출물 감사 로그"], 0),
            table(
                [("상태", "92px"), ("실행 ID", "184px"), ("source run", None), ("시작", "122px"), ("소요", "112px"), ("산출물", "92px")],
                run_rows, selected=1, min_width=820,
            ),
            f'<section class="bo-facts-grid">{telemetry}{always_on}</section>',
        ], gap=3)
        + "</main>"
    )
    tb = topbar(
        "실행 상태",
        f'{text("운영자 화면 · 회차 선택기 없음", "supporting", "secondary")}',
        '<span class="bo-topbar-status">스케줄러 비활성 (기본값)</span>',
    )
    return screen("실행 상태", tb, content)


# ─────────────────────────────────────────── 4단계 · 상세 공통 골격
def detail_screen():
    reqs = "".join([
        f'<div class="bo-row" style="border-left-color:transparent">'
        f'<span class="bo-row-line">{text(code, "label", "secondary")}{text(title, "body", "primary")}'
        f'<span class="bo-row-deadline">{cite}</span></span>'
        f'{text(desc, "supporting", "secondary")}</div>'
        for code, title, desc, cite in [
            ("REQ-01", "데이터 수집·정제 파이프라인 구축", "일 500만 건 규모의 정형·비정형 데이터를 수집하고 표준 스키마로 정제한다.", "제안요청서 p.12 §3.1"),
            ("REQ-02", "분석 모델 운영 환경", "GPU 추론 노드 4식 이상, 모델 버전 관리와 롤백 절차를 포함한다.", "제안요청서 p.15 §3.4"),
            ("REQ-04", "사용자 대시보드", "부서별 권한 분리와 지표 위젯 구성 기능을 제공한다.", "제안요청서 p.18 §4.2"),
        ]
    ])
    no_cite = (
        '<div class="bo-row" style="border-left-color:var(--color-border-yellow);background:var(--color-background-yellow)">'
        f'<span class="bo-row-line">{text("REQ-03", "label", "secondary")}{text("정보보호 인증 요건", "body", "primary")}'
        f'<span class="bo-row-deadline">{badge("근거 위치 없음", "warning")}</span></span>'
        f'{text("모델이 만든 요구사항이지만 원문 위치와 연결되지 않았습니다. 검증을 통과시키지 않고 사람 검토로 보냅니다.", "supporting", "secondary")}</div>'
    )

    history = "".join(
        f'<li style="display:flex;gap:10px;padding:9px 0;border-bottom:1px solid var(--color-border)">'
        f'{status_dot(t, v)}<span style="min-width:0">{text(t, "body", "primary")}<br>{text(m, "supporting", "secondary")}</span></li>'
        for t, m, v in [
            ("개요 검토 완료 · 추진 검토", "2026-09-01 11:05 · qwen3.8:27b", "success"),
            ("attempt 1 실패 · timeout", "2026-09-01 11:02 · 120,000 ms", "warning"),
            ("첨부 확보 완료", "2026-09-01 10:41 · 3개 파일", "neutral"),
            ("사전규격 관측", "2026-09-01 10:00 · 91d8c2e4…0101", "neutral"),
        ]
    )

    rail = (
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("이력", "label", "primary")}</div>'
        f'<div class="bo-panel-body"><ul style="list-style:none;margin:0;padding:0">{history}</ul>'
        f'{divider()}'
        f'<div style="padding-top:10px">{stack([text("연결된 화면", "label", "primary"), link("심층 검토 보고서 →"), link("사업기회 →"), link("실행 상태에서 이 실행 보기 →")], gap=1)}</div>'
        f'<div style="padding-top:10px">{text("우측 레일은 이력과 연결만 담습니다. 결정 액션은 헤더에만 둡니다.", "supporting", "secondary")}</div>'
        "</div></div>"
    )

    body_panel = (
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("요구사항 항목", "label", "primary")}'
        f'<span style="display:flex;gap:8px">{badge("12건", "neutral")}{badge("근거 없음 2건", "warning")}</span></div>'
        f"<div>{reqs}{no_cite}</div></div>"
    )

    header = (
        '<section class="bo-panel" style="margin-bottom:14px">'
        '<div class="bo-detail-head">'
        f'{stack([text("사전규격 20260901-004 · 서울특별시 디지털정책관", "supporting", "secondary"), heading("차세대 통합 데이터 분석 플랫폼 구축", 3)], gap=1)}'
        f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        f'{grade_tag("우선 검토")}{badge("준비 부분 확인 필요", "warning")}'
        f'{badge("개요 completed", "success")}{badge("추적 승인 unknown", "neutral")}'
        f'<span style="margin-left:auto;display:flex;align-items:center;gap:8px">'
        f'{text("의견등록 마감 D-2 · 2026-09-04", "supporting", "secondary")}'
        f'{button("심층 추적 승인", "primary")}{button("보류")}</span></div>'
        "</div></section>"
    )

    content = (
        '<main class="bo-canvas">'
        f'<div style="padding-bottom:12px">{text("상세 화면 3종(사전규격 상세 · 발주계획 상세 · 입찰 변경 비교)이 공유하는 골격입니다. 결정 액션은 헤더에 고정되어 스크롤 위치와 무관하게 첫 화면에서 보입니다.", "supporting", "secondary")}</div>'
        f'{header}<section class="bo-facts-grid">{body_panel}{rail}</section></main>'
    )
    tb = topbar(
        "사전규격 상세",
        f'{text("누적 데이터 · 회차 선택기 없음", "supporting", "secondary")}',
        '<span class="bo-topbar-status">상세 3종 공통 골격</span>',
    )
    return screen("사전규격", tb, content)


SCREENS = [
    ("Main.dc.html", main_screen, W, H),
    ("Navigation.dc.html", navigation_screen, 1320, 920),
    ("GoNoGo.dc.html", gonogo_screen, W, H),
    ("PreSpecs.dc.html", prespecs_screen, W, H),
    ("Dashboard.dc.html", dashboard_screen, W, H),
    ("Criteria.dc.html", criteria_screen, W, 820),
    ("RunStatus.dc.html", runstatus_screen, W, 820),
    ("DetailSkeleton.dc.html", detail_screen, W, 900),
]

if __name__ == "__main__":
    for name, fn, w, h in SCREENS:
        n = artboard(name, fn(), w, h)
        print(f"{name:<24} {n:>8,} bytes  ({w}×{h})")
