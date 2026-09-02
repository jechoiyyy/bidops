#!/usr/bin/env python3
"""나머지 화면 아트보드. screens.py와 같은 재료를 쓴다."""
from build import (
    artboard, badge, button, cls, divider, grade_tag, heading, link, screen,
    segmented, selector, stack, status_dot, table, text, text_input, topbar,
)
from screens import fact, row

W, H = 1440, 940


def panel(title, body, right=""):
    return (
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text(title, "label", "primary")}{right}</div>'
        f'<div class="bo-panel-body">{body}</div></div>'
    )


def actions_bar(*btns, note=""):
    """결정 액션은 상세 pane 바닥에 고정한다(4단계 게이트: 첫 화면에서 보임)."""
    tail = f'<span style="margin-left:auto">{note}</span>' if note else ""
    return (
        '<div style="margin-top:auto;display:flex;align-items:center;gap:10px;'
        'padding:14px 20px;border-top:1px solid var(--color-border);'
        f'background:var(--color-background-card)">{"".join(btns)}{tail}</div>'
    )


def rail(items, links, note):
    lis = "".join(
        '<li style="display:flex;gap:10px;padding:9px 0;border-bottom:1px solid var(--color-border)">'
        f'{status_dot(t, v)}<span style="min-width:0">{text(t, "body", "primary")}<br>'
        f'{text(m, "supporting", "secondary")}</span></li>'
        for t, m, v in items
    )
    ls = stack([text("연결된 화면", "label", "primary")] + [link(x) for x in links], gap=1)
    return (
        '<div class="bo-panel">'
        f'<div class="bo-panel-head">{text("이력", "label", "primary")}</div>'
        f'<div class="bo-panel-body"><ul style="list-style:none;margin:0;padding:0">{lis}</ul>'
        f'{divider()}<div style="padding-top:10px">{ls}</div>'
        f'<div style="padding-top:10px">{text(note, "supporting", "secondary")}</div>'
        "</div></div>"
    )


def summary_header(kicker, title, tags, right):
    return (
        '<section class="bo-panel" style="margin-bottom:14px">'
        '<div class="bo-detail-head">'
        f'{stack([text(kicker, "supporting", "secondary"), heading(title, 3)], gap=1)}'
        '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        f'{tags}<span style="margin-left:auto;display:flex;align-items:center;gap:8px">{right}</span>'
        "</div></div></section>"
    )


# ─────────────────────────────────────── 2단계 · 검토 대기열 (공고 1차 판정)
def queue_screen():
    filters = (
        '<section class="bo-filters">'
        f'<span class="bo-filter-field">{text("저장된 뷰", "label", "secondary")}'
        f'{segmented(["판정 대기", "마감 임박", "리뷰 완료", "전체"], 0)}</span>'
        f'<span class="bo-filter-field">{text("등급", "label", "secondary")}{selector("우선 검토 · 검토 권장")}</span>'
        f'<span class="bo-filter-field">{text("참여 준비 상태", "label", "secondary")}{selector("전체", "140px")}</span>'
        f'{text_input("공고명·공고번호 검색")}{button("필터 초기화")}'
        "</section>"
    )

    rows = "".join([
        row("차세대 지방행정 통합정보시스템 구축 사업",
            [grade_tag("우선 검토"), badge("부분 확인 필요", "warning")],
            "행정안전부 · 48.2억 · 20260901-0117", selected=True, deadline="D-4"),
        row("공공 클라우드 전환 지원 통합 사업 2단계",
            [grade_tag("검토 권장"), badge("확인 완료", "success")],
            "한국지능정보사회진흥원 · 12.7억 · 20260901-0132", deadline="D-8"),
        row("교통정보 수집·연계 장비 유지관리",
            [grade_tag("관찰 대상"), badge("해당 없음", "neutral")],
            "한국도로공사 · 3.4억 · 20260901-0140", deadline="D-11"),
        row("국방 정보체계 보안관제 위탁 운영",
            [grade_tag("제외"), badge("참여 불가 확인", "neutral")],
            "국방부 · null (미제공) · 20260901-0155", deadline="D-15"),
        row("스마트팜 데이터 플랫폼 고도화",
            [grade_tag("unknown"), badge("unknown · 확인 대기", "warning")],
            "농림축산식품부 · 6.1억 · 20260901-0161", deadline="D-19"),
    ])

    list_pane = (
        '<aside class="bo-list-pane">'
        '<header class="bo-list-head">'
        f'{stack([text("판정 대기", "label", "primary"), text("이번 회차 88건 중 미판정 31건", "supporting", "secondary")], gap=1)}'
        "</header>"
        f'<div class="bo-list-scroll"><span class="bo-group">{rows}</span></div>'
        f'<div class="bo-pager">{button("이전")}{text("1 / 7", "supporting", "secondary")}{button("다음")}</div>'
        "</aside>"
    )

    basis = "".join(
        '<div class="bo-row" style="border-left-color:transparent">'
        f'<span class="bo-row-line">{text(axis, "label", "secondary")}{text(claim, "body", "primary")}'
        f'<span class="bo-row-deadline">{cite}</span></span>'
        f'{text(note, "supporting", "secondary")}</div>'
        for axis, claim, note, cite in [
            ("기술 적합성", "데이터 연계·표준화 요구가 주된 과업",
             "표준 연계 규격 적용 요구가 반복 등장합니다.", "과업내용서 p.11 §3.2"),
            ("실적 정합성", "unknown — 실적 요건 원문을 찾지 못함",
             "최근 3년 유사 실적 인정 범위가 확인되지 않았습니다.", badge("근거 위치 없음", "warning")),
            ("공공 SI 적합성", "행정정보시스템 구축·운영 범위와 일치",
             "공공기관 통합 구축과 운영 이관이 함께 명시돼 있습니다.", "과업내용서 p.6 §2.4"),
            ("사업성·자격 제약", "확인 불가 — 참가자격 원문을 찾지 못함",
             "참가자격 항목에서 실적 기준 문장을 찾지 못했습니다. 확인 완료로 올리지 않습니다.",
             badge("근거 위치 없음", "warning")),
            ("전략 부합", "데이터 플랫폼 운영 역량과 전략 축이 맞음",
             "AI·데이터 우선 축과 공공 SI·통합관리 축에 모두 대응합니다.", "판정 근거 strategy-02"),
        ]
    )

    unknowns = (
        '<div class="bo-unknowns">'
        f'{text("미확인 사항 · 사람 확인 필요", "label", "primary")}'
        f'{text("• 최근 3년 유사 실적 요건 충족 여부 — unknown (원문 미확인)", "supporting", "secondary")}'
        f'{text("• 공동수급 허용 여부 — unknown (첨부 미확보)", "supporting", "secondary")}'
        f'{text("두 축 혼합 표시: 확인 요망 — 자격이 확인 불가인데 종합 등급이 우선 검토입니다. 등급을 자동으로 내리지 않습니다.", "supporting", "secondary")}'
        "</div>"
    )

    review = (
        '<div class="bo-section">'
        f'<div class="bo-section-head">{text("담당자 리뷰", "label", "primary")}'
        f'{text("등급과 참여 준비 상태는 독립적으로 기록합니다. 하나를 고쳐도 다른 하나는 자동으로 바뀌지 않습니다.", "supporting", "secondary")}</div>'
        + stack([
            stack([text("적합성 등급", "label", "secondary"),
                   segmented(["우선 검토", "검토 권장", "관찰 대상", "제외"], 0)], gap=1),
            stack([text("참여 준비 상태", "label", "secondary"),
                   segmented(["확인 완료", "부분 확인 필요", "참여 불가 확인", "해당 없음"], 1)], gap=1),
            stack([text("근거 동의", "label", "secondary"),
                   segmented(["동의", "부분 동의", "부동의"], 1)], gap=1),
            stack([text("리뷰 메모", "label", "secondary"),
                   f'<div class="{cls("astryx-text-area")}" style="min-height:60px;padding:9px 11px">'
                   + text("실적 요건 원문 확인 후 준비 상태 재판정 필요", "body", "secondary") + "</div>"], gap=1),
        ], gap=3)
        + "</div>"
    )

    detail = (
        '<section class="bo-detail-pane">'
        '<header class="bo-detail-head">'
        f'{stack([text("공고 20260901-0117 · 행정안전부 · 마감 2026-09-06", "supporting", "secondary"), heading("차세대 지방행정 통합정보시스템 구축 사업", 4)], gap=1)}'
        f'{segmented(["판정 근거", "판정 이력", "리뷰 기록"], 0)}</header>'
        '<div class="bo-detail-scroll">'
        '<div class="bo-section">'
        f'<div class="bo-section-head">{text("모델 판정", "label", "primary")}'
        f'<span style="display:flex;gap:8px">{grade_tag("우선 검토")}{badge("부분 확인 필요", "warning")}</span></div>'
        f'<div class="bo-basis">{basis}</div></div>'
        f'<div class="bo-section">{unknowns}</div>'
        f"{review}</div>"
        + actions_bar(button("리뷰 저장", "primary"), button("저장 후 다음 →"), button("되돌리기"),
                      note=text("31건 중 1번째", "supporting", "secondary"))
        + "</section>"
    )

    content = (
        '<main class="bo-canvas"><div class="bo-queue">'
        f'{filters}<div class="bo-workspace">{list_pane}{detail}</div></div></main>'
    )
    tb = topbar(
        "검토 대기열",
        f'{text("실행 회차", "supporting", "secondary")}{selector("20260901-01 · 09-01 09:40", "230px")}',
        f'<span class="bo-topbar-status">{status_dot("성공", "success")}&nbsp;성공 · 88건 판정 · 31건 미리뷰</span>',
    )
    return screen("검토 대기열", tb, content)


# ─────────────────────────────────────── 4단계 · 발주계획 상세
def orderplan_detail_screen():
    facts = "".join([
        fact("발주계획 번호", text("OP-2026-00101", "body", "primary")),
        fact("기관", text("서울특별시 디지털정책관", "body", "primary")),
        fact("예산", text("125,000,000", "body", "primary")),
        fact("계획 시기", text("2026년 11월", "body", "primary")),
        fact("계약 방법", text("null (미제공)", "body", "secondary")),
        fact("BM25 stage1", badge("선정 · 순위 1", "success")),
        fact("Qwen relevance",
             badge("relevant", "info") + " " + text("근거: 공공데이터 통합·분석 플랫폼", "supporting", "secondary")),
        fact("Qwen priority", text("null (미지정)", "body", "secondary")),
    ])

    revs = "".join(
        '<li style="padding:10px 0;border-bottom:1px solid var(--color-border)">'
        f'<span style="display:flex;align-items:center;gap:8px">{badge("rev " + str(n), "neutral")}'
        f'{badge(rel, "info")}{badge(pri, "neutral")}'
        f'<span style="margin-left:auto">{text(when, "supporting", "secondary")}</span></span>'
        f'<div style="padding-top:5px">{text(memo, "supporting", "secondary")}</div></li>'
        for n, rel, pri, when, memo in [
            (2, "relevant", "priority null (미지정)", "2026-09-01 14:12 · 홍길동",
             "공공데이터 플랫폼 구축·운영으로 회사 역량과 맞음"),
            (1, "uncertain", "priority normal", "2026-08-30 09:31 · 홍길동",
             "null (메모 미제공)"),
        ]
    )

    new_rev = stack([
        stack([text("relevance", "label", "secondary"),
               segmented(["relevant", "uncertain", "not_relevant"], 0)], gap=1),
        stack([text("priority", "label", "secondary"),
               segmented(["high", "normal", "null · 미지정"], 2)], gap=1),
        stack([text("담당자 claimed name", "label", "secondary"), text_input("예: 홍길동", "220px")], gap=1),
        stack([text("사람 검토 근거 또는 다음 확인 사항", "label", "secondary"),
               f'<div class="{cls("astryx-text-area")}" style="min-height:56px;padding:9px 11px">'
               + text("본문 공고 게시 후 예산 규모 재확인", "body", "secondary") + "</div>"], gap=1),
    ], gap=3)

    body = (
        panel("발주계획 사실",
              f'<ul class="bo-facts" style="margin:0;padding:0;list-style:none">{facts}</ul>')
        + '<div style="height:14px"></div>'
        + panel("사람 피드백 revision history",
                f'<ul style="list-style:none;margin:0;padding:0">{revs}</ul>{divider()}'
                f'<div style="padding-top:12px">{new_rev}</div>',
                badge("append-only · 2건", "neutral"))
    )

    side = rail(
        [("screening execution a2f4d7c1 · 부분 성공", "2026-09-01 11:05 · Qwen 42건 / 실패 3건", "warning"),
         ("관측 history · 예산 변경", "2026-08-30 09:00 · 118,000,000 → 125,000,000", "neutral"),
         ("관측 history · 최초 수집", "2026-08-27 09:00 · 20260827-01", "neutral")],
        ["실행 상태에서 이 실행 보기 →", "사업기회 →", "목록으로 →"],
        "관측 기록이 없는 항목은 변경 여부를 판단하지 않습니다. 서버가 준 기록만 보여줍니다.",
    )

    header = summary_header(
        "발주계획 OP-2026-00101 · 계획 ID 101 · 서울특별시 디지털정책관",
        "인공지능 기반 공공데이터 통합·분석 플랫폼 구축 및 운영 지원 사업",
        badge("BM25 선정 · 1", "success") + badge("relevant", "info")
        + badge("피드백 rev 2", "neutral") + badge("등급 · 해당 없음", "neutral"),
        text("C-2는 relevance 흐름입니다. 등급·준비 상태를 채우지 않습니다.", "supporting", "secondary")
        + button("새 revision 저장", "primary") + button("목록으로"),
    )

    content = (
        '<main class="bo-canvas">'
        f'{header}<section class="bo-facts-grid">'
        f'<div style="min-width:0">{body}</div>{side}</section></main>'
    )
    tb = topbar(
        "발주계획 상세",
        text("누적 데이터 · 회차 선택기 없음", "supporting", "secondary"),
        f'<span class="bo-topbar-status">{status_dot("부분 성공", "warning")}&nbsp;부분 성공 · a2f4d7c1</span>',
    )
    return screen("발주계획 C-2", tb, content)


# ─────────────────────────────────────── 4단계 · 사전규격 상세
def prespec_detail_screen():
    stages = "".join(
        '<li style="display:flex;align-items:center;gap:10px;padding:9px 0;'
        f'border-bottom:1px solid var(--color-border)">{status_dot(s, v)}'
        f'<span style="min-width:0">{text(s, "body", "primary")}<br>{text(d, "supporting", "secondary")}</span>'
        f'<span style="margin-left:auto">{badge(tag, v)}</span></li>'
        for s, d, v, tag in [
            ("첨부 확보", "3개 파일 · ClamAV 통과 · 2026-09-01 10:41", "success", "완료"),
            ("문서 구조화", "제안요청서 62쪽 → 절 단위 구조화", "success", "완료"),
            ("개요 입력 범위 확정", "서버가 구조화 문서에서 앞부분 12쪽을 확정", "success", "완료"),
            ("모델 실행", "attempt 2 · qwen3.8:27b · prompt-v3", "success", "완료"),
            ("결과 검증", "요구사항 12건 중 2건이 원문 위치와 연결되지 않음", "warning", "사람 검토 필요"),
        ]
    )

    reqs = "".join(
        '<div class="bo-row" style="border-left-color:transparent">'
        f'<span class="bo-row-line">{text(code, "label", "secondary")}{text(t, "body", "primary")}'
        f'<span class="bo-row-deadline">{cite}</span></span>'
        f'{text(d, "supporting", "secondary")}</div>'
        for code, t, d, cite in [
            ("REQ-01", "데이터 수집·정제 파이프라인 구축",
             "일 500만 건 규모의 정형·비정형 데이터를 표준 스키마로 정제한다.", "제안요청서 p.12 §3.1"),
            ("REQ-02", "분석 모델 운영 환경",
             "GPU 추론 노드 4식 이상, 모델 버전 관리와 롤백 절차를 포함한다.", "제안요청서 p.15 §3.4"),
        ]
    )
    bad = "".join(
        '<div class="bo-row" style="border-left-color:var(--color-border-yellow);'
        'background:var(--color-background-yellow)">'
        f'<span class="bo-row-line">{text(code, "label", "secondary")}{text(t, "body", "primary")}'
        f'<span class="bo-row-deadline">{badge("근거 위치 없음", "warning")}</span></span>'
        + text("모델이 만든 항목이지만 원문 위치와 연결되지 않았습니다. 검증을 통과시키지 않고 사람 검토로 보냅니다. 자동 보정하지 않습니다.",
               "supporting", "secondary")
        + "</div>"
        for code, t in [("REQ-03", "정보보호 인증 요건"), ("REQ-07", "운영 인력 상주 조건")]
    )

    attach = "".join(
        '<div class="bo-attach"><span style="display:flex;align-items:center;gap:8px">'
        f'{text(n, "body", "primary")}<span style="margin-left:auto">{badge(s, v)}</span></span>'
        f'{text(m, "supporting", "secondary")}</div>'
        for n, s, v, m in [
            ("제안요청서.hwp", "배포 가능", "success", "2.4 MB · 변환 완료 · 구조화 62쪽"),
            ("과업내용서.pdf", "배포 가능", "success", "1.1 MB · 변환 완료"),
            ("붙임3_서식.zip", "배포 불가", "error", "압축 내부 확인 실패 · 원본 보존, 자동 재시도 없음"),
        ]
    )

    stage_note = text(
        "이 결과는 적합성 등급, 참여 준비 상태, 심층 검토 추적 선택, 최종 입찰 Go/No-Go를 채우거나 대신하지 않습니다.",
        "supporting", "secondary")

    body = (
        panel("개요 검토 상태",
              f'<ul style="list-style:none;margin:0;padding:0">{stages}</ul>'
              f'<div style="padding-top:10px">{stage_note}</div>',
              badge("needs_human_review", "warning"))
        + '<div style="height:14px"></div>'
        + '<div class="bo-panel">'
        + f'<div class="bo-panel-head">{text("요구사항 항목", "label", "primary")}'
        + f'<span style="display:flex;gap:8px">{badge("12건", "neutral")}{badge("근거 없음 2건", "warning")}</span></div>'
        + f"<div>{reqs}{bad}</div></div>"
    )

    side = (
        '<div style="display:flex;flex-direction:column;gap:14px;min-width:0">'
        + panel("첨부", attach, badge("3개", "neutral"))
        + rail(
            [("개요 모델 제안 · 추진 검토 (미검증)", "2026-09-01 11:05 · qwen3.8:27b", "warning"),
             ("attempt 1 실패 · timeout", "2026-09-01 11:02 · 120,000 ms", "warning"),
             ("사전규격 관측", "2026-09-01 10:00 · 20260901-004", "neutral")],
            ["심층 검토 보고서 →", "사업기회 →", "사전규격 목록 →"],
            "우측 레일은 이력과 연결만 담습니다. 결정 액션은 헤더에만 둡니다.",
        )
        + "</div>"
    )

    header = summary_header(
        "사전규격 20260901-004 · 서울특별시 디지털정책관 · 의견등록 마감 2026-09-04",
        "차세대 통합 데이터 분석 플랫폼 구축",
        badge("개요 결과 null · 검증 대기", "neutral") + badge("개요 needs_human_review", "warning")
        + badge("추적 승인 unknown", "neutral") + badge("등급 · 해당 없음", "neutral"),
        text("D-2", "supporting", "secondary") + button("검증 항목 확인", "primary")
        + button("개요 다시 실행"),
    )

    content = (
        '<main class="bo-canvas">'
        f'{header}<section class="bo-facts-grid">'
        f'<div style="min-width:0">{body}</div>{side}</section></main>'
    )
    tb = topbar(
        "사전규격 상세",
        text("누적 데이터 · 회차 선택기 없음", "supporting", "secondary"),
        '<span class="bo-topbar-status">개요 검토 · 저비용 단계</span>',
    )
    return screen("사전규격", tb, content)


# ─────────────────────────────────────── 2단계 · 사업기회 목록
def opportunities_screen():
    filters = (
        '<section class="bo-filters">'
        f'<span class="bo-filter-field">{text("저장된 뷰", "label", "secondary")}'
        f'{segmented(["진행 중", "재검토 필요", "미선택", "전체"], 0)}</span>'
        f'<span class="bo-filter-field">{text("추적 상태", "label", "secondary")}{selector("미선택 · 계속 추적 · 보류")}</span>'
        f'{text_input("사업명 검색")}'
        f'<span style="margin-left:auto">{text("필터를 지우면 종료된 것을 포함한 전체를 볼 수 있습니다.", "supporting", "secondary")}</span>'
        "</section>"
    )

    rows = "".join([
        row("차세대 통합 데이터 분석 플랫폼 구축",
            [badge("계속 추적", "info"), badge("심층 검토 완료", "success"), badge("재검토 필요", "warning")],
            "서울특별시 · 사전규격 → 공고 · 재검토 신호 2건", selected=True),
        row("공공 클라우드 전환 지원 통합 사업 2단계",
            [badge("계속 추적", "info"), badge("Go/No-Go 대기", "warning")],
            "한국지능정보사회진흥원 · 공고 20260901-0132 · D-8"),
        row("지방재정 데이터 표준화 용역",
            [badge("미선택", "neutral")],
            "행정안전부 · 사전규격 20260901-011 · 심층 검토 미착수"),
        row("국가물류통합정보센터 시스템 개선",
            [badge("종료", "neutral"), badge("기록된 이유 없음", "warning")],
            "국토교통부 · 종료 2026-08-24"),
    ])

    list_pane = (
        '<aside class="bo-list-pane">'
        f'<header class="bo-list-head">{stack([text("사업기회", "label", "primary"), text("진행 중 24건 · 재검토 필요 3건", "supporting", "secondary")], gap=1)}</header>'
        f'<div class="bo-list-scroll"><span class="bo-group">{rows}</span></div>'
        "</aside>"
    )

    linked = "".join(
        '<li style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid var(--color-border)">'
        f'<span style="flex:0 0 96px">{text(k, "supporting", "secondary")}</span>'
        f'<span style="flex:1;min-width:0">{v}</span></li>'
        for k, v in [
            ("발주계획", link("OP-2026-00101 · 인공지능 기반 공공데이터 통합·분석 플랫폼 →")),
            ("사전규격", link("20260901-004 · 차세대 통합 데이터 분석 플랫폼 구축 →")),
            ("입찰공고", text("null (아직 게시되지 않음)", "body", "secondary")),
            ("심층 검토", link("DR-2026-0044 · 보고서 rev 3 →")),
        ]
    )

    signals = (
        '<div class="bo-unknowns">'
        f'{text("재검토 신호 · 2건", "label", "primary")}'
        f'{text("• 사전규격 요구사항 REQ-03이 근거 위치 없음으로 남아 있습니다.", "supporting", "secondary")}'
        f'{text("• 발주계획 예산이 118,000,000 → 125,000,000으로 관측되었습니다.", "supporting", "secondary")}'
        "</div>"
    )

    form = (
        '<div class="bo-section">'
        f'<div class="bo-section-head">{text("추적 상태 저장", "label", "primary")}'
        f'{text("이 상태는 사전규격 개요 결과나 공고 판정 등급을 대신하지 않습니다. 이유와 담당자 이름이 있어야 저장됩니다.", "supporting", "secondary")}</div>'
        + stack([
            stack([text("추적 상태", "label", "secondary"),
                   segmented(["미선택", "계속 추적", "보류", "종료"], 1)], gap=1),
            stack([text("담당자 이름 (필수)", "label", "secondary"), text_input("예: 홍길동", "220px")], gap=1),
            stack([text("이 상태를 고른 이유 (필수)", "label", "secondary"),
                   f'<div class="{cls("astryx-text-area")}" style="min-height:56px;padding:9px 11px">'
                   + text("사전규격 근거 미확인 항목 해소 후 확정 여부 판단", "body", "secondary") + "</div>"], gap=1),
        ], gap=3)
        + "</div>"
    )

    detail = (
        '<section class="bo-detail-pane">'
        '<header class="bo-detail-head">'
        f'{stack([text("사업기회 #1042 · 서울특별시 디지털정책관", "supporting", "secondary"), heading("차세대 통합 데이터 분석 플랫폼 구축", 4)], gap=1)}'
        f'{segmented(["연결 레코드", "추적 이력", "재검토 신호"], 0)}</header>'
        '<div class="bo-detail-scroll">'
        f'<div class="bo-section"><ul style="list-style:none;margin:0;padding:0">{linked}</ul></div>'
        f'<div class="bo-section">{signals}</div>{form}</div>'
        + actions_bar(button("추적 상태 저장", "primary"), button("심층 검토 보고서 →"),
                      note=text("저장하지 않은 변경 있음", "supporting", "secondary"))
        + "</section>"
    )

    content = (
        '<main class="bo-canvas"><div class="bo-queue">'
        f'{filters}<div class="bo-workspace">{list_pane}{detail}</div></div></main>'
    )
    tb = topbar(
        "사업기회",
        text("누적 데이터 · 회차 선택기 없음", "supporting", "secondary") + selector("최근 갱신순", "140px"),
        '<span class="bo-topbar-status">진행 중 24건 · 재검토 필요 3건</span>',
    )
    return screen("사업기회", tb, content)


# ─────────────────────────────────────── 2단계 · 심층 검토 보고서
def deepreview_screen():
    cards = "".join(
        '<div class="bo-kpi" style="min-height:0;padding:14px 16px">'
        f'{text(k, "supporting", "secondary")}'
        f'<span class="bo-kpi-value">{v}</span>'
        f'{text(m, "supporting", "secondary")}</div>'
        for k, v, m in [
            ("종합 판단", grade_tag("검토 권장"), "모델 제안 · 사람 확정 전"),
            ("참여 준비 상태", badge("부분 확인 필요", "warning"), "실적 요건 원문 미확인"),
            ("미확인 사항", badge("4건", "warning"), "unknown 유지 · 자동 보정 없음"),
            ("보고서 revision", badge("rev 3", "neutral"), "append-only · 최신 2026-09-01"),
        ]
    )

    items = table(
        [("항목", "130px"), ("내용", None), ("근거", "210px"), ("검증", "110px")],
        [
            [text("참가자격", "body", "primary"),
             text("정보통신공사업 등록 또는 소프트웨어사업자 신고", "body", "primary"),
             link("공고문 p.6 §4.1"), badge("verified", "success")],
            [text("배점", "body", "primary"),
             text("기술 80 · 가격 20 · 기술 최저 기준 70점", "body", "primary"),
             link("제안요청서 p.31 §7"), badge("verified", "success")],
            [text("실적 요건", "body", "primary"),
             text("unknown · 원문에서 확인하지 못함", "body", "secondary"),
             text("근거를 확인할 수 없습니다.", "supporting", "secondary"),
             badge("missing", "warning")],
            [text("제출물", "body", "primary"),
             text("기술제안서 · 가격제안서 · 참여인력 확인서", "body", "primary"),
             link("공고문 p.9 §5.2"), badge("verified", "success")],
            [text("계약 기간", "body", "primary"),
             text("모델이 12개월로 적었으나 원문은 14개월", "body", "primary"),
             link("과업내용서 p.3 §1.4"), badge("mismatch", "error")],
        ],
        min_width=600,
    )

    unknowns = (
        '<div class="bo-unknowns">'
        + text("미확인 사항 · 4건", "label", "primary")
        + "".join(text("• " + x, "supporting", "secondary") for x in [
            "최근 3년 유사 실적 요건 — unknown (원문 미확인)",
            "공동수급 허용 여부 — unknown (첨부 미확보)",
            "하도급 비율 상한 — unknown",
            "현장설명회 필수 여부 — null (해당 항목 없음)",
        ])
        + "</div>"
    )

    verify = (
        '<div class="bo-unknowns" style="border-color:var(--color-border-red);'
        'background:var(--color-background-red)">'
        + text("Validation 실패 1건", "label", "primary")
        + text("계약 기간이 원문과 다릅니다. 이 항목을 판정으로 읽지 마세요. 실패를 확인해야 심층검토 의견을 저장할 수 있고, 자동 보정하지 않습니다.",
               "supporting", "secondary")
        + f'<span style="display:flex;gap:8px;padding-top:6px">{button("원문에서 확인")}{button("새 attempt로 재시도")}</span>'
        + "</div>"
    )

    side = (
        '<div style="display:flex;flex-direction:column;gap:14px;min-width:0">'
        + panel("보고서 범위", stack([
            text("사전규격 20260901-004 · 제안요청서 62쪽 전체", "body", "primary"),
            text("모델 qwen3.8:27b · prompt-v4 · attempt 2", "supporting", "secondary"),
            text("고정 profile fact 14건 · 정책 버전 p-2026-08", "supporting", "secondary"),
        ], gap=1))
        + panel("보고서 수정본 저장", stack([
            text("수정본은 새 immutable revision으로 append-only 저장됩니다. 기존 보고서를 덮어쓰지 않습니다.",
                 "supporting", "secondary"),
            text_input("담당자 claimed name (필수)", "200px"),
            f'<div class="{cls("astryx-text-area")}" style="min-height:52px;padding:9px 11px">'
            + text("계약 기간 14개월로 정정, 근거 위치 첨부", "body", "secondary") + "</div>",
            button("수정본 저장", "primary"),
        ], gap=2))
        + rail(
            [("rev 3 저장 · 사람", "2026-09-01 15:20 · 홍길동", "neutral"),
             ("attempt 2 완료", "2026-09-01 14:02 · qwen3.8:27b", "success"),
             ("attempt 1 실패 · 검증 실패", "2026-09-01 13:40 · 근거 3건 mismatch", "error")],
            ["사전규격 상세 →", "사업기회 →", "공고 판정 →"],
            "이전 revision은 대체됨으로 남고 지워지지 않습니다.",
        )
        + "</div>"
    )

    header = summary_header(
        "심층 검토 DR-2026-0044 · 공고 20260901-0117 · 사전규격 20260901-004",
        "차세대 통합 데이터 분석 플랫폼 구축 — 심층 검토 보고서",
        badge("분석 완료", "success") + badge("Validation 실패 1건", "error") + badge("rev 3", "neutral"),
        text("모델 제안이며 사람 확정 전입니다.", "supporting", "secondary")
        + button("보고서 다시 조회") + button("검토 종료"),
    )

    content = (
        '<main class="bo-canvas">'
        f'{header}<section class="bo-kpi-grid" style="margin-bottom:14px">{cards}</section>'
        '<section class="bo-facts-grid"><div style="min-width:0">'
        + panel("결정 카드 요약", items, badge("5개 축", "neutral"))
        + '<div style="height:14px"></div><div class="bo-panel"><div class="bo-panel-body">'
        + verify + '<div style="height:10px"></div>' + unknowns + "</div></div>"
        + f"</div>{side}</section></main>"
    )
    tb = topbar(
        "심층 검토 보고서",
        text("누적 데이터 · 회차 선택기 없음", "supporting", "secondary"),
        '<span class="bo-topbar-status">append-only · 덮어쓰기 없음</span>',
    )
    return screen("사업기회", tb, content)


# ─────────────────────────────────── 2단계 · 입찰 변경 비교 · 최종 Go/No-Go
def biddelta_screen():
    def axis_row(name, verdict, v_variant, before, after, cite, cite_variant):
        return (
            '<div class="bo-row" style="border-left-color:transparent">'
            f'<span class="bo-row-line">{text(name, "label", "secondary")}'
            f'{text(after, "body", "primary")}'
            f'<span class="bo-row-deadline">{badge(verdict, v_variant)}</span></span>'
            '<span style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding-top:3px">'
            + text("사전규격: " + before, "supporting", "secondary")
            + f'<span style="margin-left:auto">{badge(cite, cite_variant)}</span></span></div>'
        )

    axes = "".join([
        axis_row("금액·경제성", "material · 중요 변경", "error",
                 "추정가격 48.2억", "추정가격 44.7억 (-7.3%)", "verified · 검증됨", "success"),
        axis_row("계약기간·일정", "material · 중요 변경", "error",
                 "14개월", "11개월 · 착수 2026-11-01", "verified · 검증됨", "success"),
        axis_row("참가자격", "material · 중요 변경", "error",
                 "SW사업자 신고", "SW사업자 신고 + 정보보호 인증", "verified · 검증됨", "success"),
        axis_row("과업·요구사항", "non_material · 비중요 변경", "neutral",
                 "요구사항 12건", "요구사항 12건 · 표현 정정 3건", "verified · 검증됨", "success"),
        axis_row("평가", "non_material · 비중요 변경", "neutral",
                 "기술 90 / 가격 10", "기술 90 / 가격 10 · 절 번호 정정", "verified · 검증됨", "success"),
        axis_row("제출", "material · 중요 변경", "error",
                 "제출 마감 2026-09-15", "제출 마감 2026-09-08", "verified · 검증됨", "success"),
        axis_row("공동수급·하도급", "unknown · 중요도 미확인", "warning",
                 "unknown (사전규격에 항목 없음)", "공동수급 허용 · 하도급 상한 unknown",
                 "missing · 근거 없음", "warning"),
    ])

    guard = (
        '<div class="bo-unknowns">'
        f'{text("저장 조건", "label", "primary")}'
        f'{text("• 계산이 완료된 비교만 최종 결정할 수 있습니다. 현재 상태 completed · 계산 완료.", "supporting", "secondary")}'
        f'{text("• unknown 축이 1건 남아 있습니다. 이를 변경 없음으로 해석하지 않습니다.", "supporting", "secondary")}'
        f'{text("• 최종 Go/No-Go는 적합성 등급·참여 준비 상태·심층 추적 승인을 대신하지 않습니다.", "supporting", "secondary")}'
        "</div>"
    )

    decide = (
        '<div class="bo-section" style="border-bottom:0">'
        f'<div class="bo-section-head">{text("최종 입찰 Go/No-Go", "label", "primary")}'
        f'{text("사람이 내리는 네 번째 결정입니다. 이 화면에서만 저장됩니다.", "supporting", "secondary")}</div>'
        + stack([
            stack([text("최종 결정", "label", "secondary"),
                   segmented(["Go · 참여", "No-Go · 불참"], None)], gap=1),
            text("보류는 최종 결정 값이 아닙니다. 결정하지 않으면 기록을 만들지 않습니다.",
                 "supporting", "secondary"),
            stack([text("담당자 claimed name (필수)", "label", "secondary"),
                   text_input("예: 홍길동", "220px")], gap=1),
            stack([text("결정 이유 (필수)", "label", "secondary"),
                   f'<div class="{cls("astryx-text-area")}" style="min-height:58px;padding:9px 11px">'
                   + text("추정가격 7.3% 하락과 기간 3개월 단축의 수익성 영향 확인 후 결정",
                          "body", "secondary") + "</div>"], gap=1),
        ], gap=3)
        + '<div style="display:flex;align-items:center;gap:8px;padding-top:14px">'
        + button("최종 결정 저장", "primary", disabled=True) + button("입력 초기화")
        + f'<span style="margin-left:auto">{text("담당자와 이유 입력 후 저장", "supporting", "secondary")}</span></div>'
        + "</div>"
    )

    side = (
        '<div style="display:flex;flex-direction:column;gap:14px;min-width:0">'
        + panel("비교 기준", stack([
            text("기준 · 사전규격 20260901-004", "body", "primary"),
            text("authoritative · ready bundle 문서 확보", "supporting", "secondary"),
            divider(),
            text("대상 · 입찰공고 20260901-0117", "body", "primary"),
            text("authoritative · ready bundle 문서 확보", "supporting", "secondary"),
            divider(),
            text("계산 completed · 2026-09-01 16:12 · request 9c1f…", "supporting", "secondary"),
        ], gap=1))
        + rail(
            [("delta 계산 완료", "2026-09-01 16:12 · 4개 축", "success"),
             ("입찰공고 게시", "2026-09-01 09:40 · 20260901-0117", "neutral"),
             ("사전규격 개요 검토", "2026-08-20 11:05 · 추진 검토", "neutral")],
            ["심층 검토 보고서 →", "사업기회 →", "공고 판정 →"],
            "결정은 append-only로 기록됩니다. current 결정이 stale이 되면 재검토로 표시됩니다.",
        )
        + "</div>"
    )

    header = summary_header(
        "사업기회 #1042 · 입찰공고 20260901-0117 · 마감 2026-09-06",
        "차세대 통합 데이터 분석 플랫폼 구축 — 입찰 변경 비교",
        badge("completed · 계산 완료", "success") + badge("material 4건", "error")
        + badge("unknown 1건", "warning") + badge("현재 결정 없음", "neutral"),
        text("D-4", "supporting", "secondary") + button("결정 저장", "primary", disabled=True)
        + button("결정 입력으로 이동") + button("비교 재계산"),
    )

    content = (
        '<main class="bo-canvas">'
        f'{header}<section class="bo-facts-grid"><div style="min-width:0">'
        + '<div class="bo-panel">'
        + f'<div class="bo-panel-head">{text("축별 변경", "label", "primary")}'
        + f'<span style="display:flex;gap:8px">{badge("7개 축", "neutral")}{badge("material 4", "error")}</span></div>'
        + f'<div>{axes}</div></div>'
        + '<div style="height:14px"></div><div class="bo-panel"><div class="bo-panel-body">'
        + guard + "</div>" + decide + "</div>"
        + f"</div>{side}</section></main>"
    )
    tb = topbar(
        "최종 Go/No-Go",
        text("누적 데이터 · 회차 선택기 없음", "supporting", "secondary"),
        '<span class="bo-topbar-status">계산 완료 · 결정 검토 가능</span>',
    )
    return screen("최종 Go/No-Go", tb, content)


MORE = [
    ("Queue.dc.html", queue_screen, W, H),
    ("OrderPlanDetail.dc.html", orderplan_detail_screen, W, 1180),
    ("PreSpecDetail.dc.html", prespec_detail_screen, W, 1180),
    ("Opportunities.dc.html", opportunities_screen, W, 980),
    ("DeepReview.dc.html", deepreview_screen, W, 1080),
    ("BidDelta.dc.html", biddelta_screen, W, 1460),
]

if __name__ == "__main__":
    for name, fn, w, h in MORE:
        n = artboard(name, fn(), w, h)
        print(f"{name:<24} {n:>8,} bytes  ({w}×{h})")
