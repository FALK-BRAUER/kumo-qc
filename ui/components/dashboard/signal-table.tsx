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
import type { Signal } from '@/lib/qc-client';

interface SignalTableProps {
  signals: Signal[] | null | undefined;
  isLoading: boolean;
}

function ratingColor(rating: string): string {
  switch (rating) {
    case '+++':
      return 'text-emerald-400 font-semibold';
    case '++':
      return 'text-green-500 font-medium';
    case '+':
      return 'text-yellow-400';
    case '=':
      return 'text-zinc-400';
    case '--':
      return 'text-red-400';
    default:
      return 'text-muted-foreground';
  }
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: 4 }).map((_, j) => (
            <TableCell key={j}>
              <Skeleton className="h-4 w-16" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

export function SignalTable({ signals, isLoading }: SignalTableProps) {
  const rows = signals ?? [];

  return (
    <div className="rounded-xl ring-1 ring-foreground/10 overflow-hidden">
      <div className="px-4 py-3 border-b border-border/50">
        <h2 className="text-sm font-semibold text-foreground">BCT Signals</h2>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Date</TableHead>
            <TableHead>Symbol</TableHead>
            <TableHead className="text-right">Score</TableHead>
            <TableHead className="text-right">Rating</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <SkeletonRows />
          ) : rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                No signals found
              </TableCell>
            </TableRow>
          ) : (
            rows.map((s, idx) => (
              <TableRow key={`${s.date}-${s.symbol}-${idx}`}>
                <TableCell className="font-mono text-muted-foreground">
                  {s.date}
                </TableCell>
                <TableCell className="font-mono font-semibold text-foreground">
                  {s.symbol}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {s.score}/8
                </TableCell>
                <TableCell className={`text-right font-mono ${ratingColor(s.rating)}`}>
                  {s.rating}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
