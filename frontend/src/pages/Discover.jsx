import React, { useState } from 'react';
import {
  Search,
  Download,
  Clock,
  User,
  ExternalLink,
  AlertCircle,
  Play,
  RotateCcw,
} from 'lucide-react';
import { YoutubeIcon, PinterestIcon, InstagramIcon } from '../components/BrandIcons';
import SourceBadge from '../components/SourceBadge';
import AudioPlayerModal from '../components/AudioPlayerModal';
import api from '../api/client';

export function Discover({ showToast, onNavigate }) {
  const [activeTab, setActiveTab] = useState('youtube');

  // Input states
  const [youtubeChannel, setYoutubeChannel] = useState('');
  const [youtubeLimit, setYoutubeLimit] = useState(10);

  const [pinterestKeyword, setPinterestKeyword] = useState('');
  const [pinterestLimit, setPinterestLimit] = useState(10);

  const [instagramAudioType, setInstagramAudioType] = useState('music');
  const [instagramLimit, setInstagramLimit] = useState(10);
  const [instagramSadFirst, setInstagramSadFirst] = useState(true);
  const [instagramAvoidRap, setInstagramAvoidRap] = useState(true);

  // Results & status
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);

  // Audio Preview Modal
  const [previewTrack, setPreviewTrack] = useState(null);

  // Queue / Download action state
  const [processingId, setProcessingId] = useState(null);

  const handleSearch = async (e) => {
    if (e) e.preventDefault();
    setError(null);
    setLoading(true);
    setResults([]);
    setHasSearched(true);

    try {
      if (activeTab === 'youtube') {
        if (!youtubeChannel.trim()) {
          setError('Please provide at least one YouTube channel URL or ID (e.g., https://www.youtube.com/@TED).');
          setLoading(false);
          return;
        }
        const channels = youtubeChannel
          .split(/[\n,]+/)
          .map((c) => c.trim())
          .filter(Boolean);

        const data = await api.discoverYouTube({
          channels,
          max_videos: Number(youtubeLimit) || 10,
        });

        if (data.status === 'error') {
          setError(data.message || 'YouTube discovery failed');
        } else {
          setResults(data.discovered_videos || []);
          if (data.discovered_videos?.length === 0) {
            showToast('No new videos found matching filter criteria', 'info');
          } else {
            showToast(`Found ${data.discovered_videos.length} YouTube videos!`, 'success');
          }
        }
      } else if (activeTab === 'pinterest') {
        if (!pinterestKeyword.trim()) {
          setError('Please enter a Pinterest search keyword or board query.');
          setLoading(false);
          return;
        }

        const data = await api.discoverPinterest({
          keyword: pinterestKeyword.trim(),
          max_videos: Number(pinterestLimit) || 10,
        });

        if (data.status === 'error') {
          setError(data.message || 'Pinterest discovery failed');
        } else {
          setResults(data.discovered_videos || []);
          if (data.discovered_videos?.length === 0) {
            showToast('No new Pinterest videos found', 'info');
          } else {
            showToast(`Discovered ${data.discovered_videos.length} Pinterest videos!`, 'success');
          }
        }
      } else if (activeTab === 'instagram') {
        const data = await api.discoverInstagram({
          audio_type: instagramAudioType,
          limit: Number(instagramLimit) || 10,
          sad_preference: instagramSadFirst,
          avoid_rap: instagramAvoidRap,
        });

        if (data.status === 'error') {
          setError(data.message || 'Instagram audio discovery failed');
        } else {
          setResults(data.tracks || []);
          if (data.tracks?.length === 0) {
            showToast('No trending audio tracks returned from Instagram API', 'info');
          } else {
            showToast(`Loaded ${data.tracks.length} trending audio tracks!`, 'success');
          }
        }
      }
    } catch (err) {
      setError(err.message);
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadVideo = async (item) => {
    setProcessingId(item.video_id || item.url);
    try {
      const res = await api.downloadVideo({
        url: item.url,
        platform: item.platform || activeTab,
        title: item.title,
        upload_to_drive: true,
      });

      if (res.status === 'queued') {
        showToast(`Download task queued: ${item.title || 'Video'}`, 'success');
      } else {
        showToast(res.message || 'Download started', 'info');
      }
    } catch (err) {
      showToast(`Download failed: ${err.message}`, 'error');
    } finally {
      setProcessingId(null);
    }
  };

  const handleDownloadAudio = async (track) => {
    setProcessingId(track.audio_asset_id || track.id);
    try {
      const res = await api.downloadInstagramAudio({
        audio_asset_id: track.audio_asset_id || track.id,
        audio_url: track.audio_url || track.preview_url,
        title: track.title,
        artist: track.artist_name,
        upload_to_drive: true,
      });

      if (res.status === 'queued') {
        showToast(`Audio sync queued: ${track.title}`, 'success');
      } else {
        showToast(res.message || 'Audio task started', 'info');
      }
    } catch (err) {
      showToast(`Audio download failed: ${err.message}`, 'error');
    } finally {
      setProcessingId(null);
    }
  };

  const clearForm = () => {
    setResults([]);
    setError(null);
    setHasSearched(false);
    if (activeTab === 'youtube') setYoutubeChannel('');
    if (activeTab === 'pinterest') setPinterestKeyword('');
  };

  return (
    <div className="page-container">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Media Discovery</h1>
          <p className="page-subtitle">
            Query YouTube channels, Pinterest search terms, and Instagram trending audio feeds.
          </p>
        </div>
      </div>

      {/* Source Selection Tabs */}
      <div className="tabs-header">
        <button
          className={`tab-btn ${activeTab === 'youtube' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('youtube');
            setResults([]);
            setError(null);
            setHasSearched(false);
          }}
        >
          <YoutubeIcon size={16} />
          <span>YouTube Channels</span>
        </button>
        <button
          className={`tab-btn ${activeTab === 'pinterest' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('pinterest');
            setResults([]);
            setError(null);
            setHasSearched(false);
          }}
        >
          <PinterestIcon size={16} />
          <span>Pinterest Search</span>
        </button>
        <button
          className={`tab-btn ${activeTab === 'instagram' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('instagram');
            setResults([]);
            setError(null);
            setHasSearched(false);
          }}
        >
          <InstagramIcon size={16} />
          <span>Instagram Audio</span>
        </button>
      </div>

      {/* Query Filter Box */}
      <div className="card" style={{ marginBottom: '28px' }}>
        <form onSubmit={handleSearch}>
          {activeTab === 'youtube' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px', gap: '16px' }}>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Channel URL or Handle</label>
                <div className="input-with-icon">
                  <YoutubeIcon className="input-icon" />
                  <input
                    type="text"
                    className="form-input"
                    placeholder="https://www.youtube.com/@TED or channel name"
                    value={youtubeChannel}
                    onChange={(e) => setYoutubeChannel(e.target.value)}
                  />
                </div>
                <div className="form-help">Uses yt-dlp to inspect channel feed without downloading immediately.</div>
              </div>

              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Max Videos</label>
                <input
                  type="number"
                  min="1"
                  max="50"
                  className="form-input"
                  value={youtubeLimit}
                  onChange={(e) => setYoutubeLimit(e.target.value)}
                />
              </div>
            </div>
          )}

          {activeTab === 'pinterest' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px', gap: '16px' }}>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Search Keyword / Topic</label>
                <div className="input-with-icon">
                  <PinterestIcon className="input-icon" />
                  <input
                    type="text"
                    className="form-input"
                    placeholder="e.g. podcast clips, nature cinematography, aesthetics"
                    value={pinterestKeyword}
                    onChange={(e) => setPinterestKeyword(e.target.value)}
                  />
                </div>
                <div className="form-help">Scrapes Pinterest public video search results into database records.</div>
              </div>

              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Max Videos</label>
                <input
                  type="number"
                  min="1"
                  max="50"
                  className="form-input"
                  value={pinterestLimit}
                  onChange={(e) => setPinterestLimit(e.target.value)}
                />
              </div>
            </div>
          )}

          {activeTab === 'instagram' && (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px', gap: '16px', marginBottom: '14px' }}>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label">Audio Stream Type</label>
                  <select
                    className="form-select"
                    value={instagramAudioType}
                    onChange={(e) => setInstagramAudioType(e.target.value)}
                  >
                    <option value="music">Commercial / Trending Music</option>
                    <option value="original">Original Audio / User Sounds</option>
                  </select>
                </div>

                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label">Limit</label>
                  <input
                    type="number"
                    min="1"
                    max="50"
                    className="form-input"
                    value={instagramLimit}
                    onChange={(e) => setInstagramLimit(e.target.value)}
                  />
                </div>
              </div>

              <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px' }}>
                  <input
                    type="checkbox"
                    checked={instagramSadFirst}
                    onChange={(e) => setInstagramSadFirst(e.target.checked)}
                    style={{ accentColor: 'var(--accent-primary)' }}
                  />
                  <span>Prioritize soft / sad / emotional mood</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px' }}>
                  <input
                    type="checkbox"
                    checked={instagramAvoidRap}
                    onChange={(e) => setInstagramAvoidRap(e.target.checked)}
                    style={{ accentColor: 'var(--accent-primary)' }}
                  />
                  <span>Exclude fast rap & offensive styles</span>
                </label>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '10px', marginTop: '18px' }}>
            <button type="button" className="btn btn-ghost btn-sm" onClick={clearForm}>
              <RotateCcw size={14} /> Clear
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              <Search size={15} className={loading ? 'pulse-spinner' : ''} />
              <span>{loading ? 'Querying API...' : 'Discover Media'}</span>
            </button>
          </div>
        </form>
      </div>

      {/* Error Banner */}
      {error && (
        <div style={{ padding: '14px 18px', background: 'var(--status-error-bg)', border: '1px solid var(--status-error-border)', borderRadius: 'var(--radius-md)', color: 'var(--status-error)', display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '24px' }}>
          <AlertCircle size={18} style={{ flexShrink: 0 }} />
          <div style={{ fontSize: '13px', lineHeight: 1.4 }}>{error}</div>
        </div>
      )}

      {/* Results Header */}
      {hasSearched && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-main)' }}>
            Discovery Results ({results.length})
          </div>
        </div>
      )}

      {/* Loading Skeletons */}
      {loading && (
        <div className="media-grid">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div className="skeleton" style={{ height: '160px', width: '100%' }} />
              <div style={{ padding: '16px' }}>
                <div className="skeleton" style={{ height: '18px', width: '80%', marginBottom: '8px' }} />
                <div className="skeleton" style={{ height: '14px', width: '50%' }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty State */}
      {!loading && hasSearched && results.length === 0 && !error && (
        <div className="empty-state card">
          <div className="empty-icon-wrap">
            <Search size={24} />
          </div>
          <div className="empty-title">No Media Discovered</div>
          <div className="empty-desc">
            No items matched your search criteria. Try a different channel URL, board keyword, or audio query.
          </div>
        </div>
      )}

      {/* Results Grid */}
      {!loading && results.length > 0 && (
        <div className="media-grid">
          {results.map((item, idx) => {
            const isAudio = activeTab === 'instagram' || item.audio_asset_id;
            const itemId = item.video_id || item.audio_asset_id || item.id || idx;
            const isProcessing = processingId === itemId;

            return (
              <div key={itemId} className="media-card">
                <div className="media-thumb-wrap">
                  {item.thumbnail ? (
                    <img src={item.thumbnail} alt={item.title} className="media-thumb" loading="lazy" />
                  ) : (
                    <div className="media-thumb-placeholder">
                      {isAudio ? <InstagramIcon size={36} /> : <YoutubeIcon size={36} />}
                    </div>
                  )}

                  {/* Top Badge Overlay */}
                  <div style={{ position: 'absolute', top: '10px', left: '10px' }}>
                    <SourceBadge platform={item.platform || activeTab} />
                  </div>

                  {/* Play button overlay if audio preview exists */}
                  {isAudio && (item.audio_url || item.preview_url) && (
                    <button
                      onClick={() => setPreviewTrack(item)}
                      style={{
                        position: 'absolute',
                        bottom: '10px',
                        right: '10px',
                        width: '36px',
                        height: '36px',
                        borderRadius: '50%',
                        background: 'rgba(0,0,0,0.7)',
                        color: '#fff',
                        border: 'none',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        backdropFilter: 'blur(4px)',
                      }}
                      title="Preview Audio"
                    >
                      <Play size={16} style={{ marginLeft: '2px' }} />
                    </button>
                  )}
                </div>

                <div className="media-card-body">
                  <div className="media-card-title" title={item.title}>
                    {item.title || 'Untitled Track / Video'}
                  </div>

                  {item.channel_title || item.artist_name || item.creator ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: 'var(--text-subtle)' }}>
                      <User size={13} />
                      <span className="truncate">{item.channel_title || item.artist_name || item.creator}</span>
                    </div>
                  ) : null}

                  {item.duration ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: 'var(--text-subtle)' }}>
                      <Clock size={13} />
                      <span>{Math.round(item.duration)}s</span>
                    </div>
                  ) : null}

                  <div className="media-card-meta">
                    {item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11.5px', color: 'var(--accent-primary)', textDecoration: 'none' }}
                      >
                        Source <ExternalLink size={12} />
                      </a>
                    ) : (
                      <span style={{ fontSize: '11px', color: 'var(--text-disabled)', fontFamily: 'var(--font-mono)' }}>
                        ID: {String(itemId).slice(0, 10)}
                      </span>
                    )}

                    {isAudio ? (
                      <button
                        className="btn btn-primary btn-sm"
                        disabled={isProcessing}
                        onClick={() => handleDownloadAudio(item)}
                      >
                        <Download size={13} className={isProcessing ? 'pulse-spinner' : ''} />
                        <span>{isProcessing ? 'Syncing...' : 'Sync Track'}</span>
                      </button>
                    ) : (
                      <button
                        className="btn btn-primary btn-sm"
                        disabled={isProcessing}
                        onClick={() => handleDownloadVideo(item)}
                      >
                        <Download size={13} className={isProcessing ? 'pulse-spinner' : ''} />
                        <span>{isProcessing ? 'Queueing...' : 'Download'}</span>
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Audio Preview Modal */}
      {previewTrack && (
        <AudioPlayerModal
          track={previewTrack}
          onClose={() => setPreviewTrack(null)}
          onDownload={(t) => handleDownloadAudio(t)}
        />
      )}
    </div>
  );
}

export default Discover;
