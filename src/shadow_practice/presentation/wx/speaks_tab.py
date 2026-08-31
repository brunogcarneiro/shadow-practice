import io
import os
import wave

import simpleaudio as sa
import wx

from ...domain.speaks import build_speaks_from_groups
from ...domain.transcript import split_rewrite_paragraphs
from ...infrastructure.persistence.json_repository import load_json, save_json_atomic


class SpeaksBehavior:
    def create_selected_detail_control(self, parent, sizer, label, width):
        sizer.Add(wx.StaticText(parent, label=f"{label}:"), 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 8)
        control = wx.TextCtrl(parent, value="", size=(width, -1), style=wx.TE_PROCESS_ENTER | wx.BORDER_SIMPLE)
        control.SetForegroundColour(wx.Colour(0, 0, 0))
        control.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        control.detail_field = label.lower()
        control.Bind(wx.EVT_TEXT_ENTER, self.on_selected_word_detail_commit)
        control.Bind(wx.EVT_KILL_FOCUS, self.on_selected_word_detail_kill_focus)
        sizer.Add(control, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        return control


    @staticmethod
    def get_speaks_file_path(transcript_file):
        suffix = ".words.json"
        if transcript_file.endswith(suffix):
            return transcript_file[:-len(suffix)] + ".speaks.json"
        return os.path.splitext(transcript_file)[0] + ".speaks.json"


    def on_notebook_page_changed(self, event):
        if self.notebook.GetPage(event.GetSelection()) is self.falas_tab:
            self.load_or_initialize_speaks()
            self.check_qwen_tts_status()
        event.Skip()


    def check_qwen_tts_status(self):
        if self.tts_status_check_in_progress:
            return
        self.tts_status_check_in_progress = True
        self.tts_status_label.SetLabel("TTS local: verificando…")
        self.generative_tasks.submit(
            self.qwen_tts_status_worker,
            lambda status, error: self.call_after_if_alive(
                self.finish_qwen_tts_status_check,
                status if error is None else "TTS local: indisponível",
            ),
        )


    def qwen_tts_status_worker(self):
        try:
            payload = self.generative_models.get_tts_health()
            return f'TTS local: pronto ({payload.get("speaker", "Aiden")})'
        except Exception:
            return "TTS local: indisponível"


    def finish_qwen_tts_status_check(self, status):
        self.tts_status_check_in_progress = False
        if hasattr(self, "tts_status_label") and not self.tts_status_label.IsBeingDeleted():
            self.tts_status_label.SetLabel(status)


    def build_speaks_from_groups(self):
        return build_speaks_from_groups(self.words, self.groups)


    def save_speaks(self):
        save_json_atomic(self.speaks_file, self.speaks, ".speaks-")


    def load_or_initialize_speaks(self):
        if not os.path.exists(self.speaks_file):
            self.speaks = self.build_speaks_from_groups()
            self.save_speaks()
        else:
            payload = load_json(self.speaks_file)
            if not isinstance(payload, list):
                raise ValueError("O arquivo speaks.json deve conter uma lista de falas.")
            self.speaks = []
            needs_save = False
            for item in payload:
                if not isinstance(item, dict):
                    continue
                raw_rewrite = item.get("rewrited", [])
                if isinstance(raw_rewrite, list):
                    rewrited = [str(paragraph) for paragraph in raw_rewrite]
                    needs_save = needs_save or any(
                        not isinstance(paragraph, str) for paragraph in raw_rewrite
                    )
                else:
                    rewrited = self.split_rewrite_paragraphs(str(raw_rewrite or ""))
                    needs_save = True
                self.speaks.append({
                    "speaker": str(item.get("speaker", "")),
                    "start": float(item.get("start", 0)),
                    "end": float(item.get("end", 0)),
                    "human-transcription": str(item.get("human-transcription", "")),
                    "rewrited": rewrited,
                })
            if needs_save:
                self.save_speaks()
        self.populate_speaks_table()


    def get_speaks_text_column_width(self):
        available_width = self.speaks_container.GetClientSize().width
        fixed_width = (
            self.SPEAK_SPEAKER_COLUMN_WIDTH +
            self.SPEAK_START_COLUMN_WIDTH +
            self.SPEAK_END_COLUMN_WIDTH +
            24  # margens das três colunas fixas
        )
        # Cada célula recebe 4px de margem em cada lado.
        return max(
            self.SPEAK_TEXT_COLUMN_MIN_WIDTH,
            (available_width - fixed_width - 16) // 2,
        )


    def create_speaks_header_row(self):
        panel = wx.Panel(self.falas_tab)
        panel.SetBackgroundColour(wx.Colour(235, 235, 235))
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        panel.SetSizer(sizer)
        self.add_speaks_cell(panel, sizer, "Speaker", self.SPEAK_SPEAKER_COLUMN_WIDTH, bold=True)
        self.add_speaks_cell(panel, sizer, "Start", self.SPEAK_START_COLUMN_WIDTH, bold=True)
        self.add_speaks_cell(panel, sizer, "End", self.SPEAK_END_COLUMN_WIDTH, bold=True)
        self.speaks_human_header = self.add_speaks_cell(panel, sizer, "Human Transcription", 0, bold=True)
        self.speaks_rewrited_header = self.add_speaks_cell(panel, sizer, "Rewrite", 0, bold=True)
        return panel


    def add_speaks_cell(self, parent, sizer, label, width, bold=False):
        cell = wx.StaticText(parent, label=label)
        if bold:
            cell.SetFont(cell.GetFont().Bold())
        if width:
            cell.SetMinSize((width, -1))
            sizer.Add(cell, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        else:
            sizer.Add(cell, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        return cell


    def on_speaks_container_size(self, event):
        event.Skip()
        if not self.is_ui_alive():
            return
        if self.speaks_resize_call is not None:
            self.speaks_resize_call.Stop()
        self.speaks_resize_call = wx.CallLater(120, self.populate_speaks_table)


    def populate_speaks_table(self):
        if not self.is_ui_alive() or not hasattr(self, "speaks_rows_sizer"):
            return
        self.speaks_resize_call = None
        text_width = self.get_speaks_text_column_width()
        if self.selected_speak_index is not None and self.selected_speak_index >= len(self.speaks):
            self.selected_speak_index = None
        self.falas_tab.Freeze()
        try:
            self.speaks_human_header.SetMinSize((text_width, -1))
            self.speaks_rewrited_header.SetMinSize((text_width, -1))
            self.selected_rewrite_paragraph_control = None
            self.speaks_rows_sizer.Clear(delete_windows=True)
            self.speaks_row_panels = {}
            self.speaks_rewrite_controls = {}
            self.rewrite_paragraph_controls = {}
            for row_index, speak in enumerate(self.speaks):
                row = wx.Panel(self.speaks_container)
                self.set_speak_row_selected(row, row_index == self.selected_speak_index, row_index)
                row_sizer = wx.BoxSizer(wx.HORIZONTAL)
                row.SetSizer(row_sizer)

                cells = [
                    self.add_speaks_row_cell(row, row_sizer, speak["speaker"], self.SPEAK_SPEAKER_COLUMN_WIDTH),
                    self.add_speaks_row_cell(row, row_sizer, f'{speak["start"]:.2f}', self.SPEAK_START_COLUMN_WIDTH),
                    self.add_speaks_row_cell(row, row_sizer, f'{speak["end"]:.2f}', self.SPEAK_END_COLUMN_WIDTH),
                ]
                human_cell = self.add_speaks_row_cell(
                    row, row_sizer, speak["human-transcription"], text_width
                )
                cells.append(human_cell)
                human_cell.Bind(wx.EVT_LEFT_DCLICK, self.on_speak_human_transcription_double_click)
                rewrite_cell = self.create_speaks_rewrite_cell(
                    row, row_sizer, row_index, speak["rewrited"], text_width
                )
                row.speak_index = row_index
                row.Bind(wx.EVT_LEFT_DOWN, self.on_speak_row_clicked)
                for cell in cells:
                    cell.speak_index = row_index
                    cell.Bind(wx.EVT_LEFT_DOWN, self.on_speak_row_clicked)
                self.speaks_row_panels[row_index] = row
                self.speaks_rewrite_controls[row_index] = rewrite_cell
                self.speaks_rows_sizer.Add(row, 0, wx.EXPAND)
            self.speaks_container.Layout()
            self.speaks_container.FitInside()
            self.falas_tab.Layout()
            self.update_rewrite_speak_button()
        finally:
            self.falas_tab.Thaw()


    def add_speaks_row_cell(self, row, sizer, value, width):
        cell = wx.StaticText(row, label=str(value))
        cell.Wrap(width)
        cell.SetMinSize((width, -1))
        sizer.Add(cell, 0, wx.ALL | wx.ALIGN_TOP, 4)
        return cell


    @staticmethod
    def split_rewrite_paragraphs(text):
        return split_rewrite_paragraphs(text)


    def create_speaks_rewrite_cell(self, row, row_sizer, speak_index, paragraphs, width):
        cell = wx.Panel(row)
        cell.SetMinSize((width, -1))
        cell_sizer = wx.BoxSizer(wx.VERTICAL)
        cell.SetSizer(cell_sizer)
        self.populate_speaks_rewrite_cell(cell, speak_index, paragraphs, width)
        row_sizer.Add(cell, 0, wx.ALL | wx.ALIGN_TOP, 4)
        return cell


    def populate_speaks_rewrite_cell(self, cell, speak_index, paragraphs, width):
        cell_sizer = cell.GetSizer()
        if (
            self.selected_rewrite_paragraph_control is not None and
            self.selected_rewrite_paragraph_control.GetParent() is cell
        ):
            self.selected_rewrite_paragraph_control = None
        cell_sizer.Clear(delete_windows=True)
        normalized_paragraphs = [str(paragraph) for paragraph in paragraphs if str(paragraph).strip()]
        for paragraph_index, paragraph in enumerate(normalized_paragraphs):
            paragraph_ctrl = wx.StaticText(cell, label=paragraph)
            paragraph_ctrl.Wrap(width)
            paragraph_ctrl.SetMinSize((width, -1))
            paragraph_ctrl.speak_index = speak_index
            paragraph_ctrl.rewrite_paragraph_index = paragraph_index
            paragraph_ctrl.Bind(wx.EVT_LEFT_DOWN, self.on_rewrite_paragraph_clicked)
            paragraph_ctrl.Bind(wx.EVT_LEFT_DCLICK, self.on_rewrite_paragraph_double_click)
            self.rewrite_paragraph_controls[(speak_index, paragraph_index)] = paragraph_ctrl
            if self.selected_rewrite_paragraph == (speak_index, paragraph_index):
                paragraph_ctrl.SetBackgroundColour(wx.Colour(255, 245, 180))
                self.selected_rewrite_paragraph_control = paragraph_ctrl
            cell_sizer.Add(paragraph_ctrl, 0, wx.BOTTOM, 6 if paragraph_index + 1 < len(normalized_paragraphs) else 0)
        cell.Layout()


    def on_rewrite_paragraph_clicked(self, event):
        paragraph_ctrl = event.GetEventObject()
        speak_index = getattr(paragraph_ctrl, "speak_index", None)
        paragraph_index = getattr(paragraph_ctrl, "rewrite_paragraph_index", None)
        if speak_index is None or paragraph_index is None:
            return
        self.select_speak(speak_index)
        previous_ctrl = self.selected_rewrite_paragraph_control
        if previous_ctrl is not None and previous_ctrl is not paragraph_ctrl and not previous_ctrl.IsBeingDeleted():
            previous_ctrl.SetBackgroundColour(wx.NullColour)
            previous_ctrl.Refresh()
        self.selected_rewrite_paragraph = (speak_index, paragraph_index)
        self.selected_rewrite_paragraph_control = paragraph_ctrl
        paragraph_ctrl.SetBackgroundColour(wx.Colour(255, 245, 180))
        paragraph_ctrl.Refresh()


    def on_rewrite_paragraph_double_click(self, event):
        paragraph_ctrl = event.GetEventObject()
        speak_index = getattr(paragraph_ctrl, "speak_index", None)
        paragraph_index = getattr(paragraph_ctrl, "rewrite_paragraph_index", None)
        if speak_index is None or paragraph_index is None:
            return
        self.on_rewrite_paragraph_clicked(event)
        self.synthesize_rewrite_paragraph(speak_index, paragraph_index)


    def synthesize_rewrite_paragraph(self, speak_index, paragraph_index):
        if not (0 <= speak_index < len(self.speaks)):
            return
        paragraphs = self.speaks[speak_index].get("rewrited", [])
        if not (0 <= paragraph_index < len(paragraphs)):
            return
        paragraph_key = (speak_index, paragraph_index)
        if paragraph_key in self.tts_in_progress_paragraphs:
            return

        text = str(paragraphs[paragraph_index]).strip()
        if not text:
            return
        self.tts_in_progress_paragraphs.add(paragraph_key)
        self.set_rewrite_paragraph_generating(paragraph_key, True)
        self.generative_tasks.submit(
            lambda: self.generative_models.synthesize_speech(text),
            lambda audio_bytes, error: self.call_after_if_alive(
                self.finish_rewrite_paragraph_synthesis,
                paragraph_key,
                audio_bytes,
                None if error is None else str(error),
            ),
        )


    def set_rewrite_paragraph_generating(self, paragraph_key, generating):
        paragraph_ctrl = self.rewrite_paragraph_controls.get(paragraph_key)
        if paragraph_ctrl is None or paragraph_ctrl.IsBeingDeleted():
            return
        paragraph_ctrl.SetForegroundColour(wx.Colour(0, 95, 180) if generating else wx.Colour(0, 0, 0))
        paragraph_ctrl.Refresh()


    def finish_rewrite_paragraph_synthesis(self, paragraph_key, audio_bytes, error_message):
        if not self.is_ui_alive():
            return
        self.tts_in_progress_paragraphs.discard(paragraph_key)
        self.set_rewrite_paragraph_generating(paragraph_key, False)
        if error_message is not None:
            if hasattr(self, "tts_status_label"):
                self.tts_status_label.SetLabel("TTS local: erro")
            wx.MessageBox(
                f"Não foi possível sintetizar o parágrafo.\n\n{error_message}",
                "Erro no Qwen3-TTS",
                wx.OK | wx.ICON_ERROR,
            )
            return

        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
                audio_data = wav_file.readframes(wav_file.getnframes())
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
            self.stop_playback()
            self.tts_play_obj = sa.play_buffer(audio_data, channels, sample_width, sample_rate)
            self.tts_status_label.SetLabel("TTS local: reproduzindo (Aiden)")
        except Exception as error:
            wx.MessageBox(
                f"O serviço retornou um WAV inválido.\n\n{error}",
                "Erro no Qwen3-TTS",
                wx.OK | wx.ICON_ERROR,
            )


    def set_speak_row_selected(self, row, selected, row_index):
        if selected:
            row.SetBackgroundColour(wx.Colour(210, 230, 250))
        elif row_index % 2:
            row.SetBackgroundColour(wx.Colour(248, 248, 248))
        else:
            row.SetBackgroundColour(wx.WHITE)


    def update_rewrite_speak_button(self):
        can_rewrite = (
            self.selected_speak_index is not None and
            0 <= self.selected_speak_index < len(self.speaks) and
            bool(self.speaks[self.selected_speak_index]["human-transcription"].strip()) and
            not self.rewrite_in_progress
        )
        self.rewrite_speak_btn.Enable(can_rewrite)


    def on_speak_row_clicked(self, event):
        speak_index = getattr(event.GetEventObject(), "speak_index", None)
        if speak_index is not None:
            self.select_speak(speak_index)
        event.Skip()


    def select_speak(self, speak_index):
        if not (0 <= speak_index < len(self.speaks)):
            return
        previous_index = self.selected_speak_index
        self.selected_speak_index = speak_index
        for row_index in {previous_index, speak_index}:
            row = self.speaks_row_panels.get(row_index)
            if row is not None:
                self.set_speak_row_selected(row, row_index == speak_index, row_index)
                row.Refresh()
        self.update_rewrite_speak_button()


    def on_speak_human_transcription_double_click(self, event):
        speak_index = getattr(event.GetEventObject(), "speak_index", None)
        if speak_index is not None:
            self.select_speak(speak_index)
            self.play_speak(speak_index)


    def on_rewrite_selected_speak(self, event):
        speak_index = self.selected_speak_index
        if (
            speak_index is None or
            not (0 <= speak_index < len(self.speaks)) or
            self.rewrite_in_progress
        ):
            return

        original_text = self.speaks[speak_index]["human-transcription"].strip()
        if not original_text:
            wx.Bell()
            return

        self.rewrite_in_progress = True
        self.update_rewrite_speak_button()
        self.generative_tasks.submit(
            lambda: self.generative_models.rewrite_meeting_speech(original_text),
            lambda rewritten_text, error: self.call_after_if_alive(
                self.finish_speak_rewrite,
                speak_index,
                rewritten_text,
                None if error is None else str(error),
            ),
        )


    def finish_speak_rewrite(self, speak_index, rewritten_text, error_message):
        if not self.is_ui_alive():
            return
        self.rewrite_in_progress = False
        try:
            if error_message is not None:
                wx.MessageBox(
                    f"Não foi possível reescrever a fala.\n\n{error_message}",
                    "Erro ao reescrever",
                    wx.OK | wx.ICON_ERROR,
                )
                return

            if not (0 <= speak_index < len(self.speaks)):
                return
            self.speaks[speak_index]["rewrited"] = self.split_rewrite_paragraphs(rewritten_text)
            self.save_speaks()

            rewrite_cell = self.speaks_rewrite_controls.get(speak_index)
            row = self.speaks_row_panels.get(speak_index)
            if rewrite_cell is not None:
                column_width = rewrite_cell.GetMinSize().width
                self.populate_speaks_rewrite_cell(
                    rewrite_cell,
                    speak_index,
                    self.speaks[speak_index]["rewrited"],
                    column_width,
                )
            if row is not None:
                row.Layout()
                row.Refresh()
            self.speaks_container.Layout()
            self.speaks_container.FitInside()
        finally:
            self.update_rewrite_speak_button()


    def play_speak(self, speak_index):
        if not (0 <= speak_index < len(self.speaks)):
            return

        speak = self.speaks[speak_index]
        start = self.clamp_time(speak["start"])
        end = self.clamp_time(speak["end"])
        if end < start:
            end = start

        self.current_time = start
        self.playback_loop_range = None
        self.update_slider_and_time()
        self.play_from(start, end)
        if not self.timer.IsRunning():
            self.timer.Start(self.PLAYBACK_TIMER_MS)
