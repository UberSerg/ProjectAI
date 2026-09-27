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
    case "MARKET_STALE":
      return "Market отстаёт";
    case "MARKET_CURRENT":
      return "Market актуален";
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
  const market = catchUp.market_data;
  const shadow = catchUp.shadow;
  const marketCurrent = market?.market_current !== false;

  return (
    <div className="panel catchup-card" data-testid="shadow-catchup-card">
      <div className="catchup-card-head">
        <h2 className="sim-section-title">Восстановление после простоя</h2>
        <span className="sim-meta-chip" data-testid="shadow-catchup-status">
          {statusLabel(catchUp.catch_up_status)}
        </span>
      </div>
      <p className="muted">
        Сначала догоняется EOD market data по торговым сессиям, затем Shadow replay день за днём
        (PIT as-of).
      </p>

      <div className="catchup-section" data-testid="catchup-market-section">
        <h3 className="catchup-section-title">Market data</h3>
        <div className="catchup-grid catchup-grid-3">
          <div>
            <span className="muted">Local EOD</span>
            <strong data-testid="market-local-eod">
              {market?.latest_local_eod_session ?? catchUp.latest_completed_market_session ?? "—"}
            </strong>
          </div>
          <div>
            <span className="muted">Expected completed</span>
            <strong data-testid="market-expected-eod">
              {market?.latest_expected_completed_session ?? "—"}
            </strong>
          </div>
          <div>
            <span className="muted">Missing sessions</span>
            <strong data-testid="market-missing-count">
              {market?.missing_market_sessions_count ?? 0}
            </strong>
          </div>
        </div>
        <p className="catchup-market-flag" data-testid="market-current-flag">
          Market current?{" "}
          <strong className={marketCurrent ? "ok" : "warn"}>{marketCurrent ? "YES" : "NO"}</strong>
          {market?.market_backfill_status ? (
            <span className="muted"> · {statusLabel(market.market_backfill_status)}</span>
          ) : null}
        </p>
      </div>

      <div className="catchup-section" data-testid="catchup-shadow-section">
        <h3 className="catchup-section-title">Shadow</h3>
        <div className="catchup-grid">
          <div>
            <span className="muted">Последняя обработанная</span>
            <strong data-testid="shadow-catchup-last">
              {shadow?.last_processed_session ??
                primary?.last_processed_session ??
                catchUp.last_successful_replay_hint ??
                "—"}
            </strong>
          </div>
          <div>
            <span className="muted">Актуальная рыночная</span>
            <strong data-testid="shadow-catchup-latest">
              {catchUp.latest_completed_market_session ?? "—"}
            </strong>
          </div>
          <div>
            <span className="muted">Replay backlog</span>
            <strong data-testid="shadow-catchup-backlog">
              {shadow?.replay_backlog ?? catchUp.backlog_session_count ?? 0}
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
            {running ? "Восстановление…" : "Запустить recovery"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
