import { useId, useState, type ReactNode } from "react";

/** Hover/focus summary; click/Enter/Space expands via onExpand (touch-friendly). */
export function HelpTooltip({
  summary,
  onExpand,
  children,
}: {
  summary: string;
  onExpand: () => void;
  children: ReactNode;
}) {
  const tipId = useId();
  const [open, setOpen] = useState(false);

  return (
    <span
      className={`help-tooltip-wrap${open ? " open" : ""}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <button
        type="button"
        className="metric-help-btn"
        aria-describedby={open ? tipId : undefined}
        aria-label="Справка по показателю"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onExpand();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onExpand();
          }
        }}
      >
        {children}
      </button>
      {open ? (
        <span className="help-tooltip" role="tooltip" id={tipId}>
          {summary}
          <span className="help-tooltip-hint">Нажмите для подробностей</span>
        </span>
      ) : null}
    </span>
  );
}
