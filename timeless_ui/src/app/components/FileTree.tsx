"use client";

import React, { useState } from "react";

export type FileTreeNode = {
  name: string;
  path: string;
  isFile: boolean;
  children?: FileTreeNode[];
};

interface FileTreeProps {
  nodes: FileTreeNode[];
  onFileClick: (path: string) => void;
  selectedFile: string | null;
  level?: number;          // <-- added for hierarchy depth
  isLast?: boolean;        // <-- added for connector drawing
}

const FileTree: React.FC<FileTreeProps> = ({
  nodes,
  onFileClick,
  selectedFile,
  level = 0,
}) => {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const toggle = (path: string) => {
    setExpanded((prev) => ({ ...prev, [path]: !prev[path] }));
  };

  return (
    <ul style={{ listStyle: "none", paddingLeft: level === 0 ? 0 : 15 }}>
      {nodes.map((node, index) => {
        const isLast = index === nodes.length - 1;

        return (
          <li key={node.path}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                cursor: "pointer",
                fontWeight: node.path === selectedFile ? "bold" : "normal",
              }}
              onClick={() => (!node.isFile ? toggle(node.path) : onFileClick(node.path))}
            >
              {/* Hierarchy lines */}
              <span style={{ whiteSpace: "pre" }}>
                {"".repeat(level)}
                {level > 0 ? (isLast ? "└─ " : "├─ ") : ""}
              </span>

              {/* Icons */}
              {!node.isFile ? (
                <span>{expanded[node.path] ? "📂" : "📁"}</span>
              ) : (
                <span>📄</span>
              )}

              <span style={{ marginLeft: 6 }}>{node.name}</span>
            </div>

            {/* Render children if expanded */}
            {!node.isFile && expanded[node.path] && node.children && (
              <FileTree
                nodes={node.children}
                onFileClick={onFileClick}
                selectedFile={selectedFile}
                level={level + 1}      // propagate depth
              />
            )}
          </li>
        );
      })}
    </ul>
  );
};

export default FileTree;
