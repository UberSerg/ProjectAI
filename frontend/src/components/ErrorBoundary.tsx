import { Component, type ErrorInfo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { reportClientError } from "../api/system";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: "" };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message || "Неизвестная ошибка интерфейса" };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    void reportClientError({
      level: "ERROR",
      component: "frontend",
      event_type: "react_error_boundary",
      message: error.message,
      route: typeof window !== "undefined" ? window.location.pathname : undefined,
      stack: `${error.stack ?? ""}\n${info.componentStack ?? ""}`.slice(0, 4000),
    });
  }

  private retry = () => {
    this.setState({ hasError: false, message: "" });
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <section className="panel error-boundary" role="alert">
        <h1>Не удалось открыть раздел</h1>
        <p>Произошла ошибка интерфейса. Событие записано в технологический журнал.</p>
        <p className="muted">{this.state.message}</p>
        <div className="page-actions">
          <button type="button" onClick={this.retry}>
            Повторить
          </button>
          <Link className="button secondary" to="/">
            На главную
          </Link>
        </div>
      </section>
    );
  }
}
