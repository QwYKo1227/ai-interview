import { useEffect, useState } from 'react';
import request from '../utils/request';

const apiPath = (path: string) => path.startsWith('/api/') ? path.slice(4) : path;

export const useAuthenticatedFileUrl = (path?: string) => {
  const [url, setUrl] = useState('');
  const [contentType, setContentType] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setUrl(previous => {
      if (previous) URL.revokeObjectURL(previous);
      return '';
    });
    setContentType('');
    if (!path) {
      return;
    }
    let objectUrl = '';
    request.get(apiPath(path), { responseType: 'blob', signal: controller.signal }).then((blob: Blob) => {
      if (controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob);
      setContentType(blob.type || 'application/octet-stream');
      setUrl(objectUrl);
    }).catch(() => {
      if (!controller.signal.aborted) {
        setUrl('');
        setContentType('');
      }
    });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  return { url, contentType };
};

export const authenticatedApiPath = apiPath;
