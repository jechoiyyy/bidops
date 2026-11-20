import { Check } from "lucide-react";
import { Link } from "react-router-dom";
import { recordRoute, stageOfLink } from "../opportunities/trackingFlow";
import { formatKstDay, stageLabelAt, STAGE_STATE_LABEL, type RecordDecisionAxis } from "../../lib/record";
import type { OpportunityLinkView, OpportunityStageEntry } from "../../lib/types";

/*
 * 사업 흐름(2026-11-19 최종 시안 `docs/1119_kstyle-shell/mockups/FinalOpportunity.dc.html`).
 * 이전의 가로 단계 바(ui-spec §3, RL-02 spec "단계 바")를 세로 흐름으로 그린다. 단계 6개
 * (발주계획·사전규격·입찰공고·마감·개찰·계약)와 상태는 서버가 판정한 값 그대로이고, 맨 끝에
 * 사람이 따로 정하는 최종 Go/No-Go 칸을 붙인다(단계가 아니라 결정 축이며 `.rec-stage`가 아니다).
 *
 * 상태: 완료=✓ 먹색 채움, 현재=먹색 링, 다가오는 마감=주의색 링, 대기·미확인=회색 링. `unknown`은
 * 라벨 뒤에 `미확인`을 글자로 적는다(건너뛴 단계나 데이터가 없는 단계를 추정해 채우지 않는다). 색만으로
 * 말하지 않도록 상태 이름을 글자로 함께 둔다(미확인 외에는 화면 낭독기용 숨은 글자).
 *
 * 앞 세 칸은 그 단계의 대표 권위 연결(`link_id`, 서버가 고른다)이 상세 `links`에 있으면 단계 이름이
 * 원천 화면 링크가 되고(설계고도화안 C-3) 그 연결의 예산·발주 예정·마감을 한 줄로 적는다. 권위 연결이
 * 없고 사람 확인 대기 후보가 있으면 `후보 확인 대기` 표식을 둔다 — 후보는 확정 관계가 아니다.
 */
interface StageBarProps {
  stages: readonly OpportunityStageEntry[];
  links?: readonly OpportunityLinkView[];
  /** 사람 확인 대기 후보 연결(`isPendingCandidate`). 단계별로 센다. */
  candidates?: readonly OpportunityLinkView[];
  /** 결정 축 요약의 최종 Go/No-Go(`recordDecisionAxes`의 `go_no_go`). 없으면 칸을 그리지 않는다. */
  goNoGo?: RecordDecisionAxis | null;
}

function plannedLabel(link: OpportunityLinkView): string | null {
  let year = link.planned_order_year?.trim();
  let month = link.planned_order_month?.trim();
  // 수집 원문에 따라 월이 `2026-09`처럼 연도를 품고 오기도 한다. 그 경우 그 연·월을 그대로 읽는다.
  const combined = /^(\d{4})-(\d{1,2})$/.exec(month ?? "");
  if (combined) {
    year = combined[1];
    month = combined[2];
  }
  if (!year && !month) return null;
  const monthNumber = month ? Number(month) : NaN;
  const monthText = Number.isFinite(monthNumber) && monthNumber > 0 ? `${monthNumber}월` : month ? `${month}월` : "";
  return `${year ? `${year}년 ` : ""}${monthText} 발주 예정`.trim();
}

function budgetLabel(value: number | null): string | null {
  return value === null ? null : `${Math.round(value).toLocaleString("ko-KR")}원`;
}

/** 권위 연결 한 줄: 발주계획은 발주 예정 · 예산, 공고는 제목 · 마감 · 금액. 값이 없으면 그 조각을 뺀다. */
function linkFacts(index: number, link: OpportunityLinkView): { main: string | null; sub: string | null } {
  const externalId = link.record_external_id || link.external_id || null;
  if (index === 0) {
    const main = [plannedLabel(link), budgetLabel(link.budget)].filter(Boolean).join(" · ") || null;
    return { main, sub: externalId ? `계획번호 ${externalId}` : null };
  }
  const deadline = formatKstDay(link.deadline_at);
  const main = link.title?.trim() || null;
  const sub = [deadline ? `${deadline} ${index === 1 ? "의견 마감" : "마감"}` : null, budgetLabel(link.budget), externalId].filter(Boolean).join(" · ") || null;
  return { main, sub };
}

const PENDING_NOTE: Record<number, string> = {
  1: "사전규격이 올라오면 이 흐름에 연결돼요.",
  2: "공고가 올라오면 사전규격과 달라진 점을 비교할 수 있어요.",
};

export function StageBar({ stages, links = [], candidates = [], goNoGo = null }: StageBarProps) {
  const byId = new Map(links.map((link) => [link.id, link] as const));
  return (
    <div className="rec-flow">
      <ol aria-label="사업 단계" className="rec-stagebar" data-testid="stage-bar">
        {stages.map((stage, index) => {
          const label = stageLabelAt(index, stage);
          const day = stage.state === "pending" || stage.state === "unknown" ? null : formatKstDay(stage.at);
          // 발주계획·사전규격·입찰공고 세 칸만 연결을 대표한다. 마감·개찰은 입찰공고 대표를 따르므로
          // 같은 화면을 두 번 걸지 않도록 앞 세 칸에서만 링크를 만든다.
          const link = index < 3 && stage.link_id !== null ? byId.get(stage.link_id) ?? null : null;
          const to = link ? recordRoute(link) : null;
          const stageCandidates = index < 3 && !link ? candidates.filter((candidate) => stageOfLink(candidate) === label) : [];
          const facts = link ? linkFacts(index, link) : null;
          const content = (
            <>
              {label}
              {stage.state === "unknown"
                ? <span className="rec-stage-unknown"> 미확인</span>
                : <span className="visually-hidden"> · {STAGE_STATE_LABEL[stage.state]}</span>}
            </>
          );
          return (
            <li className={`rec-stage${index >= 3 ? " is-minor" : ""}`} data-state={stage.state} data-stage={label} key={`${index}-${stage.key}`}>
              <span aria-hidden="true" className="rec-stage-rail">
                <span className="rec-stage-marker">
                  {stage.state === "done" ? <Check strokeWidth={3} /> : null}
                </span>
                <span className="rec-stage-line" />
              </span>
              <span className="rec-stage-body">
                <span className="rec-stage-head">
                  {to
                    ? <Link className="rec-stage-label rec-stage-link" title={`${label} 열기`} to={to}>{content}</Link>
                    : <span className="rec-stage-label">{content}</span>}
                  {link ? <span className="rec-stage-status">공식 연결</span> : null}
                  {stageCandidates.length > 0 ? <span className="bo-tag is-warning">후보 확인 대기</span> : null}
                  {index < 3 && !link && stageCandidates.length === 0 && stage.state === "pending"
                    ? <span className="rec-stage-status">아직 없음</span>
                    : null}
                  {day ? <span className="rec-stage-day">{day}</span> : null}
                </span>
                {facts?.main ? <span className="rec-stage-fact">{facts.main}</span> : null}
                {facts?.sub ? <span className="rec-stage-sub">{facts.sub}</span> : null}
                {stageCandidates.length > 0 ? (
                  <>
                    <span className="rec-stage-fact">
                      이름 검색으로 찾은 후보가 {stageCandidates.length}건 있어요.
                    </span>
                    <span className="rec-stage-sub">같은 사업으로 확인하면 이 흐름에 연결돼요.</span>
                  </>
                ) : null}
                {index < 3 && !link && stageCandidates.length === 0 && stage.state === "pending" && PENDING_NOTE[index]
                  ? <span className="rec-stage-sub">{PENDING_NOTE[index]}</span>
                  : null}
              </span>
            </li>
          );
        })}
      </ol>
      {goNoGo ? (
        <div className="rec-flow-final" data-testid="stage-flow-go-no-go">
          <span aria-hidden="true" className="rec-stage-rail">
            <span className="rec-stage-marker" />
          </span>
          <span className="rec-stage-body">
            <span className="rec-stage-head">
              <span className="rec-stage-label">{goNoGo.label}</span>
              <span className="rec-stage-status">{goNoGo.value}</span>
            </span>
            <span className="rec-stage-sub">입찰 참여는 사람이 따로 정해요. 추적을 시작해도 Go로 정해지지 않아요.</span>
          </span>
        </div>
      ) : null}
    </div>
  );
}
