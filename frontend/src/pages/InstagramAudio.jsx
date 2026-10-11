import React, { useState, useEffect } from 'react';
import {
  Music2,
  Play,
  Download,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  Radio,
  Clock,
  User,
  SlidersHorizontal,
} from 'lucide-react';
import SourceBadge from '../components/SourceBadge';
import AudioPlayerModal from '../components/AudioPlayerModal';
import api from '../api/client';

export function InstagramAudio({ showToast, onNavigate }) {
  const [status, setStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);

  // Discovery parameters
  const [audioType, setAudioType] = useState('music');
  const [limit, setLimit] = useState(12);
  const [sadPreference, setSadPreference] = useState(true);
  const [avoidRap, setAvoidRap] = useState(true);

  // Tracks list & fetching
  const [tracks, setTracks] = useState([]);
  const [loadingTracks, setLoadingTracks] = useState(false);
  const [error, setError] = useState(null);

  // Audio Preview Modal
  const [activePreviewTrack, setActivePreviewTrack] = useState(null);

  // Sync / Download state
  const [syncingTrackId, setSyncingTrackId] = useState(null);

  const fetchStatus = async () => {
    try {
      const data = await api.getInstagramStatus();
      setStatus(data);
    } catch (err) {
      // silent
    } finally {
      setLoadingStatus(false);
    }
  };

  const loadTrendingAudio = async () => {
    setLoadingTracks(true);
    setError(null);
    try {
      const data = await api.discoverInstagram({
        audio_type: audioType,
        limit: Number(limit) || 12,
        sad_preference: sadPreference,
        avoid_rap: avoidRap,
      });

      if (data.status === 'error') {
        setError(data.message || 'Instagram discovery error');
      } else {
        setTracks(data.tracks || []);
        if (data.tracks?.length === 0) {
          showToast('No audio tracks returned by Instagram API for current criteria', 'info');
        } else {
          showToast(`Loaded ${data.tracks.length} audio tracks`, 'success');
        }
      }
    } catch (err) {
      setError(err.message);
      showToast(`Instagram discovery failed: ${err.message}`, 'error');
    } finally {
      setLoadingTracks(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    loadTrendingAudio();
  }, [audioType]);

  const handleSyncTrack = async (track) => {
    const trackId = track.audio_asset_id || track.id;
    setSyncingTrackId(trackId);
    try {
      const res = await api.downloadInstagramAudio({
        audio_asset_id: trackId,
        audio_url: track.audio_url || track.preview_url,
        title: track.title,
        artist: track.artist_name,
        upload_to_drive: true,
      });

      if (res.status === 'queued') {
        showToast(`Sync queued: "${track.title}". Will upload to Drive "trending songs"`, 'success');
      } else {
        showToast(res.message || 'Download started', 'info');
      }
    } catch (err) {
      showToast(`Sync failed: ${err.message}`, 'error');
    } finally {
      setSyncingTrackId(null);
    }
  };

  return (
    <div className="page-container">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Instagram Audio</h1>
          <p className="page-subtitle">
            Discover supported music and original audio through the configured Instagram integration.
          </p>
        </div>
        <div className="page-actions">
          <button
            className="btn btn-secondary btn-sm"
            onClick={loadTrendingAudio}
            disabled={loadingTracks}
          >
            <RefreshCw size={14} className={loadingTracks ? 'pulse-spinner' : ''} />
            <span>Refresh Audio Feed</span>
          </button>
        </div>
      </div>

      {/* Integration Connection Status Panel */}
      <div className="card" style={{ marginBottom: '28px', background: '#fafafa' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: '#fae8ff', color: '#a855f7', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Music2 size={20} />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '14.5px', fontWeight: 600, color: 'var(--text-main)' }}>
                  Instagram Graph API Integration
                </span>
                {status?.configured ? (
                  <span className="badge badge-status-completed">
                    <CheckCircle2 size={12} /> Connected
                  </span>
                ) : (
                  <span className="badge badge-status-failed">
                    <AlertCircle size={12} /> Unconfigured
                  </span>
                )}
              </div>
              <div style={{ fontSize: '12.5px', color: 'var(--text-muted)', marginTop: '2px' }}>
                Target Drive Folder: <strong style={{ color: 'var(--text-main)' }}>trending songs</strong>
                {status?.account_id && (
                  <span> &bull; Account ID: <code style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', background: '#f4f4f5', padding: '2px 5px', borderRadius: '4px' }}>{status.account_id}</code></span>
                )}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-subtle)' }}>
              <ShieldCheck size={14} color="var(--status-success)" />
              <span>Token Validated</span>
            </div>
          </div>
        </div>
      </div>

      {/* Controls & Filter Bar */}
      <div className="card" style={{ marginBottom: '28px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
          {/* Audio Type Selector */}
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              className={`btn btn-sm ${audioType === 'music' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setAudioType('music')}
            >
              <Music2 size={14} />
              <span>Commercial Music</span>
            </button>
            <button
              className={`btn btn-sm ${audioType === 'original' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setAudioType('original')}
            >
              <Radio size={14} />
              <span>Original Sound</span>
            </button>
          </div>

          {/* Preferences */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '20px', flexWrap: 'wrap' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '12.5px', color: 'var(--text-main)' }}>
              <input
                type="checkbox"
                checked={sadPreference}
                onChange={(e) => setSadPreference(e.target.checked)}
                style={{ accentColor: 'var(--accent-primary)' }}
              />
              <span>Prioritize Sad/Soft Mood</span>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '12.5px', color: 'var(--text-main)' }}>
              <input
                type="checkbox"
                checked={avoidRap}
                onChange={(e) => setAvoidRap(e.target.checked)}
                style={{ accentColor: 'var(--accent-primary)' }}
              />
              <span>Avoid Rap / High BPM</span>
            </label>
            <button
              className="btn btn-secondary btn-sm"
              onClick={loadTrendingAudio}
              disabled={loadingTracks}
            >
              <SlidersHorizontal size={13} />
              <span>Apply Filters</span>
            </button>
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div style={{ padding: '16px 20px', background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)', borderRadius: 'var(--radius-md)', color: 'var(--status-error)', display: 'flex', alignItems: 'flex-start', gap: '12px', marginBottom: '24px' }}>
          <AlertCircle size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>
            <div style={{ fontWeight: 600, fontSize: '13.5px', marginBottom: '2px' }}>
              Instagram Audio API Notice
            </div>
            <div style={{ fontSize: '12.5px', lineHeight: 1.4 }}>{error}</div>
          </div>
        </div>
      )}

      {/* Loading Skeletons */}
      {loadingTracks && (
        <div className="media-grid">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div className="skeleton" style={{ height: '140px', width: '100%' }} />
              <div style={{ padding: '16px' }}>
                <div className="skeleton" style={{ height: '18px', width: '75%', marginBottom: '8px' }} />
                <div className="skeleton" style={{ height: '14px', width: '45%' }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty State */}
      {!loadingTracks && tracks.length === 0 && !error && (
        <div className="empty-state card">
          <div className="empty-icon-wrap">
            <Music2 size={24} />
          </div>
          <div className="empty-title">No Audio Tracks Available</div>
          <div className="empty-desc">
            The Instagram API did not return any trending audio assets for this query. Check your token or adjust filter settings.
          </div>
          <button className="btn btn-primary btn-sm" onClick={loadTrendingAudio}>
            Retry Request
          </button>
        </div>
      )}

      {/* Audio Tracks Grid */}
      {!loadingTracks && tracks.length > 0 && (
        <div className="media-grid">
          {tracks.map((track, idx) => {
            const trackId = track.audio_asset_id || track.id || idx;
            const hasPlayableUrl = Boolean(track.audio_url || track.preview_url);
            const isSyncing = syncingTrackId === trackId;

            return (
              <div key={trackId} className="media-card">
                <div className="media-thumb-wrap" style={{ height: '140px' }}>
                  {track.thumbnail ? (
                    <img src={track.thumbnail} alt={track.title} className="media-thumb" loading="lazy" />
                  ) : (
                    <div className="media-thumb-placeholder">
                      <Music2 size={38} color="#a855f7" />
                    </div>
                  )}

                  {/* Trend Rank Pill */}
                  <div style={{ position: 'absolute', top: '10px', left: '10px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 600, background: 'rgba(0,0,0,0.65)', color: '#fff', padding: '2px 8px', borderRadius: '4px', backdropFilter: 'blur(4px)' }}>
                      #{idx + 1} Trending
                    </span>
                  </div>

                  {/* Play preview trigger */}
                  {hasPlayableUrl ? (
                    <button
                      onClick={() => setActivePreviewTrack(track)}
                      style={{
                        position: 'absolute',
                        bottom: '10px',
                        right: '10px',
                        width: '38px',
                        height: '38px',
                        borderRadius: '50%',
                        background: 'var(--accent-primary)',
                        color: '#fff',
                        border: 'none',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        boxShadow: '0 2px 6px rgba(0,0,0,0.3)',
                      }}
                      title="Play Preview"
                    >
                      <Play size={16} style={{ marginLeft: '2px' }} />
                    </button>
                  ) : (
                    <div
                      style={{
                        position: 'absolute',
                        bottom: '10px',
                        right: '10px',
                        fontSize: '10.5px',
                        background: 'rgba(0,0,0,0.5)',
                        color: '#e4e4e7',
                        padding: '2px 6px',
                        borderRadius: '4px',
                      }}
                    >
                      Metadata Only
                    </div>
                  )}
                </div>

                <div className="media-card-body">
                  <div className="media-card-title" title={track.title}>
                    {track.title || 'Untitled Audio'}
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: 'var(--text-subtle)' }}>
                    <User size={13} />
                    <span className="truncate">{track.artist_name || track.artist || 'Original Creator'}</span>
                  </div>

                  {track.duration ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: 'var(--text-subtle)' }}>
                      <Clock size={13} />
                      <span>{Math.round(track.duration)}s</span>
                    </div>
                  ) : null}

                  <div className="media-card-meta">
                    <span style={{ fontSize: '11px', color: 'var(--text-subtle)', fontFamily: 'var(--font-mono)' }}>
                      ID: {String(trackId).slice(0, 10)}
                    </span>

                    <button
                      className="btn btn-primary btn-sm"
                      disabled={isSyncing}
                      onClick={() => handleSyncTrack(track)}
                      title="Download audio and upload to Google Drive 'trending songs' folder"
                    >
                      <Download size={13} className={isSyncing ? 'pulse-spinner' : ''} />
                      <span>{isSyncing ? 'Syncing...' : 'Sync to Drive'}</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Audio Player Modal */}
      {activePreviewTrack && (
        <AudioPlayerModal
          track={activePreviewTrack}
          onClose={() => setActivePreviewTrack(null)}
          onDownload={(t) => handleSyncTrack(t)}
        />
      )}
    </div>
  );
}

export default InstagramAudio;
