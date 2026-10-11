import React, { useState, useEffect } from 'react';
import {
  Cloud,
  CheckCircle2,
  AlertCircle,
  Folder,
  FileCheck,
  ExternalLink,
  RefreshCw,
  HardDrive,
  ShieldCheck,
  FileText,
} from 'lucide-react';
import SourceBadge from '../components/SourceBadge';
import api from '../api/client';

export function GoogleDrive({ showToast }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const data = await api.getDriveStatus();
      setStatus(data);
    } catch (err) {
      if (showToast) showToast(`Failed to load Google Drive status: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

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
          <h1 className="page-title">Google Drive Integration</h1>
          <p className="page-subtitle">
            Cloud synchronization destination for YouTube videos, Pinterest clips, and Instagram audio assets.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary btn-sm" onClick={fetchStatus} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'pulse-spinner' : ''} />
            <span>Refresh Health</span>
          </button>
        </div>
      </div>

      {/* Connection & Configuration Overview */}
      <div className="card" style={{ marginBottom: '28px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{ width: '42px', height: '42px', borderRadius: '10px', background: 'var(--accent-secondary-subtle)', color: 'var(--accent-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Cloud size={22} />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-main)' }}>
                  Google Drive Cloud Storage
                </span>
                {status?.configured ? (
                  <span className="badge badge-status-completed">
                    <CheckCircle2 size={12} /> Connected
                  </span>
                ) : (
                  <span className="badge badge-status-failed">
                    <AlertCircle size={12} /> Needs Setup
                  </span>
                )}
              </div>
              <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '2px' }}>
                Automated uploads enabled via OAuth Service / Client Credentials
              </div>
            </div>
          </div>

          {status?.configured && status.folder_id && (
            <a
              href={`https://drive.google.com/drive/folders/${status.folder_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-secondary btn-sm"
            >
              <ExternalLink size={14} />
              <span>Open Root Folder in Drive</span>
            </a>
          )}
        </div>

        {/* Configuration Matrix */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-subtle)', marginBottom: '4px' }}>Configured Root Folder</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 600, color: 'var(--text-main)', background: 'var(--bg-surface-subtle)', padding: '6px 10px', borderRadius: 'var(--radius-sm)' }}>
              {status?.folder_id || 'Not specified in .env'}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-subtle)', marginBottom: '4px' }}>OAuth Credentials</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: status?.credentials_present ? 'var(--status-success)' : 'var(--status-error)', fontWeight: 500, padding: '6px 0' }}>
              {status?.credentials_present ? <ShieldCheck size={16} /> : <AlertCircle size={16} />}
              <span>{status?.credentials_present ? 'credentials.json active' : 'Missing credentials.json'}</span>
            </div>
          </div>

          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-subtle)', marginBottom: '4px' }}>Drive Token</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: status?.token_present ? 'var(--status-success)' : 'var(--status-warning)', fontWeight: 500, padding: '6px 0' }}>
              {status?.token_present ? <ShieldCheck size={16} /> : <AlertCircle size={16} />}
              <span>{status?.token_present ? 'token.json verified' : 'No cached token.json'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Target Folder Hierarchy Card */}
      <div className="card" style={{ marginBottom: '28px' }}>
        <h2 className="card-title" style={{ marginBottom: '14px' }}>Configured Target Subfolders</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', padding: '16px', borderRadius: 'var(--radius-md)', background: 'var(--bg-surface-subtle)' }}>
            <Folder size={22} color="var(--accent-primary)" style={{ flexShrink: 0, marginTop: '2px' }} />
            <div>
              <div style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--text-main)' }}>Podcasts</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                Default upload destination for YouTube videos, shorts, and Pinterest clips.
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', padding: '16px', borderRadius: 'var(--radius-md)', background: 'var(--bg-surface-subtle)' }}>
            <Folder size={22} color="#a855f7" style={{ flexShrink: 0, marginTop: '2px' }} />
            <div>
              <div style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--text-main)' }}>trending songs</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                Dedicated folder created for Instagram trending audio MP3 assets and metadata.
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Recent Uploaded Files */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '18px 22px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h3 className="card-title">Recent Cloud Uploads</h3>
            <p className="card-subtitle">Media files synchronized to your Google Drive</p>
          </div>
        </div>

        {loading ? (
          <div style={{ padding: '24px' }}>
            <div className="skeleton" style={{ height: '24px', marginBottom: '10px' }} />
            <div className="skeleton" style={{ height: '24px' }} />
          </div>
        ) : !status?.recent_uploads || status.recent_uploads.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon-wrap">
              <Cloud size={24} />
            </div>
            <div className="empty-title">No Uploads Recorded Yet</div>
            <div className="empty-desc">
              When downloads complete with Drive sync enabled, uploaded files will appear here with direct Drive links.
            </div>
          </div>
        ) : (
          <div className="table-container" style={{ border: 'none' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Title / Media Name</th>
                  <th>File Size</th>
                  <th>Uploaded Date</th>
                  <th>Drive ID</th>
                  <th style={{ textAlign: 'right' }}>Drive Link</th>
                </tr>
              </thead>
              <tbody>
                {status.recent_uploads.map((upload) => (
                  <tr key={upload.id}>
                    <td>
                      <SourceBadge platform={upload.platform} />
                    </td>
                    <td>
                      <div className="truncate" style={{ fontWeight: 500 }} title={upload.title || upload.filename}>
                        {upload.title || upload.filename || 'Uploaded File'}
                      </div>
                      {upload.filename && (
                        <div style={{ fontSize: '11px', color: 'var(--text-subtle)', fontFamily: 'var(--font-mono)' }}>
                          {upload.filename}
                        </div>
                      )}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                      {formatBytes(upload.file_size_bytes)}
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>
                      {formatDate(upload.created_at)}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-subtle)' }}>
                      {upload.drive_file_id ? upload.drive_file_id.slice(0, 16) + '...' : '—'}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {upload.drive_file_id ? (
                        <a
                          href={`https://drive.google.com/file/d/${upload.drive_file_id}/view`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn btn-secondary btn-sm"
                          style={{ padding: '4px 10px' }}
                        >
                          <ExternalLink size={13} />
                          <span>Open</span>
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

export default GoogleDrive;
