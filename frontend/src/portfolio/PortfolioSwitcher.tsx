import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { usePortfolioContext } from "./PortfolioContext";

export function PortfolioSwitcher({ className = "" }: { className?: string }) {
  const { portfolios, selectedPortfolio, selectPortfolio, loading, createPortfolio } =
    usePortfolioContext();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (loading && portfolios.length === 0) {
    return <div className={`portfolio-switcher ${className}`}>Загрузка портфелей…</div>;
  }

  if (portfolios.length === 0) {
    return (
      <div className={`portfolio-switcher ${className}`}>
        <button type="button" className="btn btn-primary" onClick={() => navigate("/portfolio")}>
          Создать портфель
        </button>
      </div>
    );
  }

  return (
    <div className={`portfolio-switcher ${className}`}>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {selectedPortfolio?.name ?? "Портфель"} ▾
      </button>
      {open && (
        <div className="portfolio-switcher-menu" data-testid="portfolio-switcher-menu">
          {portfolios.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`portfolio-switcher-option${
                p.id === selectedPortfolio?.id ? " is-active" : ""
              }`}
              aria-pressed={p.id === selectedPortfolio?.id}
              onClick={() => {
                selectPortfolio(p.id);
                setOpen(false);
                navigate(`/portfolio/${p.id}`);
              }}
            >
              <span>{p.name}</span>
              <span className="portfolio-switcher-state">
                {p.lifecycle_state === "ACTIVE" ? "Учёт" : "Настройка"}
              </span>
            </button>
          ))}
          <hr className="portfolio-switcher-sep" />
          {!creating ? (
            <>
              <button
                type="button"
                className="portfolio-switcher-option"
                onClick={() => setCreating(true)}
              >
                + Создать портфель
              </button>
              <button
                type="button"
                className="portfolio-switcher-option"
                onClick={() => {
                  setOpen(false);
                  navigate("/portfolio");
                }}
              >
                Управление портфелями
              </button>
            </>
          ) : (
            <form
              className="portfolio-switcher-form"
              onSubmit={async (e) => {
                e.preventDefault();
                setError(null);
                try {
                  const created = await createPortfolio({ name: name.trim() });
                  setCreating(false);
                  setName("");
                  setOpen(false);
                  navigate(`/portfolio/${created.id}`);
                } catch (exc) {
                  setError(exc instanceof Error ? exc.message : String(exc));
                }
              }}
            >
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Основной"
                required
                maxLength={120}
              />
              {error && <div className="error-text">{error}</div>}
              <button type="submit" className="btn btn-primary">
                Создать
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
