'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { QCPortfolio } from '@/lib/qc-client';

interface AccountSummaryProps {
  portfolio: QCPortfolio | null;
  isLoading: boolean;
}

function fmt(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

interface MetricCardProps {
  label: string;
  value: string | null;
  isLoading: boolean;
  colorClass?: string;
}

function MetricCard({ label, value, isLoading, colorClass = 'text-foreground' }: MetricCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wider">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-7 w-32" />
        ) : (
          <p className={`text-2xl font-mono font-semibold ${colorClass}`}>
            {value ?? '—'}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function AccountSummary({ portfolio, isLoading }: AccountSummaryProps) {
  const pnl = portfolio?.totalUnrealizedProfit ?? 0;
  const pnlColor =
    isLoading || portfolio === null
      ? 'text-foreground'
      : pnl >= 0
      ? 'text-emerald-400'
      : 'text-red-400';

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <MetricCard
        label="Total Portfolio Value"
        value={portfolio ? fmt(portfolio.totalPortfolioValue) : null}
        isLoading={isLoading}
      />
      <MetricCard
        label="Cash"
        value={portfolio ? fmt(portfolio.cash) : null}
        isLoading={isLoading}
      />
      <MetricCard
        label="Unrealized P&L"
        value={portfolio ? fmt(pnl) : null}
        isLoading={isLoading}
        colorClass={pnlColor}
      />
    </div>
  );
}
