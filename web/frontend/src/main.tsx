import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "./themes/neutral/neutral.css";
import App from "./App";
import "./styles/theme.css";
import "./styles/run-screening.css";
import "./styles/quality-policy.css";
import "./styles/operations.css";

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
