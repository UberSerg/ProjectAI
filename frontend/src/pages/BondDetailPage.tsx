import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  getBondAccountingPreview,
  getBondDetail,
  type AccountingPreview,
  type BondDetail,
} from "../api/investment";
import { MetricCard, PageHeader, PageState, StatusBadge } from "../components/Ui";
import { MetricHelp } from "../help";

function fmtMoney(value: number | string | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  return `${n.toFixed(2)} ₽`;
}

export function BondDetailPage() {
  const { secid } = useParams<{ secid: string }>();
  const [bond, setBond] = useState<BondDetail | null>(null);
  const [accounting, setAccounting] = useState<AccountingPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!secid) {
      setLoading(false);
      setError("Не указан SECID облигации");
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getBondDetail(secid, controller.signal)
      .then((detail) => {
        setBond(detail);
        if (detail.support_status === "SUPPORTED") {
          return getBondAccountingPreview(detail.symbol, 1, controller.signal)
            .then(setAccounting)
            .catch((reason: unknown) => {
              if (!(reason instanceof DOMException && reason.name === "AbortError")) {
                // Keep bond detail even if accounting preview fails.
                setAccounting(null);
              }
            });
        }
        setAccounting(null);
        return undefined;
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
          setBond(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [secid]);

  if (loading) return <PageState kind="loading" title="Загрузка облигации…" />;
  if (!bond) {
    return (
      <PageState kind="error" title="Облигация не найдена">
        {error ?? "Нет данных по указанному SECID"}
        <p>
          <Link to="/bonds">← К списку облигаций</Link>
        </p>
      </PageState>
    );
  }

  const cashflows = bond.cashflows ?? [];

  return (
    <section className="bond-detail-page" data-testid="bond-detail-page">
      <nav className="breadcrumb" aria-label="Хлебные крошки">
        <Link to="/bonds">Облигации</Link>
        <span aria-hidden> / </span>
        <span>{bond.symbol}</span>
      </nav>

      <PageHeader
        title={`${bond.symbol} — ${bond.name}`}
        description="Карточка бумаги: подходит ли она, какие деньги и риски видны Kraken сейчас."
        helpPageId="bond_detail"
        actions={
          <Link to="/bonds" className="secondary button-link">
            ← К списку облигаций
          </Link>
        }
      />
      {error ? <div className="banner banner-warning">{error}</div> : null}

      <div className="card">
        <h2>Основное</h2>
        <div className="metric-grid">
          <MetricCard label="Тип" value={bond.bond_type} />
          <MetricCard label="Валюта" value={bond.currency_display ?? bond.currency ?? "—"} />
          <MetricCard label="Номинал" value={bond.nominal ?? "—"} />
          <MetricCard label="Лот" value={bond.lot_size ?? "—"} />
          <MetricCard label="Погашение" value={bond.maturity_date ?? "—"} />
          <MetricCard
            label="Поддержка"
            value={<StatusBadge status={bond.support_status.toLowerCase()} />}
            helpId="bond_supported"
          />
          <MetricCard
            label="Eligibility"
            value={bond.investment_eligibility ?? "RESEARCH_ONLY"}
            helpId="investment_eligibility"
          />
        </div>
      </div>

      <div className="card">
        <h2>Деньги</h2>
        <div className="metric-grid">
          <MetricCard label="Цена %" value={bond.clean_price_percent ?? "—"} helpId="dirty_price" />
          <MetricCard label="НКД" value={bond.nkd ?? "—"} helpId="nkd" />
          <MetricCard label="Покупка (оценка)" value={fmtMoney(bond.dirty_estimate)} helpId="dirty_price" />
          <MetricCard label="YTM" value={bond.ytm ?? "—"} hint={bond.ytm_note ?? undefined} helpId="bond_ytm" />
          <MetricCard label="Duration" value={bond.duration ?? "—"} />
          <MetricCard label="Ближ. купон" value={bond.next_coupon_date ?? "—"} helpId="bond_coupon_schedule" />
          <MetricCard label="Купон, ₽" value={bond.next_coupon_amount ?? "—"} />
        </div>
        {accounting?.status === "READY" ? (
          <div className="metric-grid">
            <MetricCard label="Чистая сумма (1 лот)" value={fmtMoney(accounting.clean_total)} />
            <MetricCard label="НКД всего" value={fmtMoney(accounting.nkd_total)} />
            <MetricCard label="Грязная покупка" value={fmtMoney(accounting.dirty_purchase)} />
            <MetricCard label="Комиссия" value={fmtMoney(accounting.fees)} />
            <MetricCard label="Купоны (всего)" value={fmtMoney(accounting.coupon_total)} />
            <MetricCard label="Погашение" value={fmtMoney(accounting.redemption_total)} />
            <MetricCard
              label="Total return до налогов"
              value={fmtMoney(accounting.total_return_before_tax)}
              helpId="tax_not_modeled"
            />
          </div>
        ) : accounting ? (
          <p className="muted">{accounting.note ?? accounting.status}</p>
        ) : null}
      </div>

      <div className="card" data-testid="bond-data-quality">
        <h2>Качество данных</h2>
        <p>
          <MetricHelp metricId="bond_known_at_quality" />
        </p>
        <p className="muted" style={{ marginBottom: 0 }}>
          known_at quality:{" "}
          <strong>{bond.data_quality?.known_at_quality ?? "CURRENT_STATE_ONLY"}</strong>. Расписание
          купонов с MOEX bondization отражает текущее состояние рынка — без исторической
          реконструкции «что было известно в момент t». Не использовать как PIT-архив для
          walk-forward.
        </p>
      </div>

      <div className="card">
        <h2>Risk</h2>
        <div className="metric-grid">
          <MetricCard
            label="Credit"
            value={bond.credit_status ?? bond.credit_quality_status}
            helpId="credit_quality"
          />
          <MetricCard label="Liquidity" value={bond.liquidity_status ?? "UNKNOWN"} helpId="liquidity_risk" />
          <MetricCard
            label="Accounting"
            value={bond.accounting_quality ?? "—"}
            helpId="accounting_vs_credit"
          />
          <MetricCard
            label="Real portfolio"
            value={bond.real_portfolio_eligible ? "кандидат" : "нет"}
          />
        </div>
        {(bond.risk_flags?.length || bond.warnings?.length) ? (
          <ul className="plain-list">
            {(bond.risk_flags ?? []).map((f) => (
              <li key={f}>Флаг: {f}</li>
            ))}
            {(bond.warnings ?? []).map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">Явных risk flags / warnings в ответе нет.</p>
        )}
        {bond.credit_safety_note ? <p className="muted">{bond.credit_safety_note}</p> : null}
      </div>

      <div className="card">
        <h2>Cashflows</h2>
        {cashflows.length === 0 ? (
          <p className="muted">График денежных потоков не загружен или пуст.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Тип</th>
                  <th className="numeric">Сумма</th>
                  <th>Валюта</th>
                  <th>Источник</th>
                </tr>
              </thead>
              <tbody>
                {cashflows.map((cf, idx) => (
                  <tr key={`${cf.cashflow_date ?? "x"}-${cf.cashflow_type ?? "t"}-${idx}`}>
                    <td>{cf.cashflow_date ?? "—"}</td>
                    <td>{cf.cashflow_type ?? "—"}</td>
                    <td className="numeric">{cf.amount ?? "—"}</td>
                    <td>{cf.currency ?? "—"}</td>
                    <td>{cf.source ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2>Why Kraken</h2>
        <p data-testid="bond-why-kraken">{bond.why_kraken_ru}</p>
        {bond.why_not_supported ? (
          <p className="muted">Почему не SUPPORTED: {bond.why_not_supported}</p>
        ) : null}
      </div>

      <div className="card">
        <h2>Data</h2>
        <div className="metric-grid">
          <MetricCard label="Instrument id" value={bond.instrument_id} />
          <MetricCard label="Known-at quality" value={bond.data_quality?.known_at_quality ?? "—"} />
          <MetricCard label="Источник" value={bond.data_quality?.source ?? "—"} />
          {bond.currency_raw ? (
            <MetricCard label="FACEUNIT (raw)" value={bond.currency_raw} />
          ) : null}
        </div>
      </div>
    </section>
  );
}
