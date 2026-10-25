import { API_BASE_URL } from '../api/client.js';

/** Stored public references download through our API; ordinary web sources open at the publisher. */
export function evidenceTarget(evidence, baseUrl = API_BASE_URL) {
  if (evidence.authority !== 'user_document' &&
      /^\/compliance\/documents\/[0-9a-f]{24}\/download$/.test(evidence.downloadPath || '')) {
    return { href: `${baseUrl.replace(/\/+$/, '')}${evidence.downloadPath}`, download: true };
  }
  try {
    const url = new URL(evidence.url);
    if (['https:', 'http:'].includes(url.protocol)) return { href: url.href, download: false };
  } catch { /* Source without a downloadable original or a safe publisher URL. */ }
  return null;
}
