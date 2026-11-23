/*
 * 화면 틀 P2(읽기 상세)·P3(최종 결정)·P5(오늘 할 일).
 * 사전규격 상세·사업기회 레코드·입찰공고 상세가 RecordView 하나를, 입찰 참여 결정이 DecisionView를 쓴다.
 */
import { useRef, useState, type ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { List, ListItem } from "@astryxdesign/core/List";
import { Outline } from "@astryxdesign/core/Outline";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Heading, Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import {
  DeadlineText, DecisionBar, Facts, FillBlock, Flow, KeyFigures, SectionBlock, StatusMark, Tag, useMode, useVariant,
  type Deadline, type Decision, type Fact, type FlowStep, type Mark, type SectionModel,
} from "./kit";

/* ── P2 읽기 상세 ──────────────────────────────────────────────────────── */

export interface RecordCfg {
  /** 운영 화면의 현재 배치. 유지안은 이 값을 그대로 따른다. */
  current: "single" | "rail";
  eyebrow: string; title: string; marks: Mark[]; tags?: string[]; summary?: string;
  facts: Fact[]; idLine?: string;
  tabs?: { items: string[]; active: string };
  flow?: { steps: FlowStep[]; active: number; current?: boolean };
  sections: SectionModel[];
  rail?: SectionModel[];
  railFacts?: Fact[];
  decision?: Decision;
  /** 운영 화면에 하단 결정 띠가 이미 있는가. 유지안은 없는 띠를 새로 만들지 않는다. */
  decisionCurrent?: boolean;
}

function RecordHead({ cfg }: { cfg: RecordCfg }) {
  return (
    <div className="mk-record-head">
      <div className="mk-record-eyebrow">
        <Text type="supporting" color="secondary">{cfg.eyebrow}</Text>
        {cfg.marks.map((mark) => <StatusMark key={mark.label} mark={mark} />)}
        {cfg.tags?.map((tag) => <Tag key={tag} label={tag} />)}
      </div>
      <Heading level={2}>{cfg.title}</Heading>
      {cfg.summary ? <Text type="body" color="secondary" display="block">{cfg.summary}</Text> : null}
    </div>
  );
}

export function RecordView({ cfg }: { cfg: RecordCfg }) {
  const variant = useVariant();
  const { mode } = useMode();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [tab, setTab] = useState(cfg.tabs?.active ?? "");
  const layout: "single" | "rail" | "outline" = variant === "k" ? cfg.current : variant === "a" ? "rail" : variant === "c" ? "outline" : "single";
  const flowSection: SectionModel | null = cfg.flow && (cfg.flow.current || variant !== "k")
    ? { id: "flow", title: "사업 흐름", body: <Flow steps={cfg.flow.steps} active={cfg.flow.active} vertical /> }
    : null;
  const railSections = cfg.rail ?? [];
  const mainSections = layout === "rail"
    ? [...(flowSection ? [flowSection] : []), ...cfg.sections]
    : [...(flowSection && variant !== "b" ? [flowSection] : []), ...cfg.sections, ...railSections];
  const outlineItems = mainSections.map((section) => ({ id: section.id, label: section.title, level: 1 as const }));

  return (
    <>
      {cfg.tabs ? (
        <div className="mk-viewbar">
          <TabList value={tab} onChange={setTab} size="md">
            {cfg.tabs.items.map((item) => <Tab key={item} value={item} label={item} />)}
          </TabList>
        </div>
      ) : null}
      <div className="mk-record" data-layout={layout} ref={scrollRef}>
        <div className="mk-record-inner">
          {layout === "outline" ? (
            <aside className="mk-record-outline">
              <Outline items={outlineItems} label="이 화면의 구역" density="compact" scrollContainerRef={scrollRef} />
            </aside>
          ) : null}
          <div className="mk-record-main">
            <RecordHead cfg={cfg} />
            {layout === "rail" ? (mode === "y" ? <KeyFigures facts={cfg.facts.filter((fact) => fact.strong)} /> : null) : <Facts facts={cfg.facts} columns={4} />}
            {cfg.idLine ? <Text type="supporting" color="secondary" display="block">{cfg.idLine}</Text> : null}
            {variant === "b" && cfg.flow ? <div className="mk-record-flow"><Flow steps={cfg.flow.steps} active={cfg.flow.active} /></div> : null}
            {mainSections.map((section) => <SectionBlock key={section.id} section={section} />)}
          </div>
          {layout === "rail" ? (
            <aside className="mk-record-rail">
              <SectionBlock section={{ id: "rail-facts", title: "사업 정보", body: <Facts facts={[...cfg.facts, ...(cfg.railFacts ?? [])]} side /> }} />
              {railSections.map((section) => <SectionBlock key={section.id} section={section} />)}
            </aside>
          ) : null}
        </div>
      </div>
      {cfg.decision && (cfg.decisionCurrent || variant !== "k") ? <DecisionBar decision={cfg.decision} readingWidth={layout === "outline" ? "outline" : true} /> : null}
    </>
  );
}

/* ── P3 최종 결정 ──────────────────────────────────────────────────────── */

export interface DecisionCfg {
  context: string;
  evidence: SectionModel[];
  basis: string;
  checks: FlowStep[];
  activeCheck: number;
  freshness: Mark;
  decision: Decision;
}

function DecisionForm({ cfg }: { cfg: DecisionCfg }) {
  const variant = useVariant();
  const [choice, setChoice] = useState("");
  const [reason, setReason] = useState("");
  const [actor, setActor] = useState("");
  return (
    <div className="mk-form">
      <FillBlock title="결정 근거 · 공고 조건 기준">{cfg.basis}</FillBlock>
      {variant === "k" || variant === "c" ? (
        <div className="mk-inline-marks">
          {cfg.checks.map((check, index) => (
            <StatusMark key={check.label} mark={{ label: index < cfg.activeCheck ? `${check.label} · 확인됨` : `${check.label} · 필요`, tone: index < cfg.activeCheck ? "success" : "neutral" }} />
          ))}
        </div>
      ) : null}
      <RadioList label="최종 결정" value={choice} onChange={setChoice} orientation="horizontal">
        <RadioListItem label="참여(Go)" value="go" />
        <RadioListItem label="불참(No-Go)" value="no-go" />
      </RadioList>
      <TextArea label="결정 이유" value={reason} onChange={setReason} placeholder="공고 조건과 차수 간 변경을 검토한 판단 근거" rows={4} width="100%" />
      {variant === "k" ? (
        <TextInput label="최종 결정 담당자 이름" value={actor} onChange={setActor} placeholder="예: 홍길동" width="100%"
          description="감사 귀속용 이름이며 로그인·신원 인증·권한 부여가 아니에요." />
      ) : null}
      <Text type="supporting" color="secondary" display="block">
        이 결정은 최신 입찰공고와 그 관측 해시에 연결돼요. 이전 결정은 고치지 않고 새 기록으로 남겨요.
      </Text>
      <div className="mk-form-fresh">
        <Text type="label" weight="semibold">최종 결정 최신 여부</Text>
        <StatusMark mark={cfg.freshness} />
      </div>
    </div>
  );
}

export function DecisionView({ cfg }: { cfg: DecisionCfg }) {
  const variant = useVariant();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const outlineItems = cfg.evidence.map((section) => ({ id: section.id, label: section.title, level: 1 as const }));
  const checklist = (
    <SectionBlock section={{ id: "checks", title: "저장 전 확인", body: <Flow steps={cfg.checks} active={cfg.activeCheck} vertical /> }} />
  );
  if (variant === "b") {
    return (
      <>
        <div className="mk-context">{cfg.context}</div>
        <div className="mk-record" data-layout="single">
          <div className="mk-record-inner">
            <div className="mk-record-main">
              <div className="mk-record-flow"><Flow steps={cfg.checks} active={cfg.activeCheck} /></div>
              {cfg.evidence.map((section) => <SectionBlock key={section.id} section={section} />)}
              <SectionBlock section={{ id: "final", title: "사람의 최종 결정", aside: "추가만 기록", body: <DecisionForm cfg={cfg} /> }} />
            </div>
          </div>
        </div>
        <DecisionBar decision={cfg.decision} readingWidth />
      </>
    );
  }
  return (
    <>
      <div className="mk-context">{cfg.context}</div>
      <div className="mk-decide" data-outline={variant === "c" ? "true" : "false"}>
        {variant === "c" ? (
          <aside className="mk-record-outline"><Outline items={outlineItems} label="결정 근거 구역" density="compact" scrollContainerRef={scrollRef} /></aside>
        ) : null}
        <div className="mk-decide-evidence" ref={scrollRef}>
          <div className="mk-pane-head"><span className="mk-pane-title">결정 근거 검토</span><Text type="supporting" color="secondary">공고 조건 기준</Text></div>
          <div className="mk-decide-body">{cfg.evidence.map((section) => <SectionBlock key={section.id} section={section} />)}</div>
        </div>
        <div className="mk-decide-final">
          <div className="mk-pane-head"><span className="mk-pane-title">사람의 최종 결정</span><Text type="supporting" color="secondary">추가만 기록</Text></div>
          <div className="mk-decide-body">
            {variant === "a" ? checklist : null}
            <DecisionForm cfg={cfg} />
          </div>
          <DecisionBar decision={cfg.decision} />
        </div>
      </div>
    </>
  );
}

/* ── P5 오늘 할 일 ─────────────────────────────────────────────────────── */

export interface WorkItem extends Record<string, unknown> { id: string; title: string; meta: string; deadline: Deadline; kind: string }
export interface StageRow extends Record<string, unknown> { stage: string; waiting: string; due: string; tracked: string; next: string }
export interface OverviewCfg {
  kpis: { label: string; value: string; note: string }[];
  collection: { name: string; mark: Mark; line: string }[];
  queues: { title: string; link: string; foot: string; items: WorkItem[] }[];
  checks: { label: string; value: string; note: string }[];
  stages: StageRow[];
}

function KpiRow({ kpis }: { kpis: OverviewCfg["kpis"] }) {
  return (
    <div className="mk-kpis">
      {kpis.map((kpi) => (
        <button type="button" className="mk-kpi" key={kpi.label}>
          <Text type="supporting" color="secondary" display="block">{kpi.label}</Text>
          <span className="mk-kpi-value">{kpi.value}</span>
          <Text type="supporting" color="secondary" display="block">{kpi.note}</Text>
        </button>
      ))}
    </div>
  );
}

function CollectionBlock({ collection }: { collection: OverviewCfg["collection"] }) {
  return (
    <div className="mk-collection">
      {collection.map((item) => (
        <div className="mk-collection-row" key={item.name}>
          <StatusMark mark={item.mark} />
          <Text type="label" weight="semibold">{item.name}</Text>
          <Text type="supporting" color="secondary">{item.line}</Text>
        </div>
      ))}
    </div>
  );
}

function QueueList({ items }: { items: WorkItem[] }) {
  return (
    <List density="compact" hasDividers>
      {items.map((item) => (
        <ListItem key={item.id} label={item.title} description={item.meta} onClick={() => undefined} endContent={<DeadlineText deadline={item.deadline} />} />
      ))}
    </List>
  );
}

function ChecksBlock({ checks, side }: { checks: OverviewCfg["checks"]; side: boolean }) {
  return <Facts side={side} columns={5} facts={checks.map((check) => ({ label: check.label, value: <>{check.value} <span className="mk-dim">{check.note}</span></>, strong: true }))} />;
}

export function OverviewView({ cfg }: { cfg: OverviewCfg }) {
  const variant = useVariant();
  const { mode, prefs } = useMode();
  const density = mode === "x" ? "balanced" : mode === "z" ? prefs.density : "compact";
  const more = (label: string): ReactNode => <a className="mk-link" href="#">{label}<ArrowRight aria-hidden="true" /></a>;
  const queueSections = cfg.queues.map((queue) => (
    <SectionBlock key={queue.title} section={{ id: queue.title, title: queue.title, aside: more(queue.link), body: <><QueueList items={queue.items} /><Text type="supporting" color="secondary" display="block">{queue.foot}</Text></> }} />
  ));
  const collection = <SectionBlock section={{ id: "collection", title: "일일 수집", aside: more("회차 기록"), body: <CollectionBlock collection={cfg.collection} /> }} />;

  if (variant === "a") {
    const stageColumns: TableColumn<StageRow>[] = [
      { key: "stage", header: "단계", width: proportional(1.2) },
      { key: "waiting", header: "결정 대기", width: pixel(110), align: "end" },
      { key: "due", header: "7일 안 마감", width: pixel(110), align: "end" },
      { key: "tracked", header: "추적 중", width: pixel(96), align: "end" },
      { key: "next", header: "다음 행동", width: proportional(2) },
    ];
    const allItems = cfg.queues.flatMap((queue) => queue.items);
    const itemColumns: TableColumn<WorkItem>[] = [
      { key: "title", header: "사업명", width: proportional(3) },
      { key: "kind", header: "결정 종류", width: pixel(130) },
      { key: "meta", header: "기관·상태", width: proportional(2) },
      { key: "deadline", header: "마감", width: pixel(100), align: "end", renderCell: (row) => <DeadlineText deadline={row.deadline} /> },
    ];
    return (
      <div className="mk-overview" data-layout="table">
        <KpiRow kpis={cfg.kpis} />
        <SectionBlock section={{ id: "stages", title: "단계별 업무량", body: <div className="mk-table"><Table data={cfg.stages} columns={stageColumns} idKey="stage" density={density} hasHover isStriped={mode === "y"} /></div> }} />
        <SectionBlock section={{ id: "today", title: "오늘 결정할 것", aside: `${allItems.length}건 · 마감순`, body: <div className="mk-table"><Table data={allItems} columns={itemColumns} idKey="id" density={density} hasHover isStriped={mode === "y"} /></div> }} />
        {collection}
      </div>
    );
  }
  if (variant === "b" || variant === "c") {
    return (
      <div className="mk-overview" data-layout="rail">
        <div className="mk-overview-main">
          {variant === "c" ? <KpiRow kpis={cfg.kpis} /> : null}
          {queueSections}
        </div>
        <aside className="mk-overview-rail">
          {collection}
          {variant === "b" ? <SectionBlock section={{ id: "load", title: "업무량", body: <Facts side facts={cfg.kpis.map((kpi) => ({ label: kpi.label, value: kpi.value, strong: true }))} /> }} /> : null}
          <SectionBlock section={{ id: "checks", title: "확인할 것", body: <ChecksBlock checks={cfg.checks} side /> }} />
        </aside>
      </div>
    );
  }
  return (
    <div className="mk-overview" data-layout="current">
      <SectionBlock section={{ id: "work", title: "오늘 검토할 업무", body: <KpiRow kpis={cfg.kpis} /> }} />
      <FillBlock><CollectionBlock collection={cfg.collection} /></FillBlock>
      <div className="mk-overview-two">{queueSections}</div>
      <SectionBlock section={{ id: "checks", title: "확인할 것", body: <FillBlock><ChecksBlock checks={cfg.checks} side={false} /></FillBlock> }} />
    </div>
  );
}

export function PrimaryLink({ label }: { label: string }) {
  return <Button label={label} variant="secondary" size="sm" />;
}
