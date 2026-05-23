'use client';

import { useState, useEffect, useCallback } from 'react';
import { RefreshCw } from 'lucide-react';
import { GateStatusBadge } from '@/components/dashboard/gate-status-badge';
import { AccountSummary } from '@/components/dashboard/account-summary';
import { PositionsTable } from '@/components/dashboard/positions-table';
import { SignalTable } from '@/components/dashboard/signal-table';
import { usePolling } from '@/lib/use-polling';
import type { QCLiveStatus, QCPortfolio, QCOrder, Signal } from '@/lib/qc-client';

interface SectionState<T> {
  data: T | null;
  isLoading: boolean;
  error: string | null;
}

function initialSection<T>(): SectionState<T> {
  return { data: null, isLoading: true, error: null };
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export default function DashboardPage() {
  const [status, setStatus] = useState<SectionState<QCLiveStatus>>(initialSection());
  const [portfolio, setPortfolio] = useState<SectionState<QCPortfolio>>(initialSection());
  const [orders, setOrders] = useState<SectionState<QCOrder[]>>(initialSection());
  const [signals, setSignals] = useState<SectionState<Signal[]>>(initialSection());
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const fetchAll = useCallback(async () => {
    setStatus((s) => ({ ...s, isLoading: true, error: null }));
    setPortfolio((s) => ({ ...s, isLoading: true, error: null }));
    setOrders((s) => ({ ...s, isLoading: true, error: null }));
    setSignals((s) => ({ ...s, isLoading: true, error: null }));

    await Promise.allSettled([
      fetchJson<QCLiveStatus>('/api/qc/status').then(
        (data) => setStatus({ data, isLoading: false, error: null }),
        (err: unknown) =>
          setStatus({ data: null, isLoading: false, error: String(err) })
      ),
      fetchJson<QCPortfolio>('/api/qc/portfolio').then(
        (data) => setPortfolio({ data, isLoading: false, error: null }),
        (err: unknown) =>
          setPortfolio({ data: null, isLoading: false, error: String(err) })
      ),
      fetchJson<QCOrder[]>('/api/qc/orders').then(
        (data) => setOrders({ data, isLoading: false, error: null }),
        (err: unknown) =>
          setOrders({ data: null, isLoading: false, error: String(err) })
      ),
      fetchJson<Signal[]>('/api/qc/signals').then(
        (data) => setSignals({ data, isLoading: false, error: null }),
        (err: unknown) =>
          setSignals({ data: null, isLoading: false, error: String(err) })
      ),
    ]);

    setLastRefreshed(new Date());
  }, []);

  // Initial load
  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  // Poll every 30s
  usePolling(fetchAll, 30_000);

  return (
    <div className="min-h-screen bg-zinc-950 text-foreground">
      {/* Header */}
      <header className="border-b border-border/50 bg-zinc-900/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-base font-semibold font-mono tracking-tight text-foreground">
              kumo-qc cockpit
            </span>
            <GateStatusBadge status={status.data?.status ?? null} />
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {lastRefreshed && (
              <span>
                Updated {lastRefreshed.toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={() => void fetchAll()}
              className="flex items-center gap-1 hover:text-foreground transition-colors"
              aria-label="Refresh"
            >
              <RefreshCw className="size-3.5" />
              Refresh
            </button>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-4 py-6 flex flex-col gap-6">
        {/* Account summary */}
        {portfolio.error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
            Portfolio error: {portfolio.error}
          </div>
        )}
        <AccountSummary
          portfolio={portfolio.data}
          isLoading={portfolio.isLoading}
        />

        {/* Positions table */}
        {orders.error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
            Orders error: {orders.error}
          </div>
        )}
        <PositionsTable
          positions={portfolio.data?.holdings}
          isLoading={portfolio.isLoading}
        />

        {/* Signals table */}
        {signals.error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
            Signals error: {signals.error}
          </div>
        )}
        <SignalTable
          signals={signals.data}
          isLoading={signals.isLoading}
        />
      </main>
    </div>
  );
}
