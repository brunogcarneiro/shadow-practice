"""Serviço de gravação de áudio, sem inicialização de interface gráfica."""

from __future__ import annotations

import datetime
import gc
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

SAMPLE_RATE = 44100
StatusCallback = Callable[[str], None]


class RecordingController:
    """Controla uma única gravação de Zoom + microfone por vez."""

    def __init__(self, recordings_dir: Path | None = None):
        from ..config import get_settings

        self.recordings_dir = Path(recordings_dir or get_settings().recordings_dir)
        self._is_recording = False
        self._paused = False
        self._lock = threading.Lock()
        self.current_file: Path | None = None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._is_recording

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def start(self, status_callback: StatusCallback) -> bool:
        with self._lock:
            if self._is_recording:
                return False
            self._is_recording = True
            self._paused = False
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.current_file = self.recordings_dir / (
            datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".wav"
        )
        threading.Thread(
            target=self._record_worker,
            args=(status_callback, self.current_file),
            daemon=True,
            name="audio-recording",
        ).start()
        return True

    def pause(self, status_callback: StatusCallback) -> None:
        with self._lock:
            if not self._is_recording:
                return
            self._paused = True
        status_callback("Pausado")

    def resume(self, status_callback: StatusCallback) -> None:
        with self._lock:
            if not self._is_recording:
                return
            self._paused = False
        status_callback("Gravando…")

    def stop(self, status_callback: StatusCallback) -> None:
        with self._lock:
            self._is_recording = False
            self._paused = False
        status_callback("Parando…")

    @staticmethod
    def _aggregate_device_index() -> int:
        from ..config import get_settings

        configured_device = get_settings().audio_device
        for device in sd.query_devices():
            if device["name"] == configured_device:
                return int(device["index"])
        raise RuntimeError(f"Audio input device {configured_device!r} was not found.")

    def _record_worker(self, status_callback: StatusCallback, output_file: Path) -> None:
        try:
            device_index = self._aggregate_device_index()

            with sf.SoundFile(
                output_file,
                mode="w",
                samplerate=SAMPLE_RATE,
                channels=2,
                subtype="PCM_16",
            ) as output:

                def callback(indata, frames, time_info, status):
                    del frames, time_info
                    if status:
                        return
                    with self._lock:
                        paused = self._paused
                    if paused:
                        return
                    system_audio = indata[:, :2]
                    mic_stereo = np.repeat(indata[:, 2:3], 2, axis=1)
                    output.write(system_audio + mic_stereo)

                with sd.InputStream(
                    device=device_index,
                    channels=3,
                    samplerate=SAMPLE_RATE,
                    callback=callback,
                ):
                    status_callback("Gravando…")
                    while self.is_recording:
                        sd.sleep(200)
        except Exception as error:
            status_callback(f"Erro na gravação: {error}")
        finally:
            with self._lock:
                self._is_recording = False
                self._paused = False
            status_callback("Parado")
            gc.collect()
