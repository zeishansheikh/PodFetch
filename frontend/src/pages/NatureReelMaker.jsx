import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  Play,
  Square,
  RefreshCw,
  CheckCircle,
  XCircle,
  Film,
  Sliders,
  ShieldCheck,
  Video,
  Eye,
  Edit3,
  ExternalLink,
  Cloud,
  Check,
  AlertTriangle,
  RotateCcw,
  Maximize2,
  Tag,
  Type,
  FileText,
  Clock,
  Layers,
  ChevronRight,
  Settings2,
  Shuffle,
  Calendar,
  Search,
  Filter,
} from 'lucide-react';
import api from '../api/client';

export function NatureReelMaker({ showToast }) {
  const [activeTab, setActiveTab] = useState('review'); // 'review' | 'candidates' | 'settings'

  // Data states
  const [reels, setReels] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [profile, setProfile] = useState(null);
  const [aiStatus, setAiStatus] = useState(null);
  const [categories, setCategories] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [pipelineStatus, setPipelineStatus] = useState(null);

  const [loading, setLoading] = useState(false);
  const [runningJob, setRunningJob] = useState(false);

  // Modals & previews
  const [selectedReel, setSelectedReel] = useState(null);
  const [editingDraft, setEditingDraft] = useState(null);
  const [rerenderingReel, setRerenderingReel] = useState(null);
  const [runModalOpen, setRunModalOpen] = useState(false);

  // Template & preview states
  const [selectedTemplatePreset, setSelectedTemplatePreset] = useState('Nature Cinematic — Minimal White Serif Quote');

  // Run pipeline parameters
  const [runCategory, setRunCategory] = useState('');
  const [runKeyword, setRunKeyword] = useState('');
  const [runMood, setRunMood] = useState('cinematic');
  const [runSeason, setRunSeason] = useState('any');
  const [runRecency, setRunRecency] = useState('any');
  const [runStrictRecency, setRunStrictRecency] = useState(false);
  const [runOrientation, setRunOrientation] = useState('vertical_9_16');
  const [runMinScore, setRunMinScore] = useState(65);
  const [runMaxInspect, setRunMaxInspect] = useState(25);
  const [runExcludedKeywords, setRunExcludedKeywords] = useState('');
  const [keywordPreview, setKeywordPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [keywordHistory, setKeywordHistory] = useState([]);
  const [runMaxReels, setRunMaxReels] = useState(1);
  const [runComposition, setRunComposition] = useState('crop');
  const [runTemplate, setRunTemplate] = useState('Nature Cinematic — Minimal White Serif Quote');
  const [runCustomThought, setRunCustomThought] = useState('');
  const [runDuration, setRunDuration] = useState(12);
  const [runFontSize, setRunFontSize] = useState(44);
  const [runLineSpacing, setRunLineSpacing] = useState(24);

  // Load profile & initial data
  const fetchData = async () => {
    setLoading(true);
    try {
      const [profData, catData, reelsData, candData, statusData, tplData] = await Promise.all([
        api.getNatureProfile().catch(() => null),
        api.getNatureCategories().catch(() => ({ categories: [] })),
        api.getNatureReels({ limit: 50 }).catch(() => ({ reels: [] })),
        api.getNatureCandidates({ limit: 50 }).catch(() => ({ candidates: [] })),
        api.getNatureStatus().catch(() => null),
        api.getNatureTemplates().catch(() => ({ templates: [] })),
      ]);

      if (profData) {
        setProfile(profData.profile);
        setAiStatus(profData.ai_status);
      }
      if (catData) setCategories(catData.categories || []);
      if (tplData && tplData.templates) setTemplates(tplData.templates || []);
      if (reelsData) setReels(reelsData.reels || []);
      if (candData) setCandidates(candData.candidates || []);
      if (statusData) {
        setPipelineStatus(statusData);
        if (statusData.latest_job && !['COMPLETED', 'FAILED', 'PAUSED', 'IDLE'].includes(statusData.latest_job.stage)) {
          setRunningJob(true);
        } else {
          setRunningJob(false);
        }
      }
    } catch (err) {
      if (showToast) showToast(`Failed to load Nature Reel Maker data: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(async () => {
      try {
        const status = await api.getNatureStatus();
        setPipelineStatus(status);
        if (status.latest_job && !['COMPLETED', 'FAILED', 'PAUSED', 'IDLE'].includes(status.latest_job.stage)) {
          setRunningJob(true);
          // Refresh reels and candidates while job is running
          const [rData, cData] = await Promise.all([
            api.getNatureReels({ limit: 50 }).catch(() => null),
            api.getNatureCandidates({ limit: 50 }).catch(() => null),
          ]);
          if (rData) setReels(rData.reels || []);
          if (cData) setCandidates(cData.candidates || []);
        } else {
          setRunningJob(false);
        }
      } catch (_) {}
    }, 4000);

    return () => clearInterval(interval);
  }, []);

  // Live Keyword Preview Fetcher
  const updateKeywordPreview = async (cat, mood, season, orient) => {
    try {
      setLoadingPreview(true);
      const res = await api.getNatureKeywordPreview({
        category: cat !== undefined ? cat : runCategory,
        mood: mood !== undefined ? mood : runMood,
        season: season !== undefined ? season : runSeason,
        orientation: orient !== undefined ? orient : runOrientation,
      });
      if (res) {
        setKeywordPreview(res);
      }
    } catch (err) {
      console.warn('Failed to fetch keyword preview:', err);
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleOpenRunModal = () => {
    const initialCat = runCategory || profile?.categories?.[0] || 'autumn_forest';
    const initialMood = runMood || profile?.search_mood || 'cinematic';
    const initialSeason = runSeason || profile?.season || 'any';
    const initialRecency = runRecency || profile?.recency_preference || 'any';
    const initialStrict = runStrictRecency || profile?.strict_recency || false;
    const initialOrient = runOrientation || profile?.preferred_orientation || 'vertical_9_16';
    const initialMinScore = runMinScore || profile?.min_quality_score || 65;

    setRunCategory(initialCat);
    setRunMood(initialMood);
    setRunSeason(initialSeason);
    setRunRecency(initialRecency);
    setRunStrictRecency(initialStrict);
    setRunOrientation(initialOrient);
    setRunMinScore(initialMinScore);
    setRunModalOpen(true);

    updateKeywordPreview(initialCat, initialMood, initialSeason, initialOrient);
    api.getNatureKeywordHistory(15).then((data) => {
      if (data && data.history) setKeywordHistory(data.history);
    }).catch(() => {});
  };

  // Trigger Pipeline Run
  const handleStartPipeline = async () => {
    try {
      setRunningJob(true);
      setRunModalOpen(false);
      await api.runNaturePipeline({
        category: runCategory || null,
        keyword: runKeyword.trim() ? runKeyword.trim() : null,
        search_mood: runMood,
        season: runSeason,
        recency_preference: runRecency,
        strict_recency: runStrictRecency,
        preferred_orientation: runOrientation,
        min_quality_score: parseFloat(runMinScore) || 65.0,
        max_candidates_to_inspect: parseInt(runMaxInspect, 10) || 25,
        excluded_terms: runExcludedKeywords.trim()
          ? runExcludedKeywords.split(',').map((s) => s.trim()).filter(Boolean)
          : null,
        max_reels: parseInt(runMaxReels, 10) || 1,
        composition_mode: runComposition,
        template_name: runTemplate || 'Nature Cinematic — Minimal White Serif Quote',
        custom_thought: runCustomThought.trim() ? runCustomThought.trim() : null,
        target_duration: parseFloat(runDuration) || 12.0,
        font_size: parseInt(runFontSize, 10) || 44,
        line_spacing: parseInt(runLineSpacing, 10) || 24,
      });
      if (showToast) showToast('Nature Cinematic Reel pipeline started.', 'success');
      fetchData();
    } catch (err) {
      setRunningJob(false);
      if (showToast) showToast(`Failed to trigger pipeline: ${err.message}`, 'error');
    }
  };

  // Stop Pipeline
  const handleStopPipeline = async () => {
    try {
      await api.stopNaturePipeline();
      if (showToast) showToast('Stop signal sent to pipeline.', 'info');
    } catch (err) {
      if (showToast) showToast(`Error stopping pipeline: ${err.message}`, 'error');
    }
  };

  // Approve Reel
  const handleApprove = async (reelId) => {
    try {
      await api.approveNatureReel(reelId);
      if (showToast) showToast('Reel approved for publishing!', 'success');
      fetchData();
    } catch (err) {
      if (showToast) showToast(`Failed to approve reel: ${err.message}`, 'error');
    }
  };

  // Reject Reel
  const handleReject = async (reelId) => {
    try {
      await api.rejectNatureReel(reelId);
      if (showToast) showToast('Reel rejected.', 'info');
      fetchData();
    } catch (err) {
      if (showToast) showToast(`Failed to reject reel: ${err.message}`, 'error');
    }
  };

  // Save edited thought / caption / hashtags
  const handleSaveDraft = async () => {
    if (!editingDraft) return;
    try {
      await api.updateNatureDraft(editingDraft.id, {
        thought_text: editingDraft.thought_text,
        caption: editingDraft.caption,
        hashtags: editingDraft.hashtags,
      });
      if (showToast) showToast('Reel draft updated successfully.', 'success');
      setEditingDraft(null);
      fetchData();
    } catch (err) {
      if (showToast) showToast(`Failed to update draft: ${err.message}`, 'error');
    }
  };

  // Rerender Reel
  const handleRerender = async () => {
    if (!rerenderingReel) return;
    try {
      await api.rerenderNatureReel(rerenderingReel.id, {
        thought_text: rerenderingReel.thought_text,
        template_name: rerenderingReel.template_name || 'Nature Cinematic — Minimal White Serif Quote',
        composition_mode: rerenderingReel.composition_mode || 'crop',
        color_preset: rerenderingReel.color_preset || 'restrained_warm',
        font_size: parseInt(rerenderingReel.font_size, 10) || 44,
        line_spacing: parseInt(rerenderingReel.line_spacing, 10) || 24,
        target_duration: parseFloat(rerenderingReel.duration_seconds) || 12.0,
        shadow_strength: parseFloat(rerenderingReel.shadow_strength) || 0.65,
      });
      if (showToast) showToast('Rerendering started in background.', 'info');
      setRerenderingReel(null);
      fetchData();
    } catch (err) {
      if (showToast) showToast(`Failed to start rerender: ${err.message}`, 'error');
    }
  };

  // Save Profile settings
  const handleSaveProfile = async (e) => {
    e.preventDefault();
    try {
      await api.updateNatureProfile(profile);
      if (showToast) showToast('Profile settings saved.', 'success');
      fetchData();
    } catch (err) {
      if (showToast) showToast(`Failed to save profile: ${err.message}`, 'error');
    }
  };

  const latestJob = pipelineStatus?.latest_job;

  return (
    <div className="page-container" style={{ padding: '24px', maxWidth: '1440px', margin: '0 auto' }}>
      {/* Top Header */}
      <div className="page-header" style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 className="page-title" style={{ margin: 0, fontSize: '26px', fontWeight: '700', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Sparkles size={24} style={{ color: 'var(--accent-primary)' }} /> Nature Reel Maker
            </h1>
            <span style={{ fontSize: '12px', background: 'var(--accent-primary-subtle)', color: 'var(--accent-primary)', padding: '2px 8px', borderRadius: '12px', fontWeight: '600' }}>
              Cinematic Style
            </span>
          </div>
          <p className="page-subtitle" style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>
            Automated Pinterest nature discovery, multi-factor video quality inspection, AI poetic thoughts, and vertical 9:16 reels inspired by creator @degraaf.david.
          </p>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {runningJob ? (
            <button className="btn btn-secondary" onClick={handleStopPipeline} style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--status-error)' }}>
              <Square size={16} /> Stop Pipeline
            </button>
          ) : (
            <button className="btn btn-primary" onClick={handleOpenRunModal} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Play size={16} /> Run Pipeline
            </button>
          )}

          <button className="btn btn-secondary" onClick={fetchData} title="Refresh data">
            <RefreshCw size={16} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {/* Active Pipeline Status Banner */}
      {latestJob && (
        <div
          className="card"
          style={{
            marginBottom: '24px',
            padding: '16px 20px',
            background: runningJob ? 'linear-gradient(90deg, #f0fdf4 0%, #ffffff 100%)' : 'var(--bg-surface)',
            border: runningJob ? '1px solid var(--status-success-border)' : '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span className={`status-dot ${runningJob ? '' : 'offline'}`} style={{ width: '10px', height: '10px' }} />
              <div>
                <span style={{ fontWeight: '600', fontSize: '14px', color: 'var(--text-main)' }}>
                  Stage: {latestJob.stage || 'IDLE'}
                </span>
                {latestJob.current_keyword && (
                  <span style={{ marginLeft: '12px', fontSize: '13px', color: 'var(--text-muted)' }}>
                    Searching: "<em>{latestJob.current_keyword}</em>" ({latestJob.current_category})
                  </span>
                )}
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '13px', color: 'var(--text-muted)' }}>
              <span>Candidates: <strong>{latestJob.total_candidates || 0}</strong></span>
              <span>Rendered Reels: <strong>{latestJob.rendered_reels || 0}</strong></span>
              <span style={{ fontWeight: '600', color: 'var(--accent-primary)' }}>{latestJob.progress || 0}%</span>
            </div>
          </div>

          {/* Progress bar */}
          <div style={{ width: '100%', height: '6px', background: 'var(--bg-surface-subtle)', borderRadius: '3px', marginTop: '12px', overflow: 'hidden' }}>
            <div
              style={{
                width: `${Math.min(100, Math.max(2, latestJob.progress || 0))}%`,
                height: '100%',
                background: runningJob ? 'var(--status-success)' : 'var(--accent-primary)',
                transition: 'width 300ms ease',
              }}
            />
          </div>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '24px' }}>
        <button
          onClick={() => setActiveTab('review')}
          style={{
            padding: '10px 18px',
            border: 'none',
            background: 'none',
            fontSize: '14px',
            fontWeight: activeTab === 'review' ? '600' : '400',
            color: activeTab === 'review' ? 'var(--accent-primary)' : 'var(--text-muted)',
            borderBottom: activeTab === 'review' ? '2px solid var(--accent-primary)' : '2px solid transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <Film size={18} /> Review & Approval ({reels.length})
        </button>

        <button
          onClick={() => setActiveTab('candidates')}
          style={{
            padding: '10px 18px',
            border: 'none',
            background: 'none',
            fontSize: '14px',
            fontWeight: activeTab === 'candidates' ? '600' : '400',
            color: activeTab === 'candidates' ? 'var(--accent-primary)' : 'var(--text-muted)',
            borderBottom: activeTab === 'candidates' ? '2px solid var(--accent-primary)' : '2px solid transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <ShieldCheck size={18} /> Candidate Quality Audit ({candidates.length})
        </button>

        <button
          onClick={() => setActiveTab('settings')}
          style={{
            padding: '10px 18px',
            border: 'none',
            background: 'none',
            fontSize: '14px',
            fontWeight: activeTab === 'settings' ? '600' : '400',
            color: activeTab === 'settings' ? 'var(--accent-primary)' : 'var(--text-muted)',
            borderBottom: activeTab === 'settings' ? '2px solid var(--accent-primary)' : '2px solid transparent',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <Sliders size={18} /> Profile & Template Config
        </button>
      </div>

      {/* TAB 1: REELS REVIEW & APPROVAL */}
      {activeTab === 'review' && (
        <div>
          {/* Template Style Selector & Aesthetic Showcase */}
          <div className="card" style={{ padding: '16px 20px', marginBottom: '24px', background: 'linear-gradient(135deg, rgba(24, 24, 27, 0.95), rgba(9, 9, 11, 0.95))', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(34, 197, 94, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#22c55e' }}>
                  <Type size={22} />
                </div>
                <div>
                  <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', fontWeight: '600' }}>Active Aesthetic Preset</div>
                  <div style={{ fontSize: '16px', fontWeight: '700', color: 'var(--text-main)' }}>{selectedTemplatePreset}</div>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                <select
                  className="form-select"
                  style={{ minWidth: '320px', padding: '8px 12px', fontSize: '13px', background: 'var(--bg-surface)' }}
                  value={selectedTemplatePreset}
                  onChange={(e) => {
                    setSelectedTemplatePreset(e.target.value);
                    setRunTemplate(e.target.value);
                  }}
                >
                  {templates.length > 0 ? (
                    templates.map((t) => (
                      <option key={t.id} value={t.name}>{t.name}</option>
                    ))
                  ) : (
                    <>
                      <option value="Nature Cinematic — Minimal White Serif Quote">Nature Cinematic — Minimal White Serif Quote</option>
                      <option value="Nature Cinematic — Thought Reel">Nature Cinematic — Thought Reel</option>
                    </>
                  )}
                </select>

                <button
                  className="btn btn-primary"
                  onClick={handleOpenRunModal}
                  style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <Play size={15} /> Launch Reel Maker
                </button>
              </div>
            </div>

            {/* Visual Style Highlights */}
            <div style={{ marginTop: '14px', paddingTop: '12px', borderTop: '1px solid rgba(255,255,255,0.08)', display: 'flex', flexWrap: 'wrap', gap: '20px', fontSize: '12px', color: 'var(--text-muted)' }}>
              <span>✦ <strong>Typography:</strong> Elegant White Serif (Noto / Liberation)</span>
              <span>✦ <strong>Arrangement:</strong> 4–7 readable lines, centered horizontally</span>
              <span>✦ <strong>Contrast:</strong> Soft dark shadow (no box scrim or stickers)</span>
              <span>✦ <strong>Framing:</strong> 1080×1920 9:16 Full-bleed nature footage</span>
              <span>✦ <strong>Pacing:</strong> 10–15s calm fade-in/fade-out</span>
            </div>
          </div>

          {reels.length === 0 ? (
            <div className="card" style={{ padding: '60px 20px', textAlign: 'center', color: 'var(--text-muted)' }}>
              <Film size={48} style={{ margin: '0 auto 16px', opacity: 0.4 }} />
              <h3 style={{ fontSize: '18px', color: 'var(--text-main)', marginBottom: '8px' }}>No Nature Reels Rendered Yet</h3>
              <p style={{ maxWidth: '460px', margin: '0 auto 20px', fontSize: '14px' }}>
                Run the pipeline to discover eligible nature clips, generate thoughtful on-screen text, and render vertical 9:16 reels for review.
              </p>
              <button className="btn btn-primary" onClick={handleOpenRunModal}>
                <Play size={16} /> Run Pipeline Now
              </button>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '20px' }}>
              {reels.map((reel) => {
                const isPending = reel.status === 'PENDING';
                const isApproved = reel.status === 'APPROVED';
                const isRejected = reel.status === 'REJECTED';

                return (
                  <div
                    key={reel.id}
                    className="card"
                    style={{
                      borderRadius: 'var(--radius-md)',
                      overflow: 'hidden',
                      display: 'flex',
                      flexDirection: 'column',
                      border: isApproved
                        ? '1px solid var(--status-success-border)'
                        : isRejected
                        ? '1px solid var(--status-error-border)'
                        : '1px solid var(--border-subtle)',
                    }}
                  >
                    {/* Media Thumbnail / Preview Header */}
                    <div
                      style={{
                        position: 'relative',
                        height: '240px',
                        background: '#18181b',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                      }}
                      onClick={() => setSelectedReel(reel)}
                    >
                      {reel.thumbnail_path ? (
                        <img
                          src={`/api/nature/media/${reel.thumbnail_path}`}
                          alt="Reel Thumbnail"
                          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                          onError={(e) => {
                            e.target.style.display = 'none';
                          }}
                        />
                      ) : (
                        <Film size={40} style={{ color: '#71717a' }} />
                      )}

                      {/* On-screen text overlay preview with exact white serif styling */}
                      <div
                        style={{
                          position: 'absolute',
                          inset: 0,
                          background: 'rgba(0, 0, 0, 0.25)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          padding: '20px 16px',
                          textAlign: 'center',
                        }}
                      >
                        <p
                          style={{
                            color: '#ffffff',
                            fontFamily: 'Georgia, serif',
                            fontSize: '14px',
                            fontWeight: '400',
                            textShadow: '0 2px 4px rgba(0,0,0,0.85)',
                            lineHeight: 1.45,
                            whiteSpace: 'pre-line',
                            margin: 0,
                          }}
                        >
                          "{reel.thought_text}"
                        </p>
                      </div>
                      {/* Play Icon Badge */}
                      <div
                        style={{
                          position: 'absolute',
                          bottom: '12px',
                          right: '12px',
                          background: 'rgba(0,0,0,0.7)',
                          color: '#ffffff',
                          padding: '6px',
                          borderRadius: '50%',
                          display: 'flex',
                        }}
                      >
                        <Play size={14} fill="#ffffff" />
                      </div>

                      {/* Status Tag */}
                      <div style={{ position: 'absolute', top: '12px', left: '12px' }}>
                        <span
                          style={{
                            padding: '3px 8px',
                            borderRadius: '4px',
                            fontSize: '11px',
                            fontWeight: '700',
                            textTransform: 'uppercase',
                            background: isApproved
                              ? 'var(--status-success-bg)'
                              : isRejected
                              ? 'var(--status-error-bg)'
                              : '#fef3c7',
                            color: isApproved
                              ? 'var(--status-success)'
                              : isRejected
                              ? 'var(--status-error)'
                              : '#d97706',
                          }}
                        >
                          {reel.status}
                        </span>
                      </div>
                    </div>

                    {/* Reel Metadata Content */}
                    <div style={{ padding: '16px', flex: 1, display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--accent-primary)', textTransform: 'capitalize' }}>
                          {reel.category.replace(/_/g, ' ')}
                        </span>
                        <span style={{ fontSize: '11px', color: 'var(--text-disabled)' }}>
                          {reel.duration_seconds}s • 1080×1920
                        </span>
                      </div>

                      {/* Template Name badge */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-muted)' }}>
                        <Tag size={12} />
                        <span>{reel.template_name || 'Minimal White Serif'}</span>
                      </div>

                      {/* Source Pin link */}
                      {reel.candidate_url && (
                        <div style={{ fontSize: '11px' }}>
                          <a
                            href={reel.candidate_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: 'var(--accent-primary)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                            title={reel.candidate_url}
                          >
                            <ExternalLink size={12} /> View Source Video
                          </a>
                        </div>
                      )}

                      {/* Local File Path */}
                      {reel.rendered_reel_path && (
                        <div style={{ fontSize: '11px', color: 'var(--text-disabled)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Film size={11} />
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={reel.rendered_reel_path}>
                            {reel.rendered_reel_path}
                          </span>
                        </div>
                      )}

                      {/* Caption Draft */}
                      <div>
                        <div style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-subtle)', textTransform: 'uppercase', marginBottom: '2px' }}>
                          Caption Draft
                        </div>
                        <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-main)', lineHeight: 1.4 }}>
                          {reel.caption}
                        </p>
                      </div>

                      {/* Hashtags */}
                      {reel.hashtags && reel.hashtags.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                          {reel.hashtags.map((tag, tIdx) => (
                            <span
                              key={tIdx}
                              style={{
                                fontSize: '11px',
                                background: 'var(--bg-surface-subtle)',
                                color: 'var(--text-muted)',
                                padding: '2px 6px',
                                borderRadius: '4px',
                              }}
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Google Drive Status */}
                      {reel.drive_file_id ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--status-success)', marginTop: '4px' }}>
                          <Cloud size={14} /> Backed up to Google Drive
                        </div>
                      ) : (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-disabled)', marginTop: '4px' }}>
                          <Cloud size={14} /> Local only
                        </div>
                      )}

                      {/* Action Buttons */}
                      <div style={{ marginTop: 'auto', paddingTop: '12px', borderTop: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                        <div style={{ display: 'flex', gap: '6px' }}>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => setEditingDraft(reel)}
                            title="Edit thought, caption, and hashtags"
                            style={{ padding: '6px 10px', fontSize: '12px' }}
                          >
                            <Edit3 size={14} /> Edit
                          </button>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => setRerenderingReel(reel)}
                            title="Re-render with different composition or style"
                            style={{ padding: '6px 10px', fontSize: '12px' }}
                          >
                            <RotateCcw size={14} /> Re-render
                          </button>
                        </div>

                        <div style={{ display: 'flex', gap: '6px' }}>
                          {isPending && (
                            <>
                              <button
                                className="btn btn-sm"
                                onClick={() => handleApprove(reel.id)}
                                style={{ background: 'var(--status-success)', color: '#ffffff', border: 'none', padding: '6px 10px', fontSize: '12px' }}
                                title="Approve Reel"
                              >
                                <Check size={14} /> Approve
                              </button>
                              <button
                                className="btn btn-sm"
                                onClick={() => handleReject(reel.id)}
                                style={{ background: 'var(--status-error-bg)', color: 'var(--status-error)', border: '1px solid var(--status-error-border)', padding: '6px 10px', fontSize: '12px' }}
                                title="Reject Reel"
                              >
                                <XCircle size={14} /> Reject
                              </button>
                            </>
                          )}
                          {!isPending && (
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => setSelectedReel(reel)}
                              style={{ padding: '6px 10px', fontSize: '12px' }}
                            >
                              <Eye size={14} /> Preview
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* TAB 2: CANDIDATE QUALITY AUDIT */}
      {activeTab === 'candidates' && (
        <div className="card" style={{ padding: '20px', borderRadius: 'var(--radius-md)' }}>
          <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '600', color: 'var(--text-main)' }}>
                Footage Quality Inspection Audit
              </h3>
              <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--text-muted)' }}>
                Detailed multi-factor analysis: resolution, aspect ratio, blur & edge energy, black frames, scenic color, and mandatory rights gate.
              </p>
            </div>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Total Evaluated: {candidates.length}
            </span>
          </div>

          {candidates.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-disabled)' }}>
              No footage candidates evaluated yet. Run discovery to inspect candidates.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                    <th style={{ padding: '10px' }}>Clip / Source</th>
                    <th style={{ padding: '10px' }}>Category & Keyword</th>
                    <th style={{ padding: '10px' }}>Publication / Recency</th>
                    <th style={{ padding: '10px' }}>Specs (Res / Dur)</th>
                    <th style={{ padding: '10px' }}>Pre-Score</th>
                    <th style={{ padding: '10px' }}>Overall Quality</th>
                    <th style={{ padding: '10px' }}>Gate Status</th>
                    <th style={{ padding: '10px' }}>Reason / Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((cand) => {
                    const isEligible = cand.eligibility_status === 'ELIGIBLE';
                    const recencyColors = {
                      very_recent: { bg: 'rgba(34, 197, 94, 0.15)', text: '#22c55e', label: 'Very Recent' },
                      recent: { bg: 'rgba(16, 185, 129, 0.15)', text: '#10b981', label: 'Recent (<6mo)' },
                      moderate: { bg: 'rgba(59, 130, 246, 0.15)', text: '#3b82f6', label: 'Moderate (<1yr)' },
                      older: { bg: 'rgba(245, 158, 11, 0.15)', text: '#f59e0b', label: 'Older (>1yr)' },
                      unknown: { bg: 'rgba(113, 113, 122, 0.15)', text: '#a1a1aa', label: 'Date Unknown' },
                    };
                    const recBadge = recencyColors[cand.recency_status] || recencyColors.unknown;
                    const pubDateStr = cand.published_at ? new Date(cand.published_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : null;

                    return (
                      <tr key={cand.id || cand.source_id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        <td style={{ padding: '10px', maxWidth: '220px' }}>
                          <div style={{ fontWeight: '600', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {cand.title || `Pin ${cand.source_id}`}
                          </div>
                          <a
                            href={cand.canonical_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ fontSize: '11px', color: 'var(--accent-primary)', display: 'inline-flex', alignItems: 'center', gap: '4px', marginTop: '2px' }}
                          >
                            Source Pin <ExternalLink size={10} />
                          </a>
                        </td>
                        <td style={{ padding: '10px', maxWidth: '180px' }}>
                          <div style={{ textTransform: 'capitalize', color: 'var(--text-main)', fontWeight: '500', fontSize: '12px' }}>
                            {cand.category?.replace(/_/g, ' ')}
                          </div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {cand.search_keyword || 'Automatic Seed'}
                          </div>
                        </td>
                        <td style={{ padding: '10px', fontSize: '12px' }}>
                          <div style={{ color: pubDateStr ? 'var(--text-main)' : 'var(--text-disabled)', fontFamily: pubDateStr ? 'var(--font-mono)' : 'inherit', fontSize: '11px' }}>
                            {pubDateStr || 'No timestamp'}
                          </div>
                          <span
                            style={{
                              display: 'inline-block',
                              marginTop: '2px',
                              padding: '1px 6px',
                              borderRadius: '4px',
                              fontSize: '10px',
                              fontWeight: '600',
                              background: recBadge.bg,
                              color: recBadge.text,
                            }}
                          >
                            {recBadge.label}
                          </span>
                        </td>
                        <td style={{ padding: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                          <div>{cand.width && cand.height ? `${cand.width}×${cand.height}` : '—'}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-disabled)' }}>
                            {cand.duration_seconds ? `${cand.duration_seconds.toFixed(0)}s` : '—'} {cand.aspect_ratio ? `(${cand.aspect_ratio})` : ''}
                          </div>
                        </td>
                        <td style={{ padding: '10px', fontWeight: '600', color: (cand.pre_score || 0) >= 70 ? 'var(--status-success)' : 'var(--text-muted)' }}>
                          {cand.pre_score != null ? cand.pre_score.toFixed(1) : '—'}
                        </td>
                        <td style={{ padding: '10px', fontWeight: '700', color: (cand.overall_score || 0) >= 65 ? 'var(--status-success)' : 'var(--text-main)' }}>
                          {cand.overall_score != null ? cand.overall_score.toFixed(1) : '—'}
                        </td>
                        <td style={{ padding: '10px' }}>
                          <span
                            style={{
                              padding: '2px 8px',
                              borderRadius: '4px',
                              fontSize: '11px',
                              fontWeight: '700',
                              background: isEligible ? 'var(--status-success-bg)' : 'var(--status-error-bg)',
                              color: isEligible ? 'var(--status-success)' : 'var(--status-error)',
                            }}
                          >
                            {cand.eligibility_status}
                          </span>
                        </td>
                        <td style={{ padding: '10px', maxWidth: '240px', fontSize: '12px', color: cand.rejection_reason ? 'var(--status-error)' : 'var(--text-subtle)' }}>
                          {cand.rejection_reason || 'Passed quality and recency gate'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: PROFILE & TEMPLATE SETTINGS */}
      {activeTab === 'settings' && profile && (
        <form onSubmit={handleSaveProfile} className="card" style={{ padding: '24px', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div>
            <h3 style={{ margin: '0 0 4px', fontSize: '18px', fontWeight: '600', color: 'var(--text-main)' }}>
              Nature Cinematic Reels Configuration
            </h3>
            <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-muted)' }}>
              Customize active nature categories, search terms, minimum quality thresholds, and rendering settings.
            </p>
          </div>

          {/* AI Connection Status Card */}
          {aiStatus && (
            <div
              style={{
                padding: '16px',
                background: 'var(--bg-surface-subtle)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '12px',
              }}
            >
              <div>
                <div style={{ fontWeight: '600', fontSize: '14px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Sparkles size={16} style={{ color: 'var(--accent-primary)' }} /> AI Provider: {aiStatus.provider.toUpperCase()} ({aiStatus.model})
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  {aiStatus.has_groq_key
                    ? `Active Key: ${aiStatus.masked_key} (${aiStatus.active_keys_count} key(s) in rotation pool)`
                    : 'No GROQ_API_KEY detected. Using deterministic curated thoughts library.'}
                </div>
              </div>
              <span
                style={{
                  padding: '4px 10px',
                  borderRadius: '12px',
                  fontSize: '12px',
                  fontWeight: '600',
                  background: aiStatus.has_groq_key ? 'var(--status-success-bg)' : '#fef3c7',
                  color: aiStatus.has_groq_key ? 'var(--status-success)' : '#d97706',
                }}
              >
                {aiStatus.has_groq_key ? 'Groq Online' : 'Curated Fallback'}
              </span>
            </div>
          )}

          {/* Active Categories */}
          <div>
            <label style={{ display: 'block', fontWeight: '600', fontSize: '14px', marginBottom: '8px' }}>
              Active Nature Categories
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '10px' }}>
              {categories.map((cat) => {
                const isChecked = profile.categories?.includes(cat.id);
                return (
                  <label
                    key={cat.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '10px',
                      borderRadius: 'var(--radius-sm)',
                      background: isChecked ? 'var(--accent-primary-subtle)' : 'var(--bg-surface-subtle)',
                      border: isChecked ? '1px solid var(--accent-primary-border)' : '1px solid var(--border-subtle)',
                      cursor: 'pointer',
                      fontSize: '13px',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={(e) => {
                        const next = e.target.checked
                          ? [...(profile.categories || []), cat.id]
                          : (profile.categories || []).filter((id) => id !== cat.id);
                        setProfile({ ...profile, categories: next });
                      }}
                    />
                    <span style={{ fontWeight: isChecked ? '600' : '400' }}>{cat.name}</span>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Excluded Terms Editor */}
          <div>
            <label style={{ display: 'block', fontWeight: '600', fontSize: '14px', marginBottom: '6px' }}>
              Excluded Keywords (Comma Separated)
            </label>
            <p style={{ margin: '0 0 8px', fontSize: '12px', color: 'var(--text-muted)' }}>
              Footage whose titles or descriptions contain any of these terms will be automatically filtered out.
            </p>
            <textarea
              rows={3}
              className="form-input"
              style={{ width: '100%', fontFamily: 'var(--font-mono)', fontSize: '12px', padding: '8px' }}
              value={(profile.excluded_terms || []).join(', ')}
              onChange={(e) => {
                const terms = e.target.value.split(',').map((t) => t.trim()).filter(Boolean);
                setProfile({ ...profile, excluded_terms: terms });
              }}
            />
          </div>

          {/* Thresholds and Limits Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
            <div>
              <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                Minimum Quality Score ({profile.min_quality_score})
              </label>
              <input
                type="range"
                min="40"
                max="90"
                step="1"
                value={profile.min_quality_score}
                onChange={(e) => setProfile({ ...profile, min_quality_score: parseFloat(e.target.value) })}
                style={{ width: '100%' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                Search Limit Per Run
              </label>
              <input
                type="number"
                min="1"
                max="30"
                className="form-input"
                style={{ width: '100%', padding: '6px 10px' }}
                value={profile.search_limit}
                onChange={(e) => setProfile({ ...profile, search_limit: parseInt(e.target.value, 10) || 15 })}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                Daily Processing Limit
              </label>
              <input
                type="number"
                min="1"
                max="50"
                className="form-input"
                style={{ width: '100%', padding: '6px 10px' }}
                value={profile.daily_processing_limit}
                onChange={(e) => setProfile({ ...profile, daily_processing_limit: parseInt(e.target.value, 10) || 10 })}
              />
            </div>
          </div>

          {/* Discovery Strategy Defaults */}
          <div style={{ paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
            <h4 style={{ margin: '0 0 4px', fontSize: '15px', fontWeight: '600', color: 'var(--text-main)' }}>
              Discovery Strategy & Freshness Defaults
            </h4>
            <p style={{ margin: '0 0 12px', fontSize: '12px', color: 'var(--text-muted)' }}>
              Configure default mood, season, recency filtering, and video orientation across discovery runs.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                  Default Mood
                </label>
                <select
                  className="form-select"
                  style={{ width: '100%', padding: '6px 10px' }}
                  value={profile.search_mood || 'cinematic'}
                  onChange={(e) => setProfile({ ...profile, search_mood: e.target.value })}
                >
                  <option value="cinematic">Cinematic (Recommended)</option>
                  <option value="dreamy">Dreamy & Ethereal</option>
                  <option value="peaceful">Peaceful & Calm</option>
                  <option value="moody">Moody & Atmospheric</option>
                  <option value="cozy">Cozy & Warm</option>
                  <option value="dramatic">Dramatic & Epic</option>
                  <option value="any">Any Mood</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                  Default Season
                </label>
                <select
                  className="form-select"
                  style={{ width: '100%', padding: '6px 10px' }}
                  value={profile.season || 'any'}
                  onChange={(e) => setProfile({ ...profile, season: e.target.value })}
                >
                  <option value="any">Any Season</option>
                  <option value="autumn">Autumn / Fall Foliage</option>
                  <option value="winter">Winter / Snowy</option>
                  <option value="spring">Spring / Meadows</option>
                  <option value="summer">Summer / Sunlit</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                  Recency Preference
                </label>
                <select
                  className="form-select"
                  style={{ width: '100%', padding: '6px 10px' }}
                  value={profile.recency_preference || 'any'}
                  onChange={(e) => setProfile({ ...profile, recency_preference: e.target.value })}
                >
                  <option value="any">Any Publication Date</option>
                  <option value="last_12_months">Last 12 Months</option>
                  <option value="last_6_months">Last 6 Months</option>
                  <option value="last_3_months">Last 3 Months (Fresh Footage)</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                  Preferred Orientation
                </label>
                <select
                  className="form-select"
                  style={{ width: '100%', padding: '6px 10px' }}
                  value={profile.preferred_orientation || 'vertical_9_16'}
                  onChange={(e) => setProfile({ ...profile, preferred_orientation: e.target.value })}
                >
                  <option value="vertical_9_16">Vertical 9:16 Reel (Recommended)</option>
                  <option value="any">Any Aspect Ratio</option>
                  <option value="landscape">Landscape 16:9</option>
                </select>
              </div>
            </div>

            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '12px', fontSize: '13px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={Boolean(profile.strict_recency)}
                onChange={(e) => setProfile({ ...profile, strict_recency: e.target.checked })}
              />
              <span style={{ fontWeight: '500' }}>
                Strict Recency Enforcement (Disallow older footage or pins with unknown publication timestamps)
              </span>
            </label>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
            <button type="submit" className="btn btn-primary" style={{ padding: '8px 20px' }}>
              Save Profile Settings
            </button>
          </div>
        </form>
      )}

      {/* MODAL: RUN PIPELINE */}
      {runModalOpen && (
        <div className="mobile-overlay visible" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="card" style={{ width: '560px', maxWidth: '95%', maxHeight: '90vh', overflowY: 'auto', padding: '24px', borderRadius: 'var(--radius-lg)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Sparkles size={20} style={{ color: '#22c55e' }} />
                <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '700' }}>Launch Nature Reel Pipeline</h3>
              </div>
              <button onClick={() => setRunModalOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer' }}>
                <XCircle size={20} />
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {/* Template Preset Selector */}
              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                  Template Preset
                </label>
                <select
                  className="form-select"
                  style={{ width: '100%', padding: '8px' }}
                  value={runTemplate}
                  onChange={(e) => {
                    setRunTemplate(e.target.value);
                    setSelectedTemplatePreset(e.target.value);
                  }}
                >
                  <option value="Nature Cinematic — Minimal White Serif Quote">
                    Nature Cinematic — Minimal White Serif Quote (Recommended)
                  </option>
                  <option value="Nature Cinematic — Thought Reel">
                    Nature Cinematic — Thought Reel (With Dark Scrim)
                  </option>
                </select>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginTop: '4px' }}>
                  Matches reference video: 1080×1920 full-frame footage, centered white serif typography, soft drop-shadow, no boxes.
                </span>
              </div>

              {/* Target Category */}
              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                  Nature Category
                </label>
                <select
                  className="form-select"
                  style={{ width: '100%', padding: '8px' }}
                  value={runCategory}
                  onChange={(e) => {
                    const nextCat = e.target.value;
                    setRunCategory(nextCat);
                    updateKeywordPreview(nextCat, runMood, runSeason, runOrientation);
                  }}
                >
                  <option value="">Automatic Rotation (All Categories)</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Dynamic Live Keyword & Strategy Preview */}
              <div
                style={{
                  background: 'rgba(34, 197, 94, 0.06)',
                  border: '1px solid rgba(34, 197, 94, 0.25)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '12px 14px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: '700', color: '#22c55e' }}>
                    <Search size={14} /> Pinterest Live Query Preview
                  </div>
                  <button
                    type="button"
                    onClick={() => updateKeywordPreview(runCategory, runMood, runSeason, runOrientation)}
                    disabled={loadingPreview}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: 'var(--accent-primary)',
                      fontSize: '11px',
                      fontWeight: '600',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                    }}
                  >
                    <Shuffle size={12} className={loadingPreview ? 'spin' : ''} /> Rotate Seed
                  </button>
                </div>

                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px',
                    background: 'rgba(0, 0, 0, 0.35)',
                    padding: '8px 10px',
                    borderRadius: '4px',
                    color: '#f4f4f5',
                    wordBreak: 'break-word',
                  }}
                >
                  {loadingPreview
                    ? 'Generating smart query...'
                    : keywordPreview?.generated_query || 'aesthetic autumn forest cinematic vertical video'}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '6px', fontSize: '11px', color: 'var(--text-muted)' }}>
                  <span>
                    Base Seed: <em>"{keywordPreview?.base_keyword || 'cinematic nature video'}"</em>
                  </span>
                  <span>{keywordPreview?.available_keywords?.length || 0} variations in category pool</span>
                </div>

                {/* Sample quick seed chips */}
                {keywordPreview?.sample_queries?.length > 0 && (
                  <div style={{ marginTop: '8px', paddingTop: '6px', borderTop: '1px dashed rgba(255,255,255,0.08)' }}>
                    <span style={{ fontSize: '10px', color: 'var(--text-disabled)', display: 'block', marginBottom: '4px' }}>
                      Click quick seed to use:
                    </span>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                      {keywordPreview.sample_queries.map((sq, idx) => (
                        <button
                          key={idx}
                          type="button"
                          onClick={() => setRunKeyword(sq)}
                          style={{
                            background: runKeyword === sq ? 'var(--accent-primary)' : 'rgba(255,255,255,0.06)',
                            color: runKeyword === sq ? '#ffffff' : 'var(--text-muted)',
                            border: '1px solid rgba(255,255,255,0.1)',
                            borderRadius: '12px',
                            padding: '2px 8px',
                            fontSize: '10px',
                            cursor: 'pointer',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {sq.length > 28 ? `${sq.slice(0, 28)}...` : sq}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Custom Override Keyword */}
              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                  Custom Keyword Override (Optional)
                </label>
                <input
                  type="text"
                  className="form-input"
                  style={{ width: '100%', padding: '6px 10px', fontSize: '13px' }}
                  placeholder="Leave empty to use smart library rotation and mood blending..."
                  value={runKeyword}
                  onChange={(e) => setRunKeyword(e.target.value)}
                />
              </div>

              {/* Discovery Strategy: Mood, Season & Orientation Grid */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px' }}>
                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                    Search Mood
                  </label>
                  <select
                    className="form-select"
                    style={{ width: '100%', padding: '6px' }}
                    value={runMood}
                    onChange={(e) => {
                      const nextMood = e.target.value;
                      setRunMood(nextMood);
                      updateKeywordPreview(runCategory, nextMood, runSeason, runOrientation);
                    }}
                  >
                    <option value="cinematic">Cinematic</option>
                    <option value="dreamy">Dreamy</option>
                    <option value="peaceful">Peaceful</option>
                    <option value="moody">Moody</option>
                    <option value="cozy">Cozy</option>
                    <option value="dramatic">Dramatic</option>
                    <option value="any">Any Mood</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                    Season
                  </label>
                  <select
                    className="form-select"
                    style={{ width: '100%', padding: '6px' }}
                    value={runSeason}
                    onChange={(e) => {
                      const nextSeason = e.target.value;
                      setRunSeason(nextSeason);
                      updateKeywordPreview(runCategory, runMood, nextSeason, runOrientation);
                    }}
                  >
                    <option value="any">Any Season</option>
                    <option value="autumn">Autumn</option>
                    <option value="winter">Winter</option>
                    <option value="spring">Spring</option>
                    <option value="summer">Summer</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                    Orientation
                  </label>
                  <select
                    className="form-select"
                    style={{ width: '100%', padding: '6px' }}
                    value={runOrientation}
                    onChange={(e) => {
                      const nextOrient = e.target.value;
                      setRunOrientation(nextOrient);
                      updateKeywordPreview(runCategory, runMood, runSeason, nextOrient);
                    }}
                  >
                    <option value="vertical_9_16">Vertical 9:16</option>
                    <option value="any">Any</option>
                    <option value="landscape">Landscape</option>
                  </select>
                </div>
              </div>

              {/* Freshness & Quality Gating Controls */}
              <div
                style={{
                  background: 'var(--bg-surface-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '12px',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  <div>
                    <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                      Recency Preference
                    </label>
                    <select
                      className="form-select"
                      style={{ width: '100%', padding: '6px' }}
                      value={runRecency}
                      onChange={(e) => setRunRecency(e.target.value)}
                    >
                      <option value="any">Any Publication Date</option>
                      <option value="last_12_months">Last 12 Months</option>
                      <option value="last_6_months">Last 6 Months</option>
                      <option value="last_3_months">Last 3 Months (Fresh)</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                      Max Inspect per Run ({runMaxInspect})
                    </label>
                    <input
                      type="range"
                      min="5"
                      max="40"
                      value={runMaxInspect}
                      onChange={(e) => setRunMaxInspect(parseInt(e.target.value, 10))}
                      style={{ width: '100%' }}
                    />
                  </div>
                </div>

                <div style={{ marginTop: '10px' }}>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                    Min Quality Score Threshold ({runMinScore} / 100)
                  </label>
                  <input
                    type="range"
                    min="45"
                    max="85"
                    value={runMinScore}
                    onChange={(e) => setRunMinScore(parseInt(e.target.value, 10))}
                    style={{ width: '100%' }}
                  />
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Evaluates stream availability, resolution, aspect ratio, scenic color & recency.
                  </span>
                </div>

                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '10px', fontSize: '12px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={runStrictRecency}
                    onChange={(e) => setRunStrictRecency(e.target.checked)}
                  />
                  <span>Enforce Strict Recency (reject clips older than selected window or without verified timestamp)</span>
                </label>
              </div>

              {/* Excluded Keywords Negative Filter */}
              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                  Exclude Keywords (Negative Filters)
                </label>
                <input
                  type="text"
                  className="form-input"
                  style={{ width: '100%', padding: '6px 10px', fontSize: '12px', fontFamily: 'var(--font-mono)' }}
                  placeholder="anime, cartoon, gaming, makeup, shopping, ads, workout"
                  value={runExcludedKeywords}
                  onChange={(e) => setRunExcludedKeywords(e.target.value)}
                />
              </div>

              {/* Pre-render Thought Editing */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <label style={{ fontWeight: '600', fontSize: '13px' }}>
                    Custom Thought Text (Optional 4–7 Lines)
                  </label>
                  <span style={{ fontSize: '11px', color: 'var(--accent-primary)', cursor: 'pointer' }}
                    onClick={() => setRunCustomThought("With every passing day,\nthe heart learns softness:\nLet the sun go down.\nRelease what was heavy.\nTomorrow is waiting,\nunwritten and clear.")}>
                    Insert Sample Thought
                  </span>
                </div>
                <textarea
                  rows={3}
                  className="form-input"
                  style={{ width: '100%', fontFamily: 'Georgia, serif', fontSize: '13px', padding: '8px', lineHeight: 1.5 }}
                  placeholder="Leave empty for Groq AI to generate original poetic reflection, or write 4–7 short lines here..."
                  value={runCustomThought}
                  onChange={(e) => setRunCustomThought(e.target.value)}
                />
              </div>

              {/* Framing & Duration Row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                    Video Crop Strategy
                  </label>
                  <select
                    className="form-select"
                    style={{ width: '100%', padding: '8px' }}
                    value={runComposition}
                    onChange={(e) => setRunComposition(e.target.value)}
                  >
                    <option value="crop">Full-Frame Crop (Clean 9:16)</option>
                    <option value="blurred-background">Blurred Background</option>
                    <option value="fit-with-background">Fit with Black Bars</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                    Target Duration
                  </label>
                  <select
                    className="form-select"
                    style={{ width: '100%', padding: '8px' }}
                    value={runDuration}
                    onChange={(e) => setRunDuration(parseFloat(e.target.value))}
                  >
                    <option value="10">10 seconds (Short & sweet)</option>
                    <option value="12">12 seconds (Reference match)</option>
                    <option value="15">15 seconds (Calm reading)</option>
                  </select>
                </div>
              </div>

              {/* Typography Settings */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                    Font Size ({runFontSize}px)
                  </label>
                  <input
                    type="range"
                    min="36"
                    max="52"
                    value={runFontSize}
                    onChange={(e) => setRunFontSize(parseInt(e.target.value, 10))}
                    style={{ width: '100%' }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                    Line Spacing ({runLineSpacing}px)
                  </label>
                  <input
                    type="range"
                    min="16"
                    max="36"
                    value={runLineSpacing}
                    onChange={(e) => setRunLineSpacing(parseInt(e.target.value, 10))}
                    style={{ width: '100%' }}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '6px' }}>
                  Max Reels to Render (1–5)
                </label>
                <input
                  type="number"
                  min="1"
                  max="5"
                  className="form-input"
                  style={{ width: '100%', padding: '8px' }}
                  value={runMaxReels}
                  onChange={(e) => setRunMaxReels(e.target.value)}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '12px' }}>
                <button className="btn btn-secondary" onClick={() => setRunModalOpen(false)}>
                  Cancel
                </button>
                <button className="btn btn-primary" onClick={handleStartPipeline}>
                  <Play size={16} /> Start Pipeline
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: VIDEO PLAYER PREVIEW */}
      {selectedReel && (
        <div className="mobile-overlay visible" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="card" style={{ width: '460px', maxWidth: '95%', maxHeight: '92vh', overflowY: 'auto', padding: '20px', borderRadius: 'var(--radius-lg)', background: '#09090b', color: '#ffffff', border: '1px solid rgba(255,255,255,0.12)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Film size={16} style={{ color: '#22c55e' }} />
                <span style={{ fontSize: '14px', fontWeight: '700', color: '#f4f4f5' }}>
                  {selectedReel.template_name || 'Nature Cinematic — Minimal White Serif Quote'}
                </span>
              </div>
              <button onClick={() => setSelectedReel(null)} style={{ background: 'none', border: 'none', color: '#a1a1aa', cursor: 'pointer' }}>
                <XCircle size={20} />
              </button>
            </div>

            {/* 9:16 Video Player */}
            <div style={{ width: '100%', aspectRatio: '9/16', background: '#000000', borderRadius: '10px', overflow: 'hidden', boxShadow: '0 8px 24px rgba(0,0,0,0.6)' }}>
              <video
                src={`/api/nature/media/${selectedReel.rendered_reel_path}`}
                controls
                autoPlay
                playsInline
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            </div>

            {/* Video Specs & Details */}
            <div style={{ marginTop: '14px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', fontSize: '11px' }}>
                <span style={{ padding: '3px 8px', borderRadius: '4px', background: 'rgba(255,255,255,0.08)', color: '#e4e4e7' }}>
                  1080 × 1920 (9:16)
                </span>
                <span style={{ padding: '3px 8px', borderRadius: '4px', background: 'rgba(255,255,255,0.08)', color: '#e4e4e7' }}>
                  30 FPS • H.264
                </span>
                <span style={{ padding: '3px 8px', borderRadius: '4px', background: 'rgba(255,255,255,0.08)', color: '#e4e4e7' }}>
                  {selectedReel.duration_seconds}s Duration
                </span>
                <span style={{ padding: '3px 8px', borderRadius: '4px', background: 'rgba(34, 197, 94, 0.15)', color: '#22c55e', textTransform: 'uppercase', fontWeight: '700' }}>
                  {selectedReel.status}
                </span>
              </div>

              {/* On-screen thought */}
              <div style={{ padding: '12px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px' }}>
                <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#a1a1aa', marginBottom: '4px' }}>
                  On-Screen Reflection
                </div>
                <p style={{ margin: 0, fontStyle: 'italic', fontFamily: 'Georgia, serif', fontSize: '14px', lineHeight: 1.5, whiteSpace: 'pre-line', color: '#ffffff' }}>
                  "{selectedReel.thought_text}"
                </p>
              </div>

              {/* Social Caption */}
              <div>
                <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#a1a1aa', marginBottom: '2px' }}>
                  Social Caption
                </div>
                <p style={{ margin: 0, color: '#d4d4d8', fontSize: '12px', lineHeight: 1.4 }}>
                  {selectedReel.caption}
                </p>
              </div>

              {/* Source Pin link */}
              {selectedReel.candidate_url && (
                <div style={{ fontSize: '12px' }}>
                  <a
                    href={selectedReel.candidate_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: '#60a5fa', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                  >
                    <ExternalLink size={13} /> Original Pinterest Source URL
                  </a>
                </div>
              )}

              {/* Output Path */}
              {selectedReel.rendered_reel_path && (
                <div style={{ fontSize: '11px', color: '#71717a', wordBreak: 'break-all' }}>
                  <strong>Output File:</strong> {selectedReel.rendered_reel_path}
                </div>
              )}

              {/* Modal Actions */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => {
                    const r = selectedReel;
                    setSelectedReel(null);
                    setRerenderingReel(r);
                  }}
                  style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <RotateCcw size={14} /> Re-render Style
                </button>
                <button className="btn btn-secondary btn-sm" onClick={() => setSelectedReel(null)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: EDIT DRAFT CONTENT */}
      {editingDraft && (
        <div className="mobile-overlay visible" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="card" style={{ width: '520px', maxWidth: '95%', padding: '24px', borderRadius: 'var(--radius-lg)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '700' }}>Edit Reel Draft</h3>
              <button onClick={() => setEditingDraft(null)} style={{ background: 'none', border: 'none', cursor: 'pointer' }}>
                <XCircle size={20} />
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '4px' }}>
                  On-Screen Thought Text (Appears on video)
                </label>
                <textarea
                  rows={4}
                  className="form-input"
                  style={{ width: '100%', fontFamily: 'Georgia, serif', fontSize: '14px', padding: '8px', lineHeight: 1.5 }}
                  value={editingDraft.thought_text}
                  onChange={(e) => setEditingDraft({ ...editingDraft, thought_text: e.target.value })}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '4px' }}>
                  Social Caption
                </label>
                <textarea
                  rows={3}
                  className="form-input"
                  style={{ width: '100%', fontSize: '13px', padding: '8px' }}
                  value={editingDraft.caption}
                  onChange={(e) => setEditingDraft({ ...editingDraft, caption: e.target.value })}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '4px' }}>
                  Hashtags (Comma Separated)
                </label>
                <input
                  type="text"
                  className="form-input"
                  style={{ width: '100%', fontSize: '13px', padding: '8px' }}
                  value={(editingDraft.hashtags || []).join(', ')}
                  onChange={(e) => {
                    const tags = e.target.value.split(',').map((t) => t.trim()).filter(Boolean);
                    setEditingDraft({ ...editingDraft, hashtags: tags });
                  }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '12px' }}>
                <button className="btn btn-secondary" onClick={() => setEditingDraft(null)}>
                  Cancel
                </button>
                <button className="btn btn-primary" onClick={handleSaveDraft}>
                  Save Changes
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: RERENDER REEL */}
      {rerenderingReel && (
        <div className="mobile-overlay visible" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="card" style={{ width: '520px', maxWidth: '95%', maxHeight: '90vh', overflowY: 'auto', padding: '24px', borderRadius: 'var(--radius-lg)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <RotateCcw size={18} style={{ color: 'var(--accent-primary)' }} />
                <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '700' }}>Re-render Nature Reel</h3>
              </div>
              <button onClick={() => setRerenderingReel(null)} style={{ background: 'none', border: 'none', cursor: 'pointer' }}>
                <XCircle size={20} />
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {/* Template Preset Selector */}
              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '4px' }}>
                  Template Preset
                </label>
                <select
                  className="form-select"
                  style={{ width: '100%', padding: '8px' }}
                  value={rerenderingReel.template_name || 'Nature Cinematic — Minimal White Serif Quote'}
                  onChange={(e) => setRerenderingReel({ ...rerenderingReel, template_name: e.target.value })}
                >
                  <option value="Nature Cinematic — Minimal White Serif Quote">Nature Cinematic — Minimal White Serif Quote</option>
                  <option value="Nature Cinematic — Thought Reel">Nature Cinematic — Thought Reel</option>
                </select>
              </div>

              {/* Thought Text */}
              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '4px' }}>
                  On-Screen Thought Text (4–7 Lines)
                </label>
                <textarea
                  rows={4}
                  className="form-input"
                  style={{ width: '100%', fontFamily: 'Georgia, serif', fontSize: '14px', padding: '8px', lineHeight: 1.5 }}
                  value={rerenderingReel.thought_text || ''}
                  onChange={(e) => setRerenderingReel({ ...rerenderingReel, thought_text: e.target.value })}
                />
              </div>

              {/* Composition Mode & Duration */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '4px' }}>
                    Crop Strategy
                  </label>
                  <select
                    className="form-select"
                    style={{ width: '100%', padding: '8px' }}
                    value={rerenderingReel.composition_mode || 'crop'}
                    onChange={(e) => setRerenderingReel({ ...rerenderingReel, composition_mode: e.target.value })}
                  >
                    <option value="crop">Full-Frame Crop (9:16)</option>
                    <option value="blurred-background">Blurred Background</option>
                    <option value="fit-with-background">Black Bars</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '4px' }}>
                    Duration
                  </label>
                  <select
                    className="form-select"
                    style={{ width: '100%', padding: '8px' }}
                    value={rerenderingReel.duration_seconds || 12}
                    onChange={(e) => setRerenderingReel({ ...rerenderingReel, duration_seconds: parseFloat(e.target.value) })}
                  >
                    <option value="10">10 seconds</option>
                    <option value="12">12 seconds</option>
                    <option value="15">15 seconds</option>
                  </select>
                </div>
              </div>

              {/* Typography Sliders */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                    Font Size ({rerenderingReel.font_size || 44}px)
                  </label>
                  <input
                    type="range"
                    min="36"
                    max="54"
                    value={rerenderingReel.font_size || 44}
                    onChange={(e) => setRerenderingReel({ ...rerenderingReel, font_size: parseInt(e.target.value, 10) })}
                    style={{ width: '100%' }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontWeight: '600', fontSize: '12px', marginBottom: '4px' }}>
                    Line Spacing ({rerenderingReel.line_spacing || 24}px)
                  </label>
                  <input
                    type="range"
                    min="16"
                    max="36"
                    value={rerenderingReel.line_spacing || 24}
                    onChange={(e) => setRerenderingReel({ ...rerenderingReel, line_spacing: parseInt(e.target.value, 10) })}
                    style={{ width: '100%' }}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontWeight: '600', fontSize: '13px', marginBottom: '4px' }}>
                  Color Grading Preset
                </label>
                <select
                  className="form-select"
                  style={{ width: '100%', padding: '8px' }}
                  value={rerenderingReel.color_preset || 'restrained_warm'}
                  onChange={(e) => setRerenderingReel({ ...rerenderingReel, color_preset: e.target.value })}
                >
                  <option value="restrained_warm">Restrained Warm (Cinematic Default)</option>
                  <option value="golden_hour">Golden Hour (Warm Amber Highlights)</option>
                  <option value="cool_mist">Cool Mist (Subtle Nordic Slate)</option>
                  <option value="none">None (Passthrough Original Colors)</option>
                </select>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '12px' }}>
                <button className="btn btn-secondary" onClick={() => setRerenderingReel(null)}>
                  Cancel
                </button>
                <button className="btn btn-primary" onClick={handleRerender}>
                  <RotateCcw size={16} /> Start Re-render
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default NatureReelMaker;
