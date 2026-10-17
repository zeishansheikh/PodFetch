import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import TopNav from './components/TopNav';
import Overview from './pages/Overview';
import Discover from './pages/Discover';
import VideoDownloads from './pages/VideoDownloads';
import InstagramAudio from './pages/InstagramAudio';
import ProcessingQueue from './pages/ProcessingQueue';
import Library from './pages/Library';
import GoogleDrive from './pages/GoogleDrive';
import Settings from './pages/Settings';
import NatureReelMaker from './pages/NatureReelMaker';
import api from './api/client';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';

export function App() {
  const [activePage, setActivePage] = useState('overview');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  // System & background status
  const [backendConnected, setBackendConnected] = useState(true);
  const [activeJobsCount, setActiveJobsCount] = useState(0);

  // Toast notifications
  const [toasts, setToasts] = useState([]);

  const showToast = (message, type = 'info') => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  };

  const removeToast = (id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  // Heartbeat & task status check
  const checkHealthAndTasks = async () => {
    try {
      const [health, active] = await Promise.all([
        api.getHealth().catch(() => null),
        api.getActiveJobs().catch(() => null),
      ]);

      if (health && health.status === 'ok') {
        setBackendConnected(true);
      } else {
        setBackendConnected(false);
      }

      if (active && Array.isArray(active.active_jobs)) {
        setActiveJobsCount(active.active_jobs.length);
      }
    } catch (_) {
      setBackendConnected(false);
    }
  };

  useEffect(() => {
    checkHealthAndTasks();
    const interval = setInterval(checkHealthAndTasks, 6000);
    return () => clearInterval(interval);
  }, []);

  const renderCurrentPage = () => {
    switch (activePage) {
      case 'overview':
        return <Overview onNavigate={setActivePage} showToast={showToast} />;
      case 'discover':
        return <Discover onNavigate={setActivePage} showToast={showToast} />;
      case 'video-downloads':
        return <VideoDownloads onNavigate={setActivePage} showToast={showToast} />;
      case 'nature-reels':
        return <NatureReelMaker showToast={showToast} />;
      case 'instagram-audio':
        return <InstagramAudio onNavigate={setActivePage} showToast={showToast} />;
      case 'processing-queue':
        return <ProcessingQueue showToast={showToast} />;
      case 'library':
        return <Library showToast={showToast} />;
      case 'google-drive':
        return <GoogleDrive showToast={showToast} />;
      case 'settings':
        return <Settings showToast={showToast} />;
      default:
        return <Overview onNavigate={setActivePage} showToast={showToast} />;
    }
  };

  return (
    <div className="app-container">
      {/* Sidebar Navigation */}
      <Sidebar
        activePage={activePage}
        onNavigate={setActivePage}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed((prev) => !prev)}
        isMobileOpen={isMobileOpen}
        onCloseMobile={() => setIsMobileOpen(false)}
        backendConnected={backendConnected}
        activeJobsCount={activeJobsCount}
      />

      {/* Main Content Area */}
      <div className={`main-wrapper ${isSidebarCollapsed ? 'collapsed' : ''}`}>
        <TopNav
          activePage={activePage}
          onOpenMobile={() => setIsMobileOpen(true)}
          activeJobsCount={activeJobsCount}
          backendConnected={backendConnected}
          onQuickAction={setActivePage}
        />

        <main style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          {renderCurrentPage()}
        </main>
      </div>

      {/* Global Toast Stack */}
      {toasts.length > 0 && (
        <div className="toast-container">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={`toast ${
                toast.type === 'error'
                  ? 'toast-error'
                  : toast.type === 'success'
                  ? 'toast-success'
                  : ''
              }`}
            >
              {toast.type === 'error' && <AlertCircle size={16} />}
              {toast.type === 'success' && <CheckCircle2 size={16} />}
              {toast.type === 'info' && <Info size={16} />}
              <span style={{ flex: 1 }}>{toast.message}</span>
              <button
                onClick={() => removeToast(toast.id)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'inherit',
                  cursor: 'pointer',
                  padding: '2px',
                  display: 'flex',
                }}
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default App;
