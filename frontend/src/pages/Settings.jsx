import React, { useState, useEffect } from 'react';
import {
  Settings as SettingsIcon,
  CheckCircle2,
  AlertCircle,
  ShieldCheck,
  Terminal,
  RefreshCw,
  Folder,
  Layers,
  Music2,
  Sliders,
} from 'lucide-react';
import api from '../api/client';

export function Settings({ showToast }) {
  const [settings, setSettings] = useState(null);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingLogs, setLoadingLogs] = useState(false);

  const fetchSettings = async () => {
    try {
      const data = await api.getSettings();
      setSettings(data);
    } catch (err) {
      if (showToast) showToast(`Failed to load settings: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const fetchLogs = async () => {
    setLoadingLogs(true);
    try {
      const data = await api.getLogs(80);
      setLogs(data.logs || []);
    } catch (err) {
      // silent
    } finally {
      setLoadingLogs(false);
    }
  };

  useEffect(() => {
    fetchSettings();
    fetchLogs();
  }, []);

  return (
    <div className="page-container">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Settings & Diagnostics</h1>
          <p className="page-subtitle">
            Configuration parameters, active processing rules, and real-time backend operational logs.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary btn-sm" onClick={fetchLogs} disabled={loadingLogs}>
            <RefreshCw size={13} className={loadingLogs ? 'pulse-spinner' : ''} />
            <span>Refresh Logs</span>
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '28px' }}>
        {/* Source Configuration Status */}
        <div className="card">
          <div className="card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'var(--accent-primary-subtle)', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Layers size={16} />
              </div>
              <div>
                <h2 className="card-title">Media Sources Configuration</h2>
                <p className="card-subtitle">Active integrations read from config.py and .env</p>
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
            <div style={{ padding: '16px', background: 'var(--bg-surface-subtle)', borderRadius: 'var(--radius-md)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ fontWeight: 600, fontSize: '13.5px' }}>YouTube Downloader</span>
                <span className="badge badge-status-completed">
                  <CheckCircle2 size={12} /> Active
                </span>
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                yt-dlp extraction with automatic audio/video merge and SQLite deduplication.
              </div>
            </div>

            <div style={{ padding: '16px', background: 'var(--bg-surface-subtle)', borderRadius: 'var(--radius-md)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ fontWeight: 600, fontSize: '13.5px' }}>Pinterest Scraper</span>
                <span className="badge badge-status-completed">
                  <CheckCircle2 size={12} /> Active
                </span>
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Keyword search and public pin video extraction pipeline.
              </div>
            </div>

            <div style={{ padding: '16px', background: 'var(--bg-surface-subtle)', borderRadius: 'var(--radius-md)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ fontWeight: 600, fontSize: '13.5px' }}>Instagram Audio</span>
                {settings?.instagram?.enabled ? (
                  <span className="badge badge-status-completed">
                    <CheckCircle2 size={12} /> Active
                  </span>
                ) : (
                  <span className="badge badge-status-failed">
                    <AlertCircle size={12} /> Inactive
                  </span>
                )}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Trending audio pipeline targeting Drive folder: <strong>trending songs</strong>.
              </div>
            </div>
          </div>
        </div>

        {/* Processing Rules & Video Filter */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '24px' }}>
          {/* Video Filter Rules */}
          <div className="card">
            <div className="card-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Sliders size={18} color="var(--accent-primary)" />
                <h3 className="card-title">Video Filter Parameters</h3>
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '13px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Duration Bounds</span>
                <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                  {settings?.video_filter?.min_duration ?? 5}s &mdash; {settings?.video_filter?.max_duration ?? 300}s
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '13px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Max Video Size</span>
                <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                  {settings?.video_filter?.max_video_size_mb ?? 500} MB
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '13px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Minimum Resolution</span>
                <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                  {settings?.video_filter?.min_resolution ?? '720p'}
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', fontSize: '13px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Max Videos per Channel</span>
                <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                  {settings?.video_filter?.max_videos_per_channel ?? 10}
                </span>
              </div>
            </div>
          </div>

          {/* Instagram Audio Preference Rules */}
          <div className="card">
            <div className="card-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Music2 size={18} color="#a855f7" />
                <h3 className="card-title">Audio Filtering Rules</h3>
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '13px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Target Drive Folder</span>
                <span style={{ fontWeight: 600, color: '#a855f7' }}>
                  {settings?.instagram?.drive_folder_name || 'trending songs'}
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '13px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Avoid Rap / High BPM</span>
                <span style={{ fontWeight: 600, color: 'var(--status-success)' }}>
                  Enabled (Avoid fast rap / poetry)
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '13px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Mood Priority</span>
                <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>
                  Soft / Sad / Emotional First
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', fontSize: '13px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Manifest Cache</span>
                <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                  audio_manifest.json
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Live System Diagnostics Logs */}
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Terminal size={16} color="var(--text-muted)" />
              <h3 className="card-title">Backend Diagnostics & Event Logs</h3>
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-subtle)', fontFamily: 'var(--font-mono)' }}>
              logs/podfetch.log
            </div>
          </div>

          <div style={{ padding: '16px', background: '#09090b', minHeight: '240px', maxHeight: '420px', overflowY: 'auto' }}>
            {logs.length === 0 ? (
              <div style={{ color: '#71717a', fontFamily: 'var(--font-mono)', fontSize: '12px', textAlign: 'center', paddingTop: '40px' }}>
                No log output recorded yet in logs/podfetch.log.
              </div>
            ) : (
              <pre style={{ color: '#e4e4e7', fontFamily: 'var(--font-mono)', fontSize: '11.5px', lineHeight: 1.5, margin: 0, whiteSpace: 'pre-wrap' }}>
                {logs.join('\n')}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default Settings;
