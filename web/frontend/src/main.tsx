import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./styles/layers.css";
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "./themes/bidops/bidops.css";
import "./themes/bidops/grade-ramp.css";
import "./styles/theme.css";
import "./styles/typography.css";
import "./styles/shell-relaxed.css";
import "./styles/review-primitives.css";
import "./styles/workspace-filters.css";
import "./styles/run-screening.css";
import "./styles/quality-policy.css";
import "./styles/operations.css";
import App from "./App";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
