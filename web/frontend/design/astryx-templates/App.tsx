import { useEffect, useMemo, useState } from "react";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { AnalysisPage } from "./analysis";
import { DEFAULT_PREFS, ModeContext, VariantContext, type Mode, type ModeState, type Variant, type ViewPrefs } from "./kit";
import { PAGES } from "./pages";
import { Shell } from "./templates";

/** 2026-11-23 사용자가 전체 배치를 시안 1(표 작업대)로 정했다. 아래 넷은 그 위에서 보기 편하게 만드는 방안이다. */
const MODES: { id: Mode; label: string }[] = [
  { id: "base", label: "시안 1 기준" },
  { id: "x", label: "1-A 크게 보기" },
  { id: "y", label: "1-B 훑기 길잡이" },
  { id: "z", label: "1-C 내 화면 맞춤" },
];
/** 앞선 비교안(유지안·시안 2·3)은 주소의 v 값으로만 열 수 있다. 기본은 정해진 시안 1(a)이다. */
const LEGACY_VARIANTS: Variant[] = ["k", "a", "b", "c"];

function readLocation(): { variant: Variant; mode: Mode; page: string } {
  const params = new URLSearchParams(window.location.search);
  const variant = LEGACY_VARIANTS.find((item) => item === params.get("v")) ?? "a";
  const mode = MODES.find((item) => item.id === params.get("m"))?.id ?? "base";
  const page = params.get("page") ?? "analysis";
  return { variant, mode: variant === "a" ? mode : "base", page: page === "analysis" || PAGES.some((item) => item.id === page) ? page : "analysis" };
}

export function App() {
  const [{ variant, mode, page }, setState] = useState(readLocation);
  const [prefs, setPrefsState] = useState<ViewPrefs>(DEFAULT_PREFS);
  useEffect(() => {
    const params = new URLSearchParams({ m: mode, page });
    if (variant !== "a") params.set("v", variant);
    window.history.replaceState(null, "", `?${params.toString()}`);
  }, [variant, mode, page]);
  const go = (next: string) => setState((prev) => ({ ...prev, page: next }));
  const current = PAGES.find((item) => item.id === page);
  const modeState = useMemo<ModeState>(() => ({ mode, prefs, setPrefs: (patch) => setPrefsState((prev) => ({ ...prev, ...patch })) }), [mode, prefs]);
  const largeText = mode === "x" || (mode === "z" && prefs.text === "large");

  return (
    <VariantContext.Provider value={variant}>
      <ModeContext.Provider value={modeState}>
        <div className="mk-frame" data-v={variant} data-m={mode} data-text={largeText ? "large" : "normal"}>
          <div className="mk-mockbar" role="toolbar" aria-label="시안 도구">
            <Text type="label" weight="semibold">Astryx 적용 시안</Text>
            {variant === "a" ? (
              <SegmentedControl label="보기 방안" value={mode} onChange={(next) => setState((prev) => ({ ...prev, mode: next as Mode }))} size="sm">
                {MODES.map((item) => <SegmentedControlItem key={item.id} value={item.id} label={item.label} />)}
              </SegmentedControl>
            ) : <Text type="supporting" color="secondary">앞선 비교안({variant}) · 정해진 안은 시안 1</Text>}
            <div className="mk-mockbar-page">
              <Selector label="화면" isLabelHidden size="sm" value={page} onChange={(next) => go(String(next))}
                options={[{ value: "analysis", label: "분석·제안" }, ...PAGES.map((item) => ({ value: item.id, label: `${item.title} · ${item.template}` }))]} />
            </div>
            <Text type="supporting" color="secondary">예시 데이터 · 저장되지 않아요</Text>
          </div>
          {current ? (
            <Shell key={`${variant}-${current.id}`} navPage={current.navPage} title={current.title} crumbs={current.crumbs} actions={current.actions}
              listPage={current.template.startsWith("P1")} onNavigate={go}>
              {current.render()}
            </Shell>
          ) : <AnalysisPage />}
        </div>
      </ModeContext.Provider>
    </VariantContext.Provider>
  );
}
