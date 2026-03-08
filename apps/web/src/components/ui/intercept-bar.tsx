'use client';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { conversationsApi } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { UserCheck, Bot, ArrowLeftRight } from 'lucide-react';

interface Props {
  conversationId: string;
  mode: 'ai' | 'human' | 'paused';
  aiDraft?: string | null;
  onDraftApproved?: () => void;
}

export function InterceptBar({ conversationId, mode, aiDraft, onDraftApproved }: Props) {
  const qc = useQueryClient();

  const intercept = useMutation({
    mutationFn: () => conversationsApi.intercept(conversationId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversation', conversationId] }),
  });

  const release = useMutation({
    mutationFn: () => conversationsApi.release(conversationId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversation', conversationId] }),
  });

  const approve = useMutation({
    mutationFn: () => conversationsApi.approveDraft(conversationId, aiDraft ?? undefined),
    onSuccess: () => { onDraftApproved?.(); qc.invalidateQueries({ queryKey: ['thread', conversationId] }); },
  });

  return (
    <div className="flex items-center gap-3 p-3 border-b border-zinc-800 bg-zinc-900/50">
      <Badge variant="outline" className={
        mode === 'ai' ? 'text-emerald-400 border-emerald-500/30' :
        mode === 'human' ? 'text-amber-400 border-amber-500/30' :
        'text-zinc-400 border-zinc-600'
      }>
        {mode === 'ai' ? <Bot className="w-3 h-3 mr-1" /> : <UserCheck className="w-3 h-3 mr-1" />}
        {mode.toUpperCase()}
      </Badge>

      {mode === 'ai' && (
        <Button size="sm" variant="outline"
          onClick={() => intercept.mutate()}
          disabled={intercept.isPending}>
          <UserCheck className="w-3 h-3 mr-1" /> Take Over
        </Button>
      )}

      {mode === 'human' && (
        <>
          {aiDraft && (
            <Button size="sm" variant="outline" className="text-emerald-400 border-emerald-500/30"
              onClick={() => approve.mutate()}
              disabled={approve.isPending}>
              Approve AI Draft
            </Button>
          )}
          <Button size="sm" variant="ghost"
            onClick={() => release.mutate()}
            disabled={release.isPending}>
            <Bot className="w-3 h-3 mr-1" /> Release to AI
          </Button>
        </>
      )}
    </div>
  );
}