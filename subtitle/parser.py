#!/usr/bin/env python
# coding: utf-8
"""Subtitle parsing, validation, and format conversion utilities."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import List, Optional


@dataclass
class SubtitleCue:
    index: int
    start_ms: int
    end_ms: int
    text: str

    def to_srt_time(self, ms: int) -> str:
        ms = max(0, ms)
        hours = ms // 3600000
        ms %= 3600000
        minutes = ms // 60000
        ms %= 60000
        seconds = ms // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    def to_srt_block(self) -> str:
        start_str = self.to_srt_time(self.start_ms)
        end_str = self.to_srt_time(self.end_ms)
        return f"{self.index}\n{start_str} --> {end_str}\n{self.text.strip()}\n"


def parse_timestamp_ms(ts: str) -> int:
    """Parse HH:MM:SS,mmm or HH:MM:SS.mmm or MM:SS.mmm into milliseconds."""
    ts = ts.strip().replace(',', '.')
    parts = ts.split(':')
    try:
        if len(parts) == 3:
            h, m, s = parts
            sec_parts = s.split('.')
            sec = int(sec_parts[0])
            ms = int(sec_parts[1].ljust(3, '0')[:3]) if len(sec_parts) > 1 else 0
            return (int(h) * 3600 + int(m) * 60 + sec) * 1000 + ms
        elif len(parts) == 2:
            m, s = parts
            sec_parts = s.split('.')
            sec = int(sec_parts[0])
            ms = int(sec_parts[1].ljust(3, '0')[:3]) if len(sec_parts) > 1 else 0
            return (int(m) * 60 + sec) * 1000 + ms
    except (ValueError, IndexError):
        pass
    return 0


def sanitize_text(text: str) -> str:
    """Strip dangerous tags, scripts, or path characters from subtitle text."""
    if not text:
        return ""
    # Remove script tags or dangerous constructs
    text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    # Remove style overrides from ASS if any remain
    text = re.sub(r'\{[^\}]*\}', '', text)
    # Standardize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return text.strip()


def parse_srt(text: str) -> List[SubtitleCue]:
    """Parse raw SRT content into a list of SubtitleCues."""
    cues: List[SubtitleCue] = []
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n[ \t]*\n', text.strip())
    
    idx = 1
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        
        # Determine where timing line is
        timing_idx = -1
        for i, line in enumerate(lines[:3]):
            if '-->' in line:
                timing_idx = i
                break
        
        if timing_idx == -1:
            continue
        
        time_parts = lines[timing_idx].split('-->')
        if len(time_parts) != 2:
            continue
        
        start_ms = parse_timestamp_ms(time_parts[0])
        end_ms = parse_timestamp_ms(time_parts[1])
        text_lines = lines[timing_idx + 1:]
        cue_text = sanitize_text('\n'.join(text_lines))
        
        if cue_text:
            cues.append(SubtitleCue(
                index=idx,
                start_ms=start_ms,
                end_ms=end_ms,
                text=cue_text
            ))
            idx += 1

    return cues


def parse_vtt(text: str) -> List[SubtitleCue]:
    """Parse WebVTT content into SubtitleCues."""
    cues: List[SubtitleCue] = []
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    # Remove WEBVTT header and NOTE blocks
    text = re.sub(r'^WEBVTT.*?\n', '', text, flags=re.IGNORECASE)
    text = re.sub(r'NOTE.*?\n\n', '', text, flags=re.DOTALL)
    
    blocks = re.split(r'\n[ \t]*\n', text.strip())
    idx = 1
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        
        timing_idx = -1
        for i, line in enumerate(lines[:3]):
            if '-->' in line:
                timing_idx = i
                break
        
        if timing_idx == -1:
            continue
        
        # Remove cue settings after timestamp if present (e.g. position:50%)
        timing_line = lines[timing_idx]
        timing_parts = timing_line.split('-->')
        if len(timing_parts) != 2:
            continue
        
        start_str = timing_parts[0].strip()
        end_raw = timing_parts[1].strip()
        end_str = end_raw.split()[0]
        
        start_ms = parse_timestamp_ms(start_str)
        end_ms = parse_timestamp_ms(end_str)
        text_lines = lines[timing_idx + 1:]
        cue_text = sanitize_text('\n'.join(text_lines))
        
        if cue_text:
            cues.append(SubtitleCue(
                index=idx,
                start_ms=start_ms,
                end_ms=end_ms,
                text=cue_text
            ))
            idx += 1
            
    return cues


def parse_ass(text: str) -> List[SubtitleCue]:
    """Parse ASS/SSA content into SubtitleCues."""
    cues: List[SubtitleCue] = []
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    lines = text.splitlines()
    
    in_events = False
    format_cols = []
    idx = 1
    
    for line in lines:
        line_s = line.strip()
        if not line_s or line_s.startswith(';'):
            continue
        
        if line_s.casefold() == '[events]':
            in_events = True
            continue
        elif line_s.startswith('[') and line_s.endswith(']'):
            in_events = False
            continue
        
        if in_events:
            if line_s.startswith('Format:'):
                cols = line_s[7:].split(',')
                format_cols = [c.strip().casefold() for c in cols]
            elif line_s.startswith('Dialogue:'):
                parts = line_s[9:].split(',', len(format_cols) - 1 if format_cols else 9)
                if len(parts) >= 9:
                    start_str = parts[1].strip() if len(parts) > 1 else ""
                    end_str = parts[2].strip() if len(parts) > 2 else ""
                    raw_text = parts[-1] if parts else ""
                    
                    start_ms = parse_timestamp_ms(start_str)
                    end_ms = parse_timestamp_ms(end_str)
                    
                    # Convert ASS line breaks \N or \n
                    raw_text = raw_text.replace('\\N', '\n').replace('\\n', '\n')
                    cue_text = sanitize_text(raw_text)
                    
                    if cue_text:
                        cues.append(SubtitleCue(
                            index=idx,
                            start_ms=start_ms,
                            end_ms=end_ms,
                            text=cue_text
                        ))
                        idx += 1
                        
    return cues


def load_and_normalize_subtitle(file_path: str) -> tuple[List[SubtitleCue], str]:
    """Load any supported subtitle file (.srt, .vtt, .ass, .ssa) and return cues + extension."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Subtitle file not found: {file_path}")
    
    ext = os.path.splitext(file_path)[1].lower()
    
    # Read text with auto encoding detection (utf-8, utf-8-sig, shift_jis, gbk, latin1)
    content = ""
    for enc in ('utf-8-sig', 'utf-8', 'shift_jis', 'gbk', 'gb2312', 'big5', 'latin1'):
        try:
            with open(file_path, 'r', encoding=enc) as f:
                content = f.read()
            break
        except (UnicodeDecodeError, TypeError):
            continue
            
    if not content:
        raise ValueError("Failed to read or decode subtitle file")
        
    if ext == '.vtt':
        cues = parse_vtt(content)
    elif ext in ('.ass', '.ssa'):
        cues = parse_ass(content)
    else:
        # Default to SRT parsing
        cues = parse_srt(content)
        
    return cues, ext


def convert_to_srt_file(file_path: str, output_path: str) -> str:
    """Convert input subtitle file to standard SRT file at output_path if needed."""
    cues, ext = load_and_normalize_subtitle(file_path)
    if not cues:
        raise ValueError("No valid subtitle cues found in file")
        
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    srt_text = "\n".join(cue.to_srt_block() for cue in cues)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(srt_text)
        
    return output_path
