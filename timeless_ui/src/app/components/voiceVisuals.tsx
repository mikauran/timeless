"use client";
import React, { useEffect, useRef } from "react";

interface VoiceVisualsProps {
  onClose?: () => void;
  /** When false the canvas freezes — mic bars drop to zero and animation stops */
  active?: boolean;
}

export default function VoiceVisuals({ onClose, active = true }: VoiceVisualsProps) {
  const canvasRef   = useRef<HTMLCanvasElement | null>(null);
  const activeRef   = useRef(active);

  // Keep a ref in sync so the draw loop can read the latest value without
  // needing to tear down and rebuild the AudioContext on every change.
  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  useEffect(() => {
    let animationId: number;
    let audioContext: AudioContext | null = null;

    async function setupAudio() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

        audioContext = new (window.AudioContext ||
          (window as any).webkitAudioContext)();

        const source = audioContext.createMediaStreamSource(stream);
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;

        const bufferLength = analyser.frequencyBinCount;
        const dataArray    = new Uint8Array(bufferLength);

        source.connect(analyser);

        function draw() {
          const canvas = canvasRef.current;
          if (!canvas) return;

          const ctx = canvas.getContext("2d")!;
          const W   = canvas.width;
          const H   = canvas.height;

          ctx.clearRect(0, 0, W, H);
          ctx.fillStyle = "#04080f";
          ctx.fillRect(0, 0, W, H);

          if (activeRef.current) {
            // Live mic bars
            analyser.getByteFrequencyData(dataArray);
          } else {
            // Fill with zeros — flat line
            dataArray.fill(0);
          }

          const barWidth = 18;
          const gap      = 2;
          let x          = 0;

          for (let i = 0; i < bufferLength; i++) {
            const barHeight = activeRef.current
              ? dataArray[i] / 2
              : 2; // tiny flat stub when inactive

            const gradient = ctx.createLinearGradient(0, 0, 0, H);
            if (activeRef.current) {
              gradient.addColorStop(0, "#00eaff");
              gradient.addColorStop(1, "#c623ff");
            } else {
              gradient.addColorStop(0, "rgba(0,234,255,0.18)");
              gradient.addColorStop(1, "rgba(198,35,255,0.18)");
            }

            ctx.fillStyle = gradient;
            ctx.fillRect(x, H / 2 - barHeight / 2, barWidth, barHeight);
            x += barWidth + gap;
          }

          // Centre circle
          ctx.beginPath();
          ctx.lineWidth   = 3;
          ctx.strokeStyle = activeRef.current ? "#6ad4ff" : "rgba(106,212,255,0.25)";
          ctx.shadowBlur  = activeRef.current ? 20 : 0;
          ctx.shadowColor = "#6ad4ff";
          ctx.arc(W / 2, H / 2, 50, 0, Math.PI * 2);
          ctx.stroke();
          ctx.shadowBlur = 0;

          drawSimpleLineMic(ctx, W / 2, H / 2);

          animationId = requestAnimationFrame(draw);
        }

        draw();
      } catch (e) {
        console.error("Mic denied:", e);
      }
    }

    setupAudio();

    return () => {
      cancelAnimationFrame(animationId);
      if (audioContext) audioContext.close();
    };
  }, []); // runs once — active changes are handled via activeRef

  function drawSimpleLineMic(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
    ctx.save();
    ctx.lineWidth   = 2.2;
    ctx.strokeStyle = activeRef.current ? "#e2f5ff" : "rgba(226,245,255,0.22)";

    ctx.beginPath();
    ctx.roundRect(cx - 12, cy - 28, 24, 45, 12);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(cx - 8, cy - 18); ctx.lineTo(cx + 8, cy - 18);
    ctx.moveTo(cx - 8, cy - 8);  ctx.lineTo(cx + 8, cy - 8);
    ctx.moveTo(cx - 8, cy + 2);  ctx.lineTo(cx + 8, cy + 2);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(cx, cy + 17); ctx.lineTo(cx, cy + 35);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(cx - 18, cy + 35); ctx.lineTo(cx + 18, cy + 35);
    ctx.stroke();

    ctx.restore();
  }

  return (
    <div style={{ width: "100%", position: "relative", background: "transparent" }}>
      <canvas
        ref={canvasRef}
        width={1200}
        height={150}
        style={{ width: "100%", borderRadius: "0", background: "#04080f" }}
      />
    </div>
  );
}
