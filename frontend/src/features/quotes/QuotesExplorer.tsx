import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { errorMessage } from "../../api/client";
import { getCandles, type Candle } from "../../api/market";
import { PageState } from "../../components/Ui";
import { MetricHelp } from "../../help";
import { formatDate, formatPrice, formatNumber } from "../../utils/format";
import { PriceChart } from "./PriceChart";
import { RangeNavigator } from "./RangeNavigator";
import {
  clampRange,
  formatPeriodLabel,
  isoFromTimestamp,
  presetRange,
  RANGE_PRESETS,
  tradingDaysEstimate,
  type DateBounds,
  type RangePreset,
} from "./range";

interface Props {
  instrumentId: string;
  symbol: string;
  firstTimestamp: string | null;
  lastTimestamp: string | null;
  recordsCount: number;
}

export function QuotesExplorer({
  instrumentId,
  symbol,
  firstTimestamp,
  lastTimestamp,
  recordsCount,
}: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const available = useMemo<DateBounds | null>(() => {
    const from = isoFromTimestamp(firstTimestamp);
    const to = isoFromTimestamp(lastTimestamp);
    if (!from || !to) return null;
    return { from, to };
  }, [firstTimestamp, lastTimestamp]);

  const initial = useMemo(() => {
    if (!available) return null;
    const qFrom = searchParams.get("from");
    const qTo = searchParams.get("to");
    if (qFrom && qTo) return clampRange({ from: qFrom, to: qTo }, available);
    return presetRange("1Y", available);
  }, [available, searchParams]);

  const [range, setRange] = useState<DateBounds | null>(initial);
  const [draftFrom, setDraftFrom] = useState(initial?.from ?? "");
  const [draftTo, setDraftTo] = useState(initial?.to ?? "");
  const [activePreset, setActivePreset] = useState<RangePreset | "custom" | null>(() => {
    if (!available || !initial) return "1Y";
    const qFrom = searchParams.get("from");
    const qTo = searchParams.get("to");
    if (qFrom && qTo) return "custom";
    return "1Y";
  });
  const [candles, setCandles] = useState<Candle[] | null>(null);
  const [overview, setOverview] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!initial) return;
    setRange(initial);
    setDraftFrom(initial.from);
    setDraftTo(initial.to);
  }, [initial]);

  useEffect(() => {
    if (!available) return;
    const controller = new AbortController();
    getCandles(instrumentId, { limit: 5000, date_from: available.from, date_to: available.to }, controller.signal)
      .then((items) => setOverview(downsample(items, 400)))
      .catch(() => setOverview([]));
    return () => controller.abort();
  }, [instrumentId, available]);

  const applyRange = useCallback(
    (next: DateBounds, preset: RangePreset | "custom" | null = "custom") => {
      if (!available) return;
      const clamped = clampRange(next, available);
      setRange(clamped);
      setDraftFrom(clamped.from);
      setDraftTo(clamped.to);
      setActivePreset(preset);
      const params = new URLSearchParams(searchParams);
      params.set("from", clamped.from);
      params.set("to", clamped.to);
      setSearchParams(params, { replace: true });
    },
    [available, searchParams, setSearchParams],
  );

  useEffect(() => {
    if (!range || !available) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const limit = Math.min(5000, Math.max(60, tradingDaysEstimate(range.from, range.to)));
    getCandles(instrumentId, { limit, date_from: range.from, date_to: range.to }, controller.signal)
      .then((items) => setCandles(items))
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(errorMessage(reason));
          setCandles([]);
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [instrumentId, range, available]);

  if (!available) {
    return (
      <PageState kind="empty" title="История котировок ещё не загружена">
        Для {symbol} нет дневных RAW-свечей. После листинга и backfill здесь появится график.
      </PageState>
    );
  }

  const shortHistory = recordsCount > 0 && recordsCount < 80;
  const showCandles = candles ?? [];
  const keepingPrevious = loading && candles != null && candles.length > 0;
  const navigatorSeries = overview.length >= 2 ? overview : !loading && showCandles.length >= 2 ? showCandles : [];
  const navigatorLoading = Boolean(range && loading && navigatorSeries.length < 2);

  return (
    <div className="quotes-explorer">
      <div className="quotes-toolbar">
        <div className="quotes-presets" role="group" aria-label="Пресеты периода">
          {RANGE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className={`chip${activePreset === preset ? " active" : ""}`}
              onClick={() => applyRange(presetRange(preset, available), preset)}
            >
              {preset}
            </button>
          ))}
        </div>
        <div className="quotes-manual">
          <label>
            С
            <input type="date" value={draftFrom} min={available.from} max={available.to} onChange={(e) => setDraftFrom(e.target.value)} />
          </label>
          <label>
            По
            <input type="date" value={draftTo} min={available.from} max={available.to} onChange={(e) => setDraftTo(e.target.value)} />
          </label>
          <button type="button" onClick={() => applyRange({ from: draftFrom, to: draftTo }, "custom")}>
            Применить
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => applyRange(presetRange("1Y", available), "1Y")}
          >
            Сбросить
          </button>
        </div>
      </div>

      <div className="quotes-meta">
        <p>
          Период: <strong>{range ? formatPeriodLabel(range.from, range.to) : "—"}</strong>
          <span className="muted">
            {" "}
            · доступно {formatDate(firstTimestamp)} → {formatDate(lastTimestamp)} · RAW OHLCV
          </span>
          <MetricHelp metricId="raw_candles" />
        </p>
        {shortHistory ? (
          <p className="muted">
            Короткая история (поздний листинг). Длинные пресеты (3Y/5Y/MAX) совпадут с доступным окном.
          </p>
        ) : null}
      </div>

      {error ? <PageState kind="error">{error}</PageState> : null}

      <div className={`quotes-chart-panel${keepingPrevious ? " is-refreshing" : ""}`}>
        {loading && !candles ? (
          <PageState kind="loading" title="Загрузка котировок…" />
        ) : showCandles.length === 0 ? (
          <PageState kind="empty" title="Нет свечей в выбранном периоде">
            Измените диапазон или выполните backfill истории.
          </PageState>
        ) : (
          <PriceChart candles={showCandles} />
        )}
      </div>

      {range && navigatorSeries.length >= 2 ? (
        <RangeNavigator
          overview={navigatorSeries}
          available={available}
          range={range}
          onChange={(next) => applyRange(next, "custom")}
        />
      ) : navigatorLoading ? (
        <p className="muted range-nav-caption">Загрузка навигатора периода…</p>
      ) : range ? (
        <p className="muted range-nav-caption">Навигатор периода недоступен — мало точек истории.</p>
      ) : null}

      {showCandles.length ? (
        <>
          <h2 style={{ marginTop: "1rem" }}>Свечи периода</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Open</th>
                  <th>High</th>
                  <th>Low</th>
                  <th>Close</th>
                  <th>Volume</th>
                </tr>
              </thead>
              <tbody>
                {[...showCandles].reverse().slice(0, 90).map((candle, index) => (
                  <tr key={`${candle.timestamp}-${candle.source ?? ""}-${index}`}>
                    <td>{formatDate(candle.timestamp)}</td>
                    <td className="numeric">{formatPrice(candle.open)}</td>
                    <td className="numeric">{formatPrice(candle.high)}</td>
                    <td className="numeric">{formatPrice(candle.low)}</td>
                    <td className="numeric">{formatPrice(candle.close)}</td>
                    <td className="numeric">{formatNumber(candle.volume)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {showCandles.length > 90 ? (
            <p className="muted">Показаны последние 90 свечей выбранного периода (всего {showCandles.length}).</p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function downsample(items: Candle[], maxPoints: number): Candle[] {
  if (items.length <= maxPoints) return items;
  const step = items.length / maxPoints;
  const out: Candle[] = [];
  for (let i = 0; i < maxPoints - 1; i += 1) {
    out.push(items[Math.floor(i * step)]);
  }
  out.push(items[items.length - 1]);
  return out;
}
