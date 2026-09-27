import type { ShadowCatchUpStatus } from "../../api/shadow";

function statusLabel(code: string | undefined): string {
  switch (code) {
    case "CATCH_UP_NO_OP":
      return "Актуально";
    case "CATCH_UP_SUCCESS":
      return "Восстановление завершено";
    case "CATCH_UP_PARTIAL":
      return "Есть отставание";
    case "CATCH_UP_BLOCKED":
      return "Ожидает данные";
    default:
      return code ?? "—";
  }
}

export function CatchUpStatusCard({
  catchUp,
  onRun,
  running,
}: {
  catchUp: ShadowCatchUpStatus | null | undefined;
  onRun?: () => void;
  running?: boolean;
}) {
  if (!catchUp) {
    return (
      <div className="panel catchup-card" data-testid="shadow-catchup-card">
        <h2 className="sim-section-title">Восстановление Shadow</h2>
        <p className="muted">Статус catch-up ещё не загружен.</p>
      </div>
    );
  }

  const primary = catchUp.portfolios?.[0];

  return (
    <div className="panel catchup-card" data-testid="shadow-catchup-card">
      <div className="catchup-card-head">
        <h2 className="sim-section-title">Восстановление после простоя</h2>
        <span className="sim-meta-chip" data-testid="shadow-catchup-status">
          {statusLabel(catchUp.catch_up_status)}
        </span>
      </div>
      <p className="muted">
        Пропущенные торговые сессии обрабатываются по порядку на том же production-пути, что и
        ежедневный Shadow.
      </p>
      <div className="catchup-grid">
        <div>
          <span className="muted">Последняя обработанная</span>
          <strong data-testid="shadow-catchup-last">
            {primary?.last_processed_session ?? catchUp.last_successful_replay_hint ?? "—"}
          </strong>
        </div>
        <div>
          <span className="muted">Актуальная рыночная</span>
          <strong data-testid="shadow-catchup-latest">
            {catchUp.latest_completed_market_session ?? "—"}
          </strong>
        </div>
        <div>
          <span className="muted">Backlog</span>
          <strong data-testid="shadow-catchup-backlog">
            {catchUp.backlog_session_count ?? 0}
          </strong>
        </div>
        <div>
          <span className="muted">Блокер</span>
          <strong data-testid="shadow-catchup-block">
            {catchUp.blocking_reason
              ? `${catchUp.blocking_reason}${
                  catchUp.blocking_session ? ` @ ${catchUp.blocking_session}` : ""
                }`
              : "нет"}
          </strong>
        </div>
      </div>
      {onRun ? (
        <div className="cockpit-footer-links" style={{ marginTop: "0.75rem" }}>
          <button
            type="button"
            className="button secondary"
            data-testid="shadow-catchup-run"
            disabled={running}
            onClick={onRun}
          >
            {running ? "Восстановление…" : "Запустить catch-up"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
