import { Container, getContainer } from '@cloudflare/containers';
import { handleRequest } from './gateway.js';

export class TidelineContainer extends Container {
  defaultPort = 8080;
  sleepAfter = '15m';
  enableInternet = true;
  envVars = {
    TIDELINE_MODE: 'mongo',
    MONGODB_URI: this.env.MONGODB_URI || '',
    MONGODB_DB: this.env.MONGODB_DB || 'tideline',
    COPERNICUS_USERNAME: this.env.COPERNICUS_USERNAME || '',
    COPERNICUS_PASSWORD: this.env.COPERNICUS_PASSWORD || '',
    TIDELINE_INTERNAL_TOKEN: this.env.TIDELINE_INTERNAL_TOKEN || '',
    AUTO_REFRESH_FORECASTS: 'false',
    ROUTE_TIMEOUT_SECONDS: '90',
    GEMINI_API_KEY: this.env.GEMINI_API_KEY || '',
    GEMINI_MODEL: 'gemini-4-argon',
    CONGESTION_CALLS_PER_HOUR: this.env.CONGESTION_CALLS_PER_HOUR || '20',
    COMPLIANCE_CALLS_PER_HOUR: this.env.COMPLIANCE_CALLS_PER_HOUR || '60',
    COMPLIANCE_CONCURRENCY: this.env.COMPLIANCE_CONCURRENCY || '6',
    COMPLIANCE_MAX_CONTEXT_BYTES: this.env.COMPLIANCE_MAX_CONTEXT_BYTES || '3000000',
  };
}

export default {
  fetch(request, env) {
    return handleRequest(request, env, forwarded => getContainer(env.ROUTER, 'routing').fetch(forwarded));
  },
  async scheduled(_event, env) {
    // Independent refreshes share the cron window; their deadlines do not add together.
    const results = await Promise.allSettled([
      ['refresh', 14], ['refresh-compliance', 5]
    ].map(async ([path, minutes]) => {
      const response = await getContainer(env.ROUTER, 'routing').fetch(new Request(`http://container/internal/${path}`, {
        method: 'POST', headers: { 'X-Tideline-Internal-Token': env.TIDELINE_INTERNAL_TOKEN },
        signal: AbortSignal.timeout(minutes * 60 * 1000)
      }));
      await response.body?.cancel();
      if (!response.ok) throw new Error(`${path} failed (${response.status}).`);
    }));
    const failures = results.filter(result => result.status === 'rejected');
    if (failures.length) throw new AggregateError(failures.map(result => result.reason), 'Scheduled refresh failed.');
  },
};
