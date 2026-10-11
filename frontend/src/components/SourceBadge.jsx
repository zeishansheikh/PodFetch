import React from 'react';
import { Music } from 'lucide-react';
import { YoutubeIcon, PinterestIcon, InstagramIcon } from './BrandIcons';

export function SourceBadge({ platform, className = '' }) {
  const p = (platform || '').toLowerCase();

  if (p === 'youtube') {
    return (
      <span className={`badge badge-source-youtube ${className}`}>
        <YoutubeIcon size={12} />
        YouTube
      </span>
    );
  }

  if (p === 'pinterest') {
    return (
      <span className={`badge badge-source-pinterest ${className}`}>
        <PinterestIcon size={12} />
        Pinterest
      </span>
    );
  }

  if (p === 'instagram' || p === 'instagram_audio') {
    return (
      <span className={`badge badge-source-instagram ${className}`}>
        <InstagramIcon size={12} />
        Instagram Audio
      </span>
    );
  }

  return (
    <span className={`badge ${className}`}>
      <Music size={12} />
      {platform || 'Unknown'}
    </span>
  );
}

export default SourceBadge;
