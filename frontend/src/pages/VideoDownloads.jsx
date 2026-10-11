import React, { useState, useEffect } from 'react';
import {
  Video,
  Download,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  RefreshCw,
  CloudUpload,
  History,
} from 'lucide-react';
import { YoutubeIcon, PinterestIcon } from '../components/BrandIcons';
import SourceBadge from '../components/SourceBadge';
import StatusBadge from '../components/StatusBadge';
import api from '../api/client';

export function VideoDownloads({ showToast, onNavigate }) {
  const [platform, setPlatform] = useState('youtube');
  const [videoUrl, setVideoUrl] = useState('');
  const [customTitle, setCustomTitle] = useState('');
  const [uploadToDrive, setUploadToDrive] = useState(true);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  // History state
  const [history, setHistory] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(true);

  const fetchHistory = async () => {
    try {
      const data = await api.getJobs({ limit: 12 });
      if (data && data.jobs) {
        // filter for youtube / pinterest
        const videoJobs = data.jobs.filter(
          (j) => j.platform === 'youtube' || j.platform === 'pinterest'
        );
        setHistory(videoJobs);
      }
    } catch (err) {
      // silent or mild toast
    } finally {
      setLoadingHistory(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    const url = videoUrl.trim();
    if (!url) {
      setError('Please provide a video URL to download.');
      return;
    }

    // Basic validation
    if (platform === 'youtube' && !url.includes('youtube.com') && !url.includes('youtu.be')) {
      setError('The provided URL does not appear to be a valid YouTube link.');
      return;
    }
    if (platform === 'pinterest' && !url.includes('pinterest.com') && !url.includes('pin.it')) {
      setError('The provided URL does not appear to be a valid Pinterest link.');
      return;
    }

    setSubmitting(true);
    try {
      const res = await api.downloadVideo({
        url,
        platform,
        title: customTitle.trim() || undefined,
        upload_to_drive: uploadToDrive,
      });

      if (res.status === 'queued') {
        setSuccessMsg(`Task queued successfully (Job ID: ${res.job_id}). View live progress in Processing Queue.`);
        showToast('Download queued successfully!', 'success');
        setVideoUrl('');
        setCustomTitle('');
        fetchHistory();
      } else {
        setSuccessMsg(res.message || 'Download request received.');
        fetchHistory();
      }
    } catch (err) {
      setError(err.message);
      showToast(`Download failed: ${err.message}`, 'error');
    } finally {
      setSubmitting(false);
    }
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
          <h1 className="page-title">Video Downloads</h1>
          <p className="page-subtitle">
            Direct download workspace for YouTube shorts/videos and Pinterest clips with automated Google Drive upload.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary btn-sm" onClick={() => onNavigate('processing-queue')}>
            <span>Open Queue</span>
          </button>
        </div>
      </div>

      {/* Main Download Form Card */}
      <div className="card" style={{ maxWidth: '800px', marginBottom: '32px' }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'var(--accent-primary-subtle)', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Video size={16} />
            </div>
            <div>
              <h2 className="card-title">New Video Download Job</h2>
              <p className="card-subtitle">Executes yt-dlp / Pinterest downloader pipelines on backend</p>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          {/* Source Toggle */}
          <div className="form-group">
            <label className="form-label">Platform Source</label>
            <div style={{ display: 'flex', gap: '12px' }}>
              <button
                type="button"
                className={`btn ${platform === 'youtube' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ flex: 1 }}
                onClick={() => setPlatform('youtube')}
              >
                <YoutubeIcon size={16} />
                <span>YouTube Video / Short</span>
              </button>
              <button
                type="button"
                className={`btn ${platform === 'pinterest' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ flex: 1 }}
                onClick={() => setPlatform('pinterest')}
              >
                <PinterestIcon size={16} />
                <span>Pinterest Pin Video</span>
              </button>
            </div>
          </div>

          {/* URL Input */}
          <div className="form-group">
            <label className="form-label">Video URL</label>
            <input
              type="url"
              className="form-input"
              placeholder={
                platform === 'youtube'
                  ? 'https://www.youtube.com/watch?v=... or https://youtube.com/shorts/...'
                  : 'https://www.pinterest.com/pin/... or https://pin.it/...'
              }
              value={videoUrl}
              onChange={(e) => setVideoUrl(e.target.value)}
              required
            />
            <div className="form-help">
              Direct video URL from browser address bar or share link.
            </div>
          </div>

          {/* Optional Title Override */}
          <div className="form-group">
            <label className="form-label">Custom Title (Optional)</label>
            <input
              type="text"
              className="form-input"
              placeholder="Leave blank to use metadata title from video"
              value={customTitle}
              onChange={(e) => setCustomTitle(e.target.value)}
            />
          </div>

          {/* Drive Upload Toggle */}
          <div className="form-group" style={{ marginBottom: '24px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', padding: '12px', background: 'var(--bg-surface-subtle)', borderRadius: 'var(--radius-md)' }}>
              <input
                type="checkbox"
                checked={uploadToDrive}
                onChange={(e) => setUploadToDrive(e.target.checked)}
                style={{ accentColor: 'var(--accent-primary)', width: '16px', height: '16px' }}
              />
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CloudUpload size={16} color="var(--accent-primary)" />
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)' }}>
                    Upload to Google Drive
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Synchronize downloaded video file directly to configured folder upon completion.
                  </div>
                </div>
              </div>
            </label>
          </div>

          {/* Feedback states */}
          {error && (
            <div style={{ padding: '12px 16px', background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)', borderRadius: 'var(--radius-md)', color: 'var(--status-error)', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px', fontSize: '13px' }}>
              <AlertCircle size={16} style={{ flexShrink: 0 }} />
              <div>{error}</div>
            </div>
          )}

          {successMsg && (
            <div style={{ padding: '12px 16px', background: 'var(--status-success-bg)', border: '1px solid var(--status-success-border)', borderRadius: 'var(--radius-md)', color: 'var(--status-success)', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px', fontSize: '13px' }}>
              <CheckCircle2 size={16} style={{ flexShrink: 0 }} />
              <div>{successMsg}</div>
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting}
            style={{ width: '100%', padding: '11px' }}
          >
            <Download size={16} className={submitting ? 'pulse-spinner' : ''} />
            <span>{submitting ? 'Initiating Pipeline...' : 'Start Download'}</span>
          </button>
        </form>
      </div>

      {/* Video Downloads History */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '18px 22px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <History size={16} color="var(--text-muted)" />
            <h3 className="card-title">Recent Video Downloads</h3>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={fetchHistory}>
            <RefreshCw size={13} />
            <span>Refresh History</span>
          </button>
        </div>

        {loadingHistory ? (
          <div style={{ padding: '24px' }}>
            <div className="skeleton" style={{ height: '24px', marginBottom: '10px' }} />
            <div className="skeleton" style={{ height: '24px' }} />
          </div>
        ) : history.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon-wrap">
              <Video size={24} />
            </div>
            <div className="empty-title">No Video Downloads Yet</div>
            <div className="empty-desc">
              Submit a YouTube or Pinterest link above to initiate your first download.
            </div>
          </div>
        ) : (
          <div className="table-container" style={{ border: 'none' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Title / File</th>
                  <th>Status</th>
                  <th>Created At</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {history.map((job) => (
                  <tr key={job.id}>
                    <td>
                      <SourceBadge platform={job.platform} />
                    </td>
                    <td>
                      <div className="truncate" style={{ fontWeight: 500 }} title={job.title || job.filename}>
                        {job.title || job.filename || 'Untitled Media'}
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
        )}
      </div>
    </div>
  );
}

export default VideoDownloads;
