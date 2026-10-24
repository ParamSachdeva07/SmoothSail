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
  };
}

export default {
  fetch(request, env) {
    return handleRequest(request, env, forwarded => getContainer(env.ROUTER, 'routing').fetch(forwarded));
  },
  async scheduled(_event, env) {
    const response = await getContainer(env.ROUTER, 'routing').fetch(new Request('http://container/internal/refresh', {
      method: 'POST',
      headers: { 'X-Tideline-Internal-Token': env.TIDELINE_INTERNAL_TOKEN },
      signal: AbortSignal.timeout(14 * 60 * 1000),
    }));
    await response.body?.cancel();
    if (!response.ok) throw new Error(`Forecast refresh failed (${response.status}).`);
  },
};
