import { NextRequest, NextResponse } from 'next/server';
import { qcFetch } from '@/lib/qc-server-client';
import type { Signal } from '@/lib/qc-client';

const PROJECT_ID = process.env.QC_PROJECT_ID ?? '32033824';

interface QCLogsResponse {
  success: boolean;
  logs?: string | string[];
  [key: string]: unknown;
}

// Parse SIGNAL|{date}|{symbol}|score={n}/8 lines
// Also capture ENTRY|{date}|{symbol} lines as score=8 entries
const SIGNAL_RE = /SIGNAL\|(\d{4}-\d{2}-\d{2})\|([A-Z]+)\|score=(\d+)\/8/;
const ENTRY_RE = /ENTRY\|(\d{4}-\d{2}-\d{2})\|([A-Z]+)/;

function scoreToRating(score: number): string {
  if (score >= 7) return '+++';
  if (score >= 5) return '++';
  if (score >= 3) return '+';
  if (score >= 1) return '=';
  return '--';
}

function parseLogs(rawLogs: string | string[]): Signal[] {
  const lines = Array.isArray(rawLogs)
    ? rawLogs
    : rawLogs.split('\n');

  const signals: Signal[] = [];

  for (const line of lines) {
    const sigMatch = SIGNAL_RE.exec(line);
    if (sigMatch) {
      const [, date, symbol, scoreStr] = sigMatch;
      const score = parseInt(scoreStr, 10);
      signals.push({ date, symbol, score, rating: scoreToRating(score) });
      continue;
    }
    const entryMatch = ENTRY_RE.exec(line);
    if (entryMatch) {
      const [, date, symbol] = entryMatch;
      signals.push({ date, symbol, score: 8, rating: '+++' });
    }
  }

  // Sort descending by date
  signals.sort((a, b) => b.date.localeCompare(a.date));
  return signals;
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const backtestId = searchParams.get('backtestId');

  try {
    const path = backtestId
      ? `/projects/${PROJECT_ID}/backtests/${backtestId}/logs`
      : `/projects/${PROJECT_ID}/live/logs`;

    const data = await qcFetch<QCLogsResponse>(path);
    const rawLogs = data.logs ?? '';
    const signals = parseLogs(rawLogs);
    return NextResponse.json(signals);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error('[qc/signals]', message);
    // Graceful empty array on any error
    return NextResponse.json([]);
  }
}
