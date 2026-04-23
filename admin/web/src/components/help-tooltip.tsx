"use client";

interface HelpTooltipProps {
  label: string;
  content: string;
}

export function HelpTooltip({ label, content }: HelpTooltipProps) {
  return (
    <span className="help-tooltip" tabIndex={0} aria-label={label}>
      <span className="help-tooltip-trigger" aria-hidden="true">
        ?
      </span>
      <span className="help-tooltip-content" role="tooltip">
        <strong>{label}</strong>
        <span>{content}</span>
      </span>
    </span>
  );
}
