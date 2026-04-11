"""
web_code_generation_service.py
================================
Receives software requirements → generates AI images → calls OpenCode CLI → writes project files.

Required .env variables:
  OPENCODE_MODEL               e.g. "anthropic/claude-sonnet-4-5"
  OPENAI_API_KEY               for DALL-E 3 image generation + OpenAI models
  ANTHROPIC_API_KEY            for Anthropic models
  PROJECTS_DIR                 where generated projects live  (default: projects)
  WEB_CODE_GENERATION_PORT     port for this service          (default: 8084)
"""

import json
import os
import re
import subprocess
import textwrap
import urllib.request
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv()

# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────

OPENCODE_MODEL    = os.environ.get("OPENCODE_MODEL", "openai/gpt-4o")
PROJECTS_DIR      = os.environ.get("PROJECTS_DIR", "projects")
SERVICE_PORT      = int(os.environ.get("WEB_CODE_GENERATION_PORT", "8084"))
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ─────────────────────────────────────────────────────────────────
# AI Image Generation
# ─────────────────────────────────────────────────────────────────

def analyze_image_needs(requirements: str) -> list:
    """
    Ask Claude (or GPT) what images this project needs based on the requirements.
    Returns a list of dicts: [{"filename": "hero.png", "prompt": "...", "usage": "..."}]
    """
    analysis_prompt = f"""You are a web designer. Analyze these software requirements and list the images needed for the website.

Requirements:
{requirements}

Return a JSON array of up to 5 images. Each object must have:
- "filename": short snake_case name ending in .png (e.g. "hero_banner.png", "team_photo.png")
- "prompt": a detailed DALL-E image generation prompt. Be specific: style, colors, mood, subject.
  Always end with "professional website photo, high quality, modern design"
- "usage": where this image is used (e.g. "hero section background", "team member avatar", "services card")

Only include images genuinely needed by the requirements. If no images are needed, return [].
Respond with ONLY the JSON array, no explanation."""

    try:
        if ANTHROPIC_API_KEY:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": analysis_prompt}]
            )
            text = response.content[0].text
        elif OPENAI_API_KEY:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": analysis_prompt}],
                max_tokens=800
            )
            text = response.choices[0].message.content
        else:
            print("[images] No API key available for image analysis")
            return []

        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            specs = json.loads(match.group())
            print(f"[images] Image analysis: {len(specs)} images identified")
            return specs
        return []

    except Exception as e:
        print(f"[images] Image analysis failed: {e}")
        return []


def generate_ai_images(requirements: str, project_path: Path) -> dict:
    """
    Generate AI images using DALL-E 3 and save to frontend/public/images/.
    Returns dict mapping filename -> usage description, or {} if generation is unavailable.
    """
    if not OPENAI_API_KEY:
        print("[images] OPENAI_API_KEY not set — skipping AI image generation")
        return {}

    image_specs = analyze_image_needs(requirements)
    if not image_specs:
        print("[images] No images identified for this project")
        return {}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        print("[images] openai package not installed — skipping AI image generation")
        return {}

    images_dir = project_path / "frontend" / "public" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    generated = {}
    for spec in image_specs[:5]:
        filename = spec.get("filename", "image.png")
        dalle_prompt = spec.get("prompt", "")
        usage = spec.get("usage", "image")

        if not dalle_prompt:
            continue

        try:
            print(f"[images] Generating '{filename}' — {usage}")
            response = client.images.generate(
                model="dall-e-3",
                prompt=dalle_prompt,
                size="1792x1024",
                quality="standard",
                n=1,
            )
            image_url = response.data[0].url
            save_path = images_dir / filename
            urllib.request.urlretrieve(image_url, str(save_path))
            generated[filename] = usage
            print(f"[images] Saved → {save_path}")
        except Exception as e:
            print(f"[images] Failed to generate '{filename}': {e}")

    print(f"[images] Generated {len(generated)} AI images: {list(generated.keys())}")
    return generated


# ─────────────────────────────────────────────────────────────────
# Prompt Builder
# ─────────────────────────────────────────────────────────────────

def build_prompt(project_id: str, requirements: str, generated_images: dict) -> str:

    # Build the images section dynamically
    if generated_images:
        img_lines = ["AI-generated images are already saved in frontend/public/images/. Use them:"]
        for filename, usage in generated_images.items():
            img_lines.append(f"  /images/{filename}  ←  {usage}")
        img_lines += [
            "",
            "Use Next.js <Image> component with unoptimized prop for these local files:",
            "  import Image from 'next/image'",
            "  <Image src=\"/images/hero_banner.png\" alt=\"...\" width={1200} height={600}",
            "         unoptimized className=\"w-full h-full object-cover\" />",
            "",
            "For any OTHER images not in this list, use picsum.photos:",
            "  https://picsum.photos/seed/{keyword}/{width}/{height}",
        ]
        images_section = "\n        ".join(img_lines)
    else:
        images_section = textwrap.dedent("""
            No AI images were pre-generated. Use these free services instead:
            • Stock photos:   https://picsum.photos/seed/{keyword}/{width}/{height}
              Example: https://picsum.photos/seed/dentist/1200/600
              Vary the seed per item: seed/doctor1, seed/doctor2, etc.
            • Colored placeholders: https://placehold.co/600x400/6366f1/ffffff?text=Label
            • Use Next.js <Image unoptimized ...> for all external image URLs.
            • Create frontend/public/logo.svg as an SVG illustration for the brand logo.
        """).strip()

    return textwrap.dedent(f"""
        You are a world-class full-stack developer and UI/UX designer.
        Your job: build a COMPLETE, IMMEDIATELY RUNNABLE web application.

        ╔══════════════════════════════════════════════════════════════╗
        ║          REQUIREMENTS  —  IMPLEMENT EVERY SINGLE ONE        ║
        ╚══════════════════════════════════════════════════════════════╝

        {requirements}

        ╔══════════════════════════════════════════════════════════════╗
        ║                    CRITICAL RULES                           ║
        ╚══════════════════════════════════════════════════════════════╝

        1. BUILD EVERY FEATURE listed in the requirements above. Do not skip any.
        2. If the requirements mention specific content (menu items, team names, prices,
           services, schedule, etc.) — include realistic dummy data for all of it.
        3. FRONTEND ONLY with Next.js 14 + Tailwind CSS unless a backend/API is explicitly needed.
        4. Write EVERY file completely. No placeholders, no "...", no TODO.
        5. Do NOT ask questions — implement the best interpretation immediately.

        ╔══════════════════════════════════════════════════════════════╗
        ║               MANDATORY FILES TO WRITE                      ║
        ╚══════════════════════════════════════════════════════════════╝

        Write ALL of these — missing any one breaks the project:

          frontend/package.json        — scripts + all deps (see template below)
          frontend/next.config.mjs     — export default {{}}
          frontend/tailwind.config.ts  — with keyframes + fontFamily (see template below)
          frontend/postcss.config.js   — CommonJS module.exports (NOT .mjs)
          frontend/tsconfig.json       — standard Next.js TS config
          frontend/src/app/globals.css — starts with @tailwind directives
          frontend/src/app/layout.tsx  — imports globals.css, sets up Inter font
          frontend/src/app/page.tsx    — full page with all sections
          README.md                    — project root, starts with TIMELESS_RUN_CONFIG block

        ── package.json template ──
        {{
          "name": "generated-app", "version": "0.1.0", "private": true,
          "scripts": {{"dev":"next dev","build":"next build","start":"next start"}},
          "dependencies": {{"next":"14.2.3","react":"^18","react-dom":"^18"}},
          "devDependencies": {{
            "@types/node":"^20","@types/react":"^18","@types/react-dom":"^18",
            "autoprefixer":"^10","postcss":"^8","tailwindcss":"^3","typescript":"^5"
          }}
        }}

        ── tailwind.config.ts template (copy exactly) ──
        import type {{ Config }} from 'tailwindcss'
        const config: Config = {{
          content: ['./src/**/*.{{js,ts,jsx,tsx,mdx}}'],
          theme: {{ extend: {{
            keyframes: {{
              fadeIn:        {{ '0%': {{opacity:'0',transform:'translateY(20px)'}}, '100%': {{opacity:'1',transform:'translateY(0)'}} }},
              fadeInLeft:    {{ '0%': {{opacity:'0',transform:'translateX(-20px)'}}, '100%': {{opacity:'1',transform:'translateX(0)'}} }},
              scaleIn:       {{ '0%': {{opacity:'0',transform:'scale(0.9)'}}, '100%': {{opacity:'1',transform:'scale(1)'}} }},
              float:         {{ '0%,100%': {{transform:'translateY(0)'}}, '50%': {{transform:'translateY(-10px)'}} }},
              gradientShift: {{ '0%,100%': {{backgroundPosition:'0% 50%'}}, '50%': {{backgroundPosition:'100% 50%'}} }},
            }},
            animation: {{
              'fade-in':        'fadeIn 0.6s ease-out forwards',
              'fade-in-left':   'fadeInLeft 0.6s ease-out forwards',
              'scale-in':       'scaleIn 0.4s ease-out forwards',
              'float':          'float 4s ease-in-out infinite',
              'gradient-shift': 'gradientShift 8s ease infinite',
            }},
            backgroundSize: {{ '200%': '200%' }},
            fontFamily: {{ sans: ['Inter', 'system-ui', 'sans-serif'] }},
          }} }},
          plugins: [],
        }}
        export default config

        ── postcss.config.js — copy this EXACTLY (use .js NOT .mjs) ──
        module.exports = {{
          plugins: {{
            tailwindcss: {{}},
            autoprefixer: {{}},
          }},
        }}
        ⛔ NEVER create postcss.config.mjs — the .mjs extension forces ES module mode which
           makes `module` undefined and crashes the build with "module is not defined in ES module scope".
           Always use postcss.config.js with module.exports.

        ── layout.tsx — copy this EXACTLY (no font imports at all) ──
        import './globals.css'
        import type {{ Metadata }} from 'next'
        export const metadata: Metadata = {{ title: 'App', description: 'Generated app' }}
        export default function RootLayout({{ children }}: {{ children: React.ReactNode }}) {{
          return (
            <html lang="en">
              <body className="font-sans antialiased">{{children}}</body>
            </html>
          )
        }}

        ⛔ FONT RULES — follow exactly:
        ✗ NEVER import anything from 'next/font/google' or 'next/font/local'
        ✗ NEVER use Geist, GeistMono, Inter, or any next/font function
        ✓ Font is loaded via CSS @import in globals.css (see below) — no JS imports needed

        ── globals.css must start with exactly this (copy verbatim) ──
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
        @tailwind base;
        @tailwind components;
        @tailwind utilities;
        @layer utilities {{
          .animation-delay-100 {{ animation-delay: 0.1s; }}
          .animation-delay-200 {{ animation-delay: 0.2s; }}
          .animation-delay-300 {{ animation-delay: 0.3s; }}
          .animation-delay-500 {{ animation-delay: 0.5s; }}
        }}
        html {{ scroll-behavior: smooth; }}

        ── README.md must start with ──
        <!-- TIMELESS_RUN_CONFIG
        {{
          "frontend": {{
            "dir": "frontend",
            "install_cmd": "npm install --legacy-peer-deps",
            "start_cmd": "npm run dev",
            "type": "nextjs"
          }}
        }}
        -->

        ╔══════════════════════════════════════════════════════════════╗
        ║                        IMAGES                               ║
        ╚══════════════════════════════════════════════════════════════╝

        {images_section}

        ╔══════════════════════════════════════════════════════════════╗
        ║              DESIGN — MAKE IT LOOK STUNNING                 ║
        ╚══════════════════════════════════════════════════════════════╝

        Target quality: Stripe / Linear / Apple.com. A plain white page = FAILURE.

        COLOR PALETTE — pick one that fits the domain:
          Tech/SaaS  → bg-gradient-to-br from-indigo-900 via-purple-900 to-slate-900  accent: cyan-400
          Health     → bg-gradient-to-br from-teal-600 via-emerald-600 to-cyan-700    accent: lime-300
          Warm/Food  → bg-gradient-to-br from-orange-500 via-rose-500 to-pink-600     accent: yellow-300
          Finance    → bg-gradient-to-br from-slate-800 via-blue-900 to-indigo-900    accent: sky-400
          Creative   → bg-gradient-to-br from-violet-600 via-fuchsia-600 to-pink-600  accent: amber-300

        NAVBAR — sticky glassmorphism:
          className="sticky top-0 z-50 backdrop-blur-md bg-black/20 border-b border-white/10 px-6 py-4 flex justify-between items-center"
          Logo left, links right, CTA button pill (gradient + rounded-full).

        HERO SECTION — full viewport, animated:
          - Background: main gradient + animate-gradient-shift bg-[size:200%]
          - 2–3 floating blurred color blobs: absolute, w-72 h-72, blur-3xl, animate-float
          - Headline: text-5xl md:text-7xl font-black, gradient text (bg-clip-text text-transparent)
          - Subheadline: text-lg text-white/70
          - Staggered fade-in: apply animate-fade-in + animation-delay-100/200/300/500 classes
          - CTA buttons: gradient primary + outline secondary (see styles below)
          - If a hero image is available: full-width rounded-2xl with subtle shadow

        CONTENT SECTIONS — alternate dark/light backgrounds, each with:
          - Centered section heading (text-3xl font-bold) + subtitle
          - Responsive grid: grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6

        GLASS CARDS:
          className="bg-white/10 backdrop-blur-sm border border-white/20 rounded-2xl p-6
                     hover:-translate-y-2 hover:shadow-2xl hover:shadow-purple-500/20
                     transition-all duration-300"
          Icon in: bg-gradient-to-br from-violet-500 to-indigo-600 rounded-xl p-3 w-12 h-12 mb-4

        BUTTONS:
          Primary:   bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500
                     text-white font-semibold px-8 py-3 rounded-full shadow-lg shadow-violet-500/30
                     hover:scale-105 hover:shadow-violet-500/50 transition-all duration-200 active:scale-95
          Secondary: border border-white/30 text-white hover:bg-white/10 px-8 py-3
                     rounded-full transition-all duration-200 hover:scale-105 active:scale-95

        FORMS (if needed):
          Input:  bg-white/10 border border-white/20 rounded-xl px-4 py-3 text-white
                  placeholder-white/40 focus:ring-2 focus:ring-violet-500 focus:outline-none transition-all
          Card:   bg-white/10 backdrop-blur-md border border-white/20 rounded-3xl p-8 shadow-2xl

        FOOTER:
          className="bg-slate-900 border-t border-white/10 py-12 px-8"
          Brand + tagline left, nav columns right, copyright bottom in text-white/40.

        ANIMATIONS — use these everywhere:
          animate-fade-in + animation-delay-100/200/300/500 for staggered entrances
          animate-fade-in-left for list items / sidebar content
          animate-scale-in for modals / feature callouts
          animate-float on decorative blobs
          animate-gradient-shift bg-[size:200%] on gradient hero backgrounds

        RULES:
          ✗ No plain white or plain black backgrounds on main sections
          ✗ No unstyled text — every element must have Tailwind classes
          ✗ No empty image boxes — every <img> / <Image> needs a real src
          ✓ All text on dark bg must be white/light coloured
          ✓ Every interactive element must have hover: and active: variants
          ✓ Use rounded-2xl / rounded-3xl for cards, rounded-full for buttons

        ╔══════════════════════════════════════════════════════════════╗
        ║                   FINAL CHECKLIST                           ║
        ╚══════════════════════════════════════════════════════════════╝

        Before finishing, verify:
        [ ] Every requirement from the top is implemented with real content
        [ ] All dummy data is complete and realistic (names, prices, descriptions, etc.)
        [ ] frontend/package.json has "dev" script and all imported packages listed
        [ ] frontend/tailwind.config.ts has keyframes + fontFamily.sans
        [ ] frontend/src/app/globals.css starts with @tailwind directives
        [ ] layout.tsx has NO font imports — no next/font/google, no next/font/local, no Geist, no Inter import
        [ ] layout.tsx body uses className="font-sans antialiased" only
        [ ] globals.css first line is @import url('https://fonts.googleapis.com/css2?family=Inter...')
        [ ] NO className="font-inter" anywhere — only "font-sans" is valid
        [ ] page.tsx has navbar, hero, multiple content sections, footer — all styled
        [ ] Hero has animated gradient + floating blobs + staggered fade-in text
        [ ] All images have real src URLs (AI-generated, picsum.photos, or placehold.co)
        [ ] README.md starts with TIMELESS_RUN_CONFIG block
    """).strip()


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def make_project_dir(project_id: str) -> Path:
    path = Path(PROJECTS_DIR) / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def collect_files(project_path: Path) -> list:
    return [
        str(p.relative_to(project_path))
        for p in sorted(project_path.rglob("*"))
        if p.is_file()
    ]


def parse_assistant_message(raw_stdout: str) -> str:
    last_text = ""
    for line in raw_stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event    = json.loads(line)
            evt_type = event.get("type", "")
            props    = event.get("properties", {})
            if evt_type in ("message.part.text", "assistant.text"):
                last_text = props.get("text", last_text)
            elif evt_type == "message.complete":
                for part in props.get("parts", []):
                    if isinstance(part, dict) and part.get("type") == "text":
                        last_text = part.get("text", last_text)
        except json.JSONDecodeError:
            pass
    return last_text


def build_env() -> dict:
    env = {**os.environ}
    if OPENAI_API_KEY:
        env["OPENAI_API_KEY"] = OPENAI_API_KEY
    if ANTHROPIC_API_KEY:
        env["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
    env["OPENCODE_PERMISSION"] = json.dumps({"write": "allow", "edit": "allow", "bash": "allow"})
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps({
        "$schema":    "https://opencode.ai/config.json",
        "model":      OPENCODE_MODEL,
        "permission": {"write": "allow", "edit": "allow", "bash": "allow"},
    })
    return env


def run_opencode(project_path: Path, prompt: str) -> tuple:
    cmd = ["opencode", "run", "--model", OPENCODE_MODEL, "--format", "json", prompt]
    print(f"\n[codegen] ▶ opencode run --model {OPENCODE_MODEL} ...")
    print(f"[codegen] cwd: {project_path}")

    result = subprocess.run(
        cmd,
        cwd=str(project_path),
        capture_output=True,
        text=True,
        timeout=600,
        env=build_env(),
    )

    print(f"[codegen] exit: {result.returncode}")
    print(f"[codegen] stdout ({len(result.stdout)} chars): {result.stdout[:400] or '(empty)'}")
    print(f"[codegen] stderr ({len(result.stderr)} chars): {result.stderr[:200] or '(empty)'}")
    return result.stdout, result.stderr, result.returncode


# ─────────────────────────────────────────────────────────────────
# FastAPI
# ─────────────────────────────────────────────────────────────────

app    = FastAPI(title="Web Code Generation Service")
router = APIRouter(prefix="/api/v0")


class GenerateProjectRequest(BaseModel):
    project_id:   str
    requirements: str


@router.post("/generate_project")
def generate_project(req: GenerateProjectRequest):
    project_id   = req.project_id.strip()
    requirements = req.requirements.strip()

    if not project_id or not requirements:
        raise HTTPException(status_code=400, detail="Missing project_id or requirements")

    print(f"\n{'='*60}")
    print(f"[codegen] NEW REQUEST  project='{project_id}'")
    print(f"{'='*60}")

    project_path = make_project_dir(project_id)

    # ── Step 1: Generate AI images before code generation ─────────
    print("[codegen] Step 1/2 — Generating AI images...")
    generated_images = generate_ai_images(requirements, project_path)

    # ── Step 2: Build prompt and run OpenCode ──────────────────────
    print("[codegen] Step 2/2 — Running OpenCode...")
    prompt = build_prompt(project_id, requirements, generated_images)

    try:
        stdout, stderr, returncode = run_opencode(project_path, prompt)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Code generation timed out (10 min)")
    except FileNotFoundError:
        raise HTTPException(status_code=500,
            detail="'opencode' not found on PATH. Run: npm install -g opencode-ai")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if returncode != 0:
        raise HTTPException(status_code=500,
            detail=f"opencode exited {returncode}. stderr: {stderr[:400]}")

    if '"name":"APIError"' in stdout or '"statusCode":401' in stdout:
        raise HTTPException(status_code=401,
            detail="OpenCode got an API auth error. Check your API key in .env")

    assistant_message = parse_assistant_message(stdout) or stdout.strip()
    changed_files     = collect_files(project_path)

    print(f"[codegen] ✅ {len(changed_files)} files written")
    print(f"[codegen] AI images included: {list(generated_images.keys())}")

    return JSONResponse(content={
        "status":            "OK",
        "project_id":        project_id,
        "assistant_message": assistant_message,
        "changed_files":     changed_files,
        "project_path":      str(project_path),
        "generated_images":  generated_images,
        "frontend_url":      "http://localhost:3001",
    })


@router.get("/health")
def health():
    try:
        r   = subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=5)
        cli = {"available": r.returncode == 0, "version": (r.stdout or r.stderr).strip()}
    except FileNotFoundError:
        cli = {"available": False, "error": "opencode not found on PATH"}

    try:
        a    = subprocess.run(["opencode", "auth", "list"], capture_output=True, text=True, timeout=5)
        auth = a.stdout.strip() or a.stderr.strip()
    except Exception:
        auth = "could not run 'opencode auth list'"

    return {
        "service":        "web_code_generation_service",
        "status":         "OK",
        "model":          OPENCODE_MODEL,
        "projects_dir":   PROJECTS_DIR,
        "image_generation": "enabled (DALL-E 3)" if OPENAI_API_KEY else "disabled (no OPENAI_API_KEY)",
        "opencode_cli":   cli,
        "opencode_auth":  auth,
    }


@router.get("/projects/{project_id}/files")
def list_project_files(project_id: str):
    project_path = Path(PROJECTS_DIR) / project_id
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": project_id, "files": collect_files(project_path)}


@router.get("/projects/{project_id}/file")
def read_project_file(project_id: str, path: str):
    file_path = Path(PROJECTS_DIR) / project_id / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": path, "content": file_path.read_text(errors="replace")}


# ─────────────────────────────────────────────────────────────────
# Wiring
# ─────────────────────────────────────────────────────────────────

app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    print(f"{'='*60}")
    print(f"  Web Code Generation Service")
    print(f"  Port        : {SERVICE_PORT}")
    print(f"  Model       : {OPENCODE_MODEL}")
    print(f"  Projects dir: {PROJECTS_DIR}")
    print(f"  AI Images   : {'DALL-E 3 enabled' if OPENAI_API_KEY else 'disabled (set OPENAI_API_KEY)'}")
    print(f"{'='*60}")
    uvicorn.run(
        "web_code_generation_service:app",
        host="0.0.0.0",
        port=SERVICE_PORT,
        reload=False,
    )
