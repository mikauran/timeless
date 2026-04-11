# server.py
import os
import json
import logging                   # ...new import...
from openai import OpenAI
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import asyncio

# ---------------------------
# Logging configuration (new)
# ---------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logging.info("Logging is initialized")

# ---------------------------
# Config
# ---------------------------
load_dotenv()

SERVICE_PORT = int(os.getenv("CODEGEN_SERVICE_PORT", "8083"))  # .env-driven
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_ADVANCED_MODEL", "o3-mini-high")

OUTPUT_DIR = os.path.abspath(os.getenv("OUTPUT_DIR", "./output"))
PYTHON_EXECUTABLE = "python"  # requirement (4)

# In-code config knob per (7)
CONFIG_MAX_FIX_ATTEMPTS = int(os.getenv("CONFIG_MAX_FIX_ATTEMPTS", "2"))

# ---------------------------
# App
# ---------------------------
app = FastAPI(title="Code Generation Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# Models
# ---------------------------
class PromptIn(BaseModel):
    prompt: str

# ---------------------------
# State
# ---------------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)

CURRENT_PROCESS = None  # asyncio.subprocess.Process
CURRENT_SCRIPT_PATH = None

client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------
# Helpers
# ---------------------------
SYSTEM_INSTRUCTIONS = """You generate a single, fully self-contained Python Tkinter app script.
Constraints:
- Must be valid Python 3.
- Use only the standard library and Tkinter.
- Include `if __name__ == "__main__":` launcher.
- Avoid long-running background tasks on import; put code under main.
- When reading files or saving, use the current working directory.
"""

FIX_INSTRUCTIONS = """You are given a Tkinter script, the runtime stderr/traceback, and the original requirements.
Return a FIXED full script that addresses the error. Do not include explanations, only code.
"""

async def write_script(code: str) -> str:
    logging.info("Writing generated script to file")
    fname = "app_tk.py"
    fpath = os.path.join(OUTPUT_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(code)
    return fpath

async def generate_tkinter_code(requirements: str, previous_code: str | None = None, error_text: str | None = None) -> str:
    if previous_code is None and error_text is None:
        logging.info("Generating initial Tkinter code")
        user_content = ("Generate a single-file, self-contained Python 3 Tkinter application.\n\n"+
        """Additional implementation notes / Constraints for the LLM:
- Produce clear, runnable code that can be executed with `python script.py`.
- Besides Tkinter, avoid other dependencies (no pip available).
- Avoid long explanations; return only the code file content.
- Print runtime exceptions to stderr for debugging.
- Keep main loop and UI responsive; avoid blocking calls.
- Do not perform file or network I/O. Do not spawn background threads on import.
- Use only Python standard library and Tkinter. No external packages.
- Single file with `if __name__ == "__main__":` entrypoint.

Your task is to implement these requirements:\n"""+
        f"\n{requirements}\n\n")
        messages = [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": user_content},
        ]
    else:
        logging.info("Generating fixed Tkinter code after error")
        user_content = (
            f"Original requirements:\n{requirements}\n\n"
            f"Previous script:\n```python\n{previous_code}\n```\n\n"
            f"Runtime stderr/traceback:\n```\n{error_text}\n```\n\n"
            f"Please fix."
        )
        messages = [
            {"role": "system", "content": FIX_INSTRUCTIONS},
            {"role": "user", "content": user_content},
        ]

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages
    )

    code = resp.choices[0].message.content or ""
    # Strip possible markdown fences
    if code.strip().startswith("```"):
        code = code.strip().strip("`")
        # remove possible "python" after the opening fence
        lines = code.splitlines()
        if lines and lines[0].lower().startswith("python"):
            code = "\n".join(lines[1:])
        # remove trailing triple backticks if present
        code = code.replace("```", "")
    return code.strip()

async def run_script_capture(path: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        PYTHON_EXECUTABLE, path,
        cwd=os.path.dirname(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    global CURRENT_PROCESS
    CURRENT_PROCESS = proc
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

def ensure_no_running_process():
    global CURRENT_PROCESS
    if CURRENT_PROCESS and CURRENT_PROCESS.returncode is None:
        raise HTTPException(status_code=409, detail="A generated app is already running. Stop it first.")

# ---------------------------
# Endpoints
# ---------------------------

# Maintain compatibility with the calling client
@app.post("/prompt")
async def prompt(payload: PromptIn):
    logging.info("Received /prompt call")
    global CURRENT_PROCESS, CURRENT_SCRIPT_PATH
        
    requirements = payload.prompt.strip()
    logging.info(f"Requirements received")
    if not requirements:
        raise HTTPException(status_code=400, detail="Empty prompt.")

    # If something is still running, fail fast
    if CURRENT_PROCESS and CURRENT_PROCESS.returncode is None:
        logging.warning("Attempt to generate new code while a process is running")
        return JSONResponse(
            status_code=409,
            content={"status": "busy", "detail": "A generated app is already running. Call /stop to kill it."},
        )

    # Gen 1: initial code
    code = await generate_tkinter_code(requirements)
    logging.info("Initial code generated")
    script_path = await write_script(code)

    attempts = 0
    last_stdout = ""
    last_stderr = ""
    last_rc = 0

    while attempts <= CONFIG_MAX_FIX_ATTEMPTS:
        logging.info(f"Launching generated script at '{script_path}' (attempt {attempts})")
        # Start the script and return immediately if it starts successfully and remains running
        # Strategy:
        # - Launch the process detached from waiting. If it exits quickly with error, we capture and fix.
        # - If it stays alive for a short grace period, treat as "running" and expose PID.
        proc = await asyncio.create_subprocess_exec(
            PYTHON_EXECUTABLE, script_path,
            cwd=os.path.dirname(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        CURRENT_PROCESS = proc
        CURRENT_SCRIPT_PATH = script_path

        # Grace window: 1.0s to detect immediate crashes
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.0)
            # Process terminated within grace window -> likely crash
            rc = proc.returncode
            out, err = await proc.communicate()
            last_rc = rc
            last_stdout = (out or b"").decode("utf-8", errors="replace")
            last_stderr = (err or b"").decode("utf-8", errors="replace")
            logging.info(f"Script exited during grace period with code {rc}")

            if rc == 0:
                logging.info("Script exited cleanly")
                # Exited cleanly immediately; still return logs
                return JSONResponse(
                    content={
                        "status": "exited",
                        "returncode": rc,
                        "pid": None,
                        "script_path": script_path,
                        "stdout": last_stdout,
                        "stderr": last_stderr,
                        "attempts": attempts,
                    }
                )

            # Crash: try to fix if attempts remain
            if attempts < CONFIG_MAX_FIX_ATTEMPTS:
                attempts += 1
                logging.warning("Script crash detected, attempting fix")
                fixed_code = await generate_tkinter_code(requirements, previous_code=code, error_text=last_stderr)
                code = fixed_code
                script_path = await write_script(code)
                CURRENT_PROCESS = None
                continue
            else:
                logging.error("Exceeded maximum fix attempts")
                # Out of attempts
                return JSONResponse(
                    status_code=500,
                    content={
                        "status": "error",
                        "returncode": last_rc,
                        "pid": None,
                        "script_path": script_path,
                        "stdout": last_stdout,
                        "stderr": last_stderr,
                        "attempts": attempts,
                    },
                )
        except asyncio.TimeoutError:
            logging.info("Script is running (grace period passed without crashing)")
            # Did not exit within grace window -> consider running
            return JSONResponse(
                content={
                    "status": "running",
                    "pid": proc.pid,
                    "script_path": script_path,
                    "stdout": "",
                    "stderr": "",
                    "attempts": attempts,
                }
            )

    # Fallback (should not reach)
    return JSONResponse(content={"status": "unknown"})

@app.post("/stop")
async def stop():
    logging.info("Received /stop call")
    global CURRENT_PROCESS, CURRENT_SCRIPT_PATH
    if not CURRENT_PROCESS or CURRENT_PROCESS.returncode is not None:
        logging.warning("No running process to stop")
        return JSONResponse(content={"status": "idle", "detail": "No running process."})

    try:
        logging.info("Killing running process")
        CURRENT_PROCESS.kill()  # hard terminate
        await CURRENT_PROCESS.wait()
        pid = CURRENT_PROCESS.pid
        CURRENT_PROCESS = None
        return JSONResponse(content={"status": "killed", "pid": pid, "script_path": CURRENT_SCRIPT_PATH})
    except Exception as e:
        logging.error(f"Error killing process: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to kill process: {e}")

@app.get("/status")
async def status():
    logging.info("Received /status call")
    if CURRENT_PROCESS is None:
        return {"status": "idle", "pid": None, "script_path": CURRENT_SCRIPT_PATH}
    alive = CURRENT_PROCESS.returncode is None
    return {
        "status": "running" if alive else "exited",
        "pid": CURRENT_PROCESS.pid,
        "returncode": None if alive else CURRENT_PROCESS.returncode,
        "script_path": CURRENT_SCRIPT_PATH,
    }

# ---------------------------
# Local runner
# ---------------------------
def main():
    # Run with: python server.py
    # Use: uvicorn server:app --host 0.0.0.0 --port SERVICE_PORT
    import uvicorn
    logging.info(f"Starting server on port {SERVICE_PORT}")
    print(f"Starting Tkinter Service on port {SERVICE_PORT}")
    # uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
    uvicorn.run("coder_service:app", host="0.0.0.0", port=int(SERVICE_PORT), workers=1, reload=False)

if __name__ == "__main__":
    main()
