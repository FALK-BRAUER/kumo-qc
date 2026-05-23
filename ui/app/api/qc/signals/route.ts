import { NextRequest, NextResponse } from 'next/server';
import { qcPost } from '@/lib/qc-server-client';
import type { Signal } from '@/lib/qc-client';

const PROJECT_ID = parseInt(process.env.QC_PROJECT_ID ?? '32033824', 10);
const PAGE_SIZE = 200;

// Actual log format: SIGNAL|2025-01-01|AAPL|++|7/8|T,T,T,T,T,T,F,T
const SIGNAL_RE = /SIGNAL\|(\d{4}-\d{2}-\d{2})\|([A-Z0-9.]+)\|([\+\-=]+)\|(\d+)\/8/;

interface LogPage {
  success: boolean;
  logs: string[];
  length: number;
}

async function fetchAllLogs(backtestId: string): Promise<string[]> {
  const first = await qcPost<LogPage>('/backtests/read/log', {
    projectId: PROJECT_ID,
    backtestId,
    start: 0,
    end: PAGE_SIZE,
    query: '',
  });

  const total = first.length;
  const all: string[] = [...(first.logs ?? [])];

  for (let start = PAGE_SIZE; start < total; start += PAGE_SIZE) {
    const page = await qcPost<LogPage>('/backtests/read/log', {
      projectId: PROJECT_ID,
      backtestId,
      start,
      end: Math.min(start + PAGE_SIZE, total),
      query: '',
    });
    all.push(...(page.logs ?? []));
  }

  return all;
}

function parseLogs(lines: string[]): Signal[] {
  const signals: Signal[] = [];
  for (const line of lines) {
    const m = SIGNAL_RE.exec(line);
    if (!m) continue;
    const [, date, symbol, rating, scoreStr] = m;
    signals.push({ date, symbol, score: parseInt(scoreStr, 10), rating });
  }
  signals.sort((a, b) => b.date.localeCompare(a.date));
  return signals;
}

export async function GET(request: NextRequest) {
  const backtestId = new URL(request.url).searchParams.get('backtestId');
  if (!backtestId) {
    return NextResponse.json({ error: 'backtestId required' }, { status: 400 });
  }

  try {
    const lines = await fetchAllLogs(backtestId);
    const signals = parseLogs(lines);
    return NextResponse.json(signals);
  } catch (err) {
    console.error('[qc/signals]', err instanceof Error ? err.message : String(err));
    return NextResponse.json([]);
  }
}
