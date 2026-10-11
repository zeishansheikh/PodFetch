import React from 'react';

export function StatCard({ label, value, subtext, icon: Icon, loading = false, valueColor }) {
  return (
    <div className="metric-card">
      <div className="metric-card-top">
        <span className="metric-label">{label}</span>
        {Icon && (
          <div className="metric-icon-wrap">
            <Icon size={18} />
          </div>
        )}
      </div>

      {loading ? (
        <div className="skeleton" style={{ height: '36px', width: '90px', margin: '4px 0' }} />
      ) : (
        <div className="metric-value" style={valueColor ? { color: valueColor } : undefined}>
          {value !== undefined && value !== null ? value.toLocaleString() : '—'}
        </div>
      )}

      {subtext && <div className="metric-subtext">{subtext}</div>}
    </div>
  );
}

export default StatCard;
