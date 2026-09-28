import { useKrakenRole } from "./KrakenRoleContext";

/** Presentation switch for the machine operator. Not a security control / IAM. */
export function RoleModeSwitch() {
  const { role, setRole, canSwitchRoles } = useKrakenRole();
  if (!canSwitchRoles) return null;

  return (
    <div className="role-mode-switch" data-testid="role-mode-switch">
      <span className="role-mode-label" id="role-mode-label">
        Режим интерфейса
      </span>
      <div
        className="role-mode-buttons switch-segments"
        role="group"
        aria-labelledby="role-mode-label"
        title="Технический переключатель вида. Не смена аккаунта."
      >
        <button
          type="button"
          className={`switch-segment${role === "USER" ? " active" : ""}`}
          data-testid="role-switch-user"
          aria-pressed={role === "USER"}
          onClick={() => setRole("USER")}
        >
          USER
        </button>
        <button
          type="button"
          className={`switch-segment${role === "OWNER" ? " active" : ""}`}
          data-testid="role-switch-owner"
          aria-pressed={role === "OWNER"}
          onClick={() => setRole("OWNER")}
        >
          OWNER
        </button>
      </div>
      <p className="role-mode-note">
        Presentation mode · не IAM
      </p>
    </div>
  );
}
