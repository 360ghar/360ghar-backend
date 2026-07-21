import json
import time
from pathlib import Path
import google.generativeai as genai
from typing import List, Dict, Any

from app.config.settings import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)


def segment_video_into_rooms(video_path: str) -> List[Dict[str, Any]]:
    """
    Uploads a 360 walkthrough video to Gemini 1.5 Pro and asks it to segment 
    the video into distinct rooms based on doorways and thresholds.
    
    Returns a list of dictionaries, e.g.:
    [
        {"room_name": "Living Room", "start_time_sec": 0, "end_time_sec": 45},
        {"room_name": "Kitchen", "start_time_sec": 45, "end_time_sec": 72},
        {"room_name": "Living Room", "start_time_sec": 72, "end_time_sec": 90}
    ]
    """
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is required for video segmentation")

    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    logger.info(f"Uploading {video_path} to Gemini for segmentation...")
    video_file = genai.upload_file(path=str(path))
    
    # Wait for the video to be processed by Gemini API
    logger.info("Waiting for video processing in Gemini...")
    while video_file.state.name == "PROCESSING":
        time.sleep(10)
        video_file = genai.get_file(video_file.name)
        
    if video_file.state.name == "FAILED":
        raise RuntimeError("Video processing failed in Gemini.")
        
    logger.info("Video processed successfully. Analyzing rooms...")

    prompt = """
    You are an AI tasked with analyzing a 360-degree virtual tour video walkthrough.
    
    Your goal is to segment the video chronologically into distinct "rooms" or "areas".
    The person holding the camera walks through a house. Every time the camera crosses a doorway, threshold, or moves into a completely new functional area, that marks a boundary.
    
    CRITICAL INSTRUCTIONS:
    1. Identify the name of each room (e.g., "Living Room", "Kitchen", "Hallway", "Master Bedroom"). Use generic descriptive names.
    2. If the camera re-enters a room it has ALREADY visited (e.g., they walk from Living Room -> Kitchen -> Living Room), you MUST use the EXACT SAME room name for the re-entry segment.
    3. Output the chronological segments. The first segment must start at 0. There should be no gaps between segments.
    4. Provide the output strictly as a JSON array of objects. Do not include markdown formatting or backticks around the JSON.
    
    Example Output Format:
    [
      {"room_name": "Entrance Foyer", "start_time_sec": 0, "end_time_sec": 12.5},
      {"room_name": "Living Room", "start_time_sec": 12.5, "end_time_sec": 45.0},
      {"room_name": "Kitchen", "start_time_sec": 45.0, "end_time_sec": 72.0},
      {"room_name": "Living Room", "start_time_sec": 72.0, "end_time_sec": 90.0}
    ]
    """

    model = genai.GenerativeModel(model_name="gemini-1.5-pro")
    
    response = model.generate_content(
        [video_file, prompt],
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json"
        )
    )
    
    # Clean up the uploaded file to save space
    logger.info("Deleting video file from Gemini API...")
    genai.delete_file(video_file.name)
    
    try:
        segments = json.loads(response.text)
        logger.info(f"Detected {len(segments)} segments: {segments}")
        return segments
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response: {response.text}")
        raise ValueError("Invalid JSON received from Gemini") from e

import subprocess

def split_and_group_video(video_path: str, segments: List[Dict[str, Any]], output_dir: str) -> Dict[str, List[str]]:
    """
    Splits the video into chunks using FFmpeg based on segments,
    and groups them by room_name.
    
    Returns a dict mapping room_name -> list of chunk file paths.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    room_clips = {}
    
    for i, seg in enumerate(segments):
        room_name = seg["room_name"]
        start_sec = seg["start_time_sec"]
        end_sec = seg["end_time_sec"]
        
        chunk_filename = f"chunk_{i}_{room_name.replace(' ', '_')}.mp4"
        chunk_path = out_path / chunk_filename
        
        logger.info(f"Extracting {chunk_filename} from {start_sec}s to {end_sec}s...")
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", str(start_sec),
            "-to", str(end_sec),
            "-c", "copy",  # Fast stream copy without re-encoding
            str(chunk_path)
        ]
        
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"Failed to split video: {res.stderr}")
            raise RuntimeError(f"FFmpeg failed to extract {chunk_filename}")
            
        if room_name not in room_clips:
            room_clips[room_name] = []
        room_clips[room_name].append(str(chunk_path))
        
    return room_clips
