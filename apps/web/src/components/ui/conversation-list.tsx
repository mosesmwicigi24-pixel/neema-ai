'use client';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { conversationsApi } from '@/lib/api';
import { useWs } from '@/lib/websocket';
import { useEffect } from 'react';
import { Badge } from '@/components/ui/badge';
import { formatDistanceToNow } from 'date-fns';
import Link from 'next/link';

const modeBadge: Record<string, string> = {
  ai:     'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  human:  'bg-amber-500/10 text-amber-400 border-amber-500/20',
  paused: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20',
};

export function ConversationList() {
  const qc = useQueryClient();
  const socket = useWs();

  const { data: conversations = [] } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => conversationsApi.list().then(r => r.data),
    refetchInterval: 30_000,
  });

  // Invalidate list on any new message or intercept change
  useEffect(() => {
    if (!socket) return;
    socket.on('event', (e) => {
      if (['new_message', 'intercept_changed'].includes(e.type)) {
        qc.invalidateQueries({ queryKey: ['conversations'] });
      }
    });
    return () => { socket.off('event'); };
  }, [socket, qc]);

  return (
    <div className="divide-y divide-zinc-800">
      {conversations.map((conv: any) => (
        <Link
          key={conv.id}
          href={`/conversations/${conv.id}`}
          className="flex items-start gap-3 p-4 hover:bg-zinc-900/50 transition-colors"
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="text-sm font-medium text-zinc-100 truncate">
                {conv.wa_id}
              </span>
              <span className={`text-[10px] px-2 py-0.5 rounded-full border font-mono
                               ${modeBadge[conv.intercept_mode] ?? modeBadge.paused}`}>
                {conv.intercept_mode.toUpperCase()}
              </span>
            </div>
            <p className="text-xs text-zinc-500 truncate">
              {conv.last_message_preview ?? 'No messages yet'}
            </p>
          </div>
          {conv.last_message_at && (
            <span className="text-[10px] text-zinc-600 whitespace-nowrap">
              {formatDistanceToNow(new Date(conv.last_message_at), { addSuffix: true })}
            </span>
          )}
        </Link>
      ))}
    </div>
  );
}