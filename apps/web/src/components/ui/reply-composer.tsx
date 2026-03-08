'use client';
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { conversationsApi } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Send } from 'lucide-react';

export function ReplyComposer({ conversationId }: { conversationId: string }) {
  const [text, setText] = useState('');
  const qc = useQueryClient();

  const send = useMutation({
    mutationFn: () => conversationsApi.reply(conversationId, text),
    onSuccess: () => {
      setText('');
      qc.invalidateQueries({ queryKey: ['thread', conversationId] });
    },
  });

  return (
    <div className="p-3 border-t border-zinc-800 bg-zinc-900/50">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Type a reply…"
        className="mb-2 min-h-[80px] bg-zinc-950 border-zinc-700 text-sm resize-none"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send.mutate();
        }}
      />
      <div className="flex justify-between items-center">
        <span className="text-xs text-zinc-600">⌘↵ to send</span>
        <Button size="sm" onClick={() => send.mutate()}
          disabled={!text.trim() || send.isPending}>
          <Send className="w-3 h-3 mr-1" />
          {send.isPending ? 'Sending…' : 'Send'}
        </Button>
      </div>
    </div>
  );
}