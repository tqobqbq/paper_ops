import axios from 'axios';
import * as fs from 'fs';
import * as path from 'path';
import { Readable } from 'stream';
import { TIMEOUTS, USER_AGENT } from '../config/constants.js';

export interface PdfDownloadOptions {
  headers?: Record<string, string>;
}

export function safeFilename(value: string, fallback = 'paper'): string {
  const safe = value.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^[_\-.]+|[_\-.]+$/g, '');
  return (safe || fallback).slice(0, 120);
}

export function isPdfBuffer(buffer: Buffer, contentType = ''): boolean {
  return contentType.toLowerCase().includes('pdf') || buffer.subarray(0, 4).toString() === '%PDF';
}

async function getStreamSnippet(stream: any, maxBytes = 240): Promise<string> {
  return new Promise((resolve) => {
    let buffer = Buffer.alloc(0);
    const onData = (chunk: Buffer) => {
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length >= maxBytes) {
        cleanup();
        stream.destroy?.();
      }
    };
    const cleanup = () => {
      if (typeof stream.off === 'function') {
        stream.off('data', onData);
      }
    };
    stream.on('data', onData);
    stream.on('end', () => {
      cleanup();
      resolve(buffer.subarray(0, maxBytes).toString('utf8').replace(/\s+/g, ' ').trim());
    });
    stream.on('close', () => {
      cleanup();
      resolve(buffer.subarray(0, maxBytes).toString('utf8').replace(/\s+/g, ' ').trim());
    });
    stream.on('error', () => {
      cleanup();
      resolve(buffer.subarray(0, maxBytes).toString('utf8').replace(/\s+/g, ' ').trim());
    });
  });
}

export async function downloadPdfFromUrl(
  pdfUrl: string,
  savePath: string,
  filenameHint: string,
  options: PdfDownloadOptions = {}
): Promise<string> {
  if (!pdfUrl) {
    throw new Error('Missing PDF URL');
  }
  if (pdfUrl.startsWith('ftp://')) {
    throw new Error(`FTP PDF links are not supported by the Node downloader: ${pdfUrl}`);
  }

  fs.mkdirSync(savePath, { recursive: true });
  const outputPath = path.join(savePath, `${safeFilename(filenameHint)}.pdf`);

  const response = await axios.get(pdfUrl, {
    responseType: 'stream',
    timeout: TIMEOUTS.DOWNLOAD,
    maxRedirects: 5,
    headers: {
      'User-Agent': USER_AGENT,
      Accept: 'application/pdf,*/*',
      ...(options.headers || {})
    },
    validateStatus: status => status < 500
  });

  if (response.status >= 400) {
    let errStream = response.data;
    if (!(errStream instanceof Readable) && !(errStream && typeof errStream.on === 'function')) {
      errStream = Readable.from(Buffer.isBuffer(errStream) ? errStream : Buffer.from(errStream || ''));
    }
    const errorSnippet = await getStreamSnippet(errStream);
    const cfHeader = response.headers['cf-mitigated'];
    const challenge = !!cfHeader || /cloudflare|challenge|just a moment/i.test(errorSnippet);
    const reason = challenge ? 'provider returned an HTML anti-bot challenge instead of a PDF' : 'provider refused the request';
    throw new Error(`PDF download failed with HTTP ${response.status}: ${reason}`);
  }

  return new Promise<string>((resolve, reject) => {
    const writer = fs.createWriteStream(outputPath);
    let reader = response.data;
    if (!(reader instanceof Readable) && !(reader && typeof reader.on === 'function')) {
      reader = Readable.from(Buffer.isBuffer(reader) ? reader : Buffer.from(reader || ''));
    }
    let checked = false;
    let totalBytes = 0;
    const contentLengthHeader = response.headers['content-length'];
    const expectedLength = contentLengthHeader ? parseInt(String(contentLengthHeader), 10) : 0;

    writer.on('error', (err) => {
      if (typeof reader.destroy === 'function') reader.destroy();
      fs.unlink(outputPath, () => {});
      reject(err);
    });

    reader.on('data', (chunk: Buffer) => {
      totalBytes += chunk.length;

      if (!checked) {
        checked = true;
        const contentType = String(response.headers['content-type'] || '').toLowerCase();
        const isPdf = contentType.includes('pdf') || chunk.subarray(0, 4).toString() === '%PDF';

        if (!isPdf) {
          const snippet = chunk.subarray(0, 240).toString('utf8').replace(/\s+/g, ' ').trim();
          const cfHeader = response.headers['cf-mitigated'];
          const challenge = !!cfHeader || /cloudflare|challenge|preparing to download|proof-of-work|<!doctype html/i.test(snippet);
          const reason = challenge
            ? 'the provider returned an HTML challenge page instead of a PDF'
            : `content-type was ${contentType || 'unknown'}`;

          if (typeof reader.destroy === 'function') reader.destroy();
          writer.destroy();
          fs.unlink(outputPath, () => {});
          reject(new Error(`Resolved URL did not return a PDF (${reason}): ${pdfUrl}`));
          return;
        }
      }

      if (!writer.write(chunk)) {
        if (typeof reader.pause === 'function') reader.pause();
      }
    });

    writer.on('drain', () => {
      if (typeof reader.resume === 'function') reader.resume();
    });

    reader.on('end', () => {
      writer.end();
    });

    reader.on('close', () => {
      if (typeof reader.destroy === 'function') reader.destroy();
    });

    writer.on('finish', () => {
      if (expectedLength && totalBytes !== expectedLength) {
        fs.unlink(outputPath, () => {});
        reject(new Error(`PDF download incomplete: received ${totalBytes} bytes, expected ${expectedLength} bytes`));
        return;
      }
      resolve(outputPath);
    });

    reader.on('error', (err: any) => {
      writer.destroy();
      fs.unlink(outputPath, () => {});
      reject(err);
    });
  });
}
