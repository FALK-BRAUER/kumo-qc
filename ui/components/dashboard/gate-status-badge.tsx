'use client';

import { Lock, Square, CircleDashed } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

interface GateStatusBadgeProps {
  status: string | null;
}

export function GateStatusBadge({ status }: GateStatusBadgeProps) {
  if (status === 'Running') {
    return (
      <Badge className="gap-1.5 bg-emerald-500/20 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20 h-6 px-3 text-xs font-semibold">
        <Lock className="size-3" />
        PAPER LIVE
      </Badge>
    );
  }

  if (status === 'Stopped') {
    return (
      <Badge className="gap-1.5 bg-red-500/20 text-red-400 border-red-500/30 hover:bg-red-500/20 h-6 px-3 text-xs font-semibold">
        <Square className="size-3 fill-current" />
        STOPPED
      </Badge>
    );
  }

  // 'not_deployed', null, or any other value
  return (
    <Badge className="gap-1.5 bg-zinc-700/50 text-zinc-400 border-zinc-600/50 hover:bg-zinc-700/50 h-6 px-3 text-xs font-semibold">
      <CircleDashed className="size-3" />
      NOT DEPLOYED
    </Badge>
  );
}
