import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../../src/styles/layers.css";
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "../../src/themes/bidops/bidops.css";
import "../../src/themes/bidops/brand.css";
import "../../src/styles/typography.css";
import "./mock.css";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}>
      <App />
    </InternationalizationProvider>
  </StrictMode>,
);
