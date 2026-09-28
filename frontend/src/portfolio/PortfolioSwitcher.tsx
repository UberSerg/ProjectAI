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
    <div className={`portfolio-switcher ${className}`} style={{ position: "relative" }}>
      <button
        type="button"
        className="btn"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {selectedPortfolio?.name ?? "Портфель"} ▾
      </button>
      {open && (
        <div
          className="panel"
          style={{
            position: "absolute",
            zIndex: 40,
            top: "100%",
            left: 0,
            minWidth: 240,
            marginTop: 4,
            padding: 8,
          }}
        >
          {portfolios.map((p) => (
            <button
              key={p.id}
              type="button"
              className="btn"
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                marginBottom: 4,
                opacity: p.id === selectedPortfolio?.id ? 1 : 0.85,
              }}
              onClick={() => {
                selectPortfolio(p.id);
                setOpen(false);
                navigate(`/portfolio/${p.id}`);
              }}
            >
              {p.name}
              <span style={{ opacity: 0.6, marginLeft: 8, fontSize: 12 }}>
                {p.lifecycle_state === "ACTIVE" ? "Учёт" : "Настройка"}
              </span>
            </button>
          ))}
          <hr style={{ borderColor: "rgba(255,255,255,0.1)" }} />
          {!creating ? (
            <>
              <button
                type="button"
                className="btn"
                style={{ display: "block", width: "100%", textAlign: "left" }}
                onClick={() => setCreating(true)}
              >
                + Создать портфель
              </button>
              <button
                type="button"
                className="btn"
                style={{ display: "block", width: "100%", textAlign: "left" }}
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
                style={{ width: "100%", marginBottom: 6 }}
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
