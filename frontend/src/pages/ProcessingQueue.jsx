import React, { useState, useEffect } from 'react';
import {
  ListOrdered,
  RefreshCw,
  RotateCcw,
  Filter,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  Layers,
  Clock,
  Play,
} from 'lucide-react';
import SourceBadge from '../components/SourceBadge';
import StatusBadge from '../components/StatusBadge';
import api from '../api/client';

export function ProcessingQueue({ showToast }) {
  const [jobs, setJobs] = useState([]);
  const [activeJobs, setActiveJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [retrying, setRetrying] = useState(false);

  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [platformFilter, setPlatformFilter] = useState('');

  const fetchJobs = async () => {
    try {
      const [jobsData, activeData] = await Promise.all([
        api.getJobs({
          status: statusFilter || undefined,
          platform: platformFilter || undefined,
          limit: 50,
        }),
        api.getActiveJobs().catch(() => ({ active_jobs: [] })),
      ]);

      if (jobsData && jobsData.jobs) setJobs(jobsData.jobs);
      if (activeData && activeData.active_jobs) setActiveJobs(activeData.active_jobs);
    } catch (err) {
      if (showToast) showToast(`Failed to load queue: ${err.message}`, 'error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 8000); // 8s interval
    return () => clearInterval(interval);
  }, [statusFilter, platformFilter]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchJobs();
  };

  const handleRetryFailed = async () => {
    setRetrying(true);
    try {
      const res = await api.retryFailedJobs();
      showToast(res.message || 'Retrying failed jobs in background', 'success');
      fetchJobs();
    } catch (err) {
      showToast(`Retry failed: ${err.message}`, 'error');
    } finally {
      setRetrying(false);
    }
  };

  const formatBytes = (bytes) => {
    if (!bytes || bytes === 0) return '—';
    const mb = bytes / (1024 * 1024);
    if (mb > 1024) return `${(mb / 1024).toFixed(2)} GB`;
    return `${mb.toFixed(1)} MB`;
  };

  const formatDate = (isoString) => {
    if (!isoString) return '—';
    try {
      const d = new Date(isoString);
      return d.toLocaleDateString(undefined, {
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
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Processing Queue</h1>
          <p className="page-subtitle">
            Live background workers, task scheduling, and SQLite execution history.
          </p>
        </div>
        <div className="page-actions">
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleRetryFailed}
            disabled={retrying}
            title="Re-run all failed database records"
          >
            <RotateCcw size={14} className={retrying ? 'pulse-spinner' : ''} />
            <span>Retry Failed Jobs</span>
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleRefresh}
            disabled={refreshing}
          >
            <RefreshCw size={14} className={refreshing ? 'pulse-spinner' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Active Running Workers Section (if any) */}
      {activeJobs.length > 0 && (
        <div className="card" style={{ marginBottom: '24px', borderColor: 'var(--accent-primary-border)', background: 'var(--accent-primary-subtle)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <span className="pulse-spinner" />
            <h2 style={{ fontSize: '14.5px', fontWeight: 600, color: 'var(--accent-primary)' }}>
              Active Background Tasks ({activeJobs.length})
            </h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {activeJobs.map((task) => (
              <div
                key={task.job_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '10px 14px',
                  background: '#fff',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <SourceBadge platform={task.platform} />
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 600 }}>{task.title || 'Pipeline Task'}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-subtle)', fontFamily: 'var(--font-mono)' }}>
                      Job ID: {task.job_id} &bull; Started: {formatDate(task.started_at)}
                    </div>
                  </div>
                </div>
                <span className="badge badge-status-processing">
                  <Play size={11} /> Running
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filter Toolbar */}
      <div className="card" style={{ marginBottom: '24px', padding: '14px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Filter size={15} color="var(--text-muted)" />
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)' }}>Filters</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <select
              className="form-select"
              style={{ width: '160px', padding: '6px 10px', fontSize: '12.5px' }}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">All Statuses</option>
              <option value="UPLOADED">Uploaded</option>
              <option value="COMPLETED">Completed</option>
              <option value="DISCOVERED">Discovered</option>
              <option value="FAILED">Failed</option>
              <option value="SKIPPED">Skipped</option>
            </select>

            <select
              className="form-select"
              style={{ width: '160px', padding: '6px 10px', fontSize: '12.5px' }}
              value={platformFilter}
              onChange={(e) => setPlatformFilter(e.target.value)}
            >
              <option value="">All Platforms</option>
              <option value="youtube">YouTube</option>
              <option value="pinterest">Pinterest</option>
              <option value="instagram">Instagram Audio</option>
            </select>

            {(statusFilter || platformFilter) && (
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setStatusFilter('');
                  setPlatformFilter('');
                }}
              >
                Reset Filters
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Queue Table */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: '24px' }}>
            <div className="skeleton" style={{ height: '24px', marginBottom: '12px' }} />
            <div className="skeleton" style={{ height: '24px', marginBottom: '12px' }} />
            <div className="skeleton" style={{ height: '24px' }} />
          </div>
        ) : jobs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon-wrap">
              <ListOrdered size={24} />
            </div>
            <div className="empty-title">Queue is Empty</div>
            <div className="empty-desc">
              No jobs found matching your filters.
            </div>
          </div>
        ) : (
          <div className="table-container" style={{ border: 'none' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Source</th>
                  <th>Title / Media Name</th>
                  <th>Status</th>
                  <th>Size</th>
                  <th>Created At</th>
                  <th>Error / Detail</th>
                  <th style={{ textAlign: 'right' }}>Drive</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-subtle)' }}>
                      #{job.id}
                    </td>
                    <td>
                      <SourceBadge platform={job.platform} />
                    </td>
                    <td>
                      <div className="truncate" style={{ fontWeight: 500 }} title={job.title || job.filename}>
                        {job.title || job.filename || 'Untitled Task'}
                      </div>
                      {job.video_id && (
                        <div style={{ fontSize: '11px', color: 'var(--text-subtle)', fontFamily: 'var(--font-mono)' }}>
                          ID: {job.video_id}
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
                    <td>
                      {job.error_message ? (
                        <span style={{ fontSize: '11.5px', color: 'var(--status-error)', maxWidth: '240px', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={job.error_message}>
                          {job.error_message}
                        </span>
                      ) : (
                        <span style={{ fontSize: '12px', color: 'var(--text-disabled)' }}>—</span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {job.drive_file_id ? (
                        <a
                          href={`https://drive.google.com/file/d/${job.drive_file_id}/view`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn btn-ghost btn-sm"
                          title="Open uploaded file in Google Drive"
                          style={{ padding: '4px 8px' }}
                        >
                          <ExternalLink size={13} />
                          <span>View</span>
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

export default ProcessingQueue;
