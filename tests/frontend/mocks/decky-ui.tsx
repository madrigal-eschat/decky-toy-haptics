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
