import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { reportClientError } from "./api/system";
import { PortfolioProvider } from "./portfolio/PortfolioContext";
import { KrakenRoleProvider } from "./role/KrakenRoleContext";
import { initKrakenTheme } from "./theme/useKrakenTheme";
import "./styles.css";
import "./design-system.css";
import "./styles/kraken-dark.css";

// Re-applied here so the stored theme also wins when index.html runs without JS-inline init.
initKrakenTheme();

function installGlobalErrorHandlers() {
  window.addEventListener("error", (event) => {
    void reportClientError({
      event_type: "window_error",
      message: event.message || "window error",
      route: window.location.pathname,
      stack: event.error instanceof Error ? event.error.stack : undefined,
    });
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    const message = reason instanceof Error ? reason.message : String(reason ?? "unhandledrejection");
    const stack = reason instanceof Error ? reason.stack : undefined;
    void reportClientError({
      event_type: "unhandled_rejection",
      message,
      route: window.location.pathname,
      stack,
    });
  });
}

installGlobalErrorHandlers();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ErrorBoundary>
        <KrakenRoleProvider>
          <PortfolioProvider>
            <App />
          </PortfolioProvider>
        </KrakenRoleProvider>
      </ErrorBoundary>
    </BrowserRouter>
  </React.StrictMode>,
);
