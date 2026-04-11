"use client";

/**
 * Subscribe to the manager service SSE stream.
 * Auto-reconnects with exponential backoff if the connection drops.
 * Returns an unsubscribe function.
 */
export function subscribeToSSE(setData: (data: any) => void) {
  const SSE_URL = "http://localhost:8082/api/v0/sse";

  let eventSource: EventSource | null = null;
  let retryTimeout: ReturnType<typeof setTimeout> | null = null;
  let retryDelay = 1000;   // start at 1 s, cap at 8 s
  let destroyed = false;

  function connect() {
    if (destroyed) return;

    eventSource = new EventSource(SSE_URL);

    eventSource.onopen = () => {
      retryDelay = 1000; // reset backoff on successful connection
    };

    eventSource.onmessage = (event) => {
      try {
        const newData = JSON.parse(event.data);
        setData(newData);
      } catch (e) {
        console.error("SSE parse error:", e);
      }
    };

    eventSource.onerror = () => {
      // Close the broken connection
      eventSource?.close();
      eventSource = null;

      if (!destroyed) {
        console.warn(`SSE disconnected — retrying in ${retryDelay}ms`);
        retryTimeout = setTimeout(() => {
          retryDelay = Math.min(retryDelay * 2, 8000);
          connect();
        }, retryDelay);
      }
    };
  }

  connect();

  // Return cleanup function
  return () => {
    destroyed = true;
    if (retryTimeout) clearTimeout(retryTimeout);
    eventSource?.close();
    eventSource = null;
  };
}
