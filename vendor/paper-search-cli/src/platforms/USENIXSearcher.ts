import { Paper, PaperFactory } from '../models/Paper.js';
import { DownloadOptions, PaperSource, PlatformCapabilities, SearchOptions } from './PaperSource.js';
import { DBLPSearcher } from './DBLPSearcher.js';

const USENIX_TERMS = [
  'usenix',
  'osdi',
  'fast',
  'nsdi',
  'atc',
  'security symposium',
  'lisa',
  'srecon',
  'hotcloud',
  'hotstorage',
  'hotsec',
  'woot'
];

export class USENIXSearcher extends PaperSource {
  private readonly dblp: DBLPSearcher;

  constructor(dblpSearcher = new DBLPSearcher()) {
    super('usenix', 'https://dblp.org/search/publ/api');
    this.dblp = dblpSearcher;
  }

  getCapabilities(): PlatformCapabilities {
    return {
      search: true,
      download: false,
      fullText: false,
      citations: false,
      requiresApiKey: false,
      supportedOptions: ['maxResults', 'year', 'author', 'journal', 'sortBy', 'sortOrder']
    };
  }

  async search(query: string, options: SearchOptions = {}): Promise<Paper[]> {
    const maxResults = options.maxResults || 10;
    const dblpResults = await this.dblp.search(`${query} USENIX`, {
      ...options,
      maxResults: Math.min(Math.max(maxResults * 4, 40), 100)
    });

    return dblpResults
      .filter(paper => this.isUsenixPaper(paper))
      .map(paper => this.toUsenixPaper(paper))
      .slice(0, maxResults);
  }

  async downloadPdf(_paperId: string, _options: DownloadOptions = {}): Promise<string> {
    throw new Error('USENIX search returns metadata only; use returned URLs or download_with_fallback.');
  }

  async readPaper(_paperId: string, _options: DownloadOptions = {}): Promise<string> {
    throw new Error('USENIX search does not provide full-text extraction.');
  }

  private isUsenixPaper(paper: Paper): boolean {
    const haystack = [
      paper.title,
      paper.journal || '',
      paper.url,
      paper.doi,
      JSON.stringify(paper.extra || {})
    ].join(' ').toLowerCase();

    return USENIX_TERMS.some(term => haystack.includes(term));
  }

  private toUsenixPaper(paper: Paper): Paper {
    return PaperFactory.create({
      ...paper,
      paperId: paper.paperId,
      title: paper.title,
      source: 'usenix',
      extra: {
        ...(paper.extra || {}),
        backingSource: 'dblp',
        originalSource: paper.source
      }
    });
  }
}

