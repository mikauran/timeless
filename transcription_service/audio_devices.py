import sounddevice as sd
import numpy as np

# Get the list of audio devices and host APIs
devices = sd.query_devices()
hostapis = sd.query_hostapis()

# Get default device indices
default_input_index = sd.default.device[0]
default_output_index = sd.default.device[1]

def get_hostapi_name(index):
    """Return the name of the host API for a given index."""
    return hostapis[index]['name'] if index < len(hostapis) else "Unknown"

# --- List Input Devices ---
print("=== Audio Input Devices ===")
input_devices = []
for index, device in enumerate(devices):
    if device['max_input_channels'] > 0:
        hostapi_name = get_hostapi_name(device['hostapi'])
        default_marker = " (Default)" if index == default_input_index else ""
        input_devices.append(index)
        print(f"[{index}] {hostapi_name}: {device['name']} (Channels: {device['max_input_channels']}){default_marker}")

# --- List Output Devices ---
print("\n=== Audio Output Devices ===")
output_devices = []
for index, device in enumerate(devices):
    if device['max_output_channels'] > 0:
        hostapi_name = get_hostapi_name(device['hostapi'])
        default_marker = " (Default)" if index == default_output_index else ""
        output_devices.append(index)
        print(f"[{index}] {hostapi_name}: {device['name']} (Channels: {device['max_output_channels']}){default_marker}")

# --- Select Devices for Recording and Playback ---
print("\nSelect devices by index (press Enter to use default).")

# Input device
input_index = input(f"Input device index [default {default_input_index}]: ")
input_index = int(input_index) if input_index.strip() else default_input_index
input_channels = devices[input_index]['max_input_channels']  # Use all available input channels

# Output device
output_index = input(f"Output device index [default {default_output_index}]: ")
output_index = int(output_index) if output_index.strip() else default_output_index
output_channels = devices[output_index]['max_output_channels']  # Use all available output channels

# --- Example: Record and playback ---
duration = 5  # seconds
sample_rate = 44100

print(f"\nRecording for {duration} seconds from device {input_index} ({input_channels} channel(s))...")
audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=input_channels, device=input_index)
sd.wait()
print("Recording finished!")

# Ensure playback uses the correct number of channels
playback_audio = audio
if input_channels > output_channels:
    playback_audio = audio[:, :output_channels]  # Truncate extra channels if needed
elif input_channels < output_channels:
    # Pad missing channels with zeros if output has more channels
    padding = np.zeros((audio.shape[0], output_channels - input_channels))
    playback_audio = np.hstack((audio, padding))

print(f"Playing back on device {output_index} ({output_channels} channel(s))...")
sd.play(playback_audio, samplerate=sample_rate, device=output_index)
sd.wait()
print("Playback finished!")
