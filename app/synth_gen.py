import os
import shutil
from typing import Literal

from app.utils.strings import log_attempt_number
from app.utils.strings import make_cuid
from elevenlabs import Voice, VoiceSettings, save, ElevenLabs  # <-- keep client and models only
import httpx
from loguru import logger
from pydantic import BaseModel

from app import tiktokvoice
from app.config import speech_cache_path
from app.utils.path_util import search_file, text_to_sha256_hash
from tenacity import retry, stop_after_attempt, wait_fixed

VOICE_PROVIDER = Literal["elevenlabs", "tiktok", "openai", "airforce"]


class SynthConfig(BaseModel):
    voice_provider: VOICE_PROVIDER = "tiktok"
    voice: str = "en_us_007"

    static_mode: bool = False
    """ if we're generating static audio for test """


class SynthGenerator:
    def __init__(self, cwd: str, config: SynthConfig):
        self.config = config
        self.cwd = cwd
        self.cache_key: str | None = None

        self.base = os.path.join(self.cwd, "audio_chunks")

        os.makedirs(self.base, exist_ok=True)

        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            logger.error("ELEVENLABS_API_KEY not set in environment variables.")
            raise ValueError("ELEVENLABS_API_KEY is required for ElevenLabs TTS.")
        # create client instance (keeps prior behavior)
        self.client = ElevenLabs(api_key=api_key)

    def set_speech_props(self):
        ky = (
            self.config.voice
            if self.config.static_mode
            else make_cuid(self.config.voice + "_")
        )
        self.speech_path = os.path.join(
            self.base,
            f"{self.config.voice_provider}_{ky}.mp3",
        )
        text_hash = text_to_sha256_hash(self.text)

        self.cache_key = f"{self.config.voice}_{text_hash}"

    async def generate_with_eleven(self, text: str) -> str:
        voice = Voice(
            voice_id=self.config.voice,
            settings=VoiceSettings(
                stability=0.71, similarity_boost=0.5, style=0.0, use_speaker_boost=True
            ),
        )

        audio = None

        try:
            # Preferred: client.generate(...) if available and callable
            if hasattr(self.client, "generate") and callable(getattr(self.client, "generate")):
                audio = self.client.generate(
                    text=text, voice=voice, model="eleven_multilingual_v2", stream=False
                )
            # Some SDK versions expose text_to_speech as a callable helper
            elif hasattr(self.client, "text_to_speech"):
                tts_attr = getattr(self.client, "text_to_speech")
                if callable(tts_attr):
                    audio = tts_attr(text=text, voice=voice, model="eleven_multilingual_v2")
                else:
                    # If text_to_speech returns a helper/client object, try common method names on it
                    for method_name in ("generate", "synthesize", "stream", "speak", "__call__"):
                        method = getattr(tts_attr, method_name, None)
                        if callable(method):
                            audio = method(text=text, voice=voice, model="eleven_multilingual_v2")
                            break
                    else:
                        logger.error(
                            "ElevenLabs client.text_to_speech returned a non-callable helper and no known callable method found."
                        )
                        raise AttributeError("Unsupported elevenlabs client API shape (text_to_speech helper).")
            else:
                logger.error(
                    "ElevenLabs client does not expose a supported generate/text_to_speech API. "
                    "Check your installed elevenlabs package version."
                )
                raise AttributeError("Unsupported elevenlabs client API: missing generate/text_to_speech")
        except Exception as e:
            logger.exception(f"ElevenLabs TTS call failed: {e}")
            raise

        # Try to save the returned audio in multiple formats
        save_error = None
        try:
            # If library provides a save helper that accepts the returned audio
            save(audio, self.speech_path)
            return self.speech_path
        except Exception as e:
            save_error = e
            logger.debug(f"elevenlabs.save() failed, attempting manual save fallback: {e}")

        # Fallbacks for different return types
        try:
            # bytes-like
            if isinstance(audio, (bytes, bytearray)):
                with open(self.speech_path, "wb") as fh:
                    fh.write(audio)
                return self.speech_path

            # httpx / requests Response-like
            if hasattr(audio, "content") and isinstance(audio.content, (bytes, bytearray)):
                with open(self.speech_path, "wb") as fh:
                    fh.write(audio.content)
                return self.speech_path

            # file-like object
            if hasattr(audio, "read") and callable(audio.read):
                with open(self.speech_path, "wb") as fh:
                    fh.write(audio.read())
                return self.speech_path

            # some SDK audio wrappers may expose .audio or .data
            if hasattr(audio, "audio") and isinstance(audio.audio, (bytes, bytearray)):
                with open(self.speech_path, "wb") as fh:
                    fh.write(audio.audio)
                return self.speech_path

            if hasattr(audio, "data") and isinstance(audio.data, (bytes, bytearray)):
                with open(self.speech_path, "wb") as fh:
                    fh.write(audio.data)
                return self.speech_path

            # last attempt: try converting to bytes via bytes()
            try:
                b = bytes(audio)
                with open(self.speech_path, "wb") as fh:
                    fh.write(b)
                return self.speech_path
            except Exception:
                pass

            # If none of the above worked, raise a helpful error
            logger.exception(f"Unable to save audio returned by ElevenLabs (type={type(audio)}).")
            raise RuntimeError(f"Unsupported audio return type from ElevenLabs: {type(audio)}")
        except Exception as e:
            logger.exception(f"Failed to save ElevenLabs audio (fallbacks): {e}; initial save error: {save_error}")
            raise

    async def generate_with_tiktok(self, text: str) -> str:
        tiktokvoice.tts(text, voice=str(self.config.voice), filename=self.speech_path)

        return self.speech_path

    async def cache_speech(self, text: str):
        try:
            if not self.cache_key:
                logger.warning("Skipping speech cache because it is not set")
                return

            speech_path = os.path.join(speech_cache_path, f"{self.cache_key}.mp3")
            shutil.copy2(self.speech_path, speech_path)
        except Exception as e:
            logger.exception(f"Error in cache_speech(): {e}")

    async def generate_with_openai(self, text: str) -> str:
        raise NotImplementedError

    async def generate_with_airforce(self, text: str) -> str:
        url = f"https://api.airforce/get-audio?text={text}&voice={self.config.voice}"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            save(res.content, self.speech_path)
        return self.speech_path

    async def elevenlabs_tts(self, text: str, voice: str) -> str:
        # keep a compatible helper in case other code calls it
        try:
            # reuse the same client path as generate_with_eleven
            return await self.generate_with_eleven(text)
        except Exception as e:
            logger.error(f"ElevenLabs helper failed: {e}")
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(4), after=log_attempt_number) # type: ignore
    async def synth_speech(self, text: str) -> str:
        self.text = text
        self.set_speech_props()

        cached_speech = search_file(speech_cache_path, self.cache_key)

        if cached_speech:
            logger.info(f"Found speech in cache: {cached_speech}")
            shutil.copy2(cached_speech, self.speech_path)
            return cached_speech

        logger.info(f"Synthesizing text: {text}")

        genarator = None

        if self.config.voice_provider == "openai":
            genarator = self.generate_with_openai
        elif self.config.voice_provider == "airforce":
            genarator = self.generate_with_airforce
        elif self.config.voice_provider == "tiktok":
            genarator = self.generate_with_tiktok
        elif self.config.voice_provider == "elevenlabs":
            genarator = self.generate_with_eleven
        else:
            raise ValueError(
                f"voice provider {self.config.voice_provider} is not recognized"
            )

        speech_path = await genarator(text)

        await self.cache_speech(text)

        return speech_path