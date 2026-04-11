import React from "react";

interface DownloadButtonProps {
  projectId: string;
}

export default function DownloadButton({ projectId }: DownloadButtonProps) {
  const handleDownload = () => {
    const downloadUrl = `http://localhost:8082/api/v0/download_project/${projectId}`;
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = `${projectId}.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <button onClick={handleDownload} style={{ padding: "10px 20px", fontSize: "16px", cursor: "pointer", marginTop: "10px", backgroundColor: "#035206ff", color: "white", border: "none", borderRadius: "5px" }}>
      Download Project
    </button>
  );
}
