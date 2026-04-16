import os
import io
import time
import wave
import threading
import tempfile
import requests
import sounddevice as sd
import numpy as np
import webrtcvad
import uvicorn
from fastapi import FastAPI, Request, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import subprocess
import uuid
from openai import OpenAI
from fastapi.responses import Response

# Load configuration from .env
load_dotenv()
# Control flag & thread handle for mic
mic_active = False
listener_thread = None


# --- FastAPI Lifespan ---
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     listener_thread = threading.Thread(target=listen_loop, daemon=True)
#     listener_thread.start()
#     try:
#         yield
#     finally:
#         # Wait for thread to finish if stopping
#         listener_thread.join()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Do not auto-start microphone/listener thread on app startup.
    # The UI will call /api/v0/start-mic to start listening.
    yield



# --- FastAPI App ---
app = FastAPI(lifespan=lifespan)
router = APIRouter(prefix="/api/v0")

SERVICE_PORT = os.getenv("TRANSCRIPTION_SERVICE_PORT")
TRANSCRIPTION_METHOD = os.getenv("TRANSCRIPTION_METHOD")
TASK = os.getenv("TASK", "transcribe").strip().lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MEETING_SERVICE_URL = os.getenv("MEETING_SERVICE_URL")
MANAGER_SERVICE_URL = os.getenv("MANAGER_SERVICE_URL", "http://localhost:8082/api/v0")

# --- Local Whisper Model ---
if TRANSCRIPTION_METHOD == "local":
    from faster_whisper import WhisperModel
    LOCAL_MODEL_SIZE = os.getenv("LOCAL_MODEL_SIZE", "large-v3-turbo")
    device = "cuda" if os.getenv("USE_CUDA", "False") == "True" else "cpu"
    print(f"Initializing local model on {device}...")
    local_model = WhisperModel(LOCAL_MODEL_SIZE, device=device, compute_type="float16")
else:
    local_model = None

# --- Audio Config ---
CHANNELS = 1
RATE = 16000
FRAME_DURATION = 30  # ms
FRAME_SIZE = int(RATE * FRAME_DURATION / 1000)
SILENCE_DURATION = 0.6
vad = webrtcvad.Vad(1)

# AUDIO_DEVICE_INDEX = os.getenv("AUDIO_DEVICE_INDEX", "default")
# if AUDIO_DEVICE_INDEX != "default":
#     AUDIO_DEVICE_INDEX = int(AUDIO_DEVICE_INDEX)
# else:
#     AUDIO_DEVICE_INDEX = None  # sounddevice default

def get_default_input_device():
    """
    macOS often throws PortAudio -9998 errors because the default device 
    has zero input channels. This function ensures we pick a valid input device.
    """
    try:
        devices = sd.query_devices()
        print("\nAvailable audio devices:")
        for idx, dev in enumerate(devices):
            print(f"{idx}: {dev['name']} (inputs={dev['max_input_channels']}, outputs={dev['max_output_channels']})")

        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                print(f"\n✔ Selected input device {idx}: {dev['name']}")
                return idx

        print("\n❌ No valid microphone device found. Using default input.")
        return None
    except Exception as e:
        print("❌ Failed to detect microphone:", e)
        return None

# Automatically detect valid mic
AUDIO_DEVICE_INDEX = get_default_input_device()

frames_buffer = []

# --- Audio Callback ---
def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"SoundDevice status: {status}")
    frames_buffer.append(indata.copy())

# --- Utilities ---
def is_speech(frame_bytes: bytes) -> bool:
    return vad.is_speech(frame_bytes, RATE)

def save_frames_to_wav(frames, file_path):
    audio_data = np.concatenate(frames, axis=0)
    with wave.open(file_path, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(audio_data.tobytes())

def get_wav_bytes(frames) -> bytes:
    buf = io.BytesIO()
    audio_data = np.concatenate(frames, axis=0)
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(audio_data.tobytes())
    buf.seek(0)
    return buf.read()

def send_transcription(text: str, meeting_id: int = 0):
    def send_request(endpoint):
        try:
            requests.post(endpoint, json={"transcription": text})
        except Exception as e:
            if "Failed to establish a new connection" not in str(e):
                print(f"Error sending transcription to {endpoint}: {e}")

    REST_ENDPOINT_URLS = [
        MEETING_SERVICE_URL + f"/meeting/{meeting_id}/transcription" if MEETING_SERVICE_URL else None,
        MANAGER_SERVICE_URL + f"/meeting/{meeting_id}/transcription" if MANAGER_SERVICE_URL else None
    ]
    for endpoint in REST_ENDPOINT_URLS:
        if endpoint:
            threading.Thread(target=send_request, args=(endpoint,), daemon=True).start()


def extract_transcription_text(response) -> str:
    """Support both SDK response objects and plain dict payloads."""
    if isinstance(response, dict):
        value = response.get("text", "")
    else:
        value = getattr(response, "text", "")

    if isinstance(value, str):
        return value.strip()
    return ""

def process_audio_segment(frames, meeting_id):
    print("Processing audio segment...")
    transcription = ""
    if TRANSCRIPTION_METHOD == "local":
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            temp_filename = tmp_file.name
        try:
            save_frames_to_wav(frames, temp_filename)
            segments, _ = local_model.transcribe(temp_filename, task=TASK, beam_size=5, temperature=0.0)
            transcription = " ".join(seg.text for seg in segments).strip()
        except Exception as e:
            print(f"Local transcription error: {e}")
        finally:
            os.remove(temp_filename)
    else:
        try:
            wav_bytes = get_wav_bytes(frames)
            audio_buffer = io.BytesIO(wav_bytes)
            audio_buffer.name = "audio.wav"
            # from openai import OpenAI
            openai_client = OpenAI(api_key=OPENAI_API_KEY)
            if TASK == "transcribe":
                response = openai_client.audio.transcriptions.create(model="whisper-1", file=audio_buffer)
            elif TASK == "translate":
                response = openai_client.audio.translations.create(model="whisper-1", file=audio_buffer)
            else:
                print(f"Unsupported TASK={TASK!r}; expected 'transcribe' or 'translate'.")
                response = {}
            transcription = extract_transcription_text(response)
        except Exception as e:
            print(f"REST transcription error: {e}")

    if transcription:
        print("Transcription:", transcription)
        send_transcription(transcription, meeting_id)
    else:
        print("No transcription produced.")

def create_new_meeting():
    try:
        response = requests.post(MEETING_SERVICE_URL + "/meeting")
        return response.json().get("meeting_id", None)
    except Exception as e:
        print("Error creating new meeting:", e)
        return None

# --- Listening Loop ---
def listen_loop():
    """
    Updated loop:
    ✔ Runs ONLY while mic_active is True
    ✔ Creates meeting once mic starts
    ✔ Stops immediately when mic_active becomes False
    ✔ Processes leftover frames before exit
    """
    frames_buffer.clear()

    global mic_active

    if not mic_active:
        print("Mic was requested to start, but mic_active=False. Exiting.")
        return

    frames = []
    last_speech_time = None
    meeting_id = None

    # Create meeting once microphone starts
    while not meeting_id and mic_active:
        meeting_id = create_new_meeting()
        if not meeting_id:
            print("Retrying to create a new meeting...")
            time.sleep(2)

    if not mic_active:
        print("Mic stopped before meeting initialized.")
        return

    print("New meeting ID:", meeting_id)
    print("Listening on device", AUDIO_DEVICE_INDEX or "default")

    try:
        with sd.InputStream(
            samplerate=RATE,
            channels=CHANNELS,
            blocksize=FRAME_SIZE,
            dtype='int16',
            device=AUDIO_DEVICE_INDEX if AUDIO_DEVICE_INDEX is not None else None,
            callback=audio_callback
        ):
            print("Microphone audio stream opened.")

            # --- Main Loop: RUN ONLY WHILE mic_active == True ---
            while mic_active:

                # No audio → wait a bit
                if not frames_buffer:
                    time.sleep(0.01)
                    continue

                # Pop frame from buffer
                frame_np = frames_buffer.pop(0)
                frame_bytes = frame_np.tobytes()

                # Detect speech
                if is_speech(frame_bytes):
                    if last_speech_time is None:
                        print("Speech detected...")
                    last_speech_time = time.time()
                    frames.append(frame_np)

                else:
                    # Silence — check if it's the end of a segment
                    if last_speech_time and (time.time() - last_speech_time) > SILENCE_DURATION and frames:
                        segment_duration = (len(frames) * FRAME_DURATION) / 1000.0

                        if segment_duration < 0.5:
                            print(f"Audio segment too short ({segment_duration:.2f}s), discarding...")
                        else:
                            segment_frames = frames.copy()
                            threading.Thread(
                                target=process_audio_segment,
                                args=(segment_frames, meeting_id),
                                daemon=True
                            ).start()

                        # Reset states
                        frames = []
                        last_speech_time = None

            # ======= EXIT LOOP (mic_active = False) =======

    except Exception as e:
        print("Error inside listen_loop:", e)

    finally:
        print("Microphone stopping... cleaning up")

        # Process leftover frames when stopping mic
        if frames:
            print("Processing final leftover audio segment before full stop...")
            segment_frames = frames.copy()
            threading.Thread(
                target=process_audio_segment,
                args=(segment_frames, meeting_id),
                daemon=True
            ).start()

        frames_buffer.clear()
        print("Microphone listener fully stopped.")


# --- REST Endpoint ---

@router.get("/mic-status")
async def mic_status():
    global mic_active
    return {"mic_active": mic_active}

@router.post("/start-mic")
async def start_mic():
    global mic_active, listener_thread
    if mic_active:
        return JSONResponse(content={"status": "already_running", "message": "Microphone already active."})
    mic_active = True
    # spawn listener thread
    listener_thread = threading.Thread(target=listen_loop, daemon=True)
    listener_thread.start()
    return JSONResponse(content={"status": "started", "message": "Microphone started."})

@router.post("/stop-mic")
async def stop_mic():
    global mic_active, listener_thread
    if not mic_active:
        return JSONResponse(content={"status": "not_running", "message": "Microphone not active."})
    mic_active = False
    # don't join here; let listen_loop end and clean up
    return JSONResponse(content={"status": "stopping", "message": "Stopping microphone (will finalize final transcription)."})

@router.post("/receive-text")
async def receive_text(request: Request):
    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from e
    text = data.get("text", "")
    print("Received text via REST API:", text)
    return JSONResponse(content={"status": "success", "message": "Text received"})

@router.post("/generate-avatar")
async def generate_avatar(request: Request):
    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from e

    text = data.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="Text is required")

    try:
        # Unique file names (important for multiple requests)
        unique_id = str(uuid.uuid4())
        audio_file = f"voice_{unique_id}.wav"
        output_dir = "results"
        output_video = f"{output_dir}/output_{unique_id}.mp4"

        # Ensure results folder exists
        os.makedirs(output_dir, exist_ok=True)

        # Paths to your virtual environments
        TTS_VENV = "/Users/dmd868/myDrive/Work/PhD/TAU/Timeless/timeless-architecture-base/venv_tts/bin/activate"
        SADTALK_VENV = "/Users/dmd868/myDrive/Work/PhD/TAU/Timeless/timeless-architecture-base/venv_sadtalker/bin/activate"

        TTS_PYTHON = "/Users/dmd868/myDrive/Work/PhD/TAU/Timeless/timeless-architecture-base/venv_tts/bin/python"
        SADTALK_PYTHON = "/Users/dmd868/myDrive/Work/PhD/TAU/Timeless/timeless-architecture-base/venv_sadtalker/bin/python"

        # source venv_tts/bin/activate
        # source venv_sadtalker/bin/activate

        # # 🟢 Step 1: Generate TTS audio
        # tts_command = [
        #     "/Users/dmd868/myDrive/Work/PhD/TAU/Timeless/timeless-architecture-base/SadTalker/venv310/bin/python", "transcription_service/tts.py", text, audio_file
        # ]
        # subprocess.run(tts_command, check=True)

        # Step 1: Generate audio using TTS
        # tts_command = f"""
        # source {TTS_VENV} && python -m TTS.bin.synthesize \
        # --text "{text}" \
        # --out_path {audio_file} \
        # --model_name "tts_models/en/ljspeech/tacotron2-DDC"
        # """

        tts_command = [
            TTS_PYTHON, "-m", "TTS.bin.synthesize",
            "--text", text,
            "--out_path", audio_file,
            "--model_name", "tts_models/en/ljspeech/tacotron2-DDC"
        ]
        print("Generating TTS audio...")
        # subprocess.run(tts_command, shell=True, executable="/bin/bash", check=True)
        subprocess.run(tts_command, check=True)
        print(f"Audio saved to {audio_file}")

        # 🟢 Step 2: Run SadTalker
        # sadtalker_command = [
        #     # "python", "SadTalker/inference.py",
        #     "/Users/dmd868/myDrive/Work/PhD/TAU/Timeless/timeless-architecture-base/SadTalker/venv310/bin/python",
        #     "SadTalker/inference.py",
        #     "--driven_audio", audio_file,
        #     "--source_image", "avatar.jpg",
        #     "--result_dir", output_dir,
        #     "--output_name", f"output_{unique_id}"
        # ]
        # subprocess.run(sadtalker_command, check=True)

        # Step 2: Run SadTalker using the generated audio
        # Make sure you have an input face image
        INPUT_IMAGE = "avatar.jpg"  # replace with your face image path

        # sadtalker_command = f"""
        # source {SADTALK_VENV} && python SadTalker/inference.py \
        # --driven_audio {audio_file} \
        # --source_image {INPUT_IMAGE} \
        # "--result_dir", {output_dir},
        # "--output_name", f"output_{unique_id}"
        # """

        sadtalker_command = [
            SADTALK_PYTHON, "SadTalker/inference.py",
            "--driven_audio", audio_file,
            "--source_image", INPUT_IMAGE,
            "--result_dir", output_dir,
            "--output_name", f"output_{unique_id}"
        ]

        print("Running SadTalker...")
        # subprocess.run(sadtalker_command, shell=True, executable="/bin/bash", check=True)
        # print("SadTalker video generated in results/")
        subprocess.run(sadtalker_command, check=True)
        print(f"SadTalker video generated in {output_dir}/output_{unique_id}.mp4")

        # 🟢 Return video URL
        video_url = f"http://localhost:8080/results/output_{unique_id}.mp4"

        return JSONResponse(content={
            "status": "success",
            "videoUrl": video_url
        })

    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail="Processing failed") from e


@router.post("/speak")
async def speak_text(request: Request):
    try:
        data = await request.json()
        text = data.get("text", "")
        client = OpenAI(api_key=OPENAI_API_KEY)

        response = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text
        )
        # print("TTS response:", response.content)
        return Response(content=response.content, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Middleware & Router ---
app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Run Uvicorn ---
if __name__ == "__main__":
    print(f"Starting Transcription Service on port {SERVICE_PORT}")
    uvicorn.run("transcribe_service:app", host="0.0.0.0", port=int(SERVICE_PORT), workers=1, reload=False)
