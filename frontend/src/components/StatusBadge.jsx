import React from 'react';
import { CheckCircle2, Clock, AlertCircle, Ban, ArrowUpRight, Search, Play } from 'lucide-react';

export function StatusBadge({ status, className = '' }) {
  const s = (status || '').toUpperCase();

  switch (s) {
    case 'UPLOADED':
      return (
        <span className={`badge badge-status-uploaded ${className}`}>
          <ArrowUpRight size={12} />
          Uploaded
        </span>
      );
    case 'COMPLETED':
      return (
        <span className={`badge badge-status-completed ${className}`}>
          <CheckCircle2 size={12} />
          Completed
        </span>
      );
    case 'PROCESSING':
    case 'RUNNING':
      return (
        <span className={`badge badge-status-processing ${className}`}>
          <Play size={12} />
          Processing
        </span>
      );
    case 'QUEUED':
      return (
        <span className={`badge badge-status-queued ${className}`}>
          <Clock size={12} />
          Queued
        </span>
      );
    case 'DISCOVERED':
      return (
        <span className={`badge badge-status-discovered ${className}`}>
          <Search size={12} />
          Discovered
        </span>
      );
    case 'FAILED':
      return (
        <span className={`badge badge-status-failed ${className}`}>
          <AlertCircle size={12} />
          Failed
        </span>
      );
    case 'SKIPPED':
      return (
        <span className={`badge badge-status-skipped ${className}`}>
          <Ban size={12} />
          Skipped
        </span>
      );
    default:
      return (
        <span className={`badge badge-status-skipped ${className}`}>
          {status || 'Unknown'}
        </span>
      );
  }
}

export default StatusBadge;
