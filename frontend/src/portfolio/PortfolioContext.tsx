import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listPersonalPortfolios();
      const items = res.items ?? [];
      setPortfolios(items);
      setSelectedPortfolioId((prev) => {
        const stored = prev ?? readStoredId();
        if (stored != null && items.some((p) => p.id === stored)) {
          writeStoredId(stored);
          return stored;
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
      setError(exc instanceof Error ? exc.message : String(exc));
      return [];
    } finally {
      setLoading(false);
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
      const items = await refreshList();
      const created =
        items.find((p) => p.id === summary.portfolio.id) ??
        ({
          id: summary.portfolio.id,
          name: summary.portfolio.name,
          description: summary.portfolio.description,
          lifecycle_state: summary.portfolio.lifecycle_state ?? "DRAFT",
          cash_rub: summary.summary.cash_rub,
          positions_count: summary.positions.length,
        } satisfies PortfolioCard);
      selectPortfolio(created.id);
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
