import { useEffect, useState } from 'react';
import request from '../utils/request';

const apiPath = (path: string) => path.startsWith('/api/') ? path.slice(4) : path;

export const useAuthenticatedFileUrl = (path?: string) => {
  const [url, setUrl] = useState('');
  const [contentType, setContentType] = useState('');

  useEffect(() => {
    if (!path) {
      setUrl('');
      setContentType('');
      return;
    }
    let objectUrl = '';
    let cancelled = false;
    request.get(apiPath(path), { responseType: 'blob' }).then((blob: Blob) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setContentType(blob.type || 'application/octet-stream');
      setUrl(objectUrl);
    }).catch(() => {
      if (!cancelled) setUrl('');
    });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  return { url, contentType };
};

export const authenticatedApiPath = apiPath;
