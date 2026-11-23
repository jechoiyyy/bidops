import { OpeningComparison } from "./OpeningComparison";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { BottomSheet, BottomSheetSwitcher } from "@astryxdesign/core/BottomSheet";
import { ArrowLeft, ArrowUpRight, Check, ChevronRight, ListFilter, Search, X } from "lucide-react";
import "../../src/styles/layers.css";
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "../../src/themes/bidops/bidops.css";
import "./preview.css";

const layouts = [
  { id: "grid", title: "한눈에 보기", description: "조회 범위, 개요, 추적 조건을 세 열에 펼쳐 한 번에 조정해요." },
  { id: "sections", title: "분류별 설정", description: "왼쪽에서 분류를 선택하고 오른쪽에서 해당 조건을 조정해요." },
  { id: "search", title: "조건 찾아가기", description: "조건 이름이나 값으로 검색한 뒤 한 조건씩 열어서 선택해요." },
] as const;

const groups = [
  { title: "조회 범위", fields: [
    { name: "업무구분", options: ["전체", "일반용역", "기술용역"] },
    { name: "발견 구분", options: ["전체", "독립 발견", "발주계획 연결"] },
  ] },
  { title: "개요 검토", fields: [
    { name: "개요 상태", options: ["전체", "미시작", "개요 완료", "사람 확인 필요", "실패"] },
    { name: "자동 준비 상태", options: ["전체", "진행 중", "완료", "실패"] },
  ] },
  { title: "추적·정렬", fields: [
    { name: "추적 상태", options: ["전체", "미선택", "계속 추적", "보류", "종료"] },
    { name: "표시 순서", options: ["마감 임박순", "최근 게시순"] },
  ] },
];
const fields = groups.flatMap(group => group.fields);
const defaults = Object.fromEntries(fields.map(field => [field.name, field.options[0]]));
const initial = { ...defaults, "업무구분": "일반용역", "개요 상태": "개요 완료" };
const requested = new URLSearchParams(location.search).get("variant");

function Preview() {
  const [layout, setLayout] = useState(layouts.find(item => item.id === requested) ?? layouts[0]);
  const [active, setActive] = useState<string | null>(layouts.some(item => item.id === requested) ? "filters" : null);
  const [values, setValues] = useState(initial as Record<string, string>);
  const [group, setGroup] = useState(0);
  const [query, setQuery] = useState("");
  const [field, setField] = useState(fields[0]);
  const changed = Object.keys(values).filter(key => values[key] !== defaults[key]);
  const select = (name: string, value: string) => setValues(previous => ({ ...previous, [name]: value }));
  const close = () => setActive(null);
  const control = (item: typeof field) => (
    <label className="field" key={item.name}>{item.name}
      <select value={values[item.name]} onChange={event => select(item.name, event.target.value)}>
        {item.options.map(option => <option key={option}>{option}</option>)}
      </select>
    </label>
  );
  const grid = <div className="grid">{groups.map(item => <section key={item.title}><h3>{item.title}</h3>{item.fields.map(control)}</section>)}</div>;
  const opening = new URLSearchParams(location.search).get("opening");
  if (opening) return <OpeningComparison initialMode={opening} grid={grid} values={values} count={changed.length} reset={() => setValues({...defaults})} />;
  const visible = fields.filter(item => [item.name, ...item.options].some(text => text.includes(query.trim())));
  return (
    <>
      <main className="gallery">
        <header><p>BidOps / 디자인 검토</p><h1>상세 필터 시안</h1>
          <p>사전규격의 예시 조건 6개로 배치와 조작을 비교해 보세요. 선택값은 이 미리보기에서만 사용해요.</p></header>
        <p><a href="?opening=inline">선택한 A안의 열기 방식 비교 →</a></p>
        <div className="cards">{layouts.map((item, index) => (
          <button key={item.id} className="card" onClick={() => {
            setLayout(item); setQuery(""); setGroup(0); setActive("filters");
          }}>
            <img alt="" src={`./${item.id}.png`} />
            <div><small>시안 {String.fromCharCode(65 + index)}</small><h2>{item.title}<ArrowUpRight size={22} /></h2><p>{item.description}</p></div>
          </button>
        ))}</div>
      </main>
      <BottomSheetSwitcher activeSheet={active} onActiveSheetChange={setActive}>
        <BottomSheet height="hug" sheetId="filters" label="상세 필터" className="preview-sheet">
          <div className="surface">
            <header className="sheet-head"><div><small>사전규격 · {layout.title}</small><h2><ListFilter size={23}/>상세 필터</h2></div>
              <button className="icon" aria-label="닫기" onClick={close}><X/></button></header>
            {layout.id === "grid" && grid}
            {layout.id === "sections" && <div className="split"><nav aria-label="조건 분류">{groups.map((item, i) =>
              <button key={item.title} aria-pressed={i === group} onClick={() => setGroup(i)}>{item.title}<ChevronRight size={16}/></button>)}</nav>
              <section><h3>{groups[group].title}</h3>{groups[group].fields.map(control)}</section>
              <aside><h3>선택한 조건</h3>{changed.length ? changed.map(key => <p key={key}>{key}<strong>{values[key]}</strong></p>) : <p>기본값</p>}</aside></div>}
            {layout.id === "search" && <section className="find"><label><Search size={18}/><input aria-label="조건 검색" placeholder="조건 이름 또는 값 검색" value={query} onChange={e => setQuery(e.target.value)} /></label>
              <div>{visible.map(item => <button key={item.name} onClick={() => { setField(item); setActive("options"); }}>
                {item.name}<span>{values[item.name]}</span><ChevronRight size={16}/></button>)}</div>{!visible.length && <p>일치하는 조건이 없어요.</p>}</section>}
            <footer><button className="reset" onClick={() => setValues({...defaults})}>기본값으로</button>
              <span>변경 조건 {changed.length}개</span><button className="primary" onClick={close}>완료</button></footer>
          </div>
        </BottomSheet>
        <BottomSheet height="hug" sheetId="options" label={field.name} className="preview-sheet">
          <div className="surface"><header className="sheet-head"><div><button className="back" onClick={() => setActive("filters")}><ArrowLeft size={16}/> 조건 목록</button><h2>{field.name}</h2></div>
            <button className="icon" aria-label="닫기" onClick={close}><X/></button></header>
            <div className="options">{field.options.map(option => <button key={option} aria-pressed={values[field.name] === option} onClick={() => { select(field.name, option); setActive("filters"); }}>{option}{values[field.name] === option && <Check size={18}/>}</button>)}</div>
          </div>
        </BottomSheet>
      </BottomSheetSwitcher>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<Preview/>);
