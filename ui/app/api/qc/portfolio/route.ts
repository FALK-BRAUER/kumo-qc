import { NextResponse } from 'next/server';
import { qcFetch } from '@/lib/qc-server-client';
import type { QCPortfolio, QCHolding } from '@/lib/qc-client';

const PROJECT_ID = process.env.QC_PROJECT_ID ?? '32033824';

interface QCHoldingRaw {
  symbol?: { value?: string } | string;
  quantity?: number;
  averagePrice?: number;
  marketPrice?: number;
  unrealizedPnl?: number;
  [key: string]: unknown;
}

interface QCPortfolioResponse {
  success: boolean;
  holdings?: QCHoldingRaw[];
  totalPortfolioValue?: number;
  cash?: number;
  totalUnrealizedProfit?: number;
  [key: string]: unknown;
}

function resolveSymbol(raw: QCHoldingRaw['symbol']): string {
  if (!raw) return '';
  if (typeof raw === 'string') return raw;
  return raw.value ?? '';
}

// Ensure Node.js runtime for crypto module compatibility
export const runtime = 'nodejs';

export async function GET() {
  try {
    const data = await qcFetch<QCPortfolioResponse>(`/live/${PROJECT_ID}/portfolio/holdings`);

    const holdings: QCHolding[] = (data.holdings ?? []).map((h) => ({
      symbol: resolveSymbol(h.symbol),
      quantity: h.quantity ?? 0,
      averagePrice: h.averagePrice ?? 0,
      marketPrice: h.marketPrice ?? 0,
      unrealizedPnl: h.unrealizedPnl ?? 0,
    }));

    const portfolio: QCPortfolio = {
      holdings,
      totalPortfolioValue: data.totalPortfolioValue ?? 0,
      cash: data.cash ?? 0,
      totalUnrealizedProfit: data.totalUnrealizedProfit ?? 0,
    };

    return NextResponse.json(portfolio);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error('[qc/portfolio]', message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
