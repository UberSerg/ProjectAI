import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { HelpDrawer } from "./HelpDrawer";
import { getMetricHelp, getPageHelp } from "./registry";
import type { HelpEntry, PageHelpContent } from "./types";

type DrawerMode =
  | { kind: "metric"; entry: HelpEntry }
  | { kind: "page"; page: PageHelpContent }
  | null;

interface HelpContextValue {
  openMetric: (id: string) => void;
  openPage: (id: string) => void;
  close: () => void;
}

const HelpContext = createContext<HelpContextValue | null>(null);

export function HelpProvider({ children }: { children: ReactNode }) {
  const [drawer, setDrawer] = useState<DrawerMode>(null);

  const openMetric = useCallback((id: string) => {
    const entry = getMetricHelp(id);
    if (entry) setDrawer({ kind: "metric", entry });
  }, []);

  const openPage = useCallback((id: string) => {
    const page = getPageHelp(id);
    if (page) setDrawer({ kind: "page", page });
  }, []);

  const close = useCallback(() => setDrawer(null), []);

  const value = useMemo(() => ({ openMetric, openPage, close }), [openMetric, openPage, close]);

  return (
    <HelpContext.Provider value={value}>
      {children}
      <HelpDrawer mode={drawer} onClose={close} onOpenMetric={openMetric} />
    </HelpContext.Provider>
  );
}

export function useHelp(): HelpContextValue {
  const ctx = useContext(HelpContext);
  if (!ctx) throw new Error("useHelp must be used within HelpProvider");
  return ctx;
}

export function useHelpOptional(): HelpContextValue | null {
  return useContext(HelpContext);
}
