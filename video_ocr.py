# -*- coding: utf-8 -*-
"""Hardcoded Video-OCR Subtitle Extractor for FetchJAV.

Extracts burnt-in / hardcoded subtitles directly from video frames (e.g. Chinese/English hardcoded subs),
runs optical character recognition (OCR) with multi-backend device support (RapidOCR, Windows Native OCR,
EasyOCR, Tesseract), deduplicates consecutive lines with precise timestamp intervals, and outputs standard
.srt subtitle files. Fully automated and integrated into FetchJAV AI Subtitle pipeline.
"""

from __future__ import annotations

import datetime
import difflib
import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Callable, List, Optional, Tuple
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageChops

try:
    from M3U8Sites.M3U8Crawler import locate_ffmpeg
except ImportError:
    locate_ffmpeg = lambda: 'ffmpeg'

logger = logging.getLogger('FetchJAV.VideoOCR')


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds into SRT timestamp format: HH:MM:SS,mmm"""
    total_ms = int(round(max(0.0, float(seconds)) * 1000.0))
    hours = total_ms // 3600000
    minutes = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


class SubtitleCue:
    """Represents a single subtitle entry with start/end timestamps and text."""

    def __init__(self, start_time: float, end_time: float, text: str):
        self.start_time = float(start_time)
        self.end_time = float(end_time)
        self.text = text.strip()

    def to_srt_block(self, index: int) -> str:
        start_str = format_srt_timestamp(self.start_time)
        end_str = format_srt_timestamp(self.end_time)
        return f"{index}\n{start_str} --> {end_str}\n{self.text}\n\n"


class VideoOCRExtractor:
    """Hardcoded video subtitle OCR engine with frame sampling and multi-backend device OCR."""

    def __init__(
        self,
        fps: float = 2.0,                  # Samples 2 frames per second
        crop_ratio_bottom: float = 0.22,   # Crops bottom 22% of frame for subtitles
        min_duration: float = 0.8,         # Minimum subtitle duration in seconds
        similarity_threshold: float = 0.80,# Text similarity threshold for line merging
        backend: str = 'auto'              # 'auto', 'rapidocr', 'win_native', 'easyocr', 'pytesseract'
    ):
        self.fps = max(0.5, float(fps))
        self.crop_ratio_bottom = max(0.10, min(0.50, float(crop_ratio_bottom)))
        self.min_duration = max(0.3, float(min_duration))
        self.similarity_threshold = float(similarity_threshold)
        self.requested_backend = backend or 'auto'
        self._ocr_backend = self._detect_backend(self.requested_backend)
        self._rapid_ocr_engine = None
        self._easy_ocr_reader = None

    def _detect_backend(self, requested: str = 'auto') -> str:
        """Detect available OCR engines according to preference."""
        requested = (requested or 'auto').lower()

        if requested == 'rapidocr':
            try:
                import rapidocr_onnxruntime
                return 'rapidocr'
            except ImportError:
                logger.warning("Requested RapidOCR backend not available.")

        if requested == 'easyocr':
            try:
                import easyocr
                return 'easyocr'
            except ImportError:
                logger.warning("Requested EasyOCR backend not available.")

        if requested == 'pytesseract':
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
                return 'pytesseract'
            except Exception:
                logger.warning("Requested PyTesseract backend not available.")

        if requested == 'win_native':
            if os.name == 'nt':
                return 'win_native'

        # Auto detection priority: RapidOCR (Fastest/highest accuracy local ONNX) -> EasyOCR -> PyTesseract -> WinNative
        try:
            import rapidocr_onnxruntime
            return 'rapidocr'
        except ImportError:
            pass

        try:
            import easyocr
            return 'easyocr'
        except ImportError:
            pass

        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return 'pytesseract'
        except Exception:
            pass

        if os.name == 'nt':
            return 'win_native'

        return 'rapidocr'

    def preprocess_frame(self, image: Image.Image) -> Image.Image:
        """Preprocess video frame to optimize OCR accuracy for burnt-in subtitles."""
        if not image:
            return image

        # Convert to grayscale
        gray = image.convert('L')

        # Increase contrast to make subtitle text pop against background
        enhancer = ImageEnhance.Contrast(gray)
        contrasted = enhancer.enhance(2.2)

        # Apply thresholding to isolate bright subtitle text (white/yellow with dark outline)
        threshold = 190
        table = [0 if i < threshold else 255 for i in range(256)]
        binarized = contrasted.point(table, '1')

        return binarized

    def ocr_image(self, image: Image.Image, lang: str = 'zh') -> str:
        """Extract text from a preprocessed or raw PIL Image."""
        if not image:
            return ""

        lang = (lang or 'zh').lower()

        # 1. RapidOCR (High accuracy, fast local ONNX runtime)
        if self._ocr_backend == 'rapidocr':
            try:
                from rapidocr_onnxruntime import RapidOCR
                import numpy as np
                if self._rapid_ocr_engine is None:
                    self._rapid_ocr_engine = RapidOCR()
                img_np = np.array(image.convert('RGB'))
                results, _ = self._rapid_ocr_engine(img_np)
                if results:
                    texts = [line[1] for line in results if float(line[2]) >= 0.28]
                    return " ".join(texts).strip()
            except Exception as e:
                logger.debug(f"RapidOCR failed: {e}")

        # 2. EasyOCR
        if self._ocr_backend == 'easyocr':
            try:
                import easyocr
                import numpy as np
                if self._easy_ocr_reader is None:
                    langs = ['ch_tra', 'en'] if 'zh' in lang else (['ja', 'en'] if 'ja' in lang else ['en'])
                    self._easy_ocr_reader = easyocr.Reader(langs, gpu=False)
                results = self._easy_ocr_reader.readtext(np.array(image.convert('RGB')))
                texts = [res[1] for res in results if res[2] > 0.32]
                return " ".join(texts).strip()
            except Exception as e:
                logger.debug(f"EasyOCR failed: {e}")

        # 3. Pytesseract
        if self._ocr_backend == 'pytesseract':
            try:
                import pytesseract
                if 'zh' in lang:
                    tess_lang = 'chi_tra+chi_sim+eng'
                elif 'ja' in lang:
                    tess_lang = 'jpn+eng'
                else:
                    tess_lang = 'eng'
                text = pytesseract.image_to_string(image, lang=tess_lang, config='--psm 6')
                return text.strip()
            except Exception as e:
                logger.debug(f"Pytesseract failed: {e}")

        # 4. Windows Native Device OCR Fallback (Windows 10/11)
        if self._ocr_backend == 'win_native' and os.name == 'nt':
            try:
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    tmp_path = tmp.name
                    image.save(tmp_path)

                ps_script = (
                    "[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null; "
                    "[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null; "
                    f"$f = [Windows.Storage.StorageFile]::GetFileFromPathAsync('{tmp_path}').GetAwaiter().GetResult(); "
                    "$s = $f.OpenAsync([Windows.Storage.FileAccessMode]::Read).GetAwaiter().GetResult(); "
                    "$d = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($s).GetAwaiter().GetResult(); "
                    "$b = $d.GetSoftwareBitmapAsync().GetAwaiter().GetResult(); "
                    "$eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages(); "
                    "if ($eng) { $r = $eng.RecognizeAsync($b).GetAwaiter().GetResult(); Write-Output $r.Text }"
                )
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                    capture_output=True, text=True, timeout=8
                )
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                if res.returncode == 0 and res.stdout:
                    return res.stdout.strip()
            except Exception as e:
                logger.debug(f"WinNative OCR failed: {e}")

        return ""

    def extract_from_video(
        self,
        video_path: str,
        output_srt_path: str,
        lang: str = 'zh',
        progress_cb: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Extract hardcoded subtitles from a video file and write them to an SRT file."""
        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return False

        if cancel_check and cancel_check():
            return False

        ffmpeg_bin = locate_ffmpeg() or 'ffmpeg'
        temp_dir = tempfile.mkdtemp(prefix='fetchjav_ocr_')

        try:
            # 1. Get video duration
            duration = self._get_video_duration(video_path, ffmpeg_bin)
            if duration <= 0:
                duration = 3600.0

            if progress_cb:
                progress_cb(2.0, "Extracting video frames for OCR...")

            # 2. Extract cropped subtitle frames at specified fps
            frame_pattern = os.path.join(temp_dir, 'frame_%06d.jpg')
            cmd = [
                ffmpeg_bin, '-y', '-i', video_path,
                '-vf', f'fps={self.fps},crop=in_w:in_h*{self.crop_ratio_bottom}:0:in_h*{1.0 - self.crop_ratio_bottom}',
                '-q:v', '2', frame_pattern
            ]
            logger.info(f"Extracting subtitle frames with ffmpeg: {' '.join(cmd)}")
            subprocess.run(cmd, capture_output=True, timeout=1800)

            if cancel_check and cancel_check():
                return False

            # 3. Process extracted frames
            frames = sorted([
                os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
                if f.startswith('frame_') and f.endswith('.jpg')
            ])

            if not frames:
                logger.warning("No frames extracted from video.")
                return False

            total_frames = len(frames)
            raw_cues: List[Tuple[float, str]] = []
            prev_prep_img: Optional[Image.Image] = None
            prev_text: str = ""

            for idx, frame_file in enumerate(frames):
                if cancel_check and cancel_check():
                    logger.info("OCR Extraction cancelled by user.")
                    return False

                timestamp = idx / self.fps
                if progress_cb:
                    pct = 5.0 + ((idx / max(1, total_frames)) * 88.0)
                    time_str = f"{int(timestamp//60):02d}:{int(timestamp%60):02d}"
                    progress_cb(pct, f"OCR frame {idx+1}/{total_frames} ({time_str})")

                try:
                    with Image.open(frame_file) as img:
                        prep = self.preprocess_frame(img)

                        # Frame similarity optimization: if preprocessed frame is identical to previous, reuse text
                        is_static = False
                        if prev_prep_img is not None:
                            diff = ImageChops.difference(prep, prev_prep_img)
                            # If bounding box of difference is none or very small, frames are nearly identical
                            bbox = diff.getbbox()
                            if bbox is None:
                                is_static = True

                        if is_static and prev_text:
                            cleaned_text = prev_text
                        else:
                            text = self.ocr_image(prep, lang=lang)
                            cleaned_text = re.sub(r'[\r\n]+', ' ', text).strip()
                            prev_prep_img = prep.copy()
                            prev_text = cleaned_text

                        if len(cleaned_text) >= 2:
                            raw_cues.append((timestamp, cleaned_text))
                except Exception as ex:
                    logger.debug(f"Frame OCR error at {timestamp}s: {ex}")

            if cancel_check and cancel_check():
                return False

            if progress_cb:
                progress_cb(95.0, "Merging and formatting OCR subtitles...")

            # 4. Merge consecutive raw cues into timed SubtitleCue objects
            cues = self._merge_raw_cues(raw_cues)

            # 5. Write SRT file
            os.makedirs(os.path.dirname(os.path.abspath(output_srt_path)), exist_ok=True)
            with open(output_srt_path, 'w', encoding='utf-8') as f:
                for idx, cue in enumerate(cues, start=1):
                    f.write(cue.to_srt_block(idx))

            if progress_cb:
                progress_cb(100.0, f"Extraction complete: {len(cues)} subtitles generated.")

            return True

        except Exception as e:
            logger.error(f"Error during video OCR subtitle extraction: {e}")
            return False
        finally:
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def _get_video_duration(self, video_path: str, ffmpeg_bin: str) -> float:
        """Probe video duration in seconds."""
        try:
            ffprobe_bin = ffmpeg_bin.replace('ffmpeg.exe', 'ffprobe.exe').replace('ffmpeg', 'ffprobe')
            cmd = [
                ffprobe_bin, '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', video_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout:
                return float(res.stdout.strip())
        except Exception:
            pass
        return 0.0

    def _merge_raw_cues(self, raw_cues: List[Tuple[float, str]]) -> List[SubtitleCue]:
        """Merge consecutive identical / highly similar OCR text entries into continuous subtitle spans."""
        if not raw_cues:
            return []

        cues: List[SubtitleCue] = []
        cur_text = raw_cues[0][1]
        cur_start = raw_cues[0][0]
        cur_end = cur_start + (1.0 / self.fps)

        for ts, text in raw_cues[1:]:
            sim = difflib.SequenceMatcher(None, cur_text, text).ratio()
            # If text is very similar and timestamp is contiguous (within 2 frame intervals)
            if sim >= self.similarity_threshold and (ts - cur_end) <= (2.5 / self.fps):
                cur_end = ts + (1.0 / self.fps)
                # Keep longer text variant
                if len(text) > len(cur_text):
                    cur_text = text
            else:
                # Close current cue if it satisfies minimum duration
                if (cur_end - cur_start) >= self.min_duration:
                    cues.append(SubtitleCue(cur_start, cur_end, cur_text))
                # Start new cue
                cur_text = text
                cur_start = ts
                cur_end = ts + (1.0 / self.fps)

        if (cur_end - cur_start) >= self.min_duration:
            cues.append(SubtitleCue(cur_start, cur_end, cur_text))

        return cues


def extract_subtitles_via_ocr(
    video_path: str,
    output_srt_path: Optional[str] = None,
    lang: str = 'zh',
    fps: float = 2.0,
    crop_ratio_bottom: float = 0.22,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """Convenience helper to extract hardcoded subtitles from a video file into an SRT file."""
    if not output_srt_path:
        base, _ = os.path.splitext(video_path)
        output_srt_path = f"{base}.zh-TW.srt" if 'zh' in lang else f"{base}.srt"

    extractor = VideoOCRExtractor(
        fps=fps,
        crop_ratio_bottom=crop_ratio_bottom
    )
    return extractor.extract_from_video(
        video_path=video_path,
        output_srt_path=output_srt_path,
        lang=lang,
        progress_cb=progress_callback,
        cancel_check=cancel_check
    )
