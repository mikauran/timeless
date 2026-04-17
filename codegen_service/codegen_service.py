# codegen_service/codegen_service.py

import os
import json
import asyncio
from fastapi import FastAPI, Request, HTTPException, APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import uvicorn

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WEB_CODEGEN_SERVICE_PORT = os.environ.get("WEB_CODEGEN_SERVICE_PORT")
WEB_CODEGEN_SERVICE_PORT = int(os.getenv("WEB_EXECUTOR_SERVICE_PORT", "8085"))

PROJECTS_DIR = "projects"

# ---------------------------
# MongoDB Setup
# ---------------------------
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = "timeless_codegen"
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
files_collection = db["generated_files"]

# ---------------------------
# LLM Setup
# ---------------------------
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
CHOSEN_MODEL = os.environ.get("OPENAI_GENERAL_MODEL", "gpt-4")

llm_client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------
# Request Models
# ---------------------------
class ProjectRequest(BaseModel):
    project_id: str
    requirements: str
    fast_mode: bool = False

# ---------------------------
# SSE connections
# ---------------------------
sse_connections = {}

async def send_progress(project_id: str, message: str, progress: int, total: int):
    if project_id in sse_connections:
        data = {"message": message, "progress": progress, "total": total}
        await sse_connections[project_id].put(json.dumps(data))

# ---------------------------
# Helpers
# ---------------------------
async def generate_project_skeleton(requirements: str) -> dict:
    """
    Ask LLM to generate project structure (list of files/folders)
    """
    # prompt = f"""
    # You are an AI assistant that generates a full-stack web app project skeleton.
    # Strict rules:
    # 1. Return **only a JSON object**. Do NOT add any explanation or commentary.
    # 2. Use **double quotes** for all keys and string values.
    # 3. The JSON must have exactly three top-level keys: "frontend", "backend", "shared".
    # 4. Each key's value must be a list of file paths (strings).
    # 5. If unsure, return an empty list for that key. Do not invent additional keys.
    # Requirements: {requirements}

    # Return a JSON object:
    # {{
    #   "frontend": ["App.tsx", "pages/index.tsx", "components/Header.tsx","package.json", "tsconfig.json", "next.config.js", "README.md"],
    #   "backend": ["main.py", "routes/users.py", "models/user.py"],
    #   "shared": ["utils.py"]
    # }}
    # """

    # prompt = f"""
    # You are an AI assistant that generates a full-stack web app project skeleton.
    # Strict rules:
    # 1. Return **only a JSON object**. Do NOT add any explanation or commentary.
    # 2. Use **double quotes** for all keys and string values.
    # 3. The JSON must have exactly three top-level keys: "frontend", "backend", "shared".
    # 4. Each key's value must be a list of file paths (strings).
    # 5. If unsure, return an empty list for that key. Do not invent additional keys.
    # 6. must create public/index.html in frontend
    # 6. must create src/react-dom-client.d.t in frontend
    # Requirements: {requirements}

    # Return a JSON object:
    # {{
    # "frontend": ["public/index.html", "src/App.tsx", "src/index.tsx", "src/react-dom-client.d.ts", "src/components/Header.tsx", "package.json", "tsconfig.json", "README.md"],
    # "backend": ["main.py", "routes/users.py", "models/user.py", "requirements.txt"],
    # "shared": ["utils.py"]
    # }}
    # """

    # prompt = f"""
    # You are an AI assistant that generates a full-stack web app project skeleton.

    # STRICT RULES:
    # 1. Return **ONLY a valid JSON object** — no explanations, no comments, no markdown.
    # 2. Use **double quotes** for all keys and string values.
    # 3. The JSON MUST have exactly three top-level keys: "frontend", "backend", "shared".
    # 4. Each key MUST contain a list of file paths (strings).
    # 5. If uncertain about a file, return an empty list instead of guessing.
    # 6. The frontend MUST be compatible with:
    # - React 18
    # - react-dom/client
    # - TypeScript
    # - Vite (NOT Create React App)
    # This avoids all Webpack / OpenSSL / react-dom issues.
    # 7. The frontend MUST include these exact mandatory files:
    # - "index.html" inside "frontend/public/"
    # - "src/main.tsx" (Vite standard entry point)
    # - "src/react-dom-client.d.ts"
    # - "package.json"
    # - "tsconfig.json"
    # 8. DO NOT include any Webpack configuration or CRA-specific files.
    # 9. DO NOT include version numbers or dependencies in this JSON — only file paths.
    # 10. The backend MUST include simple Python FastAPI structure.
    # 11. The shared folder MUST include only cross-layer utilities — keep minimal.
    # 12. NEVER invent new top-level keys.
    # 13. The JSON MUST be syntactically valid and error-free.

    # Your functional requirements are: {requirements}

    # Return ONLY this JSON structure:

    # {{
    # "frontend": [
    #     "public/index.html",
    #     "src/main.tsx",
    #     "src/App.tsx",
    #     "src/react-dom-client.d.ts",
    #     "src/components/Header.tsx",
    #     "package.json",
    #     "tsconfig.json",
    #     "vite.config.ts"
    # ],
    # "backend": [
    #     "main.py",
    #     "routes/users.py",
    #     "models/user.py",
    #     "requirements.txt"
    # ],
    # "shared": [
    #     "utils.py"
    # ]
    # }}
    # """

    # prompt = f"""
    # You are an AI assistant that generates a full-stack web app project skeleton.

    # STRICT RULES:
    # 1. Return ONLY a valid JSON object — no explanations, no comments, no markdown.
    # 2. Use double quotes for all keys and string values.
    # 3. The JSON MUST have exactly three top-level keys: "frontend", "backend", "shared".
    # 4. Each key MUST contain a list of file paths (strings).
    # 5. If uncertain about a file, return an empty list instead of guessing.

    # FRONTEND RULES:
    # 6. The frontend MUST be compatible with:
    # - React 18
    # - react-dom/client
    # - TypeScript
    # - Vite (NOT Create React App)
    # This avoids ALL Webpack / OpenSSL / react-dom issues.

    # 7. The frontend MUST include these exact mandatory files:
    # - "public/index.html"
    # - "src/main.tsx" (Vite standard entry point)
    # - "src/App.tsx"
    # - "src/react-dom-client.d.ts"
    # - "src/components/Header.tsx"
    # - "package.json"
    # - "tsconfig.json"
    # - "vite.config.ts"

    # 8. The generated frontend/package.json MUST be designed for Vite + React + TypeScript and must **not** include any CRA or Webpack-related files.
    # 9. You MAY add extra backend files or folders **IF requirements need them.**

    # 10. DO NOT include any Webpack configuration or CRA-specific files.
    # 11. DO NOT include version numbers or dependency lists in this JSON — only file paths.

    # BACKEND RULES:
    # 12. The backend MUST use a minimal FastAPI structure.
    # 13. It MUST include:
    # - "main.py"
    # - "routes/users.py"
    # - "models/user.py"
    # - "requirements.txt"

    # 14. You MAY add extra backend files or folders **IF requirements need them.**


    # SHARED RULES:
    # 15. The shared folder MUST include only cross-layer utilities — keep minimal.

    # GLOBAL RULES:
    # 16. NEVER invent new top-level keys.
    # 17. The JSON MUST be syntactically valid and error-free.

    # Project requirements are: {requirements}

    # Return a JSON object:

    # {{
    # "frontend": [
    #     "public/index.html",
    #     "src/main.tsx",
    #     "src/App.tsx",
    #     "src/components/Header.tsx",
    #     "package.json",
    #     "tsconfig.json",
    #     "vite.config.ts"
    # ],
    # "backend": [
    #     "main.py",
    #     "routes/users.py",
    #     "models/user.py",
    #     "requirements.txt"
    # ],
    # "shared": [
    #     "utils.py"
    # ]
    # }}
    # """

    prompt = f"""
    You are an AI assistant that generates a full-stack web app project skeleton.

    STRICT RULES:
    1. Return ONLY a valid JSON object — no explanations, no comments, no markdown.
    2. Use double quotes for all keys and string values.
    3. The JSON MUST have exactly three top-level keys: "frontend", "backend", "shared".
    4. Each key MUST contain a list of file paths (strings).
    5. If uncertain about a file, return an empty list instead of guessing.

    FRONTEND RULES:
    6. The frontend MUST match a modern Next.js App Router project structure with TypeScript.
    7. The frontend MUST include these exact mandatory files:
        - "next.config.mjs"
        - "package.json"
        - "tsconfig.json"
        - "postcss.config.mjs"
        - "src/app/layout.tsx"
        - "src/app/page.tsx"
        - "src/app/components/Header.tsx"
        - "src/app/styles/globals.css"
    8. If Tailwind CSS is used, the frontend MUST use Tailwind v4 conventions:
        - package.json must include "tailwindcss": "^4" and "@tailwindcss/postcss": "^4"
        - postcss.config.mjs must use "@tailwindcss/postcss"
        - NEVER create a legacy "postcss.config.js" that uses "tailwindcss" directly as a PostCSS plugin
    9. You MAY add extra backend files or folders **IF requirements need them.**
    10. Do NOT include Vite, CRA, Webpack, or react-dom-client files.

    BACKEND RULES:
    11. The backend MUST use a minimal FastAPI structure.
    12. It MUST include:
        - "main.py"
        - "routes/users.py"
        - "models/user.py"
        - "requirements.txt"
    13. You MAY add extra backend files or folders **IF requirements need them.**

    SHARED RULES:
    14. The shared folder MUST include only cross-layer utilities.

    GLOBAL RULES:
    15. NEVER invent new top-level keys.
    16. The JSON MUST be syntactically valid and error-free.
    
    Project requirements are: {requirements}

    Return a JSON object example:

    {{
    "frontend": [
        "next.config.mjs",
        "package.json",
        "tsconfig.json",
        "postcss.config.mjs",
        "src/app/layout.tsx",
        "src/app/page.tsx",
        "src/app/components/Header.tsx",
        "src/app/styles/globals.css"
    ],
    "backend": [
        "main.py",
        "routes/users.py",
        "models/user.py",
        "requirements.txt"
    ],
    "shared": [
        "utils.py"
    ]
    }}

    """



    # # response = llm_client.chat.completions.create(
    # #     model=CHOSEN_MODEL,
    # #     messages=[{"role": "user", "content": prompt}],
    # #     max_tokens=500
    # # )

    # # response = llm_client.chat.completions.create(
    # #     model=CHOSEN_MODEL,
    # #     messages=[
    # #         {"role": "system", "content": "You are a JSON-only codegen assistant."},
    # #         {"role": "user", "content": prompt}
    # #     ],
    # #     response_format={
    # #         "type": "json_schema",
    # #         "json_schema": {
    # #             "type": "object",
    # #             "properties": {
    # #                 "frontend": {"type": "array", "items": {"type": "string"}},
    # #                 "backend": {"type": "array", "items": {"type": "string"}},
    # #                 "shared": {"type": "array", "items": {"type": "string"}}
    # #             },
    # #             "required": ["frontend", "backend", "shared"],
    # #             "additionalProperties": False
    # #         }
    # #     }
    # # )
    # content = response.choices[0].message.content.strip()
    # try:
    #     skeleton = json.loads(content)
    # # except:
    # #     skeleton = {
    # #         "frontend": ["App.tsx"],
    # #         "backend": ["main.py"],
    # #         "shared": ["utils.py"]
    # #     }
    # except json.JSONDecodeError:
    #     # Optional: attempt a quick fix with regex
    #     import re
    #     fixed_text = re.sub(r"'", '"', response_text)
    #     try:
    #         skeleton = json.loads(fixed_text)
    #     except json.JSONDecodeError:
    #         # Fallback: default empty skeleton
    #         skeleton = {"frontend": [], "backend": [], "shared": []}

    # return skeleton

    try:
        resp = llm_client.chat.completions.create(
            model=CHOSEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        text = resp.choices[0].message.content.strip()

        # Attempt strict JSON parsing
        skeleton = json.loads(text)
        # Ensure all required keys exist
        for key in ["frontend", "backend", "shared"]:
            if key not in skeleton or not isinstance(skeleton[key], list):
                skeleton[key] = []
        return skeleton

    except json.JSONDecodeError:
        # Quick fix: replace single quotes and retry
        try:
            fixed_text = text.replace("'", '"')
            skeleton = json.loads(fixed_text)
            for key in ["frontend", "backend", "shared"]:
                if key not in skeleton or not isinstance(skeleton[key], list):
                    skeleton[key] = []
            return skeleton
        except Exception:
            # Fallback: return empty skeleton
            return {"frontend": [], "backend": [], "shared": []}
    except Exception as e:
        print("Error generating skeleton:", e)
        return {"frontend": [], "backend": [], "shared": []}
    
    

async def generate_file_code(file_path: str, requirements: str, existing_files: dict, skeleton: str):
    """
    Ask LLM to generate code for a specific file.
    """
    context = json.dumps(existing_files, indent=2)
    # prompt = f"""
    # You are an AI software engineer.

    # Project requirements: {requirements}
    # Project skeleton: {existing_files}

    # Generate the code for the file: {file_path}
    # - Only return the code (no explanations)
    # - Follow best practices for modular architecture
    # - Include type annotations in Python and TypeScript
    # - Connect backend models to MongoDB (if backend file)
    # - Frontend should consume backend API endpoints
    # - Generate simple test cases in /tests for critical files
    # """

    # prompt = f"""
    #     You are an expert full-stack AI engineer. Your task is to generate **ONLY the code**
    #     for a single file in a modular project.

    #     ----------------------------------------------------------------
    #     STRICT RULES YOU MUST FOLLOW (Never violate them):
    #     ----------------------------------------------------------------
    #     1. **Return ONLY the raw code. No explanations. No markdown. No comments.**
    #     2. Do NOT wrap the code in backticks.
    #     3. Do NOT generate any other file. Only generate code for:
    #     → "{file_path}"
    #     4. Use best practices appropriate for the file’s module:
    #     - If path starts with "backend/": 
    #             * Use Python
    #             * Use FastAPI if generating route files
    #             * Use Pydantic for models
    #             * Use Motor/MongoDB for database operations
    #             * Implement exactly the logic implied by the filename
    #     - If path starts with "frontend/": 
    #             * Use TypeScript + React
    #             * Use functional components
    #             * Use fetch/axios calls to backend endpoints (if required)
    #     - If path starts with "shared/":
    #             * Only generate generic utilities — no frontend/backend code
    #     5. Respect modular boundaries — NO mixing of frontend, backend, and shared code.
    #     6. Use type annotations everywhere (Python & TypeScript).
    #     7. Code must be deterministic, clean, and runnable.

    #     ----------------------------------------------------------------
    #     CONTEXT PROVIDED:
    #     ----------------------------------------------------------------
    #     - Project requirements:
    #     {requirements}

    #     - Project skeleton : 
    #     {skeleton}

    #     - All other files already generated:
    #     {existing_files}

    #     ----------------------------------------------------------------
    #     NOW GENERATE THE FILE CONTENT:
    #     ----------------------------------------------------------------
    #     Generate ONLY the full final code for file:
    #     "{file_path}"

    #     Your output MUST BE ONLY the code for this file.
    #     Do not include any text except the code.
        # """
    
    # prompt = f"""
    # You are an expert full-stack AI engineer. Your task is to generate **ONLY the code**
    # for a single file in a modular full-stack project.

    # ----------------------------------------------------------------
    # STRICT RULES YOU MUST FOLLOW (DO NOT VIOLATE THEM):
    # ----------------------------------------------------------------
    # 1. Return ONLY the raw code. 
    # - No explanations
    # - No markdown
    # - No comments
    # - No backticks

    # 2. Generate code ONLY for the following file:
    # "{file_path}"
    # Do NOT generate any other file.

    # 3. Respect the module boundaries:
    # - If file_path starts with "backend/":
    #         * Use Python
    #         * Use FastAPI for route/controller files
    #         * Use Pydantic for request/response models
    #         * Use Motor (async MongoDB driver) for DB operations if required by context
    #         * Keep each file responsible only for its own logic

    # - If file_path starts with "frontend/":
    #         * Use React 18 + TypeScript
    #         * Follow Vite project conventions (no CRA, no Webpack)
    #         * Use functional components and hooks
    #         * Use axios or fetch for API requests ONLY if needed
    #         * Do not include backend-specific logic

    # - If file_path starts with "shared/":
    #         * Use only framework-agnostic utilities
    #         * No React, no FastAPI, no database code

    # 4. Maintain strict modular separation:
    # - NO importing frontend code in backend or vice versa
    # - NO shared utilities that depend on backend or frontend

    # 5. Use strong typing everywhere:
    # - Python: full type annotations
    # - TypeScript: interfaces/types for props, responses, etc.

    # 6. Code must be clean, deterministic, and runnable.
    # Do not leave placeholders like TODO or pass unless required.

    # ----------------------------------------------------------------
    # CONTEXT PROVIDED:
    # ----------------------------------------------------------------
    # Project requirements:
    # {requirements}

    # Project skeleton:
    # {skeleton}

    # Other files already generated (you MUST respect them for imports & architecture):
    # {existing_files}

    # ----------------------------------------------------------------
    # NOW GENERATE THE FILE CONTENT:
    # ----------------------------------------------------------------
    # Output ONLY the full code of:
    # "{file_path}"
    # No explanations. No markdown. No comments. Only code.
    # """

    prompt = f"""
    You are an expert full-stack AI engineer. Your task is to generate **ONLY the code**
    for a single file in a modular full-stack project.

    ----------------------------------------------------------------
    STRICT RULES YOU MUST FOLLOW (DO NOT VIOLATE THEM):
    ----------------------------------------------------------------
    1. Return ONLY the raw code. 
    - No explanations
    - No markdown
    - No comments
    - No backticks

    2. Generate code ONLY for the following file:
    "{file_path}"
    Do NOT generate any other file.

    3. Respect the module boundaries:
    - If file_path starts with "backend/":
            * Use Python
            * Use FastAPI for route/controller files
            * Use Pydantic for request/response models
            * Use Motor (async MongoDB driver) for DB operations if required by context
            * Keep each file responsible only for its own logic

    - If file_path starts with "frontend/":
            * Use Next.js 13+ App Router + TypeScript
            * Use functional React Server/Client Components appropriately
            * Use fetch/axios ONLY if required
            * Do NOT include backend logic
            * must add code at top where do you think is needed: 'use client';
            * when you import globals.css then must follow the correct path like 'import './styles/globals.css';'
            * in tsconfig.json  dont do typo mistakes like in "module": "commonjs", is module not modules
            

    - If file_path starts with "shared/":
            * Use only framework-agnostic utilities
            * No React, no FastAPI, no database code

    4. Maintain strict modular separation:
    - NO importing frontend code in backend or vice versa
    - NO shared utilities that depend on backend or frontend

    5. Use strong typing everywhere:
    - Python: full type annotations
    - TypeScript: interfaces/types for props, responses, etc.

    6. Code must be clean, deterministic, and runnable.
    Do not leave placeholders like TODO or pass unless required.

    ----------------------------------------------------------------
    CONTEXT PROVIDED:
    ----------------------------------------------------------------
    Project requirements:
    {requirements}

    Project skeleton:
    {skeleton}

    Other files already generated (you MUST respect them for imports & architecture):
    {context}

    ----------------------------------------------------------------
    NOW GENERATE THE FILE CONTENT:
    ----------------------------------------------------------------
    Output ONLY the full code of:
    "{file_path}"
    No explanations. No markdown. No comments. Only code.
    """


    response = llm_client.chat.completions.create(
        model=CHOSEN_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500
    )
    code = response.choices[0].message.content.strip()
    return code


FILE_GEN_CONCURRENCY = int(os.getenv("FILE_GEN_CONCURRENCY", "4"))
MAX_CONTEXT_FILES = int(os.getenv("MAX_CONTEXT_FILES", "6"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "12000"))


def build_relevant_context(file_path: str, existing_files: dict[str, str]) -> dict[str, str]:
    """Keep only nearby/generated files that are likely to matter for this file."""
    module, _, relative_path = file_path.partition("/")
    target_dir = os.path.dirname(relative_path)
    selected: list[tuple[int, str, str]] = []

    for existing_path, content in existing_files.items():
        existing_module, _, existing_relative = existing_path.partition("/")
        score = 0

        if existing_module == "shared":
            score += 70
        if existing_module == module:
            score += 50
        if target_dir and os.path.dirname(existing_relative) == target_dir:
            score += 40
        if os.path.basename(existing_relative) in {"package.json", "tsconfig.json", "next.config.mjs", "postcss.config.mjs"}:
            score += 30
        if existing_path == file_path:
            continue
        if score > 0:
            selected.append((score, existing_path, content))

    selected.sort(key=lambda item: (-item[0], item[1]))

    context: dict[str, str] = {}
    total_chars = 0
    for _, existing_path, content in selected:
        if len(context) >= MAX_CONTEXT_FILES:
            break
        remaining = MAX_CONTEXT_CHARS - total_chars
        if remaining <= 0:
            break
        trimmed = content[:remaining]
        context[existing_path] = trimmed
        total_chars += len(trimmed)

    return context


def get_template_file_contents(file_path: str) -> str | None:
    if file_path == "frontend/next.config.mjs":
        return 'const nextConfig = {};\n\nexport default nextConfig;\n'
    if file_path == "frontend/postcss.config.mjs":
        return (
            'const config = {\n'
            '  plugins: {\n'
            '    "@tailwindcss/postcss": {},\n'
            '  },\n'
            '};\n\n'
            'export default config;\n'
        )
    return None


async def generate_file_batch(
    project_id: str,
    file_paths: list[str],
    requirements: str,
    skeleton: dict,
    existing_files: dict[str, str],
    progress_count: int,
    total_files: int,
) -> tuple[dict[str, str], int]:
    semaphore = asyncio.Semaphore(FILE_GEN_CONCURRENCY)
    generated_files: dict[str, str] = {}

    async def generate_one(file_path: str) -> tuple[str, str]:
        async with semaphore:
            template = get_template_file_contents(file_path)
            if template is not None:
                return file_path, template
            context_files = build_relevant_context(file_path, existing_files)
            code = await generate_file_code(file_path, requirements, context_files, skeleton)
            return file_path, code

    tasks = [asyncio.create_task(generate_one(file_path)) for file_path in file_paths]
    for task in asyncio.as_completed(tasks):
        file_path, code = await task
        save_file(project_id, file_path, code)
        generated_files[file_path] = code
        progress_count += 1
        await send_progress(project_id, f"Generated {file_path}", progress_count, total_files)

    return generated_files, progress_count

def save_file(project_id: str, file_path: str, content: str):
    """
    Save generated code to filesystem.
    """
    full_path = os.path.join(PROJECTS_DIR, project_id, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)


def save_skeleton(skeleton: dict, project_id: str, output_dir: str = "projects"):
    """
    Save the project skeleton in two forms:
    1. Raw text file
    2. Proper JSON file
    """
    os.makedirs(output_dir, exist_ok=True)

    # File paths
    txt_file_path = os.path.join(output_dir, f"{project_id}_skeleton.txt")
    json_file_path = os.path.join(output_dir, f"{project_id}_skeleton.json")

    try:
        # Save as raw text
        with open(txt_file_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(skeleton, indent=2))
        print(f"Skeleton saved as text file: {txt_file_path}")

        # Save as proper JSON
        with open(json_file_path, "w", encoding="utf-8") as f:
            json.dump(skeleton, f, indent=2)
        print(f"Skeleton saved as JSON file: {json_file_path}")

    except Exception as e:
        print("Error saving skeleton:", e)

    return txt_file_path, json_file_path

import re

def strip_code_fences(code: str) -> str:
    """
    Remove Markdown code fences such as ```tsx, ```python, ``` etc.
    """
    # Remove opening fences like ```ts, ```tsx, ```python, ```
    code = re.sub(r"^```[\w-]*\s*", "", code.strip())

    # Remove closing fence ```
    code = re.sub(r"\s*```$", "", code.strip())

    return code.strip()


# ---------------------------
# API Endpoints
# ---------------------------
@app.post("/api/v0/generate_project")
async def generate_project(req: ProjectRequest):
    project_id = req.project_id
    requirements = req.requirements

    # # Initialize SSE queue
    # queue = asyncio.Queue()
    # sse_connections[project_id] = queue

    # Remove old project
    project_path = os.path.join(PROJECTS_DIR, project_id)
    if os.path.exists(project_path):
        import shutil
        shutil.rmtree(project_path)

    skeleton = await generate_project_skeleton(requirements)
    save_skeleton(skeleton, project_id)
    total_files = sum(len(files) for files in skeleton.values())
    progress_count = 0
    existing_files: dict[str, str] = {}
    await send_progress(project_id, "Project generation started", progress_count, total_files)

    generation_phases = [
        [f"shared/{file_name}" for file_name in skeleton.get("shared", [])],
        [f"backend/{file_name}" for file_name in skeleton.get("backend", [])],
        [f"frontend/{file_name}" for file_name in skeleton.get("frontend", [])],
    ]

    for file_paths in generation_phases:
        if not file_paths:
            continue
        generated_batch, progress_count = await generate_file_batch(
            project_id=project_id,
            file_paths=file_paths,
            requirements=requirements,
            skeleton=skeleton,
            existing_files=existing_files,
            progress_count=progress_count,
            total_files=total_files,
        )
        existing_files.update(generated_batch)

    # All files done
    await send_progress(project_id, "Project generation complete", total_files, total_files)
    return JSONResponse(
        content={
            "status": "OK",
            "message": "Project generated",
            "project_id": project_id,
            "fast_mode": req.fast_mode,
        }
    )

@app.get("/api/v0/sse/codegen/{project_id}")
async def sse_codegen(project_id: str):
    """
    SSE endpoint to stream code generation progress for a specific project.
    """
    if project_id not in sse_connections:
        sse_connections[project_id] = asyncio.Queue()
    queue = sse_connections[project_id]

    async def event_generator():
        while True:
            data = await queue.get()
            yield f"data: {data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

async def send_progress(project_id: str, message: str, progress: int, total: int):
    if project_id in sse_connections:
        data = {
            "message": message,
            "progress": progress,
            "total": total
        }
        await sse_connections[project_id].put(json.dumps(data))

if __name__ == "__main__":
    print(f"Starting Web Codegen Service on port {WEB_CODEGEN_SERVICE_PORT}")
    uvicorn.run("codegen_service:app", host="0.0.0.0", port=int(WEB_CODEGEN_SERVICE_PORT), workers=1, reload=False)
