import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  createPersonalPortfolio,
  listPersonalPortfolios,
  type PortfolioCard,
} from "../api/personalPortfolios";

const STORAGE_KEY = "kraken.selectedPortfolioId";

type PortfolioContextValue = {
  portfolios: PortfolioCard[];
  selectedPortfolioId: number | null;
  selectedPortfolio: PortfolioCard | null;
  loading: boolean;
  error: string | null;
  refreshList: () => Promise<PortfolioCard[]>;
  selectPortfolio: (id: number | null) => void;
  createPortfolio: (input: { name: string; description?: string }) => Promise<PortfolioCard>;
};

const PortfolioContext = createContext<PortfolioContextValue | null>(null);

function readStoredId(): number | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function writeStoredId(id: number | null) {
  try {
    if (id == null) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, String(id));
  } catch {
    /* ignore */
  }
}

export function PortfolioProvider({ children }: { children: ReactNode }) {
  const [portfolios, setPortfolios] = useState<PortfolioCard[]>([]);
  // Seed from localStorage so a browser refresh keeps a valid selection before the list returns.
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<number | null>(() => readStoredId());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const refreshRequestRef = useRef(0);

  const refreshList = useCallback(async () => {
    const request = ++refreshRequestRef.current;
    setLoading(true);
    setError(null);
    try {
      const res = await listPersonalPortfolios();
      const items = res.items ?? [];
      if (request !== refreshRequestRef.current) return items;
      setPortfolios(items);
      setSelectedPortfolioId((prev) => {
        // Prefer the in-memory selection, then the stored id — never invent a deleted one.
        const preferred = prev ?? readStoredId();
        if (preferred != null && items.some((p) => p.id === preferred)) {
          writeStoredId(preferred);
          return preferred;
        }
        if (items.length > 0) {
          writeStoredId(items[0].id);
          return items[0].id;
        }
        writeStoredId(null);
        return null;
      });
      return items;
    } catch (exc) {
      if (request === refreshRequestRef.current) {
        setError(exc instanceof Error ? exc.message : String(exc));
      }
      return [];
    } finally {
      if (request === refreshRequestRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  const selectPortfolio = useCallback((id: number | null) => {
    setSelectedPortfolioId(id);
    writeStoredId(id);
  }, []);

  const createPortfolio = useCallback(
    async (input: { name: string; description?: string }) => {
      const summary = await createPersonalPortfolio(input);
      const created: PortfolioCard = {
        id: summary.portfolio.id,
        name: summary.portfolio.name,
        description: summary.portfolio.description,
        lifecycle_state: summary.portfolio.lifecycle_state ?? "DRAFT",
        cash_rub: summary.summary.cash_rub,
        positions_count: summary.positions.length,
      };
      // The POST succeeded. Never lose the created portfolio when the list GET fails.
      refreshRequestRef.current += 1;
      setPortfolios((prev) => prev.some((p) => p.id === created.id) ? prev : [created, ...prev]);
      selectPortfolio(created.id);
      await refreshList();
      return created;
    },
    [refreshList, selectPortfolio],
  );

  const selectedPortfolio = useMemo(
    () => portfolios.find((p) => p.id === selectedPortfolioId) ?? null,
    [portfolios, selectedPortfolioId],
  );

  const value = useMemo(
    () => ({
      portfolios,
      selectedPortfolioId,
      selectedPortfolio,
      loading,
      error,
      refreshList,
      selectPortfolio,
      createPortfolio,
    }),
    [
      portfolios,
      selectedPortfolioId,
      selectedPortfolio,
      loading,
      error,
      refreshList,
      selectPortfolio,
      createPortfolio,
    ],
  );

  return <PortfolioContext.Provider value={value}>{children}</PortfolioContext.Provider>;
}

export function usePortfolioContext(): PortfolioContextValue {
  const ctx = useContext(PortfolioContext);
  if (!ctx) {
    throw new Error("usePortfolioContext must be used within PortfolioProvider");
  }
  return ctx;
}
