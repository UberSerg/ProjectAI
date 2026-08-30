import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { reportClientError } from "./api/system";
import "./styles.css";

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
        <App />
      </ErrorBoundary>
    </BrowserRouter>
  </React.StrictMode>,
);
