import { describe, expect, it } from '@jest/globals';
import { ACMSearcher } from '../../src/platforms/ACMSearcher.js';
import { DBLPSearcher } from '../../src/platforms/DBLPSearcher.js';
import { IEEESearcher } from '../../src/platforms/IEEESearcher.js';
import { OpenReviewSearcher } from '../../src/platforms/OpenReviewSearcher.js';
import { USENIXSearcher } from '../../src/platforms/USENIXSearcher.js';

describe('registry-backed platform searchers', () => {
  it('exposes DBLP as a keyless metadata source', () => {
    const capabilities = new DBLPSearcher().getCapabilities();
    expect(capabilities.search).toBe(true);
    expect(capabilities.requiresApiKey).toBe(false);
  });

  it('exposes IEEE as a key-gated official API source', () => {
    const capabilities = new IEEESearcher().getCapabilities();
    expect(capabilities.search).toBe(true);
    expect(capabilities.requiresApiKey).toBe(true);
    expect(capabilities.supportedOptions).toContain('articleTitle');
  });

  it('exposes ACM as a metadata-proxy source without scraping ACM search', () => {
    const capabilities = new ACMSearcher().getCapabilities();
    expect(capabilities.search).toBe(true);
    expect(capabilities.requiresApiKey).toBe(false);
  });

  it('exposes USENIX as a DBLP-backed metadata source', () => {
    const capabilities = new USENIXSearcher().getCapabilities();
    expect(capabilities.search).toBe(true);
    expect(capabilities.requiresApiKey).toBe(false);
  });

  it('exposes OpenReview as a keyless public-note search source', () => {
    const capabilities = new OpenReviewSearcher().getCapabilities();
    expect(capabilities.search).toBe(true);
    expect(capabilities.requiresApiKey).toBe(false);
    expect(capabilities.supportedOptions).toContain('venue');
  });
});
