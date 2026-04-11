"use client";
import styles from "@/app/styles/dataProvider.module.css";

export interface Epic {
  title: string;
  description: string;
  features: string[];
}

interface EpicsComponentProps {
  epics: Epic[];
}

const EPIC_COLORS = [
  "#6366f1",
  "#0ea5e9",
  "#10b981",
  "#f59e0b",
  "#ec4899",
  "#8b5cf6",
];

export default function EpicsComponent({ epics }: EpicsComponentProps) {
  if (!epics || epics.length === 0) {
    return (
      <div className={styles.emptyEpicsState}>
        <p>No epics yet. Ask Timeless to review your requirements to generate epics.</p>
      </div>
    );
  }

  return (
    <div className={styles.epicsContainer}>
      {epics.map((epic, i) => {
        const color = EPIC_COLORS[i % EPIC_COLORS.length];
        return (
          <div
            key={i}
            className={styles.epicCard}
            style={{ borderLeftColor: color }}
          >
            <div className={styles.epicHeader}>
              <span className={styles.epicBadge} style={{ background: color }}>
                Epic {i + 1}
              </span>
              <h3 className={styles.epicTitle}>{epic.title}</h3>
            </div>
            <p className={styles.epicDesc}>{epic.description}</p>
            <ul className={styles.featureList}>
              {epic.features.map((f, j) => (
                <li key={j} className={styles.featureItem}>
                  <span
                    className={styles.featureDot}
                    style={{ background: color }}
                  />
                  {f}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
