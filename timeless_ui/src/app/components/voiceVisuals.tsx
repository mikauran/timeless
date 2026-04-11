"use client";
import React, { useEffect, useRef } from "react";

interface VoiceVisualsProps {
  onClose?: () => void; // Optional now
}

export default function VoiceVisuals({ onClose }: VoiceVisualsProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

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
        const dataArray = new Uint8Array(bufferLength);

        source.connect(analyser);

        function draw() {
          const canvas = canvasRef.current;
          if (!canvas) return;

          const ctx = canvas.getContext("2d")!;
          analyser.getByteFrequencyData(dataArray);

          const W = canvas.width;
          const H = canvas.height;

          ctx.clearRect(0, 0, W, H);

          ctx.fillStyle = "#04080f";
          ctx.fillRect(0, 0, W, H);

          const barWidth = 18;
          const gap = 2;
          let x = 0;

          for (let i = 0; i < bufferLength; i++) {
            const barHeight = dataArray[i] / 2;

            const gradient = ctx.createLinearGradient(0, 0, 0, H);
            gradient.addColorStop(0, "#00eaff");
            gradient.addColorStop(1, "#c623ff");

            ctx.fillStyle = gradient;

            ctx.fillRect(
              x,
              H / 2 - barHeight / 2,
              barWidth,
              barHeight
            );

            x += barWidth + gap;
          }

          const circleRadius = 50;

          ctx.beginPath();
          ctx.lineWidth = 3;
          ctx.strokeStyle = "#6ad4ff";
          ctx.shadowBlur = 20;
          ctx.shadowColor = "#6ad4ff";
          ctx.arc(W / 2, H / 2, circleRadius, 0, Math.PI * 2);
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
  }, []);

  function drawSimpleLineMic(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
    ctx.save();
    ctx.lineWidth = 2.2;
    ctx.strokeStyle = "#e2f5ff";

    ctx.beginPath();
    ctx.roundRect(cx - 12, cy - 28, 24, 45, 12);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(cx - 8, cy - 18);
    ctx.lineTo(cx + 8, cy - 18);
    ctx.moveTo(cx - 8, cy - 8);
    ctx.lineTo(cx + 8, cy - 8);
    ctx.moveTo(cx - 8, cy + 2);
    ctx.lineTo(cx + 8, cy + 2);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(cx, cy + 17);
    ctx.lineTo(cx, cy + 35);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(cx - 18, cy + 35);
    ctx.lineTo(cx + 18, cy + 35);
    ctx.stroke();

    ctx.restore();
  }

  return (
    <div
      style={{
        width: "100%",
        position: "relative",
        background: "transparent",
      }}
    >
      

      {/* <h3
        style={{
          fontSize: "20px",
          fontWeight: "bold",
          color: "#003366",
          marginBottom: "12px",
        }}
      >
        🎙️ Voice Visualizer
      </h3> */}

      <canvas
        ref={canvasRef}
        width={1200}
        height={150}
        style={{
          width: "100%",
          borderRadius: "0",
          background: "#04080f",
        }}
      />
    </div>
  );
}
