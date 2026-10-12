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

  const [instagramQuery, setInstagramQuery] = useState('');
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
          query: instagramQuery.trim() || undefined,
          target: instagramQuery.trim() || undefined,
          media_filter: 'video',
          audio_type: instagramAudioType,
          limit: Number(instagramLimit) || 10,
          sad_preference: instagramSadFirst,
          avoid_rap: instagramAvoidRap,
        });

        if (data.status === 'error') {
          setError(data.message || 'Instagram video discovery failed');
        } else {
          const vids = data.discovered_videos || data.items || data.tracks || [];
          setResults(vids);
          if (vids.length === 0) {
            showToast('No new Instagram videos/reels found matching filter criteria', 'info');
          } else {
            showToast(`Discovered ${vids.length} Instagram video reels!`, 'success');
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
    const targetUrl = item.url || item.canonical_url;
    const targetId = item.video_id || item.source_id || item.pin_id || item.id || targetUrl;
    setProcessingId(targetId);
    try {
      const res = await api.downloadVideo({
        url: targetUrl,
        platform: item.platform || activeTab,
        title: item.title,
        upload_to_drive: true,
      });

      if (res.status === 'queued') {
        showToast(`Download task queued: ${item.title || 'Video'}. Saving to Drive upon completion.`, 'success');
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
    const trackId = track.audio_asset_id || track.source_id || track.id;
    const audioUrl = track.audio_url || track.preview_url || track.canonical_url || track.url;
    setProcessingId(trackId);
    try {
      const res = await api.downloadInstagramAudio({
        audio_asset_id: trackId,
        audio_url: audioUrl,
        title: track.title,
        artist: track.artist || track.artist_name || 'Instagram',
        upload_to_drive: true,
      });

      if (res.status === 'queued') {
        showToast(`Audio sync queued: "${track.title}". Will upload to Drive "trending songs"`, 'success');
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
    if (activeTab === 'instagram') setInstagramQuery('');
  };

  return (
    <div className="page-container">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Media Discovery</h1>
          <p className="page-subtitle">
            Query YouTube channels, Pinterest video boards, and Instagram video reels (static images strictly excluded).
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
          <span>Instagram Reels & Videos</span>
        </button>
      </div>

      {/* Query Filter Box */}
      <div className="card" style={{ marginBottom: '28px' }}>
        <form onSubmit={handleSearch}>
          {activeTab === 'youtube' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px', gap: '16px' }}>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Channel URL, Video Link, or Search Term</label>
                <div className="input-with-icon">
                  <YoutubeIcon className="input-icon" />
                  <input
                    type="text"
                    className="form-input"
                    placeholder="e.g. @hubermanlab, YouTube link, or search keyword"
                    value={youtubeChannel}
                    onChange={(e) => setYoutubeChannel(e.target.value)}
                  />
                </div>
                <div className="form-help">Supports channel feeds (@handle), direct video links, or search keywords.</div>
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
                <label className="form-label">Search Keyword or Pin URL</label>
                <div className="input-with-icon">
                  <PinterestIcon className="input-icon" />
                  <input
                    type="text"
                    className="form-input"
                    placeholder="e.g. nature aesthetic, cars, quotes, or Pin URL"
                    value={pinterestKeyword}
                    onChange={(e) => setPinterestKeyword(e.target.value)}
                  />
                </div>
                <div className="form-help">Finds Pinterest video Pins by keyword or direct Pin URL.</div>
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
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px', gap: '16px' }}>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Profile Handle, Reel URL, or Search Topic</label>
                <div className="input-with-icon">
                  <InstagramIcon className="input-icon" />
                  <input
                    type="text"
                    className="form-input"
                    placeholder="e.g. @nature, https://www.instagram.com/reel/..., #travel, or leave blank for trending"
                    value={instagramQuery}
                    onChange={(e) => setInstagramQuery(e.target.value)}
                  />
                </div>
                <div className="form-help">
                  Discovers video reels strictly (static images are automatically filtered out). Leave empty for trending reels.
                </div>
              </div>

              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Max Videos</label>
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
            const isAudio = item.media_type === 'audio' || Boolean(item.audio_asset_id && !item.is_video);
            const itemId = item.video_id || item.source_id || item.pin_id || item.audio_asset_id || item.id || idx;
            const isProcessing = processingId === itemId;
            const thumbUrl = item.thumbnail || item.thumbnail_url;

            return (
              <div key={itemId} className="media-card">
                <div className="media-thumb-wrap">
                  {thumbUrl ? (
                    <img src={thumbUrl} alt={item.title} className="media-thumb" loading="lazy" />
                  ) : (
                    <div className="media-thumb-placeholder">
                      {item.platform === 'instagram' ? (
                        <InstagramIcon size={36} />
                      ) : item.platform === 'pinterest' ? (
                        <PinterestIcon size={36} />
                      ) : (
                        <YoutubeIcon size={36} />
                      )}
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
                    {item.title || 'Untitled Video / Track'}
                  </div>

                  {item.channel_name || item.channel_title || item.artist || item.artist_name || item.creator ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: 'var(--text-subtle)' }}>
                      <User size={13} />
                      <span className="truncate">{item.channel_name || item.channel_title || item.artist || item.artist_name || item.creator}</span>
                    </div>
                  ) : null}

                  {item.duration || item.duration_seconds ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', color: 'var(--text-subtle)' }}>
                      <Clock size={13} />
                      <span>{Math.round(item.duration || item.duration_seconds)}s</span>
                    </div>
                  ) : null}

                  <div className="media-card-meta">
                    {item.url || item.canonical_url ? (
                      <a
                        href={item.url || item.canonical_url}
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
                        <span>{isProcessing ? 'Queueing...' : 'Download Video'}</span>
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
