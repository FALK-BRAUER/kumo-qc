'use client';

import { useEffect, useRef } from 'react';

export function usePolling(callback: () => void, intervalMs = 30000) {
  const savedCallback = useRef(callback);
  useEffect(() => { savedCallback.current = callback; });
  useEffect(() => {
    const id = setInterval(() => savedCallback.current(), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}
