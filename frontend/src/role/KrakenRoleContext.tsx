import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ROLE_STORAGE_KEY, type KrakenPresentationRole } from "./types";

interface KrakenRoleContextValue {
  role: KrakenPresentationRole;
  isOwner: boolean;
  isUser: boolean;
  /** Presentation-level only — not production authorization. */
  setRole: (role: KrakenPresentationRole) => void;
  canSwitchRoles: boolean;
}

const KrakenRoleContext = createContext<KrakenRoleContextValue | null>(null);

function readStoredRole(): KrakenPresentationRole {
  try {
    const raw = localStorage.getItem(ROLE_STORAGE_KEY);
    if (raw === "USER" || raw === "OWNER") return raw;
  } catch {
    /* ignore */
  }
  // Current Kraken is owner-operated; default to full OWNER presentation.
  return "OWNER";
}

export function KrakenRoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<KrakenPresentationRole>(() => readStoredRole());

  const setRole = useCallback((next: KrakenPresentationRole) => {
    setRoleState(next);
    try {
      localStorage.setItem(ROLE_STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo<KrakenRoleContextValue>(
    () => ({
      role,
      isOwner: role === "OWNER",
      isUser: role === "USER",
      setRole,
      // Single-user stage: machine operator may switch presentation modes.
      canSwitchRoles: true,
    }),
    [role, setRole],
  );

  return <KrakenRoleContext.Provider value={value}>{children}</KrakenRoleContext.Provider>;
}

export function useKrakenRole(): KrakenRoleContextValue {
  const ctx = useContext(KrakenRoleContext);
  if (!ctx) {
    throw new Error("useKrakenRole must be used within KrakenRoleProvider");
  }
  return ctx;
}
