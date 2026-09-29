import { useCallback, useEffect, useState } from "react";
import { errorMessage } from "../../api/client";
import {
  createBrokerAccount,
  createFeeProfile,
  listBrokerAccounts,
  listFeeProfiles,
  type BrokerAccount,
  type FeeProfile,
} from "../../api/brokerAccounts";
import { assignPortfolioBroker, type PersonalSummary } from "../../api/personalPortfolios";

/**
 * Bounded broker settings for a Personal portfolio: pick/create account,
 * optional custom BUY%/SELL% tariff. No OAuth / secrets.
 */
export function BrokerSettingsPanel({
  portfolioId,
  broker,
  onChanged,
}: {
  portfolioId: number;
  broker: PersonalSummary["portfolio"]["broker"];
  onChanged: (summary: PersonalSummary) => void;
}) {
  const [open, setOpen] = useState(false);
  const [accounts, setAccounts] = useState<BrokerAccount[]>([]);
  const [profiles, setProfiles] = useState<FeeProfile[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string>(
    broker?.broker_account_id != null ? String(broker.broker_account_id) : "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newAccountName, setNewAccountName] = useState("");
  const [newProfileId, setNewProfileId] = useState("");
  const [showCustom, setShowCustom] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customBroker, setCustomBroker] = useState("");
  const [buyPct, setBuyPct] = useState("0.3");
  const [sellPct, setSellPct] = useState("0.3");

  const reloadLists = useCallback(async (signal?: AbortSignal) => {
    const [acc, prof] = await Promise.all([
      listBrokerAccounts({ signal }),
      listFeeProfiles({ signal }),
    ]);
    setAccounts(acc.items);
    setProfiles(prof.items);
    if (!newProfileId && prof.items.length > 0) {
      const sber = prof.items.find((p) => p.code === "SBER_INVESTMENT") ?? prof.items[0];
      setNewProfileId(String(sber.id));
    }
  }, [newProfileId]);

  useEffect(() => {
    setSelectedAccountId(broker?.broker_account_id != null ? String(broker.broker_account_id) : "");
  }, [broker?.broker_account_id]);

  useEffect(() => {
    if (!open) return;
    const ctrl = new AbortController();
    setError(null);
    void reloadLists(ctrl.signal).catch((e) => {
      if (!ctrl.signal.aborted) setError(errorMessage(e));
    });
    return () => ctrl.abort();
  }, [open, reloadLists]);

  async function onAssign() {
    setBusy(true);
    setError(null);
    try {
      const id = selectedAccountId.trim() ? Number(selectedAccountId) : null;
      const summary = await assignPortfolioBroker(portfolioId, id);
      onChanged(summary);
      setOpen(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function onUnassign() {
    setBusy(true);
    setError(null);
    try {
      const summary = await assignPortfolioBroker(portfolioId, null);
      setSelectedAccountId("");
      onChanged(summary);
      setOpen(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function onCreateAccount() {
    if (!newAccountName.trim() || !newProfileId) return;
    setBusy(true);
    setError(null);
    try {
      const account = await createBrokerAccount({
        name: newAccountName.trim(),
        fee_profile_id: Number(newProfileId),
      });
      setNewAccountName("");
      await reloadLists();
      setSelectedAccountId(String(account.id));
      const summary = await assignPortfolioBroker(portfolioId, account.id);
      onChanged(summary);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function onCreateCustomProfile() {
    if (!customName.trim() || !customBroker.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const profile = await createFeeProfile({
        name: customName.trim(),
        broker_name: customBroker.trim(),
        buy_rate_pct: buyPct,
        sell_rate_pct: sellPct,
      });
      setShowCustom(false);
      setCustomName("");
      setCustomBroker("");
      await reloadLists();
      setNewProfileId(String(profile.id));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const summaryLabel = broker
    ? `${broker.broker_name} · ${broker.tariff_name ?? broker.fee_profile_name ?? "тариф"}`
    : "Брокер не назначен";

  return (
    <section className="panel broker-settings" data-testid="broker-settings">
      <div className="page-header-row" style={{ alignItems: "center" }}>
        <div>
          <h3>Брокер</h3>
          <p className="muted" data-testid="broker-summary-label">
            {summaryLabel}
          </p>
        </div>
        <button
          type="button"
          className="btn ghost"
          onClick={() => setOpen((v) => !v)}
          data-testid="broker-settings-toggle"
        >
          {open ? "Скрыть" : "Настроить"}
        </button>
      </div>

      {open ? (
        <div className="broker-settings-body" data-testid="broker-settings-body">
          <label className="field">
            <span>Брокерский счёт</span>
            <select
              value={selectedAccountId}
              onChange={(e) => setSelectedAccountId(e.target.value)}
              data-testid="broker-account-select"
            >
              <option value="">— не назначен —</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.broker_name}
                  {a.fee_profile ? ` · ${a.fee_profile.name}` : ""})
                </option>
              ))}
            </select>
          </label>
          <div className="modal-actions">
            <button
              type="button"
              className="btn primary"
              disabled={busy}
              onClick={() => void onAssign()}
              data-testid="broker-assign-btn"
            >
              Применить
            </button>
            <button
              type="button"
              className="btn ghost"
              disabled={busy || !broker}
              onClick={() => void onUnassign()}
              data-testid="broker-unassign-btn"
            >
              Снять
            </button>
          </div>

          <hr />
          <h4>Новый счёт</h4>
          <label className="field">
            <span>Название</span>
            <input
              value={newAccountName}
              onChange={(e) => setNewAccountName(e.target.value)}
              data-testid="broker-new-account-name"
            />
          </label>
          <label className="field">
            <span>Тарифный профиль</span>
            <select
              value={newProfileId}
              onChange={(e) => setNewProfileId(e.target.value)}
              data-testid="broker-new-profile-select"
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.is_builtin ? " (встроенный)" : ""}
                  {p.buy_rate_pct != null ? ` · BUY ${p.buy_rate_pct}%` : ""}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn secondary"
            disabled={busy || !newAccountName.trim() || !newProfileId}
            onClick={() => void onCreateAccount()}
            data-testid="broker-create-account-btn"
          >
            Создать и назначить
          </button>

          <p>
            <button
              type="button"
              className="btn ghost"
              onClick={() => setShowCustom((v) => !v)}
              data-testid="broker-custom-toggle"
            >
              {showCustom ? "Скрыть свой тариф" : "Свой тариф BUY%/SELL%"}
            </button>
          </p>
          {showCustom ? (
            <div data-testid="broker-custom-form">
              <label className="field">
                <span>Название тарифа</span>
                <input
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  data-testid="broker-custom-name"
                />
              </label>
              <label className="field">
                <span>Брокер</span>
                <input
                  value={customBroker}
                  onChange={(e) => setCustomBroker(e.target.value)}
                  data-testid="broker-custom-broker"
                />
              </label>
              <div className="field-row">
                <label className="field">
                  <span>BUY, %</span>
                  <input
                    value={buyPct}
                    onChange={(e) => setBuyPct(e.target.value)}
                    inputMode="decimal"
                    data-testid="broker-custom-buy"
                  />
                </label>
                <label className="field">
                  <span>SELL, %</span>
                  <input
                    value={sellPct}
                    onChange={(e) => setSellPct(e.target.value)}
                    inputMode="decimal"
                    data-testid="broker-custom-sell"
                  />
                </label>
              </div>
              <button
                type="button"
                className="btn secondary"
                disabled={busy}
                onClick={() => void onCreateCustomProfile()}
                data-testid="broker-custom-save"
              >
                Создать тариф
              </button>
            </div>
          ) : null}

          {error ? (
            <p className="form-error" data-testid="broker-settings-error">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
