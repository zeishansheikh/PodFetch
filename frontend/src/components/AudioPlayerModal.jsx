import React, { useRef, useState, useEffect } from 'react';
import { X, Play, Pause, Volume2, Download, Music } from 'lucide-react';

export function AudioPlayerModal({ track, onClose, onDownload }) {
  const audioRef = useRef(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
    }
  }, [track]);

  if (!track) return null;

  const togglePlay = () => {
    if (!audioRef.current) return;
    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current.play();
      setIsPlaying(true);
    }
  };

  const handleTimeUpdate = () => {
    if (audioRef.current) {
      setCurrentTime(audioRef.current.currentTime);
      setDuration(audioRef.current.duration || 0);
    }
  };

  const formatTime = (secs) => {
    if (!secs || isNaN(secs)) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        {/* Modal Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'var(--accent-primary-subtle)', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Music size={16} />
            </div>
            <div>
              <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-main)' }}>Audio Preview</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Instagram Audio Asset</div>
            </div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} style={{ padding: '6px' }}>
            <X size={16} />
          </button>
        </div>

        {/* Modal Body */}
        <div style={{ padding: '24px 20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div>
            <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-main)', marginBottom: '4px' }}>
              {track.title || track.audio_title || 'Untitled Audio'}
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
              {track.artist_name || track.artist || 'Original Audio'}
            </div>
          </div>

          {/* Hidden or Standard HTML5 Audio element */}
          {track.audio_url || track.preview_url ? (
            <audio
              ref={audioRef}
              src={track.audio_url || track.preview_url}
              onTimeUpdate={handleTimeUpdate}
              onEnded={() => setIsPlaying(false)}
            />
          ) : (
            <div style={{ padding: '16px', background: 'var(--status-warning-bg)', border: '1px solid var(--status-warning-border)', borderRadius: 'var(--radius-md)', color: '#b45309', fontSize: '12.5px' }}>
              Audio stream URL not provided by the Instagram API for this item.
            </div>
          )}

          {/* Progress Slider */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <input
              type="range"
              min="0"
              max={duration || 100}
              value={currentTime}
              onChange={(e) => {
                if (audioRef.current) {
                  audioRef.current.currentTime = Number(e.target.value);
                  setCurrentTime(Number(e.target.value));
                }
              }}
              style={{ width: '100%', accentColor: 'var(--accent-primary)', cursor: 'pointer' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-subtle)' }}>
              <span>{formatTime(currentTime)}</span>
              <span>{formatTime(duration)}</span>
            </div>
          </div>

          {/* Controls Bar */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <button
                className="btn btn-primary"
                onClick={togglePlay}
                style={{ width: '42px', height: '42px', padding: 0, borderRadius: '50%' }}
                disabled={!track.audio_url && !track.preview_url}
              >
                {isPlaying ? <Pause size={18} /> : <Play size={18} style={{ marginLeft: '2px' }} />}
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-muted)', fontSize: '12px' }}>
                <Volume2 size={16} />
                <span>Stereo Audio</span>
              </div>
            </div>

            {onDownload && (
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  onDownload(track);
                  onClose();
                }}
              >
                <Download size={14} />
                Download & Sync
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default AudioPlayerModal;
