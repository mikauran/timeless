"use client";

interface Props {
  requirements?: string[] | string;
}

export default function RequirementsComponent({ requirements }: Props) {
  if (!requirements) {
    return (
      <p style={{
        color: "rgba(226,240,251,0.22)",
        fontSize: "12.5px",
        fontStyle: "italic",
      }}>
        No requirements captured yet.
      </p>
    );
  }

  const items: string[] =
    typeof requirements === "string"
      ? requirements.split("\n").filter((l) => l.trim() !== "")
      : requirements.filter((l) => l.trim() !== "");

  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "7px" }}>
      {items.map((req, index) => (
        <li
          key={index}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: "10px",
            padding: "9px 12px",
            background: "rgba(0,229,255,0.03)",
            border: "1px solid rgba(0,229,255,0.07)",
            borderRadius: "6px",
            fontSize: "12.5px",
            lineHeight: "1.55",
            color: "rgba(226,240,251,0.75)",
            transition: "border-color 0.2s, background 0.2s",
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLLIElement).style.borderColor = "rgba(0,229,255,0.18)";
            (e.currentTarget as HTMLLIElement).style.background  = "rgba(0,229,255,0.06)";
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLLIElement).style.borderColor = "rgba(0,229,255,0.07)";
            (e.currentTarget as HTMLLIElement).style.background  = "rgba(0,229,255,0.03)";
          }}
        >
          <span style={{
            display: "inline-block",
            width: "5px",
            height: "5px",
            borderRadius: "50%",
            background: "#00e5ff",
            flexShrink: 0,
            marginTop: "6px",
            boxShadow: "0 0 6px rgba(0,229,255,0.55)",
          }} />
          {req}
        </li>
      ))}
    </ul>
  );
}
