"use client";

import { useState } from "react";

export default function StartStopMic({ onMicStarted }: { onMicStarted?: () => void }) {
  const [phase, setPhase] = useState<"idle" | "speaking">("idle");

  const welcomeText =
    "Welcome to Timeless! Let's build something amazing together.";

  const handleStart = async () => {
    setPhase("speaking");
    try {
      // Clear previous session data before starting a new session
      await fetch("http://localhost:8082/api/v0/reset", { method: "POST" }).catch(() => {});

      const response = await fetch("http://localhost:8080/api/v0/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: welcomeText }),
      });

      const audioBlob = await response.blob();
      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);

      audio.onended = async () => {
        await fetch("http://localhost:8080/api/v0/start-mic", { method: "POST" });
        if (onMicStarted) onMicStarted();
      };

      await audio.play();
    } catch (err) {
      console.error("Error starting session:", err);
      setPhase("idle");
    }
  };

  return (
    <div className="holo-wrapper">
      {/* Wordmark */}
      <div className="holo-brand">
        <h1 className="holo-title">TIMELESS</h1>
        <p className="holo-subtitle">Holographic Meeting Intelligence</p>
      </div>

      {phase === "idle" && (
        <button className="holo-btn" onClick={handleStart}>
          <span className="holo-btn-ring holo-ring-1" />
          <span className="holo-btn-ring holo-ring-2" />
          <span className="holo-btn-core">
            <span className="holo-btn-label">Initialise</span>
          </span>
        </button>
      )}

      {phase === "speaking" && (
        <div className="holo-speaking">
          <div className="holo-rings">
            <div className="holo-ring-expand r1" />
            <div className="holo-ring-expand r2" />
            <div className="holo-ring-expand r3" />
            <div className="holo-core-dot" />
          </div>
          <p className="holo-speaking-text">Initialising session…</p>
        </div>
      )}

      <style jsx>{`
        .holo-wrapper {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0;
        }

        /* ── Brand ── */
        .holo-brand {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 6px;
          margin-bottom: 52px;
        }

        .holo-title {
          font-size: 3.2rem;
          font-weight: 700;
          letter-spacing: 0.22em;
          color: #0d1e35;
          margin: 0;
          text-shadow:
            0 0 30px rgba(0,149,200,0.18),
            0 0 60px rgba(0,149,200,0.08);
          font-family: var(--font-mono, 'JetBrains Mono', monospace);
        }

        .holo-subtitle {
          font-size: 0.85rem;
          color: rgba(13,30,53,0.40);
          margin: 0;
          letter-spacing: 0.18em;
          text-transform: uppercase;
          font-family: var(--font-mono, monospace);
        }

        /* ── Idle button ── */
        .holo-btn {
          position: relative;
          width: 160px;
          height: 160px;
          border-radius: 50%;
          background: none;
          border: none;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .holo-btn-ring {
          position: absolute;
          inset: 0;
          border-radius: 50%;
          border: 1px solid rgba(0,149,200,0.25);
          animation: ringIdle 3s ease-in-out infinite;
        }

        .holo-ring-1 { animation-delay: 0s; }
        .holo-ring-2 { animation-delay: 1.5s; border-color: rgba(91,127,212,0.20); }

        @keyframes ringIdle {
          0%, 100% { transform: scale(1);    opacity: 0.6; }
          50%       { transform: scale(1.08); opacity: 1;   }
        }

        .holo-btn-core {
          position: relative;
          width: 120px;
          height: 120px;
          border-radius: 50%;
          background: rgba(0,149,200,0.07);
          border: 1px solid rgba(0,149,200,0.40);
          display: flex;
          align-items: center;
          justify-content: center;
          transition: background 0.2s, border-color 0.2s, box-shadow 0.2s;
          box-shadow: 0 0 24px rgba(0,149,200,0.10), inset 0 0 16px rgba(0,149,200,0.04);
        }

        .holo-btn:hover .holo-btn-core {
          background: rgba(0,149,200,0.12);
          border-color: rgba(0,149,200,0.65);
          box-shadow: 0 0 36px rgba(0,149,200,0.20), inset 0 0 20px rgba(0,149,200,0.07);
        }

        .holo-btn-label {
          font-size: 0.9rem;
          font-weight: 600;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: #0095c8;
          font-family: var(--font-mono, monospace);
          text-shadow: 0 0 10px rgba(0,149,200,0.30);
        }

        /* ── Speaking ── */
        .holo-speaking {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 28px;
        }

        .holo-rings {
          position: relative;
          width: 160px;
          height: 160px;
        }

        .holo-ring-expand {
          position: absolute;
          inset: 0;
          border-radius: 50%;
          border: 1px solid rgba(0,149,200,0.40);
          animation: ringExpand 2.2s ease-out infinite;
        }

        .r1 { animation-delay: 0s;    border-color: rgba(0,149,200,0.40); }
        .r2 { animation-delay: 0.70s; border-color: rgba(91,127,212,0.30); }
        .r3 { animation-delay: 1.40s; border-color: rgba(0,149,200,0.20); }

        @keyframes ringExpand {
          0%   { transform: scale(0.50); opacity: 0.9; }
          100% { transform: scale(2.00); opacity: 0;   }
        }

        .holo-core-dot {
          position: absolute;
          inset: 36px;
          border-radius: 50%;
          background: radial-gradient(circle, rgba(0,149,200,0.45) 0%, rgba(0,149,200,0.08) 100%);
          border: 1px solid rgba(0,149,200,0.45);
          box-shadow: 0 0 24px rgba(0,149,200,0.22);
        }

        .holo-speaking-text {
          font-size: 0.78rem;
          color: rgba(13,30,53,0.42);
          margin: 0;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          font-family: var(--font-mono, monospace);
          animation: textPulse 1.8s ease-in-out infinite;
        }

        @keyframes textPulse {
          0%, 100% { opacity: 1;    }
          50%       { opacity: 0.30; }
        }
      `}</style>
    </div>
  );
}
