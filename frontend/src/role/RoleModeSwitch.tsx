import { useKrakenRole } from "./KrakenRoleContext";

/** Presentation switch for the machine operator. Not a security control. */
export function RoleModeSwitch() {
  const { role, setRole, canSwitchRoles } = useKrakenRole();
  if (!canSwitchRoles) return null;

  return (
    <div className="role-mode-switch" data-testid="role-mode-switch">
      <span className="role-mode-label">Режим</span>
      <div className="role-mode-buttons" role="group" aria-label="Режим интерфейса">
        <button
          type="button"
          className={role === "USER" ? "active" : undefined}
          data-testid="role-switch-user"
          onClick={() => setRole("USER")}
        >
          Пользователь
        </button>
        <button
          type="button"
          className={role === "OWNER" ? "active" : undefined}
          data-testid="role-switch-owner"
          onClick={() => setRole("OWNER")}
        >
          Владелец
        </button>
      </div>
      <p className="role-mode-note muted">
        Только вид интерфейса (V1). Не защита доступа.
      </p>
    </div>
  );
}
