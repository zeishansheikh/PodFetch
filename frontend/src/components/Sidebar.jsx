import React from 'react';
import {
  LayoutDashboard,
  Compass,
  Video,
  Music2,
  ListOrdered,
  FolderArchive,
  Cloud,
  Settings,
  ChevronLeft,
  ChevronRight,
  Radio,
} from 'lucide-react';

const NAV_ITEMS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'discover', label: 'Discover', icon: Compass },
  { id: 'video-downloads', label: 'Video Downloads', icon: Video },
  { id: 'instagram-audio', label: 'Instagram Audio', icon: Music2 },
  { id: 'processing-queue', label: 'Processing Queue', icon: ListOrdered },
  { id: 'library', label: 'Media Library', icon: FolderArchive },
  { id: 'google-drive', label: 'Google Drive', icon: Cloud },
  { id: 'settings', label: 'Settings', icon: Settings },
];

export function Sidebar({
  activePage,
  onNavigate,
  isCollapsed,
  onToggleCollapse,
  isMobileOpen,
  onCloseMobile,
  backendConnected,
  activeJobsCount = 0,
}) {
  return (
    <>
      {/* Mobile Backdrop */}
      <div
        className={`mobile-overlay ${isMobileOpen ? 'visible' : ''}`}
        onClick={onCloseMobile}
      />

      <aside
        className={`sidebar ${isCollapsed ? 'collapsed' : ''} ${
          isMobileOpen ? 'mobile-open' : ''
        }`}
      >
        {/* Brand Header */}
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <img src="/logo.svg" alt="PodFetch" />
            {!isCollapsed && <span>PodFetch</span>}
          </div>
          <button
            className="sidebar-collapse-btn"
            onClick={onToggleCollapse}
            title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label="Toggle sidebar"
          >
            {isCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
        </div>

        {/* Navigation Links */}
        <nav className="sidebar-nav">
          {!isCollapsed && <div className="sidebar-section-title">Navigation</div>}
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activePage === item.id;
            return (
              <button
                key={item.id}
                className={`sidebar-link ${isActive ? 'active' : ''}`}
                onClick={() => {
                  onNavigate(item.id);
                  if (onCloseMobile) onCloseMobile();
                }}
                title={isCollapsed ? item.label : undefined}
              >
                <Icon className="sidebar-link-icon" />
                {!isCollapsed && <span>{item.label}</span>}
                {!isCollapsed && item.id === 'processing-queue' && activeJobsCount > 0 && (
                  <span className="sidebar-link-badge">{activeJobsCount}</span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Footer with Backend Health Status */}
        <div className="sidebar-footer">
          <div className="backend-pill">
            <span className={`status-dot ${backendConnected ? '' : 'offline'}`} />
            {!isCollapsed && (
              <span>{backendConnected ? 'Backend Online' : 'Backend Offline'}</span>
            )}
          </div>
          {!isCollapsed && (
            <div style={{ fontSize: '11px', color: 'var(--text-disabled)', fontFamily: 'var(--font-mono)' }}>
              v1.0.0
            </div>
          )}
        </div>
      </aside>
    </>
  );
}

export default Sidebar;
