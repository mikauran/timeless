"use client";

interface Props {
  state?: string;
}

const LABELS = [
  "Conceptualization",
  "Req. Analysis",
  "Design",
  "Implementation",
  "Testing",
  "Deployment",
];

const FULL_STATES = [
  "Conceptualization",
  "Requirement Analysis",
  "Design (Tech & UI/UX)",
  "Implementation",
  "Testing",
  "Deployment and Maintenance",
];

export default function StateComponent({ state }: Props) {
  if (!state) return null;
  const currentIndex = FULL_STATES.indexOf(state);

  return (
    <div style={{ display: "flex", alignItems: "center", width: "100%", gap: "0" }}>
      {LABELS.map((label, index) => {
        const isDone    = index < currentIndex;
        const isActive  = index === currentIndex;

        return (
          <div key={index} style={{ display: "flex", alignItems: "center", flex: 1, minWidth: 0 }}>
            {/* Pill */}
            <div
              title={FULL_STATES[index]}
              style={{
                flex: 1,
                minWidth: 0,
                padding: "5px 8px",
                borderRadius: "20px",
                fontSize: "10px",
                fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
                fontWeight: 500,
                textAlign: "center",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
                transition: "all 0.35s ease",
                cursor: "default",
                border: isActive
                  ? "1px solid rgba(0,229,255,0.55)"
                  : isDone
                  ? "1px solid rgba(0,229,255,0.18)"
                  : "1px solid rgba(226,240,251,0.07)",
                background: isActive
                  ? "rgba(0,229,255,0.10)"
                  : isDone
                  ? "rgba(0,229,255,0.03)"
                  : "transparent",
                color: isActive
                  ? "#00e5ff"
                  : isDone
                  ? "rgba(0,229,255,0.50)"
                  : "rgba(226,240,251,0.20)",
                boxShadow: isActive
                  ? "0 0 14px rgba(0,229,255,0.22), inset 0 0 8px rgba(0,229,255,0.05)"
                  : "none",
                animation: isActive ? "pillPulse 2.8s ease-in-out infinite" : "none",
              }}
            >
              {label}
            </div>

            {/* Connector line */}
            {index < LABELS.length - 1 && (
              <div
                style={{
                  width: "14px",
                  flexShrink: 0,
                  height: "1px",
                  background: isDone
                    ? "linear-gradient(90deg, rgba(0,229,255,0.35), rgba(0,229,255,0.12))"
                    : "rgba(226,240,251,0.07)",
                }}
              />
            )}
          </div>
        );
      })}

      <style jsx>{`
        @keyframes pillPulse {
          0%,  100% { box-shadow: 0 0 14px rgba(0,229,255,0.22), inset 0 0 8px rgba(0,229,255,0.05); }
          50%        { box-shadow: 0 0 26px rgba(0,229,255,0.42), inset 0 0 14px rgba(0,229,255,0.10); }
        }
      `}</style>
    </div>
  );
}
