"use client";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";

interface Props {
  meetingMinutes: string;
}

export default function MeetingMinutesComponent({ meetingMinutes }: Props) {
  return (
    <div style={{
      fontSize: "12.5px",
      lineHeight: "1.75",
      color: "rgba(226,240,251,0.65)",
    }}>
      <style>{`
        .mm-body h1, .mm-body h2, .mm-body h3 {
          color: rgba(226,240,251,0.85);
          font-weight: 600;
          margin: 10px 0 6px;
          font-size: 13px;
        }
        .mm-body p  { margin: 0 0 8px 0; }
        .mm-body ul, .mm-body ol { padding-left: 18px; margin: 0 0 8px 0; }
        .mm-body li { margin-bottom: 4px; }
        .mm-body strong { color: rgba(226,240,251,0.88); }
        .mm-body em { color: rgba(226,240,251,0.50); }
        .mm-body code {
          font-family: var(--font-mono, monospace);
          font-size: 11px;
          background: rgba(0,229,255,0.07);
          border: 1px solid rgba(0,229,255,0.10);
          border-radius: 3px;
          padding: 1px 5px;
          color: #00e5ff;
        }
      `}</style>
      <div className="mm-body">
        <ReactMarkdown rehypePlugins={[rehypeRaw]}>
          {meetingMinutes || "No meeting notes available yet."}
        </ReactMarkdown>
      </div>
    </div>
  );
}
