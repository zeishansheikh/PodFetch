/**
 * PodFetch API Client
 * Centralized HTTP layer interacting with FastAPI backend.
 * Provides request validation, error normalization, and non-blocking calls.
 */

const API_BASE = '/api';

class ApiError extends Error {
  constructor(message, status = 500, details = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  try {
    const res = await fetch(url, {
      ...options,
      headers,
    });

    if (!res.ok) {
      let errorMsg = `Server error (${res.status})`;
      let details = null;
      try {
        const data = await res.json();
        errorMsg = data.detail || data.message || errorMsg;
        details = data;
      } catch (_) {
        errorMsg = await res.text() || errorMsg;
      }
      throw new ApiError(errorMsg, res.status, details);
    }

    // Check if 204 No Content
    if (res.status === 204) return null;

    return await res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    // Network / fetch error
    throw new ApiError(
      err.message === 'Failed to fetch'
        ? 'Cannot connect to PodFetch backend. Make sure the API server is running on port 8000.'
        : err.message,
      0
    );
  }
}

export const api = {
  // Health & System
  getHealth: () => request('/health'),

  // Statistics
  getStats: () => request('/stats'),

  // Jobs / Processing Queue
  getJobs: (params = {}) => {
    const query = new URLSearchParams();
    if (params.status) query.append('status', params.status);
    if (params.platform) query.append('platform', params.platform);
    if (params.limit) query.append('limit', params.limit);
    if (params.offset) query.append('offset', params.offset);
    const qs = query.toString();
    return request(`/jobs${qs ? `?${qs}` : ''}`);
  },

  getActiveJobs: () => request('/jobs/active'),

  retryFailedJobs: () => request('/jobs/retry-failed', { method: 'POST' }),

  // Media Library
  getLibrary: (params = {}) => {
    const query = new URLSearchParams();
    if (params.search) query.append('search', params.search);
    if (params.platform) query.append('platform', params.platform);
    if (params.status) query.append('status', params.status);
    if (params.limit) query.append('limit', params.limit);
    if (params.offset) query.append('offset', params.offset);
    const qs = query.toString();
    return request(`/library${qs ? `?${qs}` : ''}`);
  },

  // Google Drive
  getDriveStatus: () => request('/drive/status'),

  // Instagram Workspace
  getInstagramStatus: () => request('/instagram/status'),

  // Discovery Workflows
  discoverYouTube: (payload) =>
    request('/discover/youtube', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  discoverPinterest: (payload) =>
    request('/discover/pinterest', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  discoverInstagram: (payload) =>
    request('/discover/instagram', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Download Workflows
  downloadVideo: (payload) =>
    request('/download/video', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  downloadInstagramAudio: (payload) =>
    request('/download/instagram-audio', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Settings & Logs
  getSettings: () => request('/settings'),

  getLogs: (lines = 100) => request(`/logs?lines=${lines}`),
};

export default api;
