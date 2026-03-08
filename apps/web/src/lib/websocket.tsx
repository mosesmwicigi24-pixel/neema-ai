'use client';
import {
  createContext, useContext, useEffect, useRef, ReactNode
} from 'react';
import { io, Socket } from 'socket.io-client';
import { useSession } from 'next-auth/react';

const WsContext = createContext<Socket | null>(null);

export function WsProvider({ children }: { children: ReactNode }) {
  const { data: session } = useSession();
  const socketRef = useRef<Socket | null>(null);

  useEffect(() => {
    if (!session?.user?.id) return;

    const socket = io(process.env.NEXT_PUBLIC_WS_URL!, {
      path: '/ws',
      query:  { agentId: session.user.id },
      auth:   { token: session.accessToken },
      transports: ['websocket'],
    });

    socket.on('connect', () => console.log('[WS] connected'));
    socket.on('disconnect', () => console.log('[WS] disconnected'));
    socketRef.current = socket;

    return () => { socket.disconnect(); };
  }, [session?.user?.id]);

  return (
    <WsContext.Provider value={socketRef.current}>
      {children}
    </WsContext.Provider>
  );
}

export const useWs = () => useContext(WsContext);

// Hook: subscribe to live events for a specific conversation
export function useConversationEvents(
  conversationId: string,
  onEvent: (event: any) => void
) {
  const socket = useWs();

  useEffect(() => {
    if (!socket || !conversationId) return;
    socket.emit('join_conversation', { conversationId });
    socket.on('event', onEvent);
    return () => { socket.off('event', onEvent); };
  }, [socket, conversationId, onEvent]);
}