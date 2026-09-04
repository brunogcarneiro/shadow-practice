"""Ponto único de entrada da interface do Shadow Practice."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import soundfile as sf
import wx

from ...config import get_settings
from ...infrastructure.recording import RecordingController
from .main_frame import TranscriptPlayer
from .processing_details import ProcessingDetailsFrame


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


def processing_artifacts(audio_path: Path) -> list[Path]:
    """Return processing-owned files associated with an audio recording."""
    return [
        path
        for path in (
            audio_path.with_suffix(".words.json"),
            audio_path.with_suffix(".speaks.json"),
        )
        if path.is_file()
    ]


def delete_recording_data(audio_path: Path, include_audio: bool = False) -> list[Path]:
    """Delete generated artifacts and, when requested, the source audio."""
    targets = processing_artifacts(audio_path)
    if include_audio and audio_path.is_file():
        targets.append(audio_path)
    for target in targets:
        target.unlink()
    return targets


def audio_file_details(audio_path: Path) -> tuple[str, str]:
    """Return compact duration and binary-size labels for a WAV file."""
    try:
        duration = max(0, round(float(sf.info(audio_path).duration)))
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        duration_label = (
            f"{hours}:{minutes:02d}:{seconds:02d}"
            if hours
            else f"{minutes}:{seconds:02d}"
        )
        size = audio_path.stat().st_size
    except (OSError, RuntimeError, ValueError):
        return "—", "—"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(size)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    size_label = f"{amount:.1f} {unit}" if unit != "B" else f"{size} B"
    return duration_label, size_label


class ShadowPracticeFrame(wx.Frame):
    """Tela inicial: gravação, processamento e seleção para prática."""

    def __init__(self):
        super().__init__(None, title="Shadow Practice", size=(1040, 560))
        self.recorder = RecordingController()
        self.selected_recording: Path | None = None
        self.processing_recordings: set[Path] = set()
        self.processing_progress: dict[Path, tuple[int, str]] = {}
        self.processing_logs: dict[Path, list[dict]] = {}
        self.processing_jobs: dict[Path, subprocess.Popen] = {}
        self.processing_cancelled: set[Path] = set()
        self.processing_detail_frames: dict[Path, ProcessingDetailsFrame] = {}
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
        duration = wx.StaticText(header, label="Duração", size=(75, -1))
        size = wx.StaticText(header, label="Tamanho", size=(85, -1))
        process = wx.StaticText(header, label="Processamento")
        font = name.GetFont()
        font.MakeBold()
        name.SetFont(font)
        duration.SetFont(font)
        size.SetFont(font)
        process.SetFont(font)
        sizer.Add(name, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        sizer.Add(duration, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        sizer.Add(size, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
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
        duration, size = audio_file_details(recording)
        sizer.Add(
            wx.StaticText(row, label=duration, size=(75, -1)),
            0,
            wx.ALL | wx.ALIGN_CENTER_VERTICAL,
            6,
        )
        sizer.Add(
            wx.StaticText(row, label=size, size=(85, -1)),
            0,
            wx.ALL | wx.ALIGN_CENTER_VERTICAL,
            6,
        )

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
            stop_button = wx.Button(row, label="Interromper", size=(90, -1))
            stop_button.recording_path = recording
            stop_button.Bind(wx.EVT_BUTTON, self.on_interrupt_processing)
            details_button = wx.Button(row, label="Detalhes", size=(75, -1))
            details_button.recording_path = recording
            details_button.Bind(wx.EVT_BUTTON, self.on_show_processing_details)
            sizer.Add(stop_button, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
            sizer.Add(details_button, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        else:
            process_button = wx.Button(row, label="Processar", size=(105, -1))
            process_button.recording_path = recording
            process_button.Enable(not processed)
            process_button.Bind(wx.EVT_BUTTON, self.on_process_recording)
            sizer.Add(process_button, 0, wx.ALL, 4)
            delete_button = wx.Button(row, label="Excluir…", size=(85, -1))
            delete_button.recording_path = recording
            delete_button.Bind(wx.EVT_BUTTON, self.on_delete_recording)
            sizer.Add(delete_button, 0, wx.ALL, 4)
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
        choice = wx.SingleChoiceDialog(
            self,
            "Como deseja processar esta gravação?",
            "Modo de processamento",
            [
                "Transcrever o áudio normalmente",
                "Importar transcrição e alinhar ao áudio",
            ],
        )
        if choice.ShowModal() != wx.ID_OK:
            choice.Destroy()
            return
        selected_mode = choice.GetSelection()
        choice.Destroy()

        transcript_path = None
        if selected_mode == 1:
            file_dialog = wx.FileDialog(
                self,
                "Selecione a transcrição exportada",
                wildcard="Arquivos de texto (*.txt)|*.txt|Todos os arquivos|*.*",
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
            )
            if file_dialog.ShowModal() != wx.ID_OK:
                file_dialog.Destroy()
                return
            transcript_path = Path(file_dialog.GetPath())
            file_dialog.Destroy()

        self._start_processing(recording, transcript_path)

    def on_delete_recording(self, event: wx.CommandEvent) -> None:
        recording = event.GetEventObject().recording_path
        if recording in self.processing_recordings:
            return
        choice = wx.SingleChoiceDialog(
            self,
            f"O que deseja excluir de {recording.name}?",
            "Excluir dados da gravação",
            [
                "Somente os arquivos produzidos pelo processamento",
                "Os arquivos produzidos e também o arquivo de áudio",
            ],
        )
        choice.SetSelection(0)
        if choice.ShowModal() != wx.ID_OK:
            choice.Destroy()
            return
        include_audio = choice.GetSelection() == 1
        choice.Destroy()

        consequence = (
            "O áudio e todos os dados processados serão excluídos permanentemente."
            if include_audio
            else "A transcrição e os dados de prática serão excluídos. O áudio será mantido."
        )
        confirmation = wx.MessageDialog(
            self,
            f"{consequence}\n\nDeseja continuar?",
            "Confirmar exclusão",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        )
        confirmed = confirmation.ShowModal() == wx.ID_YES
        confirmation.Destroy()
        if not confirmed:
            return
        try:
            deleted = delete_recording_data(recording, include_audio=include_audio)
        except OSError as error:
            wx.MessageBox(
                f"Não foi possível excluir os dados.\n\n{error}",
                "Erro na exclusão",
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return
        if include_audio:
            self.selected_recording = None
        self.processing_logs.pop(recording, None)
        self.refresh_recordings()
        if not deleted:
            wx.MessageBox(
                "Nenhum arquivo produzido pelo processamento foi encontrado.",
                "Excluir dados da gravação",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )

    def _start_processing(
        self, recording: Path, transcript_path: Path | None = None
    ) -> None:
        self.processing_recordings.add(recording)
        mode = "alinhamento forçado" if transcript_path is not None else "transcrição"
        self.processing_progress[recording] = (1, f"Preparando {mode}…")
        self.processing_logs[recording] = []
        self.processing_cancelled.discard(recording)
        self.refresh_recordings()
        threading.Thread(
            target=self._run_processing_subprocess,
            args=(recording, transcript_path),
            daemon=True,
            name=f"process-{recording.stem}",
        ).start()

    def _run_processing_subprocess(
        self, recording: Path, transcript_path: Path | None = None
    ) -> None:
        source_root = Path(__file__).resolve().parents[3]
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            value for value in (str(source_root), existing_pythonpath) if value
        )
        try:
            command = [
                sys.executable,
                "-m",
                "shadow_practice.application.processing_worker",
                str(recording.resolve()),
            ]
            if transcript_path is not None:
                command.extend(("--transcript", str(transcript_path.resolve())))
            process = subprocess.Popen(
                command,
                cwd=recording.resolve().parent,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            wx.CallAfter(self._register_processing_job, recording, process)
            assert process.stdout is not None
            for line in process.stdout:
                wx.CallAfter(self._handle_processing_output, recording, line.rstrip())
            return_code = process.wait()
        except Exception as error:
            wx.CallAfter(self._finish_processing, recording, str(error))
            return
        wx.CallAfter(
            self._finish_processing,
            recording,
            None if return_code == 0 else "Processing failed.",
            recording in self.processing_cancelled,
        )

    def _register_processing_job(self, recording: Path, process: subprocess.Popen) -> None:
        if recording not in self.processing_recordings or recording in self.processing_cancelled:
            process.terminate()
            return
        self.processing_jobs[recording] = process

    def _handle_processing_output(self, recording: Path, line: str) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = {
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "stage": "system",
                "data": {},
                "description": line,
            }
        if not isinstance(event, dict):
            return
        self.processing_logs.setdefault(recording, []).append(event)
        if "percent" in event:
            self._set_processing_progress(
                recording,
                event["percent"],
                str(event.get("description", event.get("stage", "Processing…"))),
            )
        details = self.processing_detail_frames.get(recording)
        if details is not None and not details.IsBeingDeleted():
            details.refresh()

    def on_interrupt_processing(self, event: wx.CommandEvent) -> None:
        self.interrupt_processing(event.GetEventObject().recording_path)

    def interrupt_processing(self, recording: Path) -> None:
        if recording not in self.processing_recordings:
            return
        self.processing_cancelled.add(recording)
        process = self.processing_jobs.get(recording)
        if process is not None and process.poll() is None:
            process.terminate()
        self._handle_processing_output(
            recording,
            json.dumps(
                {
                    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "stage": "interruption",
                    "data": {"requested": True},
                    "description": "Interrupção solicitada pelo usuário.",
                }
            ),
        )

    def on_show_processing_details(self, event: wx.CommandEvent) -> None:
        recording = event.GetEventObject().recording_path
        frame = self.processing_detail_frames.get(recording)
        if frame is None or frame.IsBeingDeleted():
            frame = ProcessingDetailsFrame(self, recording)
            self.processing_detail_frames[recording] = frame
        self.Hide()
        frame.Show()
        frame.Raise()

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

    def _finish_processing(
        self, recording: Path, error: str | None, cancelled: bool = False
    ) -> None:
        self.processing_recordings.discard(recording)
        self.processing_progress.pop(recording, None)
        self.processing_jobs.pop(recording, None)
        self.refresh_recordings()
        details = self.processing_detail_frames.get(recording)
        if details is not None and not details.IsBeingDeleted():
            details.refresh()
        self.processing_cancelled.discard(recording)
        if error and not cancelled:
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
        for process in self.processing_jobs.values():
            if process.poll() is None:
                process.terminate()
        event.Skip()


def main() -> None:
    app = wx.App(False)
    frame = ShadowPracticeFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
