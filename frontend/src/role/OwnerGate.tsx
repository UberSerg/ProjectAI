import { Navigate, useLocation } from "react-router-dom";
import { pathAllowedForRole } from "../layout/navConfig";
import { useKrakenRole } from "./KrakenRoleContext";

/**
 * Soft presentation gate. Direct URL still reaches the API — this is not authorization.
 */
export function OwnerGate({ children }: { children: React.ReactNode }) {
  const { role } = useKrakenRole();
  const location = useLocation();
  if (!pathAllowedForRole(location.pathname, role)) {
    return <Navigate to="/" replace state={{ ownerGate: true, from: location.pathname }} />;
  }
  return <>{children}</>;
}
