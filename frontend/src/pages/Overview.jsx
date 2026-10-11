import React, { useState, useEffect } from 'react';
import {
  FileVideo,
  CheckCircle2,
  AlertCircle,
  CloudUpload,
  Layers,
  ArrowRight,
  RefreshCw,
  Compass,
  Music2,
  ExternalLink,
  HardDrive,
} from 'lucide-react';
import StatCard from '../components/StatCard';
import SourceBadge from '../components/SourceBadge';
import StatusBadge from '../components/StatusBadge';
import api from '../api/client';

export function Overview({ onNavigate, showToast }) {
  const [stats, setStats] = useState(null);
  const [recentJobs, setRecentJobs] = useState([]);
  const [activeJobs, setActiveJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = async () => {
    try {
      const [statsData, jobsData, activeData] = await Promise.all([
        api.getStats().catch(() => null),
        api.getJobs({ limit: 8 }).catch(() => ({ jobs: [] })),
        api.getActiveJobs().catch(() => ({ active_jobs: [] })),
      ]);

      if (statsData) setStats(statsData);
      if (jobsData && jobsData.jobs) setRecentJobs(jobsData.jobs);
      if (activeData && activeData.active_jobs) setActiveJobs(activeData.active_jobs);
    } catch (err) {
      if (showToast) showToast(`Failed to load dashboard data: ${err.message}`, 'error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000); // Polling every 10s
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  const formatBytes = (bytes) => {
    if (!bytes || bytes === 0) return '0 MB';
    const mb = bytes / (1024 * 1024);
    if (mb > 1024) return `${(mb / 1024).toFixed(2)} GB`;
    return `${mb.toFixed(1)} MB`;
  };

  const formatDate = (isoString) => {
    if (!isoString) return '—';
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch (_) {
      return isoString;
    }
  };

  return (
    <div className="page-container">
      {/* Welcome Banner */}
      <div className="page-header">
        <div>
          <h1 className="page-title">PodFetch Asset Dashboard</h1>
          <p className="page-subtitle">
            Automated pipeline for YouTube, Pinterest, and Instagram trending audio with Google Drive sync.
          </p>
        </div>
        <div className="page-actions">
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleRefresh}
            disabled={refreshing}
          >
            <RefreshCw size={14} className={refreshing ? 'pulse-spinner' : ''} />
            <span>Refresh</span>
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => onNavigate('discover')}
          >
            <Compass size={14} />
            <span>Start Discovery</span>
          </button>
        </div>
      </div>

      {/* Real Statistics Cards */}
      <div className="metrics-grid">
        <StatCard
          label="Total Processed"
          value={stats ? stats.total_processed : null}
          subtext="Indexed media across all sources"
          icon={Layers}
          loading={loading}
        />
        <StatCard
          label="Drive Uploads"
          value={stats ? stats.uploaded : null}
          subtext="Synchronized to Google Drive"
          icon={CloudUpload}
          loading={loading}
          valueColor="var(--status-success)"
        />
        <StatCard
          label="Tasks In Progress"
          value={activeJobs ? activeJobs.length : 0}
          subtext="Live background workers"
          icon={RefreshCw}
          loading={loading}
          valueColor="var(--accent-primary)"
        />
        <StatCard
          label="Failed Tasks"
          value={stats ? stats.failed : null}
          subtext="Errors needing resolution"
          icon={AlertCircle}
          loading={loading}
          valueColor={stats && stats.failed > 0 ? 'var(--status-error)' : undefined}
        />
        <StatCard
          label="Total Media Size"
          value={stats ? formatBytes(stats.total_size_bytes) : '0 MB'}
          subtext="Storage footprint on disk"
          icon={HardDrive}
          loading={loading}
        />
      </div>

      {/* Quick Actions Grid */}
      <div style={{ marginBottom: '32px' }}>
        <h2 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-main)', marginBottom: '14px' }}>
          Quick Workflows
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
          <div
            className="card"
            style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: '8px' }}
            onClick={() => onNavigate('discover')}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: '#fee2e2', color: '#dc2626', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <FileVideo size={16} />
                </div>
                <span style={{ fontWeight: 600, fontSize: '14px' }}>Discover Videos</span>
              </div>
              <ArrowRight size={16} color="var(--text-subtle)" />
            </div>
            <p style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
              Search YouTube channels or Pinterest boards for fresh shorts and pins.
            </p>
          </div>

          <div
            className="card"
            style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: '8px' }}
            onClick={() => onNavigate('instagram-audio')}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: '#fae8ff', color: '#a855f7', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Music2 size={16} />
                </div>
                <span style={{ fontWeight: 600, fontSize: '14px' }}>Instagram Trending Audio</span>
              </div>
              <ArrowRight size={16} color="var(--text-subtle)" />
            </div>
            <p style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
              Scan trending music & sound tracks with rap-filtering and mood prioritization.
            </p>
          </div>

          <div
            className="card"
            style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: '8px' }}
            onClick={() => onNavigate('processing-queue')}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'var(--accent-primary-subtle)', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Layers size={16} />
                </div>
                <span style={{ fontWeight: 600, fontSize: '14px' }}>Processing Queue</span>
              </div>
              <ArrowRight size={16} color="var(--text-subtle)" />
            </div>
            <p style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
              Monitor live downloads, retry failed items, and inspect sync statuses.
            </p>
          </div>
        </div>
      </div>

      {/* Recent Activity Table */}
      <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
        <div style={{ padding: '18px 22px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h3 className="card-title">Recent Activity</h3>
            <p className="card-subtitle">Real records from downloads.db</p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => onNavigate('library')}>
            View All in Library <ArrowRight size={14} />
          </button>
        </div>

        {loading ? (
          <div style={{ padding: '24px' }}>
            <div className="skeleton" style={{ height: '24px', marginBottom: '12px' }} />
            <div className="skeleton" style={{ height: '24px', marginBottom: '12px' }} />
            <div className="skeleton" style={{ height: '24px' }} />
          </div>
        ) : recentJobs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon-wrap">
              <Layers size={24} />
            </div>
            <div className="empty-title">No Media Processed Yet</div>
            <div className="empty-desc">
              Start by discovering YouTube channels, Pinterest search terms, or Instagram audio.
            </div>
            <button className="btn btn-primary btn-sm" onClick={() => onNavigate('discover')}>
              Discover Media
            </button>
          </div>
        ) : (
          <div className="table-container" style={{ border: 'none' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Title / Media Name</th>
                  <th>Status</th>
                  <th>File Size</th>
                  <th>Created At</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {recentJobs.map((job) => (
                  <tr key={job.id}>
                    <td>
                      <SourceBadge platform={job.platform} />
                    </td>
                    <td>
                      <div className="truncate" style={{ fontWeight: 500 }} title={job.title || job.filename}>
                        {job.title || job.filename || 'Untitled Item'}
                      </div>
                      {job.filename && (
                        <div style={{ fontSize: '11px', color: 'var(--text-subtle)', fontFamily: 'var(--font-mono)' }}>
                          {job.filename}
                        </div>
                      )}
                    </td>
                    <td>
                      <StatusBadge status={job.status} />
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                      {formatBytes(job.file_size_bytes)}
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>
                      {formatDate(job.created_at)}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {job.drive_file_id ? (
                        <a
                          href={`https://drive.google.com/file/d/${job.drive_file_id}/view`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn btn-ghost btn-sm"
                          title="Open in Google Drive"
                          style={{ padding: '4px 8px' }}
                        >
                          <ExternalLink size={14} />
                          <span>Drive</span>
                        </a>
                      ) : (
                        <span style={{ fontSize: '12px', color: 'var(--text-disabled)' }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default Overview;
