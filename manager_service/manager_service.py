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

PROJECTS_DIR = "projects"
MAX_FIX_RETRIES = 2           # How many times OpenCode is asked to fix errors

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
# CODEGEN_SERVICE_URL = os.environ.get("CODE_GENERATION_SERVICE_URL", "http://localhost:8083")
CODE_GENERATION_SERVICE_URL = os.environ.get("CODE_GENERATION_SERVICE_URL")
WEB_CODE_GENERATION_SERVICE_URL = os.environ.get("WEB_CODE_GENERATION_SERVICE_URL")

if not WEB_CODE_GENERATION_SERVICE_URL:
    WEB_CODE_GENERATION_SERVICE_URL = "http://localhost:8084/api/v0"   # safe fallback

OPENCODE_MODEL = os.environ.get("OPENCODE_MODEL", "openai/gpt-4o")

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


def trigger_code_generation(requirements: str):
    """
    Call the external code generation service. This call is expected to have a very long timeout.
    """
    try:
        requirements_formatted = format_requirements(requirements)
        payload = {
            "prompt": requirements_formatted,
        }
        full_url = CODE_GENERATION_SERVICE_URL + "/prompt"
        response = requests.post(full_url, json=payload, timeout=36000)
        if response.status_code == 200:
            print("Code generation triggered successfully.")
            return response.json()
        else:
            print("Code generation service error, status:", response.status_code)
            return {}
    except Exception as e:
        print("Error triggering code generation:", e)
        return {}

def trigger_web_code_generation(requirements: str, project_id: str):
    try:
        # requirements = """
        #                 - Develop a web-based dentist appointment scheduling system.
        #                 - Create a basic dentist appointment form where patients can select a date and then select a time.
        #                 - Allow appointment scheduling from 9 a.m. to 5 p.m.
        #                 - Include a dummy dentist list that can support at least 10 dentists and can be updated later with real dentist information.
        #                 - Include a submit button on the appointment form.
        #                 - Include a reset button on the appointment form that resets the form after clicking.
        #                 - Implement a color scheme for the appointment scheduling system that includes a sky color.
        #                 """

        if not project_id or not requirements:
            raise HTTPException(status_code=400, detail="Missing project_id or requirements")

        structure = f"""
        - The frontend or UI part top/main folder/directory name "frontend".
        - The beckend or server part top/main folder/directory name "backend".

        """

        
        response = requests.post(
            f"{WEB_CODE_GENERATION_SERVICE_URL}/generate_project",
            json={"project_id": project_id, "requirements": requirements+structure},
            timeout=36000
        )
        response.raise_for_status()  # <-- Raises HTTPError for non-200

        # After generation, start the project
        # current_state = "Testing"
        # current_state = DiscussionState.TESTING
        startup_result = run_generated_project(project_id)
        apply_runtime_state_from_startup(startup_result)
        print(f"Project {project_id} started with processes:", startup_result["processes"].keys())
        # for name, proc in processes.items():
        #     print(f"[{name.upper()}] log stream starting...")
        #         # You can read lines asynchronously in a thread or async loop
        #     # Example synchronous for debugging:
        #     for line in proc.stdout:
        #         print(f"[{name.upper()}]", line.strip())

        # return response.json()
        return {"status": "OK", "message": "Project generated", "project_id": project_id, "frontend_url": f"http://localhost:3002"}
        # return JSONResponse(content={"status": "OK", "message": "Project generated", "project_id": project_id, "frontend_url": f"http://localhost:3001"})
    except Exception as e:
        import traceback
        print("Error in /generation:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
# async def trigger_code_generation(requirements: str, project_id: str):
#     """
#     Call codegen service and stream SSE progress
#     """
#     formatted = format_requirements(requirements)
#     payload = {"project_id": project_id, "requirements": formatted}
#     async with aiohttp.ClientSession() as session:
#         async with session.post(f"{WEB_CODE_GENERATION_SERVICE_URL}/generate_project", json=payload, timeout=36000) as resp:
#             if resp.status != 200:
#                 print("Codegen service error", resp.status)
#                 return {}
#         sse_url = f"{CODE_GENERATION_SERVICE_URL}/sse/{project_id}"
#         async with session.get(sse_url) as sse_resp:
#             async for line in sse_resp.content:
#                 line_str = line.decode("utf-8").strip()
#                 if line_str.startswith("data:"):
#                     data_json = json.loads(line_str[5:])
#                     print(f"[CodeGen Progress] {data_json['progress']}/{data_json['total']}: {data_json['message']}")
#     # Dummy deployment URL
#     return {"frontend_url": f"http://localhost:8000/projects/{project_id}/frontend"}



# async def forward_codegen_progress(project_id: str):
#     """
#     Forward SSE events from codegen_service to manager SSE clients
#     """
#     import aiohttp

#     async with aiohttp.ClientSession() as session:
#         url = f"{CODE_GENERATION_SERVICE_URL}/sse/{project_id}"
#         async with session.get(url) as resp:
#             async for line in resp.content:
#                 if line:
#                     # Send to all manager SSE clients
#                     if project_id in codegen_sse_connections:
#                         await codegen_sse_connections[project_id].put(line.decode())


import socket
import sys

def is_port_free(port: int) -> bool:
    """Check if the given port is free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) != 0
    
def npm_install_if_needed(ui_dir):
    node_modules = os.path.join(ui_dir, "node_modules")
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    if not os.path.exists(node_modules):
        package_json = os.path.join(ui_dir, "package.json")

        if os.path.exists(package_json):
            with open(package_json, "r") as f:
                pkg = json.load(f)
            def version_exists(pkg_name, version):
                try:
                    subprocess.check_output([
                        "npm", "view", f"{pkg_name}@{version}", "version"
                    ])
                    return True
                except subprocess.CalledProcessError:
                    return False

            changed = False
            # Check deps
            for section in ["dependencies", "devDependencies"]:
                if section not in pkg:
                    continue

                for pkg_name, version in list(pkg[section].items()):
                    # Remove ^ or ~
                    clean_version = version.replace("^", "").replace("~", "")

                    if not version_exists(pkg_name, clean_version):
                        print(f"⚠️ Invalid version for {pkg_name}: {version} → fixing…")

                        # Get latest version
                        latest = subprocess.check_output(
                            ["npm", "view", pkg_name, "version"],
                            text=True
                        ).strip()

                        pkg[section][pkg_name] = f"^{latest}"
                        changed = True

            # Save patched package.json
            if changed:
                print("🛠 Writing fixed package.json…")
                with open(package_json, "w") as f:
                    json.dump(pkg, f, indent=2)
            print("package.json found — installing based on project dependencies...")
            subprocess.check_call([npm_cmd, "install", "--legacy-peer-deps"], cwd=ui_dir)
        else:
            print("Running 'npm install' in meeting project (first time setup)...")
            subprocess.check_call([npm_cmd, "install", "--legacy-peer-deps", "react@18.2.0", "react-dom@18.2.0", "typescript@5.2.2"], cwd=ui_dir)
    else:
        print("'node_modules' already exists, skipping 'npm install'.")


def run_frontend(ui_dir, npm_cmd="npm"):
    try:
        # Try: npm run dev
        proc = subprocess.Popen(
            [npm_cmd, "run", "dev", "--", "--port", "3002"],
            cwd=ui_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        stdout, stderr = proc.communicate(timeout=10)

        if proc.returncode != 0:
            raise Exception("dev failed")

        print("Running with npm run dev")
        return proc

    except Exception:
        print("Falling back to npm start...")

        proc = subprocess.Popen(
            [npm_cmd, "start"],
            cwd=ui_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        return proc
    

# def start_nextjs_dev(ui_dir):
#     print("Starting Next.js dev server in meeting project...")
#     npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
#     # proc = subprocess.Popen([npm_cmd, "run", "dev"], cwd=ui_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#     # proc = subprocess.Popen([npm_cmd, "run", "dev", "--", "--port", "3002"], cwd=ui_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#     # proc = run_frontend(ui_dir, npm_cmd=npm_cmd)
#     package_json = os.path.join(ui_dir, "package.json")

#     with open(package_json) as f:
#         scripts = json.load(f).get("scripts", {})

#     if "dev" in scripts:
#         cmd = ["npm", "run", "dev", "--", "--port", "3002"]
#     else:
#         cmd = ["npm", "start"]

#     proc = subprocess.Popen(cmd, cwd=ui_dir)
#     return proc

# def start_nextjs_dev(ui_dir):
#     print("Installing Next.js and React dependencies if missing...")
#     npm_cmd = "npm.cmd" if os.name == "nt" else "npm"

#     # Step 1: Install next, react, react-dom
#     subprocess.run([npm_cmd, "install", "next", "react", "react-dom"], cwd=ui_dir, check=True)

#     # Step 2: Read package.json scripts
#     package_json = os.path.join(ui_dir, "package.json")
#     with open(package_json, "r") as f:
#         scripts = json.load(f).get("scripts", {})

#     # Step 3: Decide which command to run
#     if "dev" in scripts:
#         cmd = [npm_cmd, "run", "dev", "--", "--port", "3002"]
#     else:
#         cmd = [npm_cmd, "start"]

#     # Step 4: Start the Next.js dev server
#     print("Starting Next.js dev server in meeting project...")
#     proc = subprocess.Popen(cmd, cwd=ui_dir)
#     return proc

# def start_nextjs_dev(ui_dir):
#     npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
#     package_json_path = os.path.join(ui_dir, "package.json")

#     # Step 1: Install Next.js and React dependencies
#     print("Installing Next.js and React dependencies if missing...")
#     subprocess.run([npm_cmd, "install", "next", "react", "react-dom"], cwd=ui_dir, check=True)

#     # Step 2: Load package.json
#     if not os.path.exists(package_json_path):
#         print("Error: package.json not found in", ui_dir)
#         return None

#     with open(package_json_path, "r") as f:
#         package_data = json.load(f)

#     scripts = package_data.get("scripts", {})

#     # Step 3: Add missing scripts if needed
#     updated = False
#     if "dev" not in scripts:
#         print("Adding missing 'dev' script...")
#         scripts["dev"] = "next dev"
#         updated = True

#     if "start" not in scripts:
#         print("Adding missing 'start' script...")
#         scripts["start"] = "next start"
#         updated = True

#     if updated:
#         package_data["scripts"] = scripts
#         with open(package_json_path, "w") as f:
#             json.dump(package_data, f, indent=2)
#         print("package.json updated with missing scripts.")

#     # Step 4: Decide command
#     # if "dev" in scripts:
#     #     cmd = [npm_cmd, "run", "dev", "--", "--port", "3002"]
#     # else:
#     #     cmd = [npm_cmd, "start"]
#     cmd = [npm_cmd, "start", "--", "--port", "3002"]
#     # Step 5: Start Next.js dev server
#     print("Starting Next.js dev server in meeting project...")
#     proc = subprocess.Popen(cmd, cwd=ui_dir)
#     return proc

def start_nextjs_dev(ui_dir, port=3002):
    """
    Starts the Next.js dev server for the given project directory.
    Steps:
    1. Creates a Python virtual environment for isolation.
    2. Installs Node.js dependencies (next, react, react-dom, plus any missing).
    3. Ensures 'dev' and 'start' scripts exist in package.json.
    4. Runs the Next.js dev server.
    """
    # Step 0: Ensure ui_dir exists
    if not os.path.exists(ui_dir):
        print(f"Error: directory {ui_dir} does not exist.")
        return None

    # # Step 1: Create a Python virtual environment if not exists
    # venv_dir = os.path.join(ui_dir, "venv")
    # if not os.path.exists(venv_dir):
    #     print("Creating Python virtual environment...")
    #     venv.create(venv_dir, with_pip=True)
    # else:
    #     print("Python virtual environment already exists.")

    # # Step 2: Activate venv (platform dependent)
    # if os.name == "nt":
    #     python_exe = os.path.join(venv_dir, "Scripts", "python.exe")
    #     npm_cmd = "npm.cmd"
    # else:
    #     python_exe = os.path.join(venv_dir, "bin", "python")
    #     npm_cmd = "npm"

    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"

    # Step 3: Ensure package.json exists before npm install
    package_json_path = os.path.join(ui_dir, "package.json")
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

    # Install Node.js dependencies
    print("Installing Next.js, React, ReactDOM, and project dependencies...")
    subprocess.run([npm_cmd, "install", "--legacy-peer-deps"], cwd=ui_dir, check=True)

    with open(package_json_path, "r") as f:
        package_data = json.load(f)

    # Step 4: Ensure dev/start scripts exist
    scripts = package_data.get("scripts", {})
    updated = False
    if "dev" not in scripts:
        print("Adding missing 'dev' script...")
        scripts["dev"] = "next dev"
        updated = True
    if "start" not in scripts:
        print("Adding missing 'start' script...")
        scripts["start"] = "next start"
        updated = True
    if updated:
        package_data["scripts"] = scripts
        with open(package_json_path, "w") as f:
            json.dump(package_data, f, indent=2)
        print("package.json updated with missing scripts.")

    # Step 5: Start Next.js dev server
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


def normalize_nextjs_typescript_setup(frontend_dir: str) -> None:
    """Ensure generated Next.js apps have a compatible TS bootstrap on Windows."""
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

    should_write_tsconfig = not os.path.exists(tsconfig_path)
    if os.path.exists(tsconfig_path):
        try:
            with open(tsconfig_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("extends") == "next/core-web-vitals":
                should_write_tsconfig = True
        except Exception:
            should_write_tsconfig = True

    if should_write_tsconfig:
        with open(tsconfig_path, "w", encoding="utf-8") as f:
            json.dump(normalized_tsconfig, f, indent=2)
            f.write("\n")
        print("[runner] Normalized frontend tsconfig.json for Next.js")

    if not os.path.exists(next_env_path):
        with open(next_env_path, "w", encoding="utf-8") as f:
            f.write('/// <reference types="next" />\n')
            f.write('/// <reference types="next/image-types/global" />\n\n')
            f.write('// This file should not be edited\n')
        print("[runner] Created missing next-env.d.ts")

def _venv_executables(project_id: str):
    """Return (python_exe, pip_exe) paths inside the project's venv."""
    base = os.path.join(PROJECTS_DIR, project_id, "venv")
    if os.name == "nt":
        return (os.path.join(base, "Scripts", "python.exe"),
                os.path.join(base, "Scripts", "pip.exe"))
    return (os.path.join(base, "bin", "python"),
            os.path.join(base, "bin", "pip"))


def _run_opencode_fix(project_path: str, error_log: str) -> bool:
    """Ask OpenCode to fix errors in the project. Returns True if successful."""
    fix_prompt = (
        "The following software project failed to start. "
        "Fix all issues so it runs correctly without errors. "
        "Do not ask clarifying questions — fix the code now.\n\n"
        f"Error log:\n{error_log[:3000]}"
    )
    cmd = ["opencode", "run", "--model", OPENCODE_MODEL, "--format", "json", fix_prompt]
    env = {**os.environ}
    env["OPENCODE_PERMISSION"] = json.dumps({"write": "allow", "edit": "allow", "bash": "allow"})
    print(f"[runner] Running OpenCode fix in {project_path}")
    try:
        result = subprocess.run(
            cmd, cwd=project_path, capture_output=True, text=True,
            timeout=600, env=env
        )
        print(f"[runner] OpenCode fix exited {result.returncode}")
        return result.returncode == 0
    except Exception as e:
        print(f"[runner] OpenCode fix error: {e}")
        return False

def run_generated_project(project_id: str) -> dict:
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

    for attempt in range(MAX_FIX_RETRIES + 1):
        error_log = ""
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
                normalize_nextjs_typescript_setup(frontend_dir)
                package_json_path = os.path.join(frontend_dir, "package.json")
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

                generation_progress = 88
                run_status_message = "Starting frontend server..."
                if "frontend" in processes:
                    try:
                        processes["frontend"].terminate()
                    except Exception:
                        pass

                # Start: use README start_cmd if available, else start_nextjs_dev
                fe_start = fe_cfg.get("start_cmd", "").strip()
                if fe_start:
                    print(f"[runner] Frontend start (from README): {fe_start} -- --port {frontend_port}")
                    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
                    start_parts = fe_start.split()
                    if start_parts and start_parts[0] in ("npm", "npx"):
                        start_parts[0] = npm_cmd
                    # Inject port: append -- --port N for npm run dev/start
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
                generation_progress = 45
                run_status_message = f"Errors found — asking OpenCode to fix (attempt {attempt + 1}/{MAX_FIX_RETRIES})..."
                _run_opencode_fix(project_path, error_log)
                continue

        break

    preview_ready = bool(deployment_url) and wait_for_deployment_ready(deployment_url, timeout=20)

    if error_log:
        run_status_message = "Project started with errors ? check logs."
    else:
        generation_progress = 100
        run_status_message = "Project is running!" if preview_ready else "Project started. Preview is warming up..."

    return {
        "processes": processes,
        "frontend_ready": frontend_ready,
        "preview_ready": preview_ready,
        "deployment_url": deployment_url,
        "error_log": error_log,
    }


def apply_runtime_state_from_startup(startup_result: dict) -> None:
    global current_state
    if startup_result.get("processes"):
        current_state = DiscussionState.TESTING
    if startup_result.get("preview_ready"):
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
    global code_generation_running, run_status_message, generation_progress, current_state
    sim_task = None
    try:
        current_state = DiscussionState.IMPLEMENTATION
        generation_progress = 5
        run_status_message = "Generating code with OpenCode..."
        sim_task = asyncio.create_task(_simulate_opencode_progress())
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, trigger_web_code_generation, requirements, proj_id)
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
    global transcriptions, notebook_summary, current_state, code_generation_running, requirements, deployment_url, current_feedback_required, current_feedback, project_id, run_status_message, evaluation_in_progress, active_popup, popup_request_id

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
    # data = await request.json()
    # project_id = data.get("project_id")
    # requirements = data.get("requirements")

    # if not project_id or not requirements:
    #     raise HTTPException(status_code=400, detail="Missing project_id or requirements")

    # # Call codegen_service to generate project
    # response = requests.post(f"{CODE_GENERATION_SERVICE_URL}/generate_project", json={
    #     "project_id": project_id,
    #     "requirements": requirements
    # }, timeout=36000)  # long timeout for code generation

    # return response.json()
    current_state = DiscussionState.IMPLEMENTATION
    try:
        data = await request.json()
        project_id = data.get("project_id")
        requirements = data.get("requirements")
        # requirements = """
        #                 - Develop a web-based dentist appointment scheduling system.
        #                 - Create a basic dentist appointment form where patients can select a date and then select a time.
        #                 - Allow appointment scheduling from 9 a.m. to 5 p.m.
        #                 - Include a dummy dentist list that can support at least 10 dentists and can be updated later with real dentist information.
        #                 - Include a submit button on the appointment form.
        #                 - Include a reset button on the appointment form that resets the form after clicking.
        #                 - Implement a color scheme for the appointment scheduling system that includes a sky color.
        #                 """

        if not project_id or not requirements:
            raise HTTPException(status_code=400, detail="Missing project_id or requirements")


        
        response = requests.post(
            f"{WEB_CODE_GENERATION_SERVICE_URL}/generate_project",
            json={"project_id": project_id, "requirements": requirements},
            timeout=36000
        )
        response.raise_for_status()  # <-- Raises HTTPError for non-200

        # After generation, start the project and advance the lifecycle automatically.
        startup_result = run_generated_project(project_id)
        apply_runtime_state_from_startup(startup_result)
        print(f"Project {project_id} started with processes:", startup_result["processes"].keys())
        # for name, proc in processes.items():
        #     print(f"[{name.upper()}] log stream starting...")
        #         # You can read lines asynchronously in a thread or async loop
        #     # Example synchronous for debugging:
        #     for line in proc.stdout:
        #         print(f"[{name.upper()}]", line.strip())

        return response.json()
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
    global epics, mind_map, advisor_suggestions

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
