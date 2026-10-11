import React from 'react';
import { Menu, Loader2, Search, CheckCircle2, AlertTriangle } from 'lucide-react';

const PAGE_NAMES = {
  overview: 'Overview',
  discover: 'Media Discovery',
  'video-downloads': 'Video Downloads',
  'instagram-audio': 'Instagram Audio',
  'processing-queue': 'Processing Queue',
  library: 'Media Library',
  'google-drive': 'Google Drive Integration',
  settings: 'Settings & Diagnostics',
};

export function TopNav({
  activePage,
  onOpenMobile,
  activeJobsCount = 0,
  backendConnected = true,
  onQuickAction,
}) {
  const pageTitle = PAGE_NAMES[activePage] || 'Dashboard';

  return (
    <header className="top-nav">
      <div className="top-nav-left">
        <button
          className="mobile-menu-btn"
          onClick={onOpenMobile}
          aria-label="Open mobile navigation"
        >
          <Menu size={18} />
        </button>

        <div className="breadcrumbs">
          <span className="breadcrumb-root">PodFetch</span>
          <span className="breadcrumb-separator">/</span>
          <span className="breadcrumb-current">{pageTitle}</span>
        </div>
      </div>

      <div className="top-nav-right">
        {/* Active Task Indicator */}
        {activeJobsCount > 0 ? (
          <div className="task-indicator active">
            <span className="pulse-spinner" />
            <span>{activeJobsCount} Task{activeJobsCount > 1 ? 's' : ''} Running</span>
          </div>
        ) : (
          <div className="task-indicator">
            <CheckCircle2 size={13} style={{ color: 'var(--status-success)' }} />
            <span>All tasks idle</span>
          </div>
        )}

        {/* Backend Connectivity Status */}
        {!backendConnected && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '4px 10px',
              borderRadius: 'var(--radius-full)',
              background: 'var(--status-error-bg)',
              color: 'var(--status-error)',
              fontSize: '12px',
              fontWeight: 500,
            }}
          >
            <AlertTriangle size={14} />
            <span>API Offline (Port 8000)</span>
          </div>
        )}
      </div>
    </header>
  );
}

export default TopNav;
