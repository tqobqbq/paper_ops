import axios from 'axios';
import { HttpsProxyAgent } from 'https-proxy-agent';
import { SocksProxyAgent } from 'socks-proxy-agent';
import { logDebug } from './Logger.js';

/**
 * Initializes global HTTP/HTTPS and SOCKS proxy agents for Axios
 * based on standard proxy environment variables.
 */
export function setupGlobalProxy(): void {
  const proxy =
    process.env.HTTPS_PROXY ||
    process.env.HTTP_PROXY ||
    process.env.https_proxy ||
    process.env.http_proxy;

  if (!proxy) {
    return;
  }

  try {
    logDebug(`Configuring global HTTP/HTTPS proxy: ${proxy}`);
    const agent = proxy.startsWith('socks')
      ? new SocksProxyAgent(proxy)
      : new HttpsProxyAgent(proxy);

    // Inject agent as default for both http and https protocols
    axios.defaults.httpAgent = agent;
    axios.defaults.httpsAgent = agent;
  } catch (error: any) {
    logDebug(`Failed to initialize global proxy agent: ${error.message}`);
  }
}
