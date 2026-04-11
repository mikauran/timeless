import React, { useEffect, useRef } from "react";

interface PopupProps {
  onClose: () => void;
}

export default function Popup({ onClose }: PopupProps) {
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

          // Background
          ctx.fillStyle = "#1b1550";
          ctx.fillRect(0, 0, W, H);

          // ------- Animated Neon Bars ------
          const barWidth = 3;
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

          // ------- Neon Circle -------
          const circleRadius = 70;

          ctx.beginPath();
          ctx.lineWidth = 3;
          ctx.strokeStyle = "#6ad4ff";
          ctx.shadowBlur = 20;
          ctx.shadowColor = "#6ad4ff";
          ctx.arc(W / 2, H / 2, circleRadius, 0, Math.PI * 2);
          ctx.stroke();

          ctx.shadowBlur = 0;

          // ------- Simple Line Microphone Icon -------
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

  // ===== Simple Thin-Line Microphone Icon (Option 1) =====
  function drawSimpleLineMic(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
    ctx.save();
    ctx.lineWidth = 2.2;
    ctx.strokeStyle = "#e2f5ff";

    // Mic capsule
    ctx.beginPath();
    ctx.roundRect(cx - 12, cy - 28, 24, 45, 12);
    ctx.stroke();

    // Inner grill lines
    ctx.beginPath();
    ctx.moveTo(cx - 8, cy - 18);
    ctx.lineTo(cx + 8, cy - 18);
    ctx.moveTo(cx - 8, cy - 8);
    ctx.lineTo(cx + 8, cy - 8);
    ctx.moveTo(cx - 8, cy + 2);
    ctx.lineTo(cx + 8, cy + 2);
    ctx.stroke();

    // Stem
    ctx.beginPath();
    ctx.moveTo(cx, cy + 17);
    ctx.lineTo(cx, cy + 35);
    ctx.stroke();

    // Base
    ctx.beginPath();
    ctx.moveTo(cx - 18, cy + 35);
    ctx.lineTo(cx + 18, cy + 35);
    ctx.stroke();

    ctx.restore();
  }

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        width: "100vw",
        height: "100vh",
        backgroundColor: "rgba(0,0,0,0.5)",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        zIndex: 1000,
      }}
    >
      <div
        style={{
          background: "white",
          padding: "20px",
          borderRadius: "12px",
          maxWidth: "600px",
          width: "90%",
          position: "relative",
          boxShadow: "0 10px 25px rgba(0,0,0,0.2)",
        }}
      >
        <button
          onClick={onClose}
          style={{
            position: "absolute",
            top: "10px",
            right: "10px",
            fontSize: "16px",
            background: "transparent",
            border: "none",
            cursor: "pointer",
          }}
        >
          ✖
        </button>

        <h2 style={{ fontSize: "22px", fontWeight: 600, marginBottom: 12 }}>
          Voice Visualizer
        </h2>

        <canvas
          ref={canvasRef}
          width={520}
          height={240}
          style={{
            width: "100%",
            borderRadius: "12px",
            background: "#1b1550",
          }}
        />
      </div>
    </div>
  );
}
