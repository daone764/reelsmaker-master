import multiprocessing
import os
import random
from typing import TYPE_CHECKING, Literal
from pathlib import Path
from datetime import datetime  # <-- Add import

from app.effects import zoom_in_effect, zoom_out_effect
from app.utils.strings import (
    FFMPEG_TYPE,
    FileClip,
    adjust_audio_to_target_dBFS,
    get_video_size,
    web_color_to_ass,
)
from loguru import logger
from app.pexel import search_for_stock_videos
from PIL import Image
from PIL import Image as pil
from pkg_resources import parse_version
from pydantic import BaseModel
import ffmpeg


if parse_version(pil.__version__) >= parse_version("10.0.0"):
    Image.ANTIALIAS = Image.LANCZOS  # type: ignore

if TYPE_CHECKING:
    from app.base import BaseEngine

# TODO: implement me
positions = {
    "center": ["center", "center"],
    "left": ["left", "center"],
    "right": ["right", "center"],
    "top": ["center", "top"],
    "bottom": ["center", "bottom"],
}


class VideoGeneratorConfig(BaseModel):
    fontsize: int = 70
    stroke_color: str = "#ffffff"
    text_color: str = "#ffffff"
    stroke_width: int | None = 5
    font_name: str = "Luckiest Guy"
    bg_color: str | None = None
    subtitles_position: str = "center,center"
    threads: int = multiprocessing.cpu_count()

    watermark_path_or_text: str | None = "VoidFace"
    watermark_opacity: float = 0.5
    watermark_type: Literal["image", "text", "none"] = "text"
    background_music_path: str | None = None

    aspect_ratio: str = "9:16"
    """ aspect ratio of the video """

    color_effect: str = "gray"


class VideoGenerator:
    def __init__(
        self,
        base_class: "BaseEngine",
    ):
        self.job_id = base_class.config.job_id
        self.config = base_class.config.video_gen_config
        self.cwd = base_class.cwd
        self.base_engine = base_class

        self.ffmpeg_cmd = os.path.join(os.getcwd(), "bin/ffmpeg")

    async def get_video_url(self, search_term: str) -> str | None:
        try:
            urls = await search_for_stock_videos(
                limit=2,
                min_dur=10,
                query=search_term,
            )
            return urls[0] if len(urls) > 0 else None
        except Exception as e:
            logger.error(f"Consistency Violation: {e}")

        return None

    def apply_subtitle(self, clip, subtitle_path: str):
        position = self.config.subtitles_position.split(",")[0]
        styles = {
            "bottom": "Alignment=2",
            "center": "Alignment=10",
            "top": "Alignment=6",
        }

        text_color = web_color_to_ass(self.config.text_color)
        stroke_color = web_color_to_ass(self.config.stroke_color)
        font_size = round(self.config.fontsize / 5)

        style = (
            f"FontName={self.config.font_name},FontSize={font_size},"
            f"PrimaryColour={text_color},OutlineColour={stroke_color},Outline={self.config.stroke_width},Bold=1,"
            f"{styles.get(position, 'Alignment=10')}"
        )

        fonts_dir = "./fonts"  # <-- Ensure this is set to your fonts directory
        if not os.path.exists(fonts_dir):
            logger.warning(f"Fonts directory {fonts_dir} not found; skipping subtitles.")
            return clip  # Return original clip without subtitles
        return clip.filter(
            "subtitles",
            filename=subtitle_path,
            fontsdir=fonts_dir,
            force_style=style,
            charenc="UTF-8",
        )

    def add_audio_mix(self, video_stream, background_music_filter, tts_audio_filter):
        audio_mix = ffmpeg.filter(
            stream_spec=[background_music_filter, tts_audio_filter],
            filter_name="amix",
            duration="longest",
            dropout_transition=0,
        )
        return ffmpeg.concat(video_stream, audio_mix, v=1, a=1)

    def concatenate_clips(self, inputs: list[FileClip], effects: list = []):
        processed_clips = []
        for data in inputs:
            clip = data.ffmpeg_clip

            if len(effects) > 0:
                effect = random.choice(effects)
                clip = effect(clip)
            clip = clip.filter("scale", 1080, 1920)

            # apply gray effect for motivational video
            if (
                self.config.color_effect == "gray"
                and self.base_engine.config.video_type == "motivational"
            ):
                clip = clip.filter("format", "gray")

            processed_clips.append(clip)
        final_video = ffmpeg.concat(*processed_clips, v=1, a=0)
        return final_video

    async def generate_video(
        self,
        clips: list[FileClip],  # the list of clips from ffmpeg
        speech_filter: FFMPEG_TYPE,
        subtitles_path: str,
        video_duration: float,
        speech_path: str,  # <-- add this parameter
    ) -> str:
        logger.info("Generating video...")
        effects = [zoom_out_effect, zoom_in_effect]

        # Fix path for Windows compatibility
        # Instead of a hash, use a timestamp-based name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(self.cwd, f"reels_video_{timestamp}.mp4")  # <-- Friendly on-disk name

        # Handle background music
        music_input = None
        if self.config.background_music_path and os.path.exists(self.config.background_music_path):
            music_input = ffmpeg.input(
                adjust_audio_to_target_dBFS(self.config.background_music_path),
                t=video_duration,
            )
        else:
            logger.warning("Background music path is None or invalid; proceeding without it.")

        if self.base_engine.config.video_type == "motivational":
            effects = []

        video_stream = self.concatenate_clips(clips, effects)
        video_stream = self.apply_watermark(video_stream)

        # Validate subtitle file
        if not os.path.exists(subtitles_path):
            logger.error(f"Subtitle file {subtitles_path} does not exist; skipping subtitles.")
            subtitles_path = None
        else:
            video_stream = self.apply_subtitle(video_stream, subtitles_path)

        # Validate speech file and prepare audio mix
        audio_mix = None
        try:
            if speech_path and os.path.exists(speech_path):
                ffmpeg.probe(speech_path)  # <-- Check if file is valid
                speech_filter = ffmpeg.input(speech_path)  # <-- Create filter here
                if music_input:
                    audio_mix = ffmpeg.filter(
                        [music_input, speech_filter], "amix", duration="longest", dropout_transition=0
                    )
                else:
                    audio_mix = speech_filter
                logger.info(f"Speech file loaded: {speech_path}")  # <-- Add success log
            else:
                logger.warning(f"Speech file {speech_path} is missing or invalid; proceeding without narration.")
                if music_input:
                    audio_mix = music_input
        except ffmpeg.Error as e:
            logger.error(f"Speech file {speech_path} is invalid or corrupt: {e}")
            if music_input:
                audio_mix = music_input

        # Output video (and audio if available)
        if audio_mix:
            output = ffmpeg.output(
                video_stream,
                audio_mix,
                output_path,
                vcodec="libx264",
                acodec="aac",
                preset="veryfast",
                threads=2,
                loglevel="error",
            ).global_args('-map', '0:v', '-map', '1:a')
        else:
            output = ffmpeg.output(
                video_stream,
                output_path,
                vcodec="libx264",
                preset="veryfast",
                threads=2,
                loglevel="error",
            )

        logger.debug(f"FFMPEG CMD: {output.get_args()}")
        try:
            # Capture stderr for debugging
            stdout, stderr = output.run(overwrite_output=True, cmd=self.ffmpeg_cmd, capture_stdout=True, capture_stderr=True)
            if stderr:
                logger.error(f"ffmpeg stderr: {stderr.decode('utf-8', errors='replace')}")
        except ffmpeg.Error as e:
            logger.error(f"ffmpeg error: {e.stderr.decode('utf-8', errors='replace') if e.stderr else 'No stderr available'}")
            raise

        logger.info("Video generation complete.")
        return output_path  # <-- Return the friendly path

    def _prepare_video_inputs(self, video_paths):
        import ffmpeg
        video_streams = []
        for path in video_paths:
            # Add setsar=1 filter to each input
            stream = ffmpeg.input(path).filter('setsar', '1')
            video_streams.append(stream)
        return video_streams

    # def get_background_audio(self, video_clip: VideoClip, song_path: str) -> AudioClip:
    #     """Takes the original audio and adds the background audio"""
    #     logger.info(f"Getting background music: {song_path}")

    #     def adjust_audio_to_target_dBFS(audio_file_path: str, target_dBFS=-30.0):
    #         audio = AudioSegment.from_file(audio_file_path)
    #         change_in_dBFS = target_dBFS - audio.dBFS
    #         adjusted_audio = audio.apply_gain(change_in_dBFS)
    #         adjusted_audio.export(audio_file_path, format="mp3")
    #         logger.info(f"Adjusted audio to target dBFS: {target_dBFS}")
    #         return audio_file_path

    #     # set the volume of the song to 10% of the original volume
    #     song_path = adjust_audio_to_target_dBFS(song_path)

    #     background_audio = AudioFileClip(song_path)

    #     if background_audio.duration < video_clip.duration:
    #         # calculate how many times the background audio needs to repeat
    #         repeats_needed = int(video_clip.duration // background_audio.duration) + 1

    #         # create a list of the background audio repeated
    #         background_audio_repeated = concatenate_audioclips(
    #             [background_audio] * repeats_needed
    #         )

    #         # trim the repeated audio to match the video duration
    #         background_audio_repeated = background_audio_repeated.subclip(
    #             0, video_clip.duration
    #         )
    #     else:
    #         background_audio_repeated = background_audio.subclip(0, video_clip.duration)

    #     comp_audio = CompositeAudioClip([video_clip.audio, background_audio_repeated])

    #     return comp_audio

    def crop(self, clip: FileClip) -> FFMPEG_TYPE:
        width, height = get_video_size(clip.filepath)
        aspect_ratio = width / height
        ffmpeg_clip = clip.ffmpeg_clip

        if aspect_ratio < 0.5625:
            crop_height = int(width / 0.5625)
            return ffmpeg_clip.filter(
                "crop", w=width, h=crop_height, x=0, y=(height - crop_height) // 2
            )
        else:
            crop_width = int(0.5625 * height)
            return ffmpeg_clip.filter(
                "crop", w=crop_width, h=height, x=(width - crop_width) // 2, y=0
            )

    def apply_watermark(self, video_stream):
        """Adds a watermark to the bottom-right of the video."""

        sysfont = os.path.join(os.getcwd(), "fonts", "LuckiestGuy-Regular.ttf")  # <-- Ensure this matches your file
        if not os.path.exists(sysfont):
            logger.warning(f"Font file {sysfont} not found; skipping watermark.")
            return video_stream  # Return original stream without watermark

        # Check if watermark path/text is set and watermark type is valid
        if (
            not self.config.watermark_path_or_text
            or self.config.watermark_type == "none"
        ):
            return video_stream  # No watermark, return original stream

        # Text-based watermark
        if self.config.watermark_type == "text":
            watermark_text = self.config.watermark_path_or_text
            video_stream = video_stream.filter(
                "drawtext",
                text=watermark_text,
                x="if(lt(mod(t,20),10), (main_w-text_w)-16, if(lt(mod(t,20),10), 16, if(lt(mod(t,20),15), 16, (main_w-text_w)-16)))",
                y="if(lt(mod(t,20),10), (main_h-text_h)-100, if(lt(mod(t,20),10), 50, if(lt(mod(t,20),15), (main_h-text_h)-100, 50)))",
                fontsize=40,
                fontcolor="white",
                fontfile=sysfont,
            )
            logger.info(f"Using font: {sysfont}")  # <-- Add debug log

        # Image-based watermark
        elif self.config.watermark_type == "image":
            watermark_path = self.config.watermark_path_or_text
            watermark = ffmpeg.input(watermark_path)

            # Resize watermark to a height of 100 while maintaining aspect ratio
            watermark = watermark.filter("scale", -1, 100)

            # Overlay the watermark in the bottom-right corner with 8px padding
            video_stream = ffmpeg.overlay(
                video_stream,
                watermark,
                x="(main_w-overlay_w)-8",
                y="(main_h-overlay_h)-8",
            )

        logger.debug("Added watermark to video.")
        return video_stream

    async def create_gif(
        self, master_video_path: str, start_time: float = 1.0, end_time: float = 1.5
    ) -> str:
        logger.debug("Creating GIF...")
        gif_path = f"{self.cwd}/{self.job_id}.gif"

        (
            ffmpeg.input(master_video_path, ss=start_time, t=end_time - start_time)
            .filter("fps", fps=6)
            .filter("scale", "iw/2", "ih/2")
            .output(gif_path, format="gif", loop=0, pix_fmt="rgb24")
            .run(overwrite_output=True)
        )

        return gif_path