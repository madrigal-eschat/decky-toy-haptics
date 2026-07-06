import React from 'react';

export const staticClasses = { Title: 'decky-title' };

export function PanelSection({ title, children }: { title?: string; children?: React.ReactNode }) {
  return (
    <div className="panel-section">
      {title && <div className="panel-title">{title}</div>}
      {children}
    </div>
  );
}

export function PanelSectionRow({ children }: { children?: React.ReactNode }) {
  return <div className="panel-row">{children}</div>;
}

export function ButtonItem({
  children,
  onClick,
  disabled,
  layout: _layout,
}: {
  children?: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  layout?: string;
}) {
  return (
    <button onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}

export function Focusable({
  children,
  style,
}: {
  children?: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return <div style={style}>{children}</div>;
}

export function SliderField({
  label,
  value,
  min,
  max,
  step,
  showValue: _showValue,
  valueSuffix: _valueSuffix,
  onChange,
}: {
  label?: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  showValue?: boolean;
  valueSuffix?: string;
  onChange?: (value: number) => void;
}) {
  return (
    <label>
      {label}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={e => onChange?.(e.target.valueAsNumber)}
      />
    </label>
  );
}
