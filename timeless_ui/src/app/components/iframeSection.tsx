"use client";

interface Props {
  url?: string;
}

export default function IframeSectionComponent({ url }: Props) {
  if (!url) return null;

  return (
    <iframe
      src={url}
      style={{ flex: 1, width: "100%", border: "none", display: "block" }}
      allowFullScreen
    />
  );
}
