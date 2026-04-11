"use client";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import MeetingMinutesComponent from "./meetingMinutes";
import RequirementsComponent from "./requirements";
import StateComponent from "./state";
import IframeSectionComponent from "./iframeSection";
import StartStopMic from "./StartStopMic";
import VoiceVisuals from "./voiceVisuals";
import { subscribeToSSE } from "./listeners/sse";
import FileTree, { FileTreeNode } from "./FileTree";
import MonacoEditor from "@monaco-editor/react";
import EpicsComponent, { Epic } from "./EpicsComponent";
import MindMapComponent, { MindMapNode } from "./MindMapComponent";
import styles from "@/app/styles/dataProvider.module.css";

interface ProjectData {
  notebook_summary: string;
  requirements: string | string[];
  current_state: string;
  deployment_url: string;
  code_generation_running: boolean;
  project_id?: string;
  directory_tree: Record<string, any>;
  files: Record<string, string>;
  transcriptions: string[];
  current_feedback_required?: boolean;
  current_feedback?: string;
  run_status_message?: string;
  evaluation_in_progress?: boolean;
  generation_progress?: number;
  active_popup?: string;
  popup_request_id?: number;
  epics?: Epic[];
  mind_map?: MindMapNode;
  advisor_suggestions?: string[];
}

type PanelId = "requirements" | "epics" | "map" | "notes" | "advisor" | "output" | "code";

const ALL_PANELS: { id: PanelId; icon: string; label: string }[] = [
  { id: "requirements", icon: "fa-list-ul",     label: "Requirements" },
  { id: "epics",        icon: "fa-th-large",    label: "Epics"        },
  { id: "map",          icon: "fa-sitemap",     label: "Mind Map"     },
  { id: "notes",        icon: "fa-book",        label: "Notes"        },
  { id: "advisor",      icon: "fa-lightbulb-o", label: "Advisor"      },
  { id: "output",       icon: "fa-desktop",     label: "Output"       },
  { id: "code",         icon: "fa-code",        label: "Code"         },
];

const SIDEBAR_LEFT  = ALL_PANELS.slice(0, 5);
const SIDEBAR_RIGHT = ALL_PANELS.slice(5);

const CODEGEN_TASKS = [
  { id: 1, label: "Analysing requirements",     min: 0,  max: 10  },
  { id: 2, label: "Planning project structure", min: 10, max: 25  },
  { id: 3, label: "Generating frontend code",   min: 25, max: 50  },
  { id: 4, label: "Building backend services",  min: 50, max: 65  },
  { id: 5, label: "Installing dependencies",    min: 65, max: 88  },
  { id: 6, label: "Starting application",       min: 88, max: 100 },
];

// N = number of panels
const N = ALL_PANELS.length; // 7

/** Circular offset from active panel: result in range [-3, 3] for N=7 */
function circularOffset(panelIdx: number, activeIdx: number): number {
  const raw = ((panelIdx - activeIdx) % N + N) % N;
  return raw > Math.floor(N / 2) ? raw - N : raw;
}

/** CSS class name for a slot at a given circular offset */
function slotClass(offset: number, s: typeof styles): string {
  switch (offset) {
    case -3: return s.slotHiddenL;
    case -2: return s.slotFarLeft;
    case -1: return s.slotNearLeft;
    case  0: return s.slotCenter;
    case  1: return s.slotNearRight;
    case  2: return s.slotFarRight;
    case  3: return s.slotHiddenR;
    default: return offset < 0 ? s.slotHiddenL : s.slotHiddenR;
  }
}

export default function ProjectDataWrapper() {
  const [data, setData]                 = useState<ProjectData | null>(null);
  const [micStarted, setMicStarted]     = useState<boolean | null>(null);
  const [projectData, setProjectData]   = useState<ProjectData | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [code, setCode]                 = useState<string>("");
  const [activePanel, setActivePanel]   = useState<PanelId>("requirements");
  const [fetchedProjectId, setFetchedProjectId] = useState<string | null>(null);
  const [dismissedSuggestions, setDismissedSuggestions] = useState<Set<number>>(new Set());
  const [evalProgress, setEvalProgress] = useState(0);
  const [sseTimeout, setSseTimeout]     = useState(false);
  const evalTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── helpers ──────────────────────────────────────────────────────
  const fetchProjectFiles = async (pid: string) => {
    try {
      const res = await fetch(`http://localhost:8082/api/v0/get_project/${pid}`);
      const fetched = await res.json();
      if (!fetched?.files) return;
      setProjectData(fetched);
      const first = Object.keys(fetched.files)[0];
      if (first) { setSelectedFile(first); setCode(fetched.files[first]); }
    } catch (e) { console.error("Failed to fetch project files:", e); }
  };

  const handleFileSelect = (filePath: string) => {
    if (!projectData) return;
    setSelectedFile(filePath);
    setCode(projectData.files?.[filePath] || "");
  };

  const buildFileTree = (files: Record<string, string>): FileTreeNode[] => {
    if (!files) return [];
    const root: Record<string, any> = {};
    Object.keys(files).forEach(filePath => {
      const parts = filePath.split("/");
      let cur = root;
      parts.forEach((part, i) => {
        if (!cur[part]) cur[part] = { name: part, path: parts.slice(0, i + 1).join("/"), children: {}, isFile: i === parts.length - 1 };
        cur = cur[part].children;
      });
    });
    const convert = (obj: any): FileTreeNode[] =>
      Object.values(obj).map((n: any) => ({
        name: n.name, path: n.path, isFile: n.isFile,
        children: n.isFile ? undefined : convert(n.children),
      }));
    return convert(root);
  };

  // ── Effects ──────────────────────────────────────────────────────
  useEffect(() => {
    fetch("http://localhost:8080/api/v0/mic-status")
      .then(r => r.json())
      .then(d => setMicStarted(d.mic_active))
      .catch(() => setMicStarted(false));
  }, []);

  useEffect(() => {
    if (!micStarted) return;
    const unsub = subscribeToSSE(setData);
    // If no SSE data arrives within 8 s, show the connection-error UI
    const timer = setTimeout(() => setSseTimeout(true), 8000);
    return () => { unsub(); clearTimeout(timer); };
  }, [micStarted]);

  // Clear the timeout flag as soon as real data arrives
  useEffect(() => {
    if (data) setSseTimeout(false);
  }, [data]);

  useEffect(() => {
    if (data?.evaluation_in_progress) {
      setEvalProgress(0);
      evalTimerRef.current = setInterval(() => {
        setEvalProgress(prev => {
          if (prev >= 92) { clearInterval(evalTimerRef.current!); return 92; }
          return Math.min(92, prev + Math.random() * 4 + 1);
        });
      }, 450);
    } else {
      if (evalTimerRef.current) clearInterval(evalTimerRef.current);
      if (data) setEvalProgress(100);
    }
    return () => { if (evalTimerRef.current) clearInterval(evalTimerRef.current); };
  }, [data?.evaluation_in_progress]);

  useEffect(() => {
    if (data?.current_feedback_required && !data.evaluation_in_progress) setActivePanel("advisor");
  }, [data?.current_feedback_required, data?.evaluation_in_progress]);

  useEffect(() => {
    if (data?.deployment_url) setActivePanel("output");
  }, [data?.deployment_url]);

  useEffect(() => {
    if (data?.project_id && !data.code_generation_running && fetchedProjectId !== data.project_id) {
      setFetchedProjectId(data.project_id);
      fetchProjectFiles(data.project_id);
    }
  }, [data?.code_generation_running, data?.project_id]);

  useEffect(() => {
    if (!data?.active_popup) return;
    const map: Partial<Record<string, PanelId>> = {
      requirements: "requirements", notes: "notes", feedback: "advisor",
    };
    const target = map[data.active_popup];
    if (target) setActivePanel(target);
  }, [data?.popup_request_id, data?.active_popup]);

  useEffect(() => {
    setDismissedSuggestions(new Set());
  }, [data?.advisor_suggestions]);

  // ── Pre-mic / loading ────────────────────────────────────────────
  if (micStarted === null) return <p className={styles.loadingText}>Loading…</p>;
  if (!micStarted) {
    return (
      <div className={styles.centerMicContainer}>
        <StartStopMic onMicStarted={() => setMicStarted(true)} />
      </div>
    );
  }
  if (!data) {
    if (sseTimeout) {
      return (
        <div className={styles.sseErrorScreen}>
          <div className={styles.sseErrorIcon}>⚠</div>
          <h2 className={styles.sseErrorTitle}>Cannot reach Timeless services</h2>
          <p className={styles.sseErrorBody}>
            The manager service on port&nbsp;<code>8082</code> is not responding.
          </p>
          <div className={styles.sseRunCmd}>
            <span className={styles.sseRunLabel}>Run in project root:</span>
            <code className={styles.sseRunCode}>python bootstrap.py --web --opencode</code>
          </div>
          <button
            className={styles.sseRetryBtn}
            onClick={() => { setSseTimeout(false); window.location.reload(); }}
          >
            Retry
          </button>
        </div>
      );
    }
    return (
      <div className={styles.sseLoadingScreen}>
        <div className={styles.sseSpinner} />
        <p className={styles.sseLoadingText}>Connecting to Timeless…</p>
      </div>
    );
  }

  // ── Derived ──────────────────────────────────────────────────────
  const formattedRequirements = Array.isArray(data.requirements)
    ? data.requirements.join("\n")
    : String(data.requirements || "");

  const fileTree      = projectData ? buildFileTree(projectData.files) : [];
  const progress      = data.generation_progress ?? 0;
  const activePanelIdx = ALL_PANELS.findIndex(p => p.id === activePanel);
  const hasAdvisorNotif = !!(
    data.current_feedback_required ||
    (data.advisor_suggestions ?? []).length > dismissedSuggestions.size
  );
  const showEvalOverlay    = !!data.evaluation_in_progress && !data.code_generation_running;
  const showCodegenOverlay = !!data.code_generation_running;
  const showOverlay        = showEvalOverlay || showCodegenOverlay;

  // ── Panel content renderer ───────────────────────────────────────
  // bg=true → lightweight version, no Monaco / iframe
  const renderBody = (panelId: PanelId, bg: boolean) => {
    switch (panelId) {
      case "requirements":
        return <RequirementsComponent requirements={formattedRequirements} />;

      case "epics":
        return <EpicsComponent epics={data.epics || []} />;

      case "map":
        return <MindMapComponent mindMap={data.mind_map || { name: "" }} />;

      case "notes":
        return <MeetingMinutesComponent meetingMinutes={data.notebook_summary} />;

      case "advisor": {
        const suggestions = data.advisor_suggestions ?? [];
        const visible = suggestions
          .map((s, i) => ({ text: s, index: i }))
          .filter(({ index }) => !dismissedSuggestions.has(index));
        const hasFeedback = !!(data.current_feedback_required && data.current_feedback);
        return (
          <div className={styles.feedbackBox}>
            {visible.map(({ text, index }) => (
              <div key={index} className={styles.suggestionCard}>
                <p className={styles.suggestionText}>{text}</p>
                {!bg && (
                  <button
                    className={styles.suggestionDismiss}
                    title="Dismiss"
                    onClick={() => setDismissedSuggestions(prev => new Set([...prev, index]))}
                  >✕</button>
                )}
              </div>
            ))}
            {hasFeedback && (
              <div className={styles.reviewFeedbackBlock}>
                <ReactMarkdown rehypePlugins={[rehypeRaw]}>{data.current_feedback}</ReactMarkdown>
              </div>
            )}
            {visible.length === 0 && !hasFeedback && (
              <p className={styles.feedbackEmpty}>Suggestions appear here automatically.</p>
            )}
          </div>
        );
      }

      case "output":
        if (bg) return <div className={styles.outputWaiting}><p>{data.deployment_url || "Awaiting output…"}</p></div>;
        return data.deployment_url ? (
          <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
            <a href={data.deployment_url} target="_blank" rel="noreferrer" className={styles.deploymentLink}>
              {data.deployment_url}
            </a>
            <IframeSectionComponent url={data.deployment_url} />
          </div>
        ) : (
          <div className={styles.outputWaiting}>
            <p>{data.code_generation_running
              ? "Generating project… app appears here once ready."
              : "No project running yet. Start a discussion to generate an app."}</p>
          </div>
        );

      case "code":
        if (bg || !projectData) return <div className={styles.emptyCodeState}><p>No code yet.</p></div>;
        return (
          <div className={styles.codePanel}>
            <div className={styles.fileTreeSidebar}>
              <FileTree nodes={fileTree} selectedFile={selectedFile} onFileClick={handleFileSelect} />
            </div>
            <div className={styles.editorArea}>
              <MonacoEditor
                height="100%"
                language="typescript"
                value={code}
                onChange={val => setCode(val || "")}
                theme="vs-dark"
                options={{ minimap: { enabled: false }, fontSize: 13 }}
              />
            </div>
          </div>
        );

      default: return null;
    }
  };

  // ── Background panel card (function, not React component) ────────
  const bgCard = (panelId: PanelId, label: string) => (
    <div className={styles.focusPanel} style={{ height: "100%", pointerEvents: "none" }}>
      <div className={styles.panelHeader}>
        <div className={styles.panelHeaderDots}>
          <span className={styles.panelHeaderDot} style={{ background: "#ff453a" }} />
          <span className={styles.panelHeaderDot} style={{ background: "#ffd60a" }} />
          <span className={styles.panelHeaderDot} style={{ background: "#30d158" }} />
        </div>
        <div className={styles.panelTitleWrap}>
          <span className={styles.panelTitle}>{label}</span>
        </div>
        <div style={{ width: 60, flexShrink: 0 }} />
      </div>
      <div className={styles.panelBody} style={{ overflow: "hidden", pointerEvents: "none" }}>
        {renderBody(panelId, true)}
      </div>
    </div>
  );

  return (
    <div className={styles.floatRoot}>

      {/* ── Icon sidebar ──────────────────────────────────────────── */}
      <nav className={styles.iconSidebar}>
        <div className={styles.sideGroup}>
          {SIDEBAR_LEFT.map(p => (
            <button
              key={p.id}
              title={p.label}
              className={`${styles.sideBtn} ${activePanel === p.id ? styles.sideBtnActive : ""}`}
              onClick={() => setActivePanel(p.id)}
            >
              <i className={`fa ${p.icon}`} />
              {p.id === "advisor" && hasAdvisorNotif && activePanel !== "advisor" && (
                <span className={styles.sideDot} />
              )}
            </button>
          ))}
        </div>
        <div className={styles.sideSep} />
        <div className={styles.sideGroup}>
          {SIDEBAR_RIGHT.map(p => (
            <button
              key={p.id}
              title={p.label}
              className={`${styles.sideBtn} ${activePanel === p.id ? styles.sideBtnActive : ""}`}
              onClick={() => setActivePanel(p.id)}
            >
              <i className={`fa ${p.icon}`} />
            </button>
          ))}
        </div>
      </nav>

      {/* ── Panel stage ───────────────────────────────────────────── */}
      <div className={styles.panelStage}>

        {/* State pill */}
        <div className={styles.statePillBar}>
          <StateComponent state={data.current_state} />
        </div>

        {/* ── Carousel ──────────────────────────────────────────── */}
        <div className={styles.carousel}>
          {ALL_PANELS.map((panel, idx) => {
            const offset   = circularOffset(idx, activePanelIdx);
            const isActive = offset === 0;
            const cls      = `${styles.panelSlot} ${slotClass(offset, styles)}`;

            return (
              <div
                key={panel.id}
                className={cls}
                onClick={() => !isActive && setActivePanel(panel.id)}
                title={!isActive ? panel.label : undefined}
              >
                {isActive ? (
                  /* ── Active panel: full content + overlay ── */
                  <div className={styles.focusPanel} style={{ height: "100%" }}>
                    <div className={styles.panelHeader}>
                      <div className={styles.panelHeaderDots}>
                        <span className={styles.panelHeaderDot} style={{ background: "#ff453a" }} />
                        <span className={styles.panelHeaderDot} style={{ background: "#ffd60a" }} />
                        <span className={styles.panelHeaderDot} style={{ background: "#30d158" }} />
                      </div>
                      <div className={styles.panelTitleWrap}>
                        <span className={styles.panelTitle}>{panel.label}</span>
                      </div>
                      <div style={{ width: 60, flexShrink: 0 }} />
                    </div>

                    <div className={`${styles.panelBody} ${(activePanel === "output" || activePanel === "code") ? styles.panelBodyFull : ""}`}>
                      {renderBody(activePanel, false)}
                    </div>

                    {/* Eval / codegen overlay inside the active panel */}
                    {showOverlay && (
                      <div className={styles.panelOverlay}>
                        <div className={styles.overlaySpinner} />
                        <h3 className={styles.overlayTitle}>
                          {showCodegenOverlay ? "Generating your project" : "Evaluating requirements"}
                        </h3>
                        {showCodegenOverlay && (
                          <ul className={styles.tasksList}>
                            {CODEGEN_TASKS.map(task => {
                              const done   = progress >= task.max;
                              const active = progress >= task.min && progress < task.max;
                              return (
                                <li
                                  key={task.id}
                                  className={`${styles.taskRow} ${done ? styles.taskDone : active ? styles.taskActive : ""}`}
                                >
                                  <span className={styles.taskIcon}>{done ? "✓" : active ? "›" : "○"}</span>
                                  <span className={styles.taskLabel}>{task.label}</span>
                                </li>
                              );
                            })}
                          </ul>
                        )}
                        <p className={styles.overlayStatus}>
                          {data.run_status_message ||
                            (showCodegenOverlay ? "Please wait…" : "Reviewing your discussion and requirements…")}
                        </p>
                        <div className={styles.overlayProgressOuter}>
                          <div
                            className={styles.overlayProgressInner}
                            style={{ width: `${showCodegenOverlay ? progress : evalProgress}%` }}
                          />
                        </div>
                        <span className={styles.overlayPercent}>
                          {Math.round(showCodegenOverlay ? progress : evalProgress)}%
                        </span>
                      </div>
                    )}
                  </div>
                ) : (
                  /* ── Background panel: lightweight ghost card ── */
                  bgCard(panel.id, panel.label)
                )}
              </div>
            );
          })}
        </div>

        {/* Ambient voice strip */}
        <div className={styles.voiceStrip}>
          <VoiceVisuals />
        </div>

      </div>
    </div>
  );
}
