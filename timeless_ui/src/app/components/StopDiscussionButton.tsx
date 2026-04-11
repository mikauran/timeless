"use client";

import React, { useState } from "react";

interface StopDiscussionButtonProps {
  projectId: string;
  requirements: string;
  onStartCodeGen?: () => void;
  onProjectGenerated?: (projectId: string) => void;
}

export default function StopDiscussionButton({ projectId, requirements, onStartCodeGen, onProjectGenerated }: StopDiscussionButtonProps) {
//   const [loading, setLoading] = useState(false);
    requirements = " - Develop a web-based dentist appointment scheduling system. - Create a basic dentist appointment form where patients can select a date and then select a time. - Allow appointment scheduling from 9 a.m. to 5 p.m. - Include a dummy dentist list that can support at least 10 dentists and can be updated later with real dentist information. - Include a submit button on the appointment form. - Include a reset button on the appointment form that resets the form after clicking. - Implement a color scheme for the appointment scheduling system that includes a sky color."
  const handleClick = async () => {
    if (!projectId || !requirements) {
      alert("Project ID or requirements are missing.");
      return;
    }

    onStartCodeGen?.();
    try {
       const response = await fetch(`http://localhost:8082/api/v0/stop-discussion`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, requirements })
      });

      if (!response.ok) {
        throw new Error(`Failed to start code generation: ${response.statusText}`);
      }
    
    
      const result = await response.json();
       
      console.log("Code generation started:", result);

    //   const { project_id } = await response.json();
    // //   setTimeout(() => loadPr|oject(project_id), 2000);
    //  console.log("Code generation started:", project_id);

      
      // Call parent to notify project is generated
      onProjectGenerated?.(projectId);
    } catch (error) {
      console.error("Error starting code generation:", error);
      alert("Failed to start code generation. Check console for details.");
    } finally {
    //   setLoading(false);
    }
  };

  return (
    <button
    //   disabled={loading}
      onClick={handleClick}
      style={{
        padding: "90px 50px",
        backgroundColor: "rgb(93, 217, 242)",
        color: "#000000",
        border: "none",
        borderRadius: "6px",
        fontSize: "20px",
        cursor: "pointer",
        // cursor: loading ? "not-allowed" : "pointer",
      }}
    >
      {/* {loading ? "Starting Code Generation..." : "Stop Discussion & Generate Software"} */}
        Stop Discussion & Generate Software
    </button>
  );
}
