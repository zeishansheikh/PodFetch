import React, { useState, useEffect } from 'react';
import {
  FolderArchive,
  Search,
  LayoutGrid,
  List,
  Filter,
  ExternalLink,
  HardDrive,
  Clock,
  User,
  RefreshCw,
  FileVideo,
  Music2,
} from 'lucide-react';
import SourceBadge from '../components/SourceBadge';
import StatusBadge from '../components/StatusBadge';
import api from '../api/client';

export function Library({ showToast }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  // View Mode: 'grid' or 'list'
  const [viewMode, setViewMode] = useState('grid');

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [platformFilter, setPlatformFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const fetchLibrary = async () => {
    setLoading(true);
    try {
      const data = await api.getLibrary({
        search: searchTerm || undefined,
        platform: platformFilter || undefined,
        status: statusFilter || undefined,
        limit: 48,
      });

      if (data) {
        setItems(data.items || []);
        setTotal(data.total || 0);
      }
    } catch (err) {
      if (showToast) showToast(`Failed to load library: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const delayDebounce = setTimeout(() => {
      fetchLibrary();
    }, 250);
    return () => clearTimeout(delayDebounce);
  }, [searchTerm, platformFilter, statusFilter]);

  const formatBytes = (bytes) => {
    if (!bytes || bytes === 0) return '0 MB';
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
        year: 'numeric',
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
          <h1 className="page-title">Media Library</h1>
          <p className="page-subtitle">
            Archive of processed assets across YouTube, Pinterest, and Instagram with Drive records ({total} items indexed).
          </p>
        </div>
        <div className="page-actions">
          {/* Grid / List View Toggle */}
          <div style={{ display: 'flex', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '2px' }}>
            <button
              className="btn btn-ghost btn-sm"
              style={{
                padding: '6px 10px',
                background: viewMode === 'grid' ? 'var(--bg-surface-subtle)' : 'transparent',
                color: viewMode === 'grid' ? 'var(--text-main)' : 'var(--text-subtle)',
              }}
              onClick={() => setViewMode('grid')}
              title="Grid View"
            >
              <LayoutGrid size={15} />
            </button>
            <button
              className="btn btn-ghost btn-sm"
              style={{
                padding: '6px 10px',
                background: viewMode === 'list' ? 'var(--bg-surface-subtle)' : 'transparent',
                color: viewMode === 'list' ? 'var(--text-main)' : 'var(--text-subtle)',
              }}
              onClick={() => setViewMode('list')}
              title="List View"
            >
              <List size={15} />
            </button>
          </div>

          <button className="btn btn-secondary btn-sm" onClick={fetchLibrary}>
            <RefreshCw size={13} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="card" style={{ marginBottom: '24px', padding: '14px 20px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: '14px', alignItems: 'center' }}>
          <div className="input-with-icon">
            <Search className="input-icon" />
            <input
              type="text"
              className="form-input"
              placeholder="Search by title, creator, or filename..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>

          <select
            className="form-select"
            style={{ width: '160px', padding: '8px 12px', fontSize: '13px' }}
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value)}
          >
            <option value="">All Sources</option>
            <option value="youtube">YouTube</option>
            <option value="pinterest">Pinterest</option>
            <option value="instagram">Instagram Audio</option>
          </select>

          <select
            className="form-select"
            style={{ width: '160px', padding: '8px 12px', fontSize: '13px' }}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">All Statuses</option>
            <option value="UPLOADED">Uploaded to Drive</option>
            <option value="COMPLETED">Completed</option>
            <option value="DISCOVERED">Discovered</option>
            <option value="FAILED">Failed</option>
            <option value="SKIPPED">Skipped</option>
          </select>
        </div>
      </div>

      {/* Content Rendering */}
      {loading ? (
        <div className="media-grid">
          {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <div key={i} className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div className="skeleton" style={{ height: '150px' }} />
              <div style={{ padding: '16px' }}>
                <div className="skeleton" style={{ height: '16px', width: '80%', marginBottom: '8px' }} />
                <div className="skeleton" style={{ height: '14px', width: '45%' }} />
              </div>
            </div>
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state card">
          <div className="empty-icon-wrap">
            <FolderArchive size={24} />
          </div>
          <div className="empty-title">No Media Matches Found</div>
          <div className="empty-desc">
            Try clearing search filters or initiate a discovery scan to index new assets.
          </div>
        </div>
      ) : viewMode === 'grid' ? (
        <div className="media-grid">
          {items.map((item) => {
            const isAudio = item.platform === 'instagram_audio';

            return (
              <div key={item.id} className="media-card">
                <div className="media-thumb-wrap">
                  {item.thumbnail ? (
                    <img src={item.thumbnail} alt={item.title} className="media-thumb" loading="lazy" />
                  ) : (
                    <div className="media-thumb-placeholder">
                      {isAudio ? <Music2 size={36} color="#a855f7" /> : <FileVideo size={36} />}
                    </div>
                  )}

                  {/* Status and Source Badges */}
                  <div style={{ position: 'absolute', top: '10px', left: '10px', display: 'flex', gap: '5px' }}>
                    <SourceBadge platform={item.platform} />
                  </div>
                  <div style={{ position: 'absolute', top: '10px', right: '10px' }}>
                    <StatusBadge status={item.status} />
                  </div>
                </div>

                <div className="media-card-body">
                  <div className="media-card-title" title={item.title || item.filename}>
                    {item.title || item.filename || 'Untitled Media'}
                  </div>

                  {item.filename && (
                    <div style={{ fontSize: '11px', color: 'var(--text-subtle)', fontFamily: 'var(--font-mono)' }} className="truncate" title={item.filename}>
                      {item.filename}
                    </div>
                  )}

                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    <span>{formatBytes(item.file_size_bytes)}</span>
                    <span>{formatDate(item.created_at)}</span>
                  </div>

                  <div className="media-card-meta">
                    {item.drive_file_id ? (
                      <a
                        href={`https://drive.google.com/file/d/${item.drive_file_id}/view`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn btn-secondary btn-sm"
                        style={{ width: '100%' }}
                      >
                        <ExternalLink size={13} />
                        <span>Open in Google Drive</span>
                      </a>
                    ) : item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn btn-ghost btn-sm"
                        style={{ width: '100%' }}
                      >
                        <ExternalLink size={13} />
                        <span>View Source URL</span>
                      </a>
                    ) : (
                      <span style={{ fontSize: '11.5px', color: 'var(--text-disabled)', width: '100%', textAlign: 'center' }}>
                        Local Database Record
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* List View */
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="table-container" style={{ border: 'none' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Title / Filename</th>
                  <th>Status</th>
                  <th>Size</th>
                  <th>Created</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <SourceBadge platform={item.platform} />
                    </td>
                    <td>
                      <div className="truncate" style={{ fontWeight: 500 }} title={item.title || item.filename}>
                        {item.title || item.filename || 'Untitled Record'}
                      </div>
                      {item.filename && (
                        <div style={{ fontSize: '11px', color: 'var(--text-subtle)', fontFamily: 'var(--font-mono)' }}>
                          {item.filename}
                        </div>
                      )}
                    </td>
                    <td>
                      <StatusBadge status={item.status} />
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                      {formatBytes(item.file_size_bytes)}
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>
                      {formatDate(item.created_at)}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {item.drive_file_id ? (
                        <a
                          href={`https://drive.google.com/file/d/${item.drive_file_id}/view`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn btn-ghost btn-sm"
                          style={{ padding: '4px 8px' }}
                        >
                          <ExternalLink size={13} />
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
        </div>
      )}
    </div>
  );
}

export default Library;
