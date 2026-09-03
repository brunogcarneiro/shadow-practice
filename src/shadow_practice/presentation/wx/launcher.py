"""Ponto único de entrada da interface do Shadow Practice."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import wx

from ...application.sense_groups import group_words_file
from ...config import get_settings
from ...infrastructure.recording import RecordingController
from ...infrastructure.transcription import transcribe_recording
from .main_frame import TranscriptPlayer


def is_processed_recording(audio_path: Path) -> bool:
    """Indica se a gravação possui uma transcrição já agrupada."""
    words_path = audio_path.with_suffix(".words.json")
    if not words_path.is_file():
        return False
    try:
        with words_path.open(encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, list) and any(
        isinstance(item, dict) and (
            "displayed" in item or "linebreak" in item
        )
        for item in payload
    )


class ShadowPracticeFrame(wx.Frame):
    """Tela inicial: gravação, processamento e seleção para prática."""

    def __init__(self):
        super().__init__(None, title="Shadow Practice", size=(780, 560))
        self.recorder = RecordingController()
        self.selected_recording: Path | None = None
        self.processing_recordings: set[Path] = set()
        self.processing_progress: dict[Path, tuple[int, str]] = {}
        self.processing_gauges: dict[Path, wx.Gauge] = {}
        self.processing_labels: dict[Path, wx.StaticText] = {}
        self.player_frame: TranscriptPlayer | None = None

        panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)

        recording_box = wx.StaticBox(panel, label="Gravação")
        recording_sizer = wx.StaticBoxSizer(recording_box, wx.HORIZONTAL)
        self.status_label = wx.StaticText(recording_box, label="Parado")
        recording_sizer.Add(self.status_label, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)

        self.start_button = wx.Button(recording_box, label="Start")
        self.pause_button = wx.Button(recording_box, label="Pause")
        self.resume_button = wx.Button(recording_box, label="Resume")
        self.stop_button = wx.Button(recording_box, label="Stop")
        for button in (
            self.start_button,
            self.pause_button,
            self.resume_button,
            self.stop_button,
        ):
            recording_sizer.Add(button, 0, wx.ALL, 4)
        layout.Add(recording_sizer, 0, wx.EXPAND | wx.ALL, 8)

        recordings_box = wx.StaticBox(panel, label="Gravações disponíveis")
        recordings_sizer = wx.StaticBoxSizer(recordings_box, wx.VERTICAL)
        self.recordings_header = self._create_header(recordings_box)
        recordings_sizer.Add(self.recordings_header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.recordings_container = wx.ScrolledWindow(
            recordings_box,
            style=wx.VSCROLL | wx.BORDER_SUNKEN,
        )
        self.recordings_container.SetScrollRate(0, 10)
        self.recordings_rows = wx.BoxSizer(wx.VERTICAL)
        self.recordings_container.SetSizer(self.recordings_rows)
        recordings_sizer.Add(self.recordings_container, 1, wx.EXPAND | wx.ALL, 5)
        layout.Add(recordings_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        footer = wx.BoxSizer(wx.HORIZONTAL)
        self.practice_button = wx.Button(panel, label="Praticar gravação selecionada")
        self.practice_button.Disable()
        footer.AddStretchSpacer()
        footer.Add(self.practice_button, 0, wx.ALL, 8)
        layout.Add(footer, 0, wx.EXPAND)

        panel.SetSizer(layout)
        self.start_button.Bind(wx.EVT_BUTTON, self.on_start_recording)
        self.pause_button.Bind(wx.EVT_BUTTON, self.on_pause_recording)
        self.resume_button.Bind(wx.EVT_BUTTON, self.on_resume_recording)
        self.stop_button.Bind(wx.EVT_BUTTON, self.on_stop_recording)
        self.practice_button.Bind(wx.EVT_BUTTON, self.on_practice_selected)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self._update_recording_buttons()
        self.refresh_recordings()

    @staticmethod
    def _create_header(parent: wx.Window) -> wx.Panel:
        header = wx.Panel(parent)
        header.SetBackgroundColour(wx.Colour(235, 235, 235))
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        name = wx.StaticText(header, label="Arquivo")
        process = wx.StaticText(header, label="Processamento")
        font = name.GetFont()
        font.MakeBold()
        name.SetFont(font)
        process.SetFont(font)
        sizer.Add(name, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        sizer.Add(process, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        header.SetSizer(sizer)
        return header

    def _set_status(self, message: str) -> None:
        wx.CallAfter(self._apply_status, message)

    def _apply_status(self, message: str) -> None:
        if self.IsBeingDeleted():
            return
        self.status_label.SetLabel(message)
        self._update_recording_buttons()
        if message == "Parado":
            self.refresh_recordings()

    def _update_recording_buttons(self) -> None:
        recording = self.recorder.is_recording
        paused = self.recorder.is_paused
        self.start_button.Enable(not recording)
        self.pause_button.Enable(recording and not paused)
        self.resume_button.Enable(recording and paused)
        self.stop_button.Enable(recording)

    def on_start_recording(self, event: wx.CommandEvent) -> None:
        self.recorder.start(self._set_status)
        self._update_recording_buttons()

    def on_pause_recording(self, event: wx.CommandEvent) -> None:
        self.recorder.pause(self._set_status)

    def on_resume_recording(self, event: wx.CommandEvent) -> None:
        self.recorder.resume(self._set_status)

    def on_stop_recording(self, event: wx.CommandEvent) -> None:
        self.recorder.stop(self._set_status)

    def available_recordings(self) -> list[Path]:
        recordings_dir = get_settings().recordings_dir
        recordings_dir.mkdir(parents=True, exist_ok=True)
        return sorted(
            recordings_dir.glob("*.wav"),
            key=lambda recording: recording.name.casefold(),
            reverse=True,
        )

    def refresh_recordings(self) -> None:
        self.processing_gauges.clear()
        self.processing_labels.clear()
        self.recordings_rows.Clear(delete_windows=True)
        recordings = self.available_recordings()
        if self.selected_recording not in recordings:
            self.selected_recording = None

        for recording in recordings:
            self.recordings_rows.Add(self._create_recording_row(recording), 0, wx.EXPAND)
        self.recordings_container.Layout()
        self.recordings_container.FitInside()
        self.practice_button.Enable(
            self.selected_recording is not None and is_processed_recording(self.selected_recording)
        )

    def _create_recording_row(self, recording: Path) -> wx.Panel:
        row = wx.Panel(self.recordings_container)
        row.recording_path = recording
        selected = recording == self.selected_recording
        row.SetBackgroundColour(wx.Colour(220, 235, 255) if selected else wx.WHITE)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        name = wx.StaticText(row, label=recording.name)
        name.recording_path = recording
        sizer.Add(name, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 7)

        processing = recording in self.processing_recordings
        processed = is_processed_recording(recording)
        if processing:
            percent, message = self.processing_progress.get(recording, (1, "Preparando…"))
            progress_sizer = wx.BoxSizer(wx.VERTICAL)
            progress_label = wx.StaticText(row, label=f"{message} {percent}%")
            progress_sizer.Add(progress_label, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 3)
            progress = wx.Gauge(row, range=100, size=(105, 12), style=wx.GA_HORIZONTAL)
            progress.SetValue(percent)
            self.processing_gauges[recording] = progress
            self.processing_labels[recording] = progress_label
            progress_sizer.Add(progress, 0, wx.EXPAND)
            sizer.Add(progress_sizer, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        else:
            process_button = wx.Button(row, label="Processar", size=(105, -1))
            process_button.recording_path = recording
            process_button.Enable(not processed)
            process_button.Bind(wx.EVT_BUTTON, self.on_process_recording)
            sizer.Add(process_button, 0, wx.ALL, 4)
        row.SetSizer(sizer)

        row.Bind(wx.EVT_LEFT_DOWN, self.on_recording_selected)
        name.Bind(wx.EVT_LEFT_DOWN, self.on_recording_selected)
        return row

    def on_recording_selected(self, event: wx.MouseEvent) -> None:
        recording = getattr(event.GetEventObject(), "recording_path", None)
        if recording is not None:
            self.selected_recording = recording
            # A linha que recebeu o clique será destruída por
            # refresh_recordings(). Adie a reconstrução para depois que wx
            # concluir o dispatch do evento; destruí-la agora pode causar um
            # segmentation fault no backend Cocoa.
            wx.CallAfter(self.refresh_recordings)

    def on_process_recording(self, event: wx.CommandEvent) -> None:
        recording = event.GetEventObject().recording_path
        if recording in self.processing_recordings or is_processed_recording(recording):
            return
        self.processing_recordings.add(recording)
        self.processing_progress[recording] = (1, "Preparando…")
        self.refresh_recordings()
        threading.Thread(
            target=self._process_recording_worker,
            args=(recording,),
            daemon=True,
            name=f"process-{recording.stem}",
        ).start()

    def _process_recording_worker(self, recording: Path) -> None:
        try:
            words_path = transcribe_recording(
                recording,
                progress_callback=lambda percent, message: wx.CallAfter(
                    self._set_processing_progress, recording, percent, message
                ),
            )
            group_words_file(
                words_path,
                progress_callback=lambda completed, total: wx.CallAfter(
                    self._set_processing_progress,
                    recording,
                    90 + round(9 * completed / max(1, total)),
                    "Criando sense groups…",
                ),
            )
        except Exception as error:
            wx.CallAfter(self._finish_processing, recording, str(error))
            return
        wx.CallAfter(self._finish_processing, recording, None)

    def _set_processing_progress(
        self, recording: Path, percent: int, message: str
    ) -> None:
        percent = max(0, min(100, int(percent)))
        self.processing_progress[recording] = (percent, message)
        gauge = self.processing_gauges.get(recording)
        label = self.processing_labels.get(recording)
        if gauge is not None and not gauge.IsBeingDeleted():
            gauge.SetValue(percent)
        if label is not None and not label.IsBeingDeleted():
            label.SetLabel(f"{message} {percent}%")
            label.GetParent().Layout()

    def _finish_processing(self, recording: Path, error: str | None) -> None:
        self.processing_recordings.discard(recording)
        self.processing_progress.pop(recording, None)
        self.refresh_recordings()
        if error:
            wx.MessageBox(
                f"Não foi possível processar {recording.name}.\n\n{error}",
                "Erro no processamento",
                wx.OK | wx.ICON_ERROR,
                self,
            )

    def on_practice_selected(self, event: wx.CommandEvent) -> None:
        recording = self.selected_recording
        if recording is None or not is_processed_recording(recording):
            return
        self.Hide()
        self.player_frame = TranscriptPlayer(
            None,
            f"Shadow Practice — {recording.name}",
            str(recording.with_suffix(".words.json")),
            str(recording),
        )
        self.player_frame.Bind(wx.EVT_CLOSE, self.on_player_close)
        self.player_frame.Show()

    def on_player_close(self, event: wx.CloseEvent) -> None:
        wx.CallAfter(self._restore_launcher)
        event.Skip()

    def _restore_launcher(self) -> None:
        self.player_frame = None
        if not self.IsBeingDeleted():
            self.refresh_recordings()
            self.Show()
            self.Raise()

    def on_close(self, event: wx.CloseEvent) -> None:
        if self.recorder.is_recording:
            self.recorder.stop(self._set_status)
        event.Skip()


def main() -> None:
    app = wx.App(False)
    frame = ShadowPracticeFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
