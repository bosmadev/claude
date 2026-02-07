#!/usr/bin/env python3
"""
YouTube Transcription Script for Claude Code CLI.

Fetches transcripts from YouTube videos and saves them as markdown files
with YAML frontmatter for easy parsing and management.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def extract_video_id(url_or_id: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",  # Raw 11-char ID
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            video_id = match.group(1)
            # Sanitize: ensure video ID contains only valid YouTube characters
            if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
                return video_id
            else:
                # Matched pattern but contains invalid characters (potential injection)
                return None
    return None


def fetch_metadata(video_id: str) -> dict:
    """Fetch video metadata using yt-dlp."""
    # Validate video_id before inserting into URL to prevent command injection
    if not re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
        raise ValueError(f"Invalid video ID format: {video_id}")

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--dump-json",
                "--no-download",
                "--no-warnings",
                f"https://youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            duration_secs = data.get("duration", 0)
            hours, remainder = divmod(int(duration_secs), 3600)
            minutes, secs = divmod(remainder, 60)
            if hours:
                duration_str = f"{hours}:{minutes:02d}:{secs:02d}"
            else:
                duration_str = f"{minutes}:{secs:02d}"

            return {
                "title": data.get("title", "Unknown"),
                "author": data.get("uploader", data.get("channel", "Unknown")),
                "duration": duration_str,
                "duration_secs": duration_secs,
            }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not fetch metadata: {e}", file=sys.stderr)

    return {"title": "Unknown", "author": "Unknown", "duration": "Unknown", "duration_secs": 0}


def fetch_transcript(video_id: str) -> tuple[list[dict], str]:
    """Fetch transcript using youtube-transcript-api."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)

        # Try manual transcripts first (higher quality)
        try:
            transcript = transcript_list.find_manually_created_transcript(
                ["en", "en-US", "en-GB"]
            )
            return transcript.fetch(), f"{transcript.language_code} (manual)"
        except NoTranscriptFound:
            pass

        # Try auto-generated English
        try:
            transcript = transcript_list.find_generated_transcript(["en", "en-US", "en-GB"])
            return transcript.fetch(), f"{transcript.language_code} (auto)"
        except NoTranscriptFound:
            pass

        # Get any transcript and translate to English
        for transcript in transcript_list:
            try:
                if transcript.language_code.startswith("en"):
                    transcript_type = "auto" if transcript.is_generated else "manual"
                    return transcript.fetch(), f"{transcript.language_code} ({transcript_type})"
                # Translate to English
                translated = transcript.translate("en")
                return translated.fetch(), f"en (translated from {transcript.language_code})"
            except Exception:
                continue

        # Last resort: get first available
        transcript = next(iter(transcript_list))
        transcript_type = "auto" if transcript.is_generated else "manual"
        return transcript.fetch(), f"{transcript.language_code} ({transcript_type})"

    except TranscriptsDisabled:
        raise RuntimeError("Transcripts are disabled for this video")
    except VideoUnavailable:
        raise RuntimeError("Video is unavailable")
    except NoTranscriptFound:
        raise RuntimeError("No transcript found for this video")


def format_timestamp(seconds: float) -> str:
    """Format seconds as [MM:SS] or [HH:MM:SS] timestamp."""
    total_secs = int(seconds)
    hours, remainder = divmod(total_secs, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"


def escape_yaml_value(value: str) -> str:
    """Escape a string value for safe YAML double-quoted string insertion.

    Handles YAML special characters, escape sequences, and injection vectors.
    Uses double-quoted strings which require escaping: \ " and control characters.
    """
    # Escape backslashes first (before other escapes that introduce backslashes)
    value = value.replace("\\", "\\\\")
    # Escape double quotes
    value = value.replace('"', '\\"')
    # Escape common control characters that could break YAML parsing
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    # Escape Unicode line/paragraph separators (rare but dangerous)
    value = value.replace("\u2028", "\\u2028")
    value = value.replace("\u2029", "\\u2029")
    return value


def generate_markdown(
    video_id: str,
    metadata: dict,
    transcript: list,
    language: str,
) -> str:
    """Generate Markdown transcript with YAML frontmatter."""
    now = datetime.now(timezone.utc).isoformat()

    # Escape title/author for safe YAML insertion
    title = escape_yaml_value(metadata["title"])
    author = escape_yaml_value(metadata["author"])

    # Build timestamped transcript
    # Handle both dict and object access (youtube-transcript-api returns objects)
    timestamped_lines = []
    for entry in transcript:
        start = entry.start if hasattr(entry, "start") else entry["start"]
        text = entry.text if hasattr(entry, "text") else entry["text"]
        ts = format_timestamp(start)
        text = text.strip().replace("\n", " ")
        timestamped_lines.append(f"{ts} {text}")

    # Build full text (no timestamps)
    def get_text(e):
        return (e.text if hasattr(e, "text") else e["text"]).strip().replace("\n", " ")

    full_text = " ".join(get_text(entry) for entry in transcript)

    # Word count
    word_count = len(full_text.split())

    return f"""---
video_id: "{video_id}"
title: "{title}"
author: "{author}"
duration: "{metadata['duration']}"
language: "{language}"
word_count: {word_count}
created: "{now}"
url: "https://youtube.com/watch?v={video_id}"
---

# {metadata['title']}

**Channel:** {metadata['author']}
**Duration:** {metadata['duration']}
**Language:** {language}
**Words:** {word_count:,}
**URL:** https://youtube.com/watch?v={video_id}

---

## Timestamped Transcript

{chr(10).join(timestamped_lines)}

---

## Full Text

{full_text}
"""


def track_usage(video_id: str, title: str, file_path: str) -> None:
    """Track YouTube transcript usage in ~/.claude/youtube/youtube-session.json (gitignored)."""
    # Store in ~/.claude/youtube/ which is gitignored, not in project .claude/ dirs
    claude_home = Path.home() / ".claude"
    tracker_file = claude_home / "youtube" / "youtube-session.json"
    tracker_file.parent.mkdir(parents=True, exist_ok=True)

    # Load or create
    if tracker_file.exists():
        try:
            data = json.loads(tracker_file.read_text())
        except json.JSONDecodeError:
            data = {"transcripts_used": []}
    else:
        data = {"transcripts_used": []}

    # Add entry if not already tracked
    existing_ids = [t["video_id"] for t in data["transcripts_used"]]
    if video_id not in existing_ids:
        data["transcripts_used"].append(
            {
                "video_id": video_id,
                "title": title,
                "file_path": file_path,
                "added_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        tracker_file.write_text(json.dumps(data, indent=2))


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: transcribe.py <video_id_or_url>")
        print()
        print("Examples:")
        print("  transcribe.py dQw4w9WgXcQ")
        print("  transcribe.py https://youtube.com/watch?v=dQw4w9WgXcQ")
        print("  transcribe.py https://youtu.be/dQw4w9WgXcQ")
        return 1

    input_arg = sys.argv[1]
    video_id = extract_video_id(input_arg)

    if not video_id:
        print(f"Error: Could not extract video ID from: {input_arg}", file=sys.stderr)
        return 1

    output_dir = Path.home() / ".claude" / "youtube" / "transcriptions"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"youtube-{video_id}.md"

    # Check if already transcribed
    if output_file.exists():
        print(f"Transcript already exists: {output_file}")
        # Still track usage for this session
        try:
            content = output_file.read_text()
            title_match = re.search(r'^title: "(.+)"', content, re.MULTILINE)
            title = title_match.group(1) if title_match else "Unknown"
            track_usage(video_id, title, str(output_file))
        except Exception:
            pass
        return 0

    print(f"Video ID: {video_id}")
    print()

    # Fetch metadata
    print("Fetching metadata...")
    metadata = fetch_metadata(video_id)
    print(f"  Title: {metadata['title']}")
    print(f"  Author: {metadata['author']}")
    print(f"  Duration: {metadata['duration']}")
    print()

    # Fetch transcript
    print("Fetching transcript...")
    try:
        transcript, language = fetch_transcript(video_id)
        print(f"  Language: {language}")
        print(f"  Segments: {len(transcript)}")
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print()

    # Generate and save markdown
    markdown = generate_markdown(video_id, metadata, transcript, language)
    output_file.write_text(markdown)

    # Track usage for RALPH cleanup
    track_usage(video_id, metadata["title"], str(output_file))

    print(f"Saved to: {output_file}")
    print()

    # Show preview
    full_text_start = markdown.find("## Full Text") + len("## Full Text\n\n")
    preview = markdown[full_text_start : full_text_start + 500]
    print("Preview (first 500 chars):")
    print("-" * 40)
    print(preview.strip() + "...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
