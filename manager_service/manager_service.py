import os
import json
import requests
from openai import OpenAI
from fastapi import FastAPI, Request, HTTPException, APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from enum import Enum
from dotenv import load_dotenv
import asyncio

import time
import uvicorn

import aiohttp

import subprocess

import sys
import venv
import shutil

load_dotenv()

app = FastAPI()
router = APIRouter(prefix="/api/v0")




# -----------------------------
# Application code below remains the same
# -----------------------------

class DiscussionState(Enum):
    CONCEPTUALIZATION = "Conceptualization"
    REQUIREMENT_ANALYSIS = "Requirement Analysis"
    DESIGN = "Design (Tech & UI/UX)"
    IMPLEMENTATION = "Implementation"
    TESTING = "Testing"
    DEPLOYMENT_MAINTENANCE = "Deployment and Maintenance"

# Global in-memory state
current_state = DiscussionState.CONCEPTUALIZATION
transcriptions = []             # List of received transcription messages
requirements = ""               # List of software requirements
notebook_summary = ""           # Summary of the discussion (the "notebook")
code_generation_running = False  # Flag to indicate if a code generation job is running
deployment_url = ""             # URL where the generated code will be deployed

project_id = ""                # Current project ID for code generation (sp created)

current_feedback= ""
current_feedback_required = False
run_status_message = ""       # Live status shown in UI spinner during project setup
evaluation_in_progress = False  # True while the LLM is reviewing requirements
generation_progress = 0         # 0-100 progress sent to UI during code generation
active_popup = ""               # Which popup is open: "requirements"|"notes"|"feedback"|""
popup_request_id = 0            # Incremented each time a popup is opened so UI re-triggers
epics: list = []                # LLM-grouped epics derived from requirements
mind_map: dict = {}             # Tree structure for visual mind map
advisor_suggestions: list = []  # Proactive advisor suggestions (array of strings)
acceptance_report: dict = {}    # Structured post-build acceptance results
acceptance_passed = False       # Whether the generated app appears to satisfy the requirements

PROJECTS_DIR = "projects"

# Environment configuration for LLM providers and service URLs
SERVICE_PORT = os.environ.get("MANAGER_SERVICE_PORT")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER") 
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_GENERAL_MODEL")
OLLAMA_URL = os.environ.get("OLLAMA_URL")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL")
VOICE_SERVICE_URL = os.environ.get("VOICE_SERVICE_URL")
MEETING_SERVICE_URL = os.environ.get("MEETING_SERVICE_URL")
WEB_CODE_GENERATION_SERVICE_URL = os.environ.get("WEB_CODE_GENERATION_SERVICE_URL")
DEMO_MODE = os.environ.get("DEMO_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
FAST_GENERATION_MODE = os.environ.get("FAST_GENERATION_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}

if not WEB_CODE_GENERATION_SERVICE_URL:
    WEB_CODE_GENERATION_SERVICE_URL = "http://localhost:8084/api/v0"   # safe fallback

OPENCODE_MODEL = os.environ.get("OPENCODE_MODEL", "openai/gpt-4o")
MAX_FIX_RETRIES = int(os.environ.get("MAX_FIX_RETRIES", "0" if DEMO_MODE else "2"))
OPENCODE_FIX_TIMEOUT_SECONDS = int(os.environ.get("OPENCODE_FIX_TIMEOUT_SECONDS", "60" if DEMO_MODE else "180"))

# Choose the model based on the provider
CHOSEN_MODEL = (
    OPENAI_MODEL if LLM_PROVIDER == "openai"
    else OPENROUTER_MODEL if LLM_PROVIDER == "openrouter"
    else OLLAMA_MODEL
)

# Add global SSE queues for project codegen
codegen_sse_connections = {}

# Setup LLM client based on provider choice.
def get_llm_client():
    if LLM_PROVIDER.lower() == "openrouter":
        return OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
    elif LLM_PROVIDER.lower() == "openai":
        return OpenAI(
            api_key=OPENAI_API_KEY,
        )
    elif LLM_PROVIDER.lower() == "ollama":
        return OpenAI(
            base_url=OLLAMA_URL,
            api_key="ollama",  # Required but unused
        )
    else:
        raise ValueError("Unsupported LLM Provider")

llm_client = get_llm_client()

# -------------------------------------------------------------------
# LLM Helper Functions
# -------------------------------------------------------------------

class ImmediateAction(BaseModel):
    take_action: bool

def poll_immediate_action(current_state: DiscussionState,  transcription: str) -> bool:
    """
    Poll the LLM to decide if immediate action is needed based on the latest transcription.
    The prompt asks for a True/False answer.
    """
    system_prompt = (
        "You are an AI system called Timeless, acting as an assistant for a software development meeting focused on creating new software. "
        "Analyze the provided transcription snippet and determine if the content indicates that an immediate action is required. "
        "Possible reasons to take action include updating meeting minutes, updating current state of discussion or generating code. "
        "Return your answer as a valid JSON with a single field 'take_action' set to true or false. Do not include any extra commentary."
    )
    user_prompt = f"Transcription snippet: '{transcription}'"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Current discussion state: {current_state}\n\nLatest transcription: {user_prompt}"},
    ]
    try:
        response = llm_client.beta.chat.completions.parse(
            model=CHOSEN_MODEL,
            messages=messages,
            max_tokens=10,
            response_format=ImmediateAction
        )
        result = response.choices[0].message.parsed.take_action
        print(f"Immediate action LLM response: {result}")
        return result
    except Exception as e:
        print("Error in poll_immediate_action:", e)
        return False

def update_notebook_summary(current_notebook: str, transcriptions: list) -> str:
    """
    Poll the LLM to update the notebook summary with the latest transcription.
    The prompt includes the current summary and the new transcription.
    """
    system_prompt = (
        "You are an AI system called Timeless, acting as an summarization assistant for a software development meeting about creating new software. "
        "Your task is to update the current notebook summary to concisely capture all discussion points, decisions, and evolving requirements. "
        "Focus on clarity and brevity in your summary."
    )
    user_prompt = (
        f"Current notebook summary: '{current_notebook}'\n"
        "New transcriptions:\n" + "\n".join(transcriptions)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    try:
        response = llm_client.chat.completions.create(
            model=CHOSEN_MODEL,
            messages=messages,
            max_tokens=1000,
        )
        new_summary = response.choices[0].message.content.strip()
        # print(f"Updated notebook summary: {new_summary}")
        return new_summary
    except Exception as e:
        print("Error in update_notebook_summary:", e)
        return current_notebook

def format_requirements(requirements: str) -> str:
    """
    Format the requirements list for code generation.
    """
    system_prompt = (
        "You are an AI system called Timeless, acting as an assistant that helps in generating software development prompts. "
        "Your task is to take a list of raw requirements and transform them into a single cohesive paragraph. "
        "Ensure that the paragraph is clear, concise, and captures all the key points from the list. "
        "The paragraph should be suitable for use as a prompt for generating code or further discussion."
    )
    user_prompt = (
        f"Raw requirements list: {requirements}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    try:
        response = llm_client.chat.completions.create(
            model=CHOSEN_MODEL,
            messages=messages,
            max_tokens=1000,
        )
        new_summary = response.choices[0].message.content.strip()
        # print(f"Formatted requirements: {new_summary}")
        return new_summary
    except Exception as e:
        print("Error in format_requirements:", e)
        return requirements

def get_requirements(meeting_id: str) -> str:
    """
    Retrieve the list of requirements from the Meeting Service (or other service).
    Expects a JSON response with a "requirements" field.
    """
    try:
        full_url = MEETING_SERVICE_URL + f"/meeting/{meeting_id}/requirements"
        response = requests.get(full_url)
        if response.status_code == 200:
            data = response.json()
            reqs = data.get("requirements", "")
            # print(f"Fetched requirements: {reqs}")
            return reqs
        else:
            print("Failed to fetch requirements, status:", response.status_code)
            return ""
    except Exception as e:
        print("Error fetching requirements:", e)
        return ""


def sync_requirements(meeting_id: str, retries: int = 3, delay_s: float = 0.15) -> str:
    """
    Refresh manager-side requirements from the requirements service.
    Retry briefly because the requirements service receives the same
    transcription on a separate request and may complete slightly later.
    """
    latest = requirements
    for attempt in range(retries):
        latest = get_requirements(meeting_id)
        if latest.strip():
            return latest
        if attempt < retries - 1:
            time.sleep(delay_s)
    return latest

class EvaluatedState(BaseModel):
    updated_state: DiscussionState
    generate_code: bool
    feedback: str
    feedback_required: bool


class AcceptanceReport(BaseModel):
    passed: bool
    summary: str
    implemented: list[str]
    missing: list[str]
    risks: list[str]
    template_signals: list[str]

def evaluate_and_maybe_update_state(current_state: DiscussionState, requirements: str, notebook: str, transcription: str):
    """
    Poll the LLM with the current state, requirements, notebook summary, and latest transcription.
    """
    # system_prompt = (
    #     f'''
    #     You are an AI system called Timeless, acting as a strategic meeting AI assistant for a software development meeting.
    #     The current discussion state can only be one of the following: Conceptualization -> Requirement Analysis -> Design (Tech & UI/UX) -> Implementation -> Testing -> Deployment and Maintenance.
    #     The discussion should be moving through these states in the aforementioned order.
    #     Based on the provided context, determine whether to update the state (choose one of these values) and whether to trigger code generation.
    #     If the users demand for code generation, you should trigger the code generation service.
    #     Respond with a valid JSON object containing the following:
    #     - 'updated_state': the new state (one of: {", ".join([s.value for s in DiscussionState])})
    #     - 'generate_code': a boolean flag indicating whether to trigger code generation
    #     - 'feedback': any additional feedback or instructions for the users
    #     Do not include any extra commentary.
    #     Respond only with a valid JSON object.
    #     '''
    # )

    system_prompt = f"""
    You are an AI system called Timeless, acting as a strategic meeting AI assistant for a software development meeting.

    The discussion state can only be one of the following, in this exact order:
    Conceptualization -> Requirement Analysis -> Design (Tech & UI/UX) -> Implementation -> Testing -> Deployment and Maintenance.

    Your job is to analyze the provided context and return only a valid JSON object.

    Rules:
    - The discussion should move through the states in the given order.
    - Always determine the most appropriate current or updated discussion state.
    - "updated_state" must always be one of: {", ".join([s.value for s in DiscussionState])}

    IMPORTANT — generate_code rule (read carefully):
    - Set "generate_code" to true ONLY when the user gives an EXPLICIT DIRECT COMMAND to start
      code/project generation in the latest transcription. Examples of valid triggers:
        "generate the code"
        "Timeless generate the code"
        "generate the project"
        "start code generation"
        "build the project now"
        "create the code"
        "Timeless build it"
        "go ahead and generate"
        "start generating"
    - Set "generate_code" to FALSE in all other cases, including:
        - The user is describing requirements (e.g. "I want a dentist website")
        - The user is discussing features or design
        - The user asks a question
        - The user says something ambiguous
        - The latest transcription does NOT contain a clear direct command to generate/build NOW
    - Describing what to build is NOT the same as commanding generation. Only an explicit
      imperative command like the examples above should set generate_code to true.

    - Do not provide feedback by default.
    - Only evaluate completeness and provide feedback if the user explicitly asks to review,
      check, validate, or verify whether requirements are complete or if something is missing.
    - If the user does NOT explicitly ask for such a review/check:
      set "feedback_required" to false and "feedback" to an empty string.
    - If the user explicitly asks to review/check the requirements:
      analyze completeness; if something is missing set "feedback_required" to true with concise feedback,
      otherwise set "feedback_required" to false and "feedback" to empty string.
    - Do not include any explanation outside the JSON.

    Respond with only a valid JSON object in exactly this format:
    {{
    "updated_state": "<one of: {", ".join([s.value for s in DiscussionState])}>",
    "generate_code": true or false,
    "feedback_required": true or false,
    "feedback": "<feedback text or empty string>"
    }}
    """

    # system_prompt = (
    #     f'''
    #     You are an AI system called Timeless, acting as a strategic meeting AI assistant for a software development meeting.
    #     The current discussion state can only be one of the following: Conceptualization -> Requirement Analysis -> Design (Tech & UI/UX) -> Implementation.
    #     The discussion should be moving through these states in the aforementioned order.
    #     Based on the provided context, determine whether to update the state (choose one of these values) and whether to trigger code generation.
    #     If the users demand for code generation, you should trigger the code generation service.
    #     Respond with a valid JSON object containing the following:
    #     - 'updated_state': the new state (one of: {", ".join([s.value for s in DiscussionState])})
    #     - 'generate_code': a boolean flag indicating whether to trigger code generation
    #     - 'feedback': any additional feedback or instructions for the users
    #     Do not include any extra commentary.
    #     Respond only with a valid JSON object.
    #     '''
    # )

    user_prompt = (
        f"Current state: '{current_state.value}'\n"
        f"Requirements: '{requirements}'\n"
        f"Notebook summary: '{notebook}'\n"
        f"Latest transcription: '{transcription}'"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    try:
        response = llm_client.beta.chat.completions.parse(
            model=CHOSEN_MODEL,
            messages=messages,
            max_tokens=150,
            response_format=EvaluatedState
        )
        result = response.choices[0].message.parsed
        print(f"State evaluation LLM response: {result}")
        # Ensure the updated_state is returned as a DiscussionState enum
        updated = result.updated_state
        if isinstance(updated, str):
            try:
                # Match by the Enum value (the human-readable string)
                updated_state_enum = next(s for s in DiscussionState if s.value == updated)
            except StopIteration:
                # Fallback: try constructing by name (in case LLM returned the Enum name)
                try:
                    updated_state_enum = DiscussionState[updated]
                except Exception:
                    # If we can't parse it, leave the state unchanged
                    updated_state_enum = current_state
        elif isinstance(updated, DiscussionState):
            updated_state_enum = updated
        else:
            updated_state_enum = current_state

        return updated_state_enum, result.generate_code, result.feedback_required, result.feedback
    except Exception as e:
        print("Error in evaluate_and_maybe_update_state:", e)
        return current_state, False, False, ""

def generate_epics_and_mindmap(requirements: str) -> tuple:
    """
    Ask the LLM to group requirements into epics and build a mind-map tree.
    Returns (epics_list, mind_map_dict).
    """
    if not requirements or not requirements.strip():
        return [], {}

    system_prompt = """
You are a product analyst AI. Given a list of software requirements, group them into high-level epics.
Return a valid JSON object with exactly this structure — no markdown, no commentary:
{
  "epics": [
    {
      "title": "Epic title",
      "description": "One sentence describing this epic",
      "features": ["Feature 1", "Feature 2", "Feature 3"]
    }
  ],
  "mind_map": {
    "name": "Product Vision",
    "description": "One sentence describing the overall product",
    "children": [
      {
        "name": "Epic title",
        "children": [
          {"name": "Feature 1"},
          {"name": "Feature 2"}
        ]
      }
    ]
  }
}

Rules:
- Group requirements into 3-6 meaningful epics
- Each epic should have 2-5 features
- The mind_map must mirror the epics structure exactly
- Return ONLY valid JSON, absolutely no other text
"""

    user_prompt = f"Requirements:\n{requirements}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        response = llm_client.chat.completions.create(
            model=CHOSEN_MODEL,
            messages=messages,
            max_tokens=1500,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
        epics_data = parsed.get("epics", [])
        mind_map_data = parsed.get("mind_map", {})
        print(f"[epics] Generated {len(epics_data)} epics")
        return epics_data, mind_map_data
    except Exception as e:
        print(f"[epics] Error generating epics: {e}")
        return [], {}


def proactive_advisor(requirements: str, notebook_summary: str) -> list:
    """
    Proactively identifies gaps and missing topics in the current requirements
    and discussion. Runs automatically — no user command needed.
    Returns a list of suggestion strings. Each call produces a FRESH list so
    anything already discussed (and thus in requirements/notes) is automatically
    excluded from the new set.
    """
    if not requirements or not requirements.strip():
        return []

    system_prompt = """
You are an experienced software product advisor integrated into a development meeting tool called Timeless.
Your role is to proactively help the team by identifying important aspects of their product that have NOT been discussed or covered yet.

CRITICAL RULE: Read the requirements and meeting notes carefully. Any topic already mentioned there must NOT appear in your suggestions. Only suggest things that are genuinely absent.

Identify 3-5 specific gaps. Return ONLY a valid JSON array of strings — no markdown, no numbering, no other text.
Each string is one concise suggestion (1-2 sentences max).

Example format:
["You haven't discussed how users will log in — consider whether you need accounts or guest booking.",
 "Error handling is missing: what happens when a form submission fails or a network error occurs?",
 "Consider adding email or SMS confirmation notifications after key actions."]

Categories to check (only include what is genuinely absent and relevant to this product):
- User authentication and authorization
- Error handling and edge cases
- Data validation and input security
- Performance and scalability
- Mobile responsiveness or cross-device support
- Third-party integrations or external APIs
- Data storage, privacy, GDPR, data retention
- Accessibility (a11y / WCAG)
- Notifications (email, push, SMS)
- Admin panel or content management tools
- Search, filtering, sorting
- Real-time or offline support
- Onboarding, help, user documentation
- Analytics or reporting

Be direct and address the team as "you". Return ONLY the JSON array.
"""

    user_prompt = (
        f"Current requirements:\n{requirements}\n\n"
        f"Meeting discussion so far:\n{notebook_summary or 'No meeting notes yet.'}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        response = llm_client.chat.completions.create(
            model=CHOSEN_MODEL,
            messages=messages,
            max_tokens=600,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        suggestions = json.loads(raw.strip())
        if not isinstance(suggestions, list):
            suggestions = []
        print(f"[advisor] {len(suggestions)} suggestions generated")
        return suggestions
    except Exception as e:
        print(f"[advisor] Error generating advice: {e}")
        return []


def collect_project_acceptance_context(project_path: str, max_files: int = 12, max_chars: int = 24000) -> dict[str, str]:
    """
    Collect a small, high-signal subset of generated files for acceptance checking.
    """
    preferred_paths = [
        "README.md",
        "frontend/package.json",
        "frontend/src/app/page.tsx",
        "frontend/src/app/layout.tsx",
        "frontend/src/app/globals.css",
        "frontend/app/page.tsx",
        "frontend/app/layout.tsx",
        "frontend/app/globals.css",
        "backend/main.py",
        "backend/app.py",
        "backend/requirements.txt",
    ]
    allowed_suffixes = {".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".css", ".py", ".txt"}
    selected: dict[str, str] = {}
    total_chars = 0

    def maybe_add(rel_path: str) -> None:
        nonlocal total_chars
        if rel_path in selected or len(selected) >= max_files or total_chars >= max_chars:
            return
        full_path = os.path.join(project_path, rel_path)
        if not os.path.isfile(full_path):
            return
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return
        remaining = max_chars - total_chars
        if remaining <= 0:
            return
        trimmed = content[:remaining]
        selected[rel_path] = trimmed
        total_chars += len(trimmed)

    for rel_path in preferred_paths:
        maybe_add(rel_path)

    if len(selected) < max_files and total_chars < max_chars:
        for root, _, files in os.walk(project_path):
            for filename in sorted(files):
                rel_path = os.path.relpath(os.path.join(root, filename), project_path)
                _, ext = os.path.splitext(filename)
                if ext.lower() not in allowed_suffixes:
                    continue
                maybe_add(rel_path)
                if len(selected) >= max_files or total_chars >= max_chars:
                    return selected

    return selected


def fetch_preview_snapshot(url: str, timeout: int = 20, max_chars: int = 12000) -> str:
    """
    Fetch rendered preview HTML from the running app for acceptance review.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = requests.get(url, timeout=3)
            if response.status_code < 500 and response.text:
                return response.text[:max_chars]
        except Exception:
            pass
        time.sleep(1)
    return ""


def evaluate_generated_project_acceptance(
    requirements: str,
    project_path: str,
    build_log: str,
    preview_snapshot: str = "",
) -> dict:
    """
    Ask the LLM for a structured acceptance check after a successful build.
    """
    context_files = collect_project_acceptance_context(project_path)
    if not context_files:
        return {
            "passed": False,
            "summary": "No generated files were available for acceptance review.",
            "implemented": [],
            "missing": ["Generated project files could not be inspected."],
            "risks": ["Acceptance check had no source context."],
            "template_signals": [],
        }

    system_prompt = """
You are a strict software acceptance reviewer.

Review whether a generated application actually implements the requested software requirements.

Rules:
- Treat successful compilation as necessary but not sufficient.
- Detect template leakage such as default framework starter text, placeholder sections, or generic stock pages.
- Be conservative: if a requirement is not clearly implemented in the provided files, list it as missing.
- Return only a valid JSON object matching the requested schema.
"""
    user_prompt = (
        f"Requirements:\n{requirements}\n\n"
        f"Frontend build log:\n{build_log[:6000]}\n\n"
        f"Rendered preview HTML (may be empty if preview was unavailable):\n{preview_snapshot[:12000]}\n\n"
        f"Project files:\n{json.dumps(context_files, indent=2)}"
    )
    try:
        response = llm_client.beta.chat.completions.parse(
            model=CHOSEN_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1200,
            response_format=AcceptanceReport,
        )
        result = response.choices[0].message.parsed
        return {
            "passed": result.passed,
            "summary": result.summary,
            "implemented": result.implemented,
            "missing": result.missing,
            "risks": result.risks,
            "template_signals": result.template_signals,
        }
    except Exception as e:
        print(f"[acceptance] Error evaluating generated project: {e}")
        return {
            "passed": False,
            "summary": "Acceptance check failed.",
            "implemented": [],
            "missing": ["Acceptance check could not be completed."],
            "risks": [str(e)[:200]],
            "template_signals": [],
        }


def trigger_web_code_generation(requirements: str, project_id: str, fast_mode: bool = FAST_GENERATION_MODE):
    try:
        if not project_id or not requirements:
            raise HTTPException(status_code=400, detail="Missing project_id or requirements")

        
        response = requests.post(
            f"{WEB_CODE_GENERATION_SERVICE_URL}/generate_project",
            json={"project_id": project_id, "requirements": requirements, "fast_mode": fast_mode},
            timeout=36000
        )
        response.raise_for_status()  # <-- Raises HTTPError for non-200

        # After generation, optionally start the project.
        startup_result = run_generated_project(project_id, requirements_text=requirements, fast_mode=fast_mode)
        apply_runtime_state_from_startup(startup_result)
        print(f"Project {project_id} started with processes:", startup_result["processes"].keys())
        # for name, proc in processes.items():
        #     print(f"[{name.upper()}] log stream starting...")
        #         # You can read lines asynchronously in a thread or async loop
        #     # Example synchronous for debugging:
        #     for line in proc.stdout:
        #         print(f"[{name.upper()}]", line.strip())

        # return response.json()
        frontend_url = startup_result.get("deployment_url") if not startup_result.get("startup_skipped") else ""
        return {
            "status": "OK",
            "message": startup_result.get("message", "Project generated"),
            "project_id": project_id,
            "frontend_url": frontend_url,
            "fast_mode": fast_mode,
            "acceptance_report": startup_result.get("acceptance_report", {}),
            "acceptance_passed": startup_result.get("acceptance_passed", False),
        }
        # return JSONResponse(content={"status": "OK", "message": "Project generated", "project_id": project_id, "frontend_url": f"http://localhost:3001"})
    except Exception as e:
        import traceback
        print("Error in /generation:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
import socket
import sys

def is_port_free(port: int) -> bool:
    """Check if the given port is free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) != 0
    
def start_nextjs_dev(ui_dir, port=3002):
    """Start the generated Next.js frontend without mutating its toolchain."""
    if not os.path.exists(ui_dir):
        print(f"Error: directory {ui_dir} does not exist.")
        return None

    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"

    package_json_path = os.path.join(ui_dir, "package.json")
    if not os.path.exists(package_json_path):
        print("[runner] package.json missing; cannot start frontend.")
        return None
    if not os.path.exists(package_json_path):
        print("[runner] package.json missing — creating a default Next.js package.json")
        default_pkg = {
            "name": "generated-frontend",
            "version": "0.1.0",
            "private": True,
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start"
            },
            "dependencies": {
                "next": "14.2.3",
                "react": "^18",
                "react-dom": "^18"
            },
            "devDependencies": {
                "@types/node": "^20",
                "@types/react": "^18",
                "@types/react-dom": "^18",
                "typescript": "^5"
            }
        }
        with open(package_json_path, "w") as f:
            json.dump(default_pkg, f, indent=2)

    if not os.path.exists(package_json_path):
        print("[runner] package.json missing; cannot start frontend.")
        return None

    print(f"Starting Next.js dev server on port {port}...")
    cmd = [npm_cmd, "run", "dev", "--", f"--port={port}"]
    proc = subprocess.Popen(cmd, cwd=ui_dir)
    return proc


def wait_for_nextjs_ready(port=3002, timeout=60):
    import socket
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("localhost", port), timeout=2):
                return True
        except Exception:
            time.sleep(1)
    return False


def wait_for_deployment_ready(url: str, timeout=20):
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = requests.get(url, timeout=3)
            if response.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def terminate_process(proc, name: str = "process") -> None:
    if not proc:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def cleanup_runtime_processes(processes: dict) -> None:
    for name, proc in list(processes.items()):
        terminate_process(proc, name)
    processes.clear()


def clear_next_build_artifacts(frontend_dir: str) -> None:
    next_dir = os.path.join(frontend_dir, ".next")
    if os.path.isdir(next_dir):
        shutil.rmtree(next_dir, ignore_errors=True)

def open_browser(url):
    import webbrowser
    print(f"Opening browser at {url}")
    webbrowser.open(url)

def find_dir(base_path, options):
    for name in options:
        path = os.path.join(base_path, name)
        if os.path.isdir(path):
            return path
    return None


def parse_run_config(project_path: str) -> dict:
    """
    Read README.md and extract the TIMELESS_RUN_CONFIG JSON block.
    Returns a dict like:
      {
        "frontend": {"dir": "frontend", "install_cmd": "...", "start_cmd": "...", "type": "nextjs"},
        "backend":  {"dir": "backend",  "install_cmd": "...", "start_cmd": "...", "entry": "main", "type": "fastapi"}
      }
    Returns {} if the block is not found or cannot be parsed.
    """
    import re
    readme_path = os.path.join(project_path, "README.md")
    if not os.path.exists(readme_path):
        print("[runner] README.md not found — will use fallback startup logic")
        return {}
    try:
        content = open(readme_path, "r", errors="replace").read()
        match = re.search(
            r"<!--\s*TIMELESS_RUN_CONFIG\s*([\s\S]*?)\s*-->",
            content
        )
        if not match:
            print("[runner] No TIMELESS_RUN_CONFIG block in README.md — will use fallback startup logic")
            return {}
        config = json.loads(match.group(1))
        print(f"[runner] Loaded run config from README.md: {list(config.keys())}")
        return config
    except Exception as e:
        print(f"[runner] Failed to parse TIMELESS_RUN_CONFIG from README.md: {e}")
        return {}


# Keywords that indicate the user wants a requirements review
_REVIEW_KEYWORDS = (
    "review", "validate", "verify", "evaluate",
    "check requirements", "check our", "anything missing",
    "is missing", "are missing", "assess", "look at our requirements",
)

def _is_review_request(transcription: str) -> bool:
    """Return True if the transcription is asking for a requirements review/evaluation."""
    t = transcription.lower()
    return any(kw in t for kw in _REVIEW_KEYWORDS)


_POPUP_PATTERNS = {
    "requirements": (
        "requirements popup", "open requirements", "show requirements",
        "popup requirements", "popup the requirements",
        "requirements popup please", "show the requirements",
        "display requirements", "display the requirements",
        "open the requirements",
    ),
    "notes": (
        "notes popup", "meeting notes popup", "open notes", "show notes",
        "open meeting notes", "show meeting notes", "meeting minutes popup",
        "popup the notes", "popup notes", "popup meeting notes",
        "popup the meeting notes", "show the notes", "show the meeting notes",
        "display notes", "display the notes", "display meeting notes",
        "open the notes", "open the meeting notes",
    ),
    "feedback": (
        "feedback popup", "open feedback", "show feedback",
        "popup feedback", "popup the feedback",
        "show the feedback", "display feedback", "display the feedback",
        "open the feedback",
    ),
}
_POPUP_CLOSE = (
    "close popup", "close the popup", "close this popup",
    "hide popup", "hide the popup",
    "dismiss popup", "dismiss the popup", "dismiss",
    "close it", "close this", "shut popup",
    "exit popup", "exit the popup",
    "go back", "go back please",
)

def _detect_popup_request(transcription: str) -> str:
    """
    Return the popup type to open ('requirements'|'notes'|'feedback'),
    'close' to dismiss the current popup, or '' if no popup intent found.
    """
    t = transcription.lower()
    if any(kw in t for kw in _POPUP_CLOSE):
        return "close"
    for popup_type, keywords in _POPUP_PATTERNS.items():
        if any(kw in t for kw in keywords):
            return popup_type
    return ""


def _get_free_port(start: int = 8090) -> int:
    """Return the first free TCP port at or after `start`."""
    port = start
    while not is_port_free(port):
        port += 1
    return port


def ensure_nextjs_typescript_bootstrap(frontend_dir: str) -> None:
    """Create minimal Next.js TypeScript bootstrap files only when missing."""
    tsconfig_path = os.path.join(frontend_dir, "tsconfig.json")
    next_env_path = os.path.join(frontend_dir, "next-env.d.ts")

    normalized_tsconfig = {
        "compilerOptions": {
            "target": "ES2017",
            "lib": ["dom", "dom.iterable", "esnext"],
            "allowJs": True,
            "skipLibCheck": True,
            "strict": False,
            "noEmit": True,
            "esModuleInterop": True,
            "module": "esnext",
            "moduleResolution": "bundler",
            "resolveJsonModule": True,
            "isolatedModules": True,
            "jsx": "preserve",
            "incremental": True,
            "plugins": [{"name": "next"}],
            "paths": {"@/*": ["./src/*"]},
        },
        "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
        "exclude": ["node_modules"],
    }

    if not os.path.exists(tsconfig_path):
        with open(tsconfig_path, "w", encoding="utf-8") as f:
            json.dump(normalized_tsconfig, f, indent=2)
            f.write("\n")
        print("[runner] Created missing tsconfig.json for Next.js")

    if not os.path.exists(next_env_path):
        with open(next_env_path, "w", encoding="utf-8") as f:
            f.write('/// <reference types="next" />\n')
            f.write('/// <reference types="next/image-types/global" />\n\n')
            f.write('// This file should not be edited\n')
        print("[runner] Created missing next-env.d.ts")


def ensure_frontend_package_json(frontend_dir: str) -> None:
    """Create a minimal package.json only when generation omitted it entirely."""
    package_json_path = os.path.join(frontend_dir, "package.json")
    if os.path.exists(package_json_path):
        return

    default_pkg = {
        "name": "generated-frontend",
        "version": "0.1.0",
        "private": True,
        "scripts": {
            "dev": "next dev",
            "build": "next build",
            "start": "next start",
        },
        "dependencies": {
            "next": "14.2.3",
            "react": "^18",
            "react-dom": "^18",
        },
        "devDependencies": {
            "@types/node": "^20",
            "@types/react": "^18",
            "@types/react-dom": "^18",
            "typescript": "^5",
        },
    }
    with open(package_json_path, "w", encoding="utf-8") as f:
        json.dump(default_pkg, f, indent=2)
        f.write("\n")
    print("[runner] Created missing package.json fallback")


def run_frontend_build(frontend_dir: str, npm_cmd: str, build_cmd: str | None = None) -> tuple[bool, str]:
    """Run the generated frontend build and return success plus combined logs."""
    if build_cmd:
        build_parts = build_cmd.split()
        if build_parts and build_parts[0] in ("npm", "npx"):
            build_parts[0] = npm_cmd
    else:
        build_parts = [npm_cmd, "run", "build"]

    print(f"[runner] Frontend build: {' '.join(build_parts)}")
    result = subprocess.run(
        build_parts,
        cwd=frontend_dir,
        capture_output=True,
        text=True,
        timeout=600,
    )
    combined_log = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    return result.returncode == 0, combined_log

def _venv_executables(project_id: str):
    """Return (python_exe, pip_exe) paths inside the project's venv."""
    base = os.path.join(PROJECTS_DIR, project_id, "venv")
    if os.name == "nt":
        return (os.path.join(base, "Scripts", "python.exe"),
                os.path.join(base, "Scripts", "pip.exe"))
    return (os.path.join(base, "bin", "python"),
            os.path.join(base, "bin", "pip"))


def resolve_opencode_command() -> list[str]:
    resolved = shutil.which("opencode") or shutil.which("opencode.cmd")
    if resolved:
        return [resolved]

    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            for candidate in (
                os.path.join(appdata, "npm", "opencode.cmd"),
                os.path.join(appdata, "npm", "opencode.ps1"),
                os.path.join(appdata, "npm", "opencode"),
            ):
                if os.path.exists(candidate):
                    return [candidate]

    raise FileNotFoundError("opencode CLI not found")


def _run_opencode_fix(project_path: str, error_log: str, requirements_text: str = "") -> bool:
    """Ask OpenCode to fix errors in the project. Returns True if successful."""
    global run_status_message, generation_progress
    requirements_block = requirements_text.strip()[:4000] if requirements_text else "Requirements not provided."
    fix_prompt = (
        "The following software project failed validation. "
        "Fix all reported issues so it builds, starts, and actually implements the missing requirements. "
        "Do not ask clarifying questions — fix the code now.\n\n"
        "Use the requirements below as the source of truth for what the app should be. "
        "Do not produce a marketing page, brochure site, placeholder sections, or image-only landing page unless the requirements explicitly call for that.\n\n"
        "Requirements:\n"
        f"{requirements_block}\n\n"
        "Required outcome:\n"
        "- Implement the real application behavior described in the requirements, not just themed UI.\n"
        "- Fix any missing interactive logic, state management, rendering, controls, workflows, or data handling needed by the requirements.\n"
        "- Keep the app usable in the environments described by the requirements, such as browser or mobile, when requested.\n"
        "- Remove template leakage such as generic metadata, boilerplate copy, and starter text.\n"
        "- Prefer a focused working product experience over extra marketing content unless the requirements explicitly ask for marketing sections.\n\n"
        "Constraints:\n"
        "- Fix the code in the current project files.\n"
        "- Keep the existing project stack and folder layout.\n"
        "- Do not ask clarifying questions.\n"
        "- Do not stop at styling changes; implement working functionality.\n\n"
        "Validation target:\n"
        "- After your changes, the app must compile, start, and present the actual requested application behavior rather than a generic landing page.\n\n"
        "Fix the code now.\n\n"
        f"Error log:\n{error_log[:3000]}"
    )
    cmd = [*resolve_opencode_command(), "run", "--model", OPENCODE_MODEL, "--format", "json", fix_prompt]
    env = {**os.environ}
    env["OPENCODE_PERMISSION"] = json.dumps({"write": "allow", "edit": "allow", "bash": "allow"})
    print(f"[runner] Running OpenCode fix in {project_path}")
    run_status_message = "OpenCode repair is running..."
    generation_progress = max(generation_progress, 46)
    try:
        result = subprocess.run(
            cmd, cwd=project_path, capture_output=True, text=True,
            timeout=OPENCODE_FIX_TIMEOUT_SECONDS, env=env
        )
        print(f"[runner] OpenCode fix exited {result.returncode}")
        if result.stdout:
            print(f"[runner] OpenCode fix stdout ({len(result.stdout)} chars): {result.stdout[:600]}")
        if result.stderr:
            print(f"[runner] OpenCode fix stderr ({len(result.stderr)} chars): {result.stderr[:600]}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[runner] OpenCode fix timed out after {OPENCODE_FIX_TIMEOUT_SECONDS}s")
        run_status_message = f"OpenCode repair timed out after {OPENCODE_FIX_TIMEOUT_SECONDS}s."
        return False
    except Exception as e:
        print(f"[runner] OpenCode fix error: {e}")
        run_status_message = f"OpenCode repair failed: {str(e)[:120]}"
        return False

def run_generated_project(project_id: str, requirements_text: str = "", fast_mode: bool = False) -> dict:
    """
    Set up and run the generated project end-to-end:
    1. Create an isolated Python venv for the backend.
    2. Install backend requirements.txt into that venv.
    3. Start the FastAPI backend (uvicorn) using the venv's Python.
    4. Install npm dependencies and start the Next.js frontend on port 3002.
    5. On any error: ask OpenCode to fix and retry (up to MAX_FIX_RETRIES times).
    """
    global run_status_message, deployment_url, generation_progress

    project_path = os.path.join(PROJECTS_DIR, project_id)

    if fast_mode:
        generation_progress = 100
        run_status_message = "Code generated. Startup skipped in fast mode."
        deployment_url = ""
        return {
            "project_id": project_id,
            "processes": {},
            "frontend_ready": False,
            "preview_ready": False,
            "deployment_url": "",
            "error_log": "",
            "acceptance_report": {},
            "acceptance_passed": False,
            "startup_skipped": True,
            "message": "Project generated in fast mode",
        }

    run_config   = parse_run_config(project_path)  # from README.md

    # Resolve dirs: prefer README config, fall back to directory scanning
    fe_cfg = run_config.get("frontend", {})
    be_cfg = run_config.get("backend", {})

    frontend_dir = (
        os.path.join(project_path, fe_cfg["dir"]) if fe_cfg.get("dir")
        else find_dir(project_path, ["frontend", "client"])
    )
    backend_dir = (
        os.path.join(project_path, be_cfg["dir"]) if be_cfg.get("dir")
        else find_dir(project_path, ["backend", "server"])
    )

    frontend_port = _get_free_port(3002)
    processes: dict = {}
    frontend_ready = False
    latest_build_log = ""
    latest_acceptance_report: dict = {
        "passed": False,
        "summary": "Acceptance check did not run.",
        "implemented": [],
        "missing": [],
        "risks": [],
        "template_signals": [],
    }

    for attempt in range(MAX_FIX_RETRIES + 1):
        error_log = ""
        frontend_ready = False
        deployment_url = ""
        frontend_port = _get_free_port(3002)
        print(f"\n[runner] ── Attempt {attempt + 1}/{MAX_FIX_RETRIES + 1} for project '{project_id}' ──")

        # ── BACKEND ──────────────────────────────────────────────────────────
        if backend_dir and os.path.exists(backend_dir):
            backend_port = _get_free_port(8090)
            python_exe = "python3" if os.name != "nt" else "python"
            pip_exe    = "pip3"    if os.name != "nt" else "pip"

            # Install: use README install_cmd if available, else fall back to requirements.txt
            generation_progress = 60
            run_status_message = "Installing backend dependencies..."
            be_install = be_cfg.get("install_cmd", "").strip()
            req_file = os.path.join(backend_dir, "requirements.txt")
            if be_install:
                print(f"[runner] Backend install (from README): {be_install}")
                install_parts = be_install.split()
                if install_parts and install_parts[0] in ("pip", "pip3"):
                    install_parts[0] = pip_exe
                r = subprocess.run(
                    install_parts, cwd=backend_dir,
                    capture_output=True, text=True, timeout=300
                )
                if r.returncode != 0:
                    error_log += f"Backend install failed:\n{r.stderr}\n"
                    print(f"[runner] Backend install error:\n{r.stderr[:500]}")
            elif os.path.exists(req_file):
                print(f"[runner] pip install -r {req_file} (fallback)")
                r = subprocess.run(
                    [pip_exe, "install", "-r", req_file],
                    cwd=backend_dir, capture_output=True, text=True, timeout=300
                )
                if r.returncode != 0:
                    error_log += f"pip install failed:\n{r.stderr}\n"
                    print(f"[runner] pip install error:\n{r.stderr[:500]}")

            # Locate entry point: README first, then scan candidates
            entry = be_cfg.get("entry", "").strip() or None
            if not entry:
                for candidate in ["main.py", "app.py", "server.py", "api.py"]:
                    if os.path.exists(os.path.join(backend_dir, candidate)):
                        entry = candidate.replace(".py", "")
                        break

            if entry and not error_log:
                generation_progress = 70
                run_status_message = "Starting backend server..."
                if "backend" in processes:
                    try:
                        processes["backend"].terminate()
                    except Exception:
                        pass

                # Build start command: README start_cmd if provided, else uvicorn default
                be_start = be_cfg.get("start_cmd", "").strip()
                if be_start:
                    print(f"[runner] Backend start (from README): {be_start} --port {backend_port}")
                    start_parts = be_start.split()
                    if start_parts and start_parts[0] == "uvicorn":
                        start_parts = [python_exe, "-m", "uvicorn"] + start_parts[1:]
                    elif start_parts and start_parts[0] in ("python", "python3"):
                        start_parts[0] = python_exe
                    start_parts += ["--port", str(backend_port)]
                else:
                    print(f"[runner] Starting uvicorn {entry}:app on port {backend_port} (fallback)")
                    start_parts = [python_exe, "-m", "uvicorn", f"{entry}:app",
                                   "--host", "0.0.0.0", "--port", str(backend_port)]

                backend_proc = subprocess.Popen(
                    start_parts, cwd=backend_dir,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                time.sleep(5)
                if backend_proc.poll() is not None:
                    try:
                        _, stderr = backend_proc.communicate(timeout=3)
                    except Exception:
                        stderr = ""
                    error_log += f"Backend crashed on startup:\n{stderr}\n"
                    print(f"[runner] Backend crashed:\n{stderr[:500]}")
                else:
                    processes["backend"] = backend_proc
                    print(f"[runner] Backend running on port {backend_port}")
            elif entry is None:
                print("[runner] No backend entry point found")

        # ── FRONTEND ─────────────────────────────────────────────────────────
        if frontend_dir and os.path.exists(frontend_dir):
            try:
                npm_cmd = "npm.cmd" if os.name == "nt" else "npm"

                # ── Ensure package.json exists ────────────────────────────
                ensure_nextjs_typescript_bootstrap(frontend_dir)
                ensure_frontend_package_json(frontend_dir)
                package_json_path = os.path.join(frontend_dir, "package.json")
                if not os.path.exists(package_json_path):
                    error_log += "Frontend package.json missing after generation.\n"
                    print("[runner] package.json missing after generation")
                    continue
                if not os.path.exists(package_json_path):
                    print("[runner] package.json missing — creating default Next.js package.json")
                    default_pkg = {
                        "name": "generated-frontend", "version": "0.1.0", "private": True,
                        "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
                        "dependencies": {"next": "14.2.3", "react": "^18", "react-dom": "^18"},
                        "devDependencies": {
                            "@types/node": "^20", "@types/react": "^18",
                            "@types/react-dom": "^18",
                            "autoprefixer": "^10", "postcss": "^8",
                            "tailwindcss": "^3", "typescript": "^5"
                        }
                    }
                    with open(package_json_path, "w") as f:
                        json.dump(default_pkg, f, indent=2)

                # ── Install dependencies ───────────────────────────────────
                generation_progress = 75
                run_status_message = "Installing frontend dependencies (this may take a minute)..."
                fe_install = fe_cfg.get("install_cmd", "").strip()
                install_parts = fe_install.split() if fe_install else [npm_cmd, "install", "--legacy-peer-deps"]
                if install_parts[0] in ("npm", "npx"):
                    install_parts[0] = npm_cmd
                print(f"[runner] Frontend install: {' '.join(install_parts)}")
                r = subprocess.run(
                    install_parts, cwd=frontend_dir,
                    capture_output=True, text=True, timeout=600   # 10 min — first install can be slow
                )
                if r.returncode != 0:
                    raise subprocess.CalledProcessError(r.returncode, install_parts, stderr=r.stderr)

                generation_progress = 82
                run_status_message = "Building generated frontend..."
                fe_build = fe_cfg.get("build_cmd", "").strip()
                clear_next_build_artifacts(frontend_dir)
                build_ok, build_log = run_frontend_build(
                    frontend_dir=frontend_dir,
                    npm_cmd=npm_cmd,
                    build_cmd=fe_build if fe_build else None,
                )
                latest_build_log = build_log
                if not build_ok:
                    error_log += f"Frontend build failed:\n{build_log[:5000]}\n"
                    print(f"[runner] Frontend build failed:\n{build_log[:1000]}")
                    continue

                generation_progress = 88
                run_status_message = "Starting frontend server..."
                if "frontend" in processes:
                    terminate_process(processes["frontend"], "frontend")
                    processes.pop("frontend", None)

                # Start: use README start_cmd if available, else start_nextjs_dev
                fe_start = fe_cfg.get("start_cmd", "").strip()
                if fe_start:
                    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
                    with open(package_json_path, "r", encoding="utf-8") as f:
                        package_json = json.load(f)
                    scripts = package_json.get("scripts", {}) if isinstance(package_json, dict) else {}
                    if "start" in scripts:
                        start_parts = [npm_cmd, "run", "start", "--", f"--port={frontend_port}"]
                        print(f"[runner] Frontend start: npm run start -- --port {frontend_port}")
                    else:
                        print(f"[runner] Frontend start (from README): {fe_start} -- --port {frontend_port}")
                        start_parts = fe_start.split()
                        if start_parts and start_parts[0] in ("npm", "npx"):
                            start_parts[0] = npm_cmd
                        start_parts += ["--", f"--port={frontend_port}"]
                    fe_proc = subprocess.Popen(start_parts, cwd=frontend_dir)
                else:
                    fe_proc = start_nextjs_dev(frontend_dir, port=frontend_port)

                ready = wait_for_nextjs_ready(port=frontend_port, timeout=90)

                if ready:
                    processes["frontend"] = fe_proc
                    frontend_ready = True
                    deployment_url = f"http://localhost:{frontend_port}"
                    print(f"[runner] Frontend ready at {deployment_url}")
                else:
                    if fe_proc and fe_proc.poll() is not None:
                        try:
                            _, stderr = fe_proc.communicate(timeout=3)
                        except Exception:
                            stderr = ""
                        error_log += f"Frontend crashed on startup:\n{stderr}\n"
                        print(f"[runner] Frontend crashed:\n{stderr[:500]}")
                    else:
                        processes["frontend"] = fe_proc
                        deployment_url = f"http://localhost:{frontend_port}"
                        print("[runner] Frontend process running (port not ready yet)")

                if requirements_text.strip():
                    generation_progress = 92
                    run_status_message = "Reviewing requirement coverage..."
                    preview_snapshot = fetch_preview_snapshot(deployment_url) if deployment_url else ""
                    latest_acceptance_report = evaluate_generated_project_acceptance(
                        requirements=requirements_text,
                        project_path=project_path,
                        build_log=build_log,
                        preview_snapshot=preview_snapshot,
                    )
                    print(
                        f"[acceptance] passed={latest_acceptance_report.get('passed')} "
                        f"missing={len(latest_acceptance_report.get('missing', []))} "
                        f"template_signals={len(latest_acceptance_report.get('template_signals', []))}"
                    )
                    if not latest_acceptance_report.get("passed"):
                        missing_items = latest_acceptance_report.get("missing", [])
                        template_signals = latest_acceptance_report.get("template_signals", [])
                        risks = latest_acceptance_report.get("risks", [])
                        error_log += "Acceptance check failed:\n"
                        if latest_acceptance_report.get("summary"):
                            error_log += f"Summary: {latest_acceptance_report['summary']}\n"
                        if missing_items:
                            error_log += "Missing requirements:\n- " + "\n- ".join(missing_items[:12]) + "\n"
                        if template_signals:
                            error_log += "Template signals:\n- " + "\n- ".join(template_signals[:8]) + "\n"
                        if risks:
                            error_log += "Acceptance risks:\n- " + "\n- ".join(risks[:8]) + "\n"
                        if attempt < MAX_FIX_RETRIES:
                            terminate_process(fe_proc, "frontend")
                            processes.pop("frontend", None)
                            frontend_ready = False
                            deployment_url = ""

            except subprocess.CalledProcessError as e:
                err = getattr(e, "stderr", "") or str(e)
                error_log += f"npm install failed:\n{err}\n"
                print(f"[runner] npm install error:\n{str(err)[:500]}")
            except Exception as e:
                error_log += f"Frontend setup error:\n{str(e)}\n"
                print(f"[runner] Frontend setup error: {e}")

        # ── RETRY WITH OPENCODE OR FINISH ────────────────────────────────────
        if error_log:
            print(f"[runner] Errors on attempt {attempt + 1}:\n{error_log[:1000]}")
            if attempt < MAX_FIX_RETRIES:
                cleanup_runtime_processes(processes)
                generation_progress = 45
                run_status_message = f"Errors found — asking OpenCode to fix (attempt {attempt + 1}/{MAX_FIX_RETRIES})..."
                _run_opencode_fix(project_path, error_log, requirements_text=requirements_text)
                continue

        break

    if error_log and not deployment_url:
        cleanup_runtime_processes(processes)
        frontend_ready = False
        deployment_url = ""

    preview_ready = bool(deployment_url) and wait_for_deployment_ready(deployment_url, timeout=20)

    acceptance_ok = bool(latest_acceptance_report.get("passed"))

    if error_log:
        if deployment_url:
            run_status_message = "Project preview is running, but requirement coverage failed."
        else:
            run_status_message = "Project started with errors ? check logs."
    else:
        generation_progress = 100
        if not acceptance_ok:
            run_status_message = "Project builds, but requirement coverage still needs review."
        else:
            run_status_message = "Project is running!" if preview_ready else "Project started. Preview is warming up..."

    return {
        "processes": processes,
        "frontend_ready": frontend_ready,
        "preview_ready": preview_ready,
        "deployment_url": deployment_url,
        "error_log": error_log,
        "acceptance_report": latest_acceptance_report,
        "acceptance_passed": acceptance_ok,
        "build_log": latest_build_log,
    }


def apply_runtime_state_from_startup(startup_result: dict) -> None:
    global current_state
    if startup_result.get("startup_skipped"):
        current_state = DiscussionState.IMPLEMENTATION
        return
    if startup_result.get("processes"):
        current_state = DiscussionState.TESTING
    if startup_result.get("preview_ready") and startup_result.get("acceptance_passed"):
        current_state = DiscussionState.DEPLOYMENT_MAINTENANCE


async def _proactive_advisor_background(reqs: str, notebook: str) -> None:
    """
    Run the proactive advisor in a background thread and replace advisor_suggestions
    with a fresh list. Items already discussed will have been excluded by the LLM.
    Triggered automatically every time the notebook summary is refreshed.
    """
    global advisor_suggestions
    try:
        loop = asyncio.get_event_loop()
        suggestions = await loop.run_in_executor(None, proactive_advisor, reqs, notebook)
        advisor_suggestions = suggestions  # full replacement — discussed items are now absent
        print(f"[advisor] Feedback tab refreshed ({len(advisor_suggestions)} suggestions remaining)")
    except Exception as e:
        print(f"[advisor background] Error: {e}")


async def _evaluation_background(meeting_id: str, transcription: str) -> None:
    """
    Run requirement evaluation in a threadpool so the SSE stream stays live
    while the LLM call is in progress.  Sets evaluation_in_progress = False when done
    and always writes the latest feedback (clearing it if requirements are complete).
    """
    global evaluation_in_progress, current_feedback_required, current_feedback, current_state, requirements, epics, mind_map
    try:
        loop = asyncio.get_event_loop()

        # Get latest requirements from the meeting service
        reqs = await loop.run_in_executor(None, get_requirements, meeting_id)
        requirements = reqs

        # Run state + feedback evaluation
        result = await loop.run_in_executor(
            None,
            evaluate_and_maybe_update_state,
            current_state, reqs, notebook_summary, transcription,
        )
        new_state, generate_code, feedback_required, feedback = result

        if new_state != current_state:
            current_state = new_state
            print(f"[eval] State updated to: {current_state}")

        # Always overwrite so the UI shows the latest result
        current_feedback_required = feedback_required
        current_feedback = feedback if feedback_required else ""

        if feedback_required:
            print(f"[eval] Feedback generated: {feedback[:200]}")
        else:
            print("[eval] Requirements look complete — no feedback needed.")

        # Generate epics and mind map from the current requirements
        new_epics, new_mind_map = await loop.run_in_executor(
            None, generate_epics_and_mindmap, reqs
        )
        if new_epics:
            epics = new_epics
            mind_map = new_mind_map
            print(f"[epics] Epics and mind map updated ({len(epics)} epics)")

    except Exception as e:
        print(f"[eval background] Error: {e}")
    finally:
        evaluation_in_progress = False


async def _simulate_opencode_progress() -> None:
    """
    Slowly increment generation_progress from its current value toward 48 while
    OpenCode is running.  Stops naturally once run_generated_project takes over (≥50).
    Increment: +1 % every 5 seconds  →  covers ~3.5 min of OpenCode generation.
    """
    global generation_progress
    while generation_progress < 48:
        await asyncio.sleep(5)
        generation_progress = min(48, generation_progress + 1)


async def _codegen_background(requirements: str, proj_id: str) -> None:
    """
    Run web code generation + project startup in a threadpool executor so the
    SSE stream continues to emit live status updates while the blocking work runs.
    """
    global code_generation_running, run_status_message, generation_progress, current_state, acceptance_report, acceptance_passed
    sim_task = None
    try:
        current_state = DiscussionState.IMPLEMENTATION
        generation_progress = 5
        run_status_message = "Generating code with OpenCode..."
        sim_task = asyncio.create_task(_simulate_opencode_progress())
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, trigger_web_code_generation, requirements, proj_id, FAST_GENERATION_MODE)
        acceptance_report = result.get("acceptance_report", {})
        acceptance_passed = result.get("acceptance_passed", False)
    except Exception as e:
        run_status_message = f"Code generation error: {str(e)[:120]}"
        print(f"[codegen background] Error: {e}")
    finally:
        if sim_task and not sim_task.done():
            sim_task.cancel()
        code_generation_running = False
        generation_progress = 0


# -------------------------------------------------------------------
# Flask Endpoints
# -------------------------------------------------------------------

@router.post("/meeting/{meeting_id}/transcription")
async def receive_transcription(meeting_id: str, request: Request):
    """
    Endpoint to receive a new transcription.
    1. Stores the transcription.
    2. Polls the LLM for an immediate action decision.
    3. If more than 5 transcriptions exist, updates the notebook summary.
    4. If immediate action is requested, evaluates whether to update state and/or trigger code generation.
    """
    # global transcriptions, notebook_summary, current_state, code_generation_running, requirements, deployment_url
    global transcriptions, notebook_summary, current_state, code_generation_running, requirements, deployment_url, current_feedback_required, current_feedback, project_id, run_status_message, evaluation_in_progress, active_popup, popup_request_id, acceptance_report, acceptance_passed

    new_state = current_state
    generate_code = False

    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from e

    transcription = data.get("transcription", "").strip()
    if not transcription:
        raise HTTPException(status_code=400, detail="No transcription provided.")

    # Add transcription to our in-memory list
    transcriptions.append(transcription)

    # ── Popup open / close request (instant keyword match, no LLM cost) ──────
    popup_intent = _detect_popup_request(transcription)
    if popup_intent:
        if popup_intent == "close":
            active_popup = ""
        else:
            active_popup = popup_intent
            popup_request_id += 1
        return JSONResponse(content={"status": "OK", "message": f"Popup: {popup_intent}"})

    # ── Review / evaluate request ────────────────────────────────────────────
    # Checked FIRST, before poll_immediate_action, so the LLM filter cannot
    # accidentally drop a "check our requirements" request.
    if _is_review_request(transcription):
        if evaluation_in_progress:
            # Already evaluating — silently drop the duplicate
            return JSONResponse(content={"status": "OK", "message": "Evaluation already in progress."})
        evaluation_in_progress = True
        project_id = f"project_{meeting_id}"
        asyncio.create_task(_evaluation_background(meeting_id, transcription))
        return JSONResponse(content={"status": "OK", "message": "Requirement evaluation started."})

    # ── Drop transcriptions while evaluation is running ──────────────────────
    if evaluation_in_progress:
        return JSONResponse(content={"status": "OK", "message": "Evaluation in progress — transcription stored."})

    # ── Normal transcription processing ──────────────────────────────────────
    immediate_action = poll_immediate_action(current_state, transcription)

    # Update notebook summary every 5 transcriptions, then run proactive advisor
    if len(transcriptions) % 5 == 0:
        notebook_summary = update_notebook_summary(notebook_summary, transcriptions)
        transcriptions = transcriptions[-5:]  # Keep only the last 5 transcriptions
        # Auto-trigger proactive advisor whenever the summary refreshes and we have requirements
        if requirements and not evaluation_in_progress and not code_generation_running:
            asyncio.create_task(_proactive_advisor_background(requirements, notebook_summary))

    # Keep the manager-side requirements snapshot in sync with the requirements service
    # so the UI's SSE stream reflects updates even when no immediate action is triggered.
    requirements = sync_requirements(meeting_id)

    if not immediate_action:
        return JSONResponse(content={"status": "OK", "message": "Transcription stored, no further action."})

    project_id = f"project_{meeting_id}"

    # Normal immediate action: evaluate state and check for code generation
    requirements = sync_requirements(meeting_id)

    new_state, generate_code, feedback_required, feedback = evaluate_and_maybe_update_state(
        current_state, requirements, notebook_summary, transcription
    )

    if new_state != current_state:
        current_state = new_state
        print(f"Updated discussion state to: {current_state}")

    if feedback_required:
        current_feedback_required = True
        current_feedback = feedback
        print(f"LLM feedback: {feedback}")
    if generate_code:
        if not code_generation_running:
            acceptance_report = {}
            acceptance_passed = False
            code_generation_running = True
            asyncio.create_task(_codegen_background(requirements, project_id))
            return JSONResponse(content={"status": "OK", "message": "Code generation started."})
        else:
            return JSONResponse(content={"status": "OK", "message": "Code generation already running."})

    return JSONResponse(content={"status": "OK", "message": "Transcription processed."})

@router.get("/status")
async def get_status():
    """
    Lightweight snapshot of the current generation state.
    Used by the UI as a polling fallback when SSE is unavailable.
    """
    return JSONResponse(content={
        "code_generation_running": code_generation_running,
        "run_status_message":      run_status_message,
        "generation_progress":     generation_progress,
        "deployment_url":          deployment_url,
        "current_state":           current_state.value,
        "project_id":              project_id,
        "acceptance_report":       acceptance_report,
        "acceptance_passed":       acceptance_passed,
    })


@router.get("/sse", status_code=200)
async def sse_stream():
    """
    SSE stream endpoint to continuously send the current state.
    """

    async def event_stream():
        while True:
            data = {
                "transcriptions": transcriptions,
                "notebook_summary": notebook_summary,
                "current_state": current_state.value,
                "code_generation_running": code_generation_running,
                "requirements": requirements,
                "deployment_url": deployment_url,
                "project_id": project_id,
                "current_feedback_required": current_feedback_required,
                "current_feedback": current_feedback,
                "run_status_message": run_status_message,
                "evaluation_in_progress": evaluation_in_progress,
                "generation_progress": generation_progress,
                "active_popup": active_popup,
                "popup_request_id": popup_request_id,
                "epics": epics,
                "mind_map": mind_map,
                "advisor_suggestions": advisor_suggestions,
                "acceptance_report": acceptance_report,
                "acceptance_passed": acceptance_passed,
            }
            # print("SSE Sent:", data)
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.get("/sse/codegen/{project_id}")
async def sse_codegen(project_id: str):
    """
    Forward codegen progress to frontend
    """
    if project_id not in codegen_sse_connections:
        codegen_sse_connections[project_id] = asyncio.Queue()
    queue = codegen_sse_connections[project_id]

    async def event_generator():
        while True:
            data = await queue.get()
            yield f"data: {data}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/stop-discussion")
async def stop_discussion(request: Request):
    global current_state
    current_state = DiscussionState.IMPLEMENTATION
    try:
        data = await request.json()
        project_id = data.get("project_id")
        requirements = data.get("requirements")

        if not project_id or not requirements:
            raise HTTPException(status_code=400, detail="Missing project_id or requirements")


        
        response = requests.post(
            f"{WEB_CODE_GENERATION_SERVICE_URL}/generate_project",
            json={"project_id": project_id, "requirements": requirements, "fast_mode": FAST_GENERATION_MODE},
            timeout=36000
        )
        response.raise_for_status()  # <-- Raises HTTPError for non-200

        # After generation, start the project and advance the lifecycle automatically.
        startup_result = run_generated_project(project_id, requirements_text=requirements, fast_mode=FAST_GENERATION_MODE)
        apply_runtime_state_from_startup(startup_result)
        print(f"Project {project_id} started with processes:", startup_result["processes"].keys())
        # for name, proc in processes.items():
        #     print(f"[{name.upper()}] log stream starting...")
        #         # You can read lines asynchronously in a thread or async loop
        #     # Example synchronous for debugging:
        #     for line in proc.stdout:
        #         print(f"[{name.upper()}]", line.strip())

        payload = response.json()
        payload["fast_mode"] = FAST_GENERATION_MODE
        payload["frontend_url"] = startup_result.get("deployment_url", "")
        payload["acceptance_report"] = startup_result.get("acceptance_report", {})
        payload["acceptance_passed"] = startup_result.get("acceptance_passed", False)
        payload["message"] = startup_result.get("message", payload.get("message", "Project generated"))
        return payload
    except Exception as e:
        import traceback
        print("Error in /stop-discussion:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
    

@router.get("/get_project/{project_id}")
async def get_project(project_id: str):
    project_path = os.path.join(PROJECTS_DIR, project_id)

    if not os.path.exists(project_path):
        return {"error": "Project not found"}

    # ---------------------------
    # Build Directory Tree
    # ---------------------------
    directory_tree = {}

    for root, dirs, files in os.walk(project_path):
        rel_root = os.path.relpath(root, project_path)

        if rel_root == ".":
            rel_root = ""  # top-level

        directory_tree[rel_root] = {
            "dirs": dirs,
            "files": files
        }

    # ---------------------------
    # Read file contents directly from the filesystem
    # ---------------------------
    all_files = {}

    for root, dirs, files in os.walk(project_path):
        for filename in files:
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, project_path)

            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except:
                content = ""

            all_files[rel_path] = content

    return {
        "project_id": project_id,
        "directory_tree": directory_tree,
        "files": all_files
    }


from fastapi.responses import FileResponse
import shutil

@router.get("/download_project/{project_id}")
async def download_project(project_id: str):
    project_path = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.exists(project_path):
        raise HTTPException(status_code=404, detail="Project not found")

    # Create a temporary zip file
    zip_path = os.path.join(PROJECTS_DIR, f"{project_id}.zip")
    shutil.make_archive(base_name=zip_path.replace(".zip",""), format="zip", root_dir=project_path)

    # Return the zip file as a downloadable response
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"{project_id}.zip"
    )


@router.post("/reset")
async def reset_session():
    """Clear all in-memory session data so the UI starts fresh."""
    global current_state, transcriptions, requirements, notebook_summary
    global code_generation_running, deployment_url, project_id
    global current_feedback, current_feedback_required, run_status_message
    global evaluation_in_progress, generation_progress, active_popup, popup_request_id
    global epics, mind_map, advisor_suggestions, acceptance_report, acceptance_passed

    current_state             = DiscussionState.CONCEPTUALIZATION
    transcriptions            = []
    requirements              = ""
    notebook_summary          = ""
    code_generation_running   = False
    deployment_url            = ""
    project_id                = ""
    current_feedback          = ""
    current_feedback_required = False
    run_status_message        = ""
    evaluation_in_progress    = False
    generation_progress       = 0
    active_popup              = ""
    popup_request_id          = 0
    epics                     = []
    mind_map                  = {}
    advisor_suggestions       = []
    acceptance_report         = {}
    acceptance_passed         = False

    return JSONResponse(content={"status": "ok", "message": "Session reset."})


app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    print(f"Starting Manager Service on port {SERVICE_PORT}")
    # workers=1 is required: the service uses in-process global state (code_generation_running,
    # generation_progress, etc.) that would be invisible across multiple worker processes.
    uvicorn.run("manager_service:app", host="0.0.0.0", port=int(SERVICE_PORT), workers=1, reload=False)
