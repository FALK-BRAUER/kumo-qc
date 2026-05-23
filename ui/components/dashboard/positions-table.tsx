'use client';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import type { QCHolding } from '@/lib/qc-client';

interface PositionsTableProps {
  positions: QCHolding[] | null | undefined;
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

function fmtPrice(value: number): string {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(value);
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 3 }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: 6 }).map((_, j) => (
            <TableCell key={j}>
              <Skeleton className="h-4 w-20" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

export function PositionsTable({ positions, isLoading }: PositionsTableProps) {
  const rows = positions ?? [];

  return (
    <div className="rounded-xl ring-1 ring-foreground/10 overflow-hidden">
      <div className="px-4 py-3 border-b border-border/50">
        <h2 className="text-sm font-semibold text-foreground">Open Positions</h2>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Symbol</TableHead>
            <TableHead className="text-right">Quantity</TableHead>
            <TableHead className="text-right">Avg Price</TableHead>
            <TableHead className="text-right">Market Price</TableHead>
            <TableHead className="text-right">Unrealized P&L</TableHead>
            <TableHead className="text-right">Kijun Stop</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <SkeletonRows />
          ) : rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                No open positions
              </TableCell>
            </TableRow>
          ) : (
            rows.map((h) => (
              <TableRow key={h.symbol}>
                <TableCell className="font-mono font-semibold text-foreground">
                  {h.symbol}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {h.quantity.toLocaleString()}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {fmtPrice(h.averagePrice)}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {fmtPrice(h.marketPrice)}
                </TableCell>
                <TableCell
                  className={`text-right font-mono font-medium ${
                    h.unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                  }`}
                >
                  {fmt(h.unrealizedPnl)}
                </TableCell>
                <TableCell className="text-right text-muted-foreground text-xs">
                  see algo
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
