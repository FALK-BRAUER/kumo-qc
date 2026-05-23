import { NextResponse } from 'next/server';
import { qcFetch } from '@/lib/qc-server-client';

// QC Project IDs:
//   backtest_bct:   32033824
//   performance_bct: 32034565
//   live_bct:       NOT deployed yet
const PROJECT_ID = process.env.QC_PROJECT_ID ?? '32033824';

interface QCLiveReadResponse {
  success: boolean;
  status?: string;
  projectId?: number;
  deployId?: string;
  accountId?: string;
  [key: string]: unknown;
}

// Ensure Node.js runtime for crypto module compatibility
export const runtime = 'nodejs';

export async function GET() {
  try {
    const data = await qcFetch<QCLiveReadResponse>(`/live/${PROJECT_ID}/read`);
    return NextResponse.json({
      status: data.status ?? 'unknown',
      projectId: data.projectId?.toString() ?? PROJECT_ID,
      deployId: data.deployId ?? null,
      accountId: data.accountId ?? null,
    });
  } catch (err) {
    // Project not deployed or API error — return safe default
    const message = err instanceof Error ? err.message : String(err);
    console.error('[qc/status]', message);
    return NextResponse.json({
      status: 'not_deployed',
      projectId: null,
      deployId: null,
      accountId: null,
    });
  }
}
