import { THEME_LABELS, THEME_ORDER } from "./theme";
import { useKrakenTheme } from "./useKrakenTheme";

/** Appearance only — unrelated to the presentation role switch next to it. */
export function ThemeSwitch() {
  const { theme, setTheme } = useKrakenTheme();

  return (
    <div className="theme-switch" data-testid="theme-switch" data-theme-value={theme}>
      <span className="theme-switch-label" id="theme-switch-label">
        Тема
      </span>
      <div className="switch-segments" role="group" aria-labelledby="theme-switch-label">
        {THEME_ORDER.map((value) => (
          <button
            key={value}
            type="button"
            className={`switch-segment${theme === value ? " active" : ""}`}
            data-testid={`theme-switch-${value}`}
            aria-pressed={theme === value}
            onClick={() => setTheme(value)}
          >
            {THEME_LABELS[value]}
          </button>
        ))}
      </div>
    </div>
  );
}
