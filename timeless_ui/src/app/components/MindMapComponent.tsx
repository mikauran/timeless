"use client";
import styles from "@/app/styles/dataProvider.module.css";

export interface MindMapNode {
  name: string;
  description?: string;
  children?: MindMapNode[];
}

interface MindMapComponentProps {
  mindMap: MindMapNode;
}

const EPIC_COLORS = [
  "#6366f1",
  "#0ea5e9",
  "#10b981",
  "#f59e0b",
  "#ec4899",
  "#8b5cf6",
];

export default function MindMapComponent({ mindMap }: MindMapComponentProps) {
  if (!mindMap || !mindMap.name) {
    return (
      <div className={styles.emptyEpicsState}>
        <p>No mind map yet. Ask Timeless to review your requirements to generate a map.</p>
      </div>
    );
  }

  return (
    <div className={styles.mindMapContainer}>
      {/* Root node — Product Vision */}
      <div className={styles.mmRootWrapper}>
        <div className={styles.mmRoot}>
          <span className={styles.mmRootName}>{mindMap.name}</span>
          {mindMap.description && (
            <span className={styles.mmRootDesc}>{mindMap.description}</span>
          )}
        </div>
        <div className={styles.mmRootLine} />
      </div>

      {/* Epic nodes + features */}
      {mindMap.children && mindMap.children.length > 0 && (
        <div className={styles.mmEpicsRow}>
          {mindMap.children.map((epic, i) => {
            const color = EPIC_COLORS[i % EPIC_COLORS.length];
            return (
              <div key={i} className={styles.mmEpicCol}>
                <div
                  className={styles.mmEpicNode}
                  style={{
                    borderColor: color,
                    boxShadow: `0 0 0 2px ${color}28`,
                  }}
                >
                  <span className={styles.mmEpicLabel} style={{ color }}>
                    {epic.name}
                  </span>
                </div>

                {epic.children && epic.children.length > 0 && (
                  <div className={styles.mmFeaturesCol}>
                    {epic.children.map((feat, j) => (
                      <div
                        key={j}
                        className={styles.mmFeatureNode}
                        style={{ borderLeftColor: color }}
                      >
                        {feat.name}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
