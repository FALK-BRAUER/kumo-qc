import { NextResponse } from 'next/server';
import { qcFetch } from '@/lib/qc-server-client';
import type { QCOrder } from '@/lib/qc-client';

const PROJECT_ID = process.env.QC_PROJECT_ID ?? '32033824';

interface QCOrderRaw {
  id?: number | string;
  symbol?: { value?: string } | string;
  quantity?: number;
  price?: number;
  status?: number | string;
  direction?: number | string;
  submittedAt?: string;
  time?: string;
  [key: string]: unknown;
}

interface QCOrdersResponse {
  success: boolean;
  orders?: QCOrderRaw[];
  [key: string]: unknown;
}

const ORDER_STATUS_MAP: Record<number, string> = {
  0: 'New',
  1: 'Submitted',
  2: 'PartiallyFilled',
  3: 'Filled',
  4: 'Canceled',
  5: 'None',
  6: 'Invalid',
  7: 'CancelPending',
  8: 'PreSubmitted',
};

const ORDER_DIRECTION_MAP: Record<number, string> = {
  0: 'Buy',
  1: 'Sell',
  2: 'Hold',
};

function resolveSymbol(raw: QCOrderRaw['symbol']): string {
  if (!raw) return '';
  if (typeof raw === 'string') return raw;
  return raw.value ?? '';
}

function resolveStatus(raw: QCOrderRaw['status']): string {
  if (raw === undefined || raw === null) return 'Unknown';
  if (typeof raw === 'string') return raw;
  return ORDER_STATUS_MAP[raw] ?? String(raw);
}

function resolveDirection(raw: QCOrderRaw['direction']): string {
  if (raw === undefined || raw === null) return 'Unknown';
  if (typeof raw === 'string') return raw;
  return ORDER_DIRECTION_MAP[raw] ?? String(raw);
}

export async function GET() {
  try {
    const data = await qcFetch<QCOrdersResponse>(`/live/${PROJECT_ID}/orders`);

    const orders: QCOrder[] = (data.orders ?? []).map((o) => ({
      id: String(o.id ?? ''),
      symbol: resolveSymbol(o.symbol),
      quantity: o.quantity ?? 0,
      price: o.price ?? 0,
      status: resolveStatus(o.status),
      direction: resolveDirection(o.direction),
      submittedAt: o.submittedAt ?? o.time ?? '',
    }));

    return NextResponse.json(orders);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error('[qc/orders]', message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
