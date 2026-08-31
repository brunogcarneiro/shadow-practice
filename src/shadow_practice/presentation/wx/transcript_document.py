"""Documento do transcript, regras de edição e persistência."""

import wx

from ...domain import (
    GroupRange,
    find_group_index,
)
from ...domain import (
    clamp_time as domain_clamp_time,
)
from ...domain import (
    group_data as domain_group_data,
)


class TranscriptDocumentBehavior:
    def load_transcript(self):
        result = self.transcript_session.load()

        self.selected_word_index = None
        self.current_text_column_width = self.calculate_text_column_width()
        self.normalize_groups()
        self.update_selected_word_details()
        self.refresh_transcript_view()
        if result.needs_save:
            self.save_transcript()



    def get_group_data(self, group_index):
        return domain_group_data(self.words, self.groups[group_index])



    def get_group_index_for_word_index(self, word_index):
        return find_group_index(self.groups, word_index)



    def is_group_displayed(self, group_index):
        return 0 <= group_index < len(self.groups) and bool(self.groups[group_index].displayed)



    def is_word_displayed(self, word_index):
        group_index = self.get_group_index_for_word_index(word_index)
        if group_index is None:
            return True
        return self.is_group_displayed(group_index)



    def validate_group_ranges(self):
        self.transcript_session.validate()



    def debug_log(self, message):
        if self.debug_enabled:
            print(f"[player-debug] {message}")



    def debug_word_snapshot(self, group_index=None, word_index=None):
        if group_index is None:
            return f"words={len(self.words)} groups={len(self.groups)}"

        if group_index < 0 or group_index >= len(self.groups):
            return f"group={group_index} out-of-range words={len(self.words)} groups={len(self.groups)}"

        group = self.groups[group_index]
        if word_index is None:
            return (
                f"group={group_index} range=[{group.start_index},{group.end_index}) "
                f"size={group.end_index - group.start_index}"
            )

        if word_index < 0 or word_index >= len(self.words):
            return f"group={group_index} word={word_index} out-of-range"

        word = self.words[word_index]
        return f"group={group_index} word={word_index} token={word.get('word')!r}"



    def clamp_time(self, value):
        return domain_clamp_time(value, self.audio_length)



    def shift_group_indexes_after_insert(self, insert_index):
        for group in self.groups:
            if group.start_index >= insert_index:
                group.start_index += 1
                group.end_index += 1
            elif group.end_index > insert_index:
                group.end_index += 1



    def shift_group_indexes_after_delete(self, delete_index):
        empty_groups = []
        for group in self.groups:
            if group.start_index > delete_index:
                group.start_index -= 1
                group.end_index -= 1
            elif group.start_index <= delete_index < group.end_index:
                group.end_index -= 1
            elif group.end_index > delete_index:
                group.end_index -= 1

            if group.start_index >= group.end_index:
                empty_groups.append(group)

        for group in empty_groups:
            self.groups.remove(group)



    def update_selected_group_controls(self):
        checkbox = getattr(self, "selected_group_displayed_checkbox", None)
        if checkbox is None:
            return
        group_index = self.get_active_group_index()
        has_group = group_index is not None and 0 <= group_index < len(self.groups)
        can_split_from = False
        can_split_until = False
        if has_group and self.selected_word_index is not None and 0 <= self.selected_word_index < len(self.words):
            group = self.groups[group_index]
            if group.start_index <= self.selected_word_index < group.end_index:
                can_split_from = self.selected_word_index > group.start_index
                can_split_until = self.selected_word_index < (group.end_index - 1)
        self.updating_selected_group_controls = True
        try:
            checkbox.Enable(has_group)
            checkbox.SetValue(bool(self.groups[group_index].displayed) if has_group else False)
            if hasattr(self, "selected_new_group_from_btn"):
                self.selected_new_group_from_btn.Enable(can_split_from)
            if hasattr(self, "selected_new_group_until_btn"):
                self.selected_new_group_until_btn.Enable(can_split_until)
        finally:
            self.updating_selected_group_controls = False
        self.refresh_waveform_panel()



    def on_loop_group_playback_changed(self, event):
        self.loop_group_playback = bool(self.loop_group_playback_checkbox.GetValue())
        if not self.is_playing:
            return

        group_index = self.get_active_group_index()
        if group_index is None or not (0 <= group_index < len(self.groups)):
            self.playback_loop_range = None
            return

        start, end = self.get_group_playback_range(group_index)
        if not self.loop_group_playback:
            self.playback_loop_range = None
            return

        if not (start <= self.current_time < end):
            self.current_time = start
        self.playback_loop_range = (start, end)
        self.play_from(self.current_time, end)



    def on_selected_group_displayed_changed(self, event):
        if self.updating_selected_group_controls:
            return
        group_index = self.get_active_group_index()
        if group_index is None or not (0 <= group_index < len(self.groups)):
            return

        group = self.groups[group_index]
        new_value = bool(self.selected_group_displayed_checkbox.GetValue())
        if bool(group.displayed) == new_value:
            return

        group.displayed = new_value
        self.save_transcript()
        self.refresh_affected_group_rows([group], selected_index=group_index)
        self.update_selected_group_controls()
        if self.selected_word_index is not None and self.get_group_index_for_word_index(self.selected_word_index) == group_index:
            self.select_word(self.selected_word_index)



    def on_split_group_from_selected_word(self, event):
        self.split_group_at_selected_word(create_new_group_after=True)



    def on_split_group_until_selected_word(self, event):
        self.split_group_at_selected_word(create_new_group_after=False)



    def split_group_at_selected_word(self, create_new_group_after):
        word_index = self.selected_word_index
        group_index = self.get_active_group_index()
        if (
            word_index is None or
            group_index is None or
            not (0 <= word_index < len(self.words)) or
            not (0 <= group_index < len(self.groups))
        ):
            wx.Bell()
            return

        group = self.groups[group_index]
        if not (group.start_index <= word_index < group.end_index):
            wx.Bell()
            return

        if create_new_group_after:
            if word_index <= group.start_index:
                wx.Bell()
                return
            new_group = GroupRange(
                word_index,
                group.end_index,
                group.displayed,
                "",
            )
            group.end_index = word_index
            self.groups.insert(group_index + 1, new_group)
            selected_group_index = group_index + 1
        else:
            if word_index >= group.end_index - 1:
                wx.Bell()
                return
            new_group = GroupRange(
                group.start_index,
                word_index + 1,
                group.displayed,
                "",
            )
            group.start_index = word_index + 1
            self.groups.insert(group_index, new_group)
            selected_group_index = group_index

        new_group.human_transcription = ""
        self.clear_runtime_group_clips()
        self.save_transcript()
        self.refresh_affected_group_rows([group, new_group], selected_index=selected_group_index)
        self.select_word(word_index)



    def normalize_groups(self):
        self.transcript_session.normalize(self.audio_length)



    def clear_runtime_group_clips(self):
        self.transcript_session.clear_runtime_clips()
        self.playback_loop_range = None
        self.refresh_waveform_panel()



    def can_move_word_to_previous_group(self, group_index):
        if group_index < 0 or group_index >= len(self.groups):
            return False
        current_group = self.groups[group_index]
        if current_group.start_index >= current_group.end_index:
            return False
        if group_index == 0:
            return current_group.end_index - current_group.start_index > 1
        previous_group = self.groups[group_index - 1]
        return (
            self.words[previous_group.start_index]["speaker"]
            == self.words[current_group.start_index]["speaker"]
        )



    def can_move_word_to_next_group(self, group_index):
        if group_index < 0 or group_index >= len(self.groups):
            return False
        current_group = self.groups[group_index]
        if current_group.start_index >= current_group.end_index:
            return False
        if group_index == len(self.groups) - 1:
            return current_group.end_index - current_group.start_index > 1
        next_group = self.groups[group_index + 1]
        return (
            self.words[next_group.start_index]["speaker"]
            == self.words[current_group.start_index]["speaker"]
        )



    def save_transcript(self):
        self.debug_log(f"save_transcript(before) {self.debug_word_snapshot()}")
        self.transcript_session.save()
        self.debug_log(f"save_transcript(after) {self.debug_word_snapshot()}")



    def on_reload_from_disk(self, event):
        # Let a pending focus-loss commit finish before making disk authoritative.
        self.call_after_if_alive(self.reload_from_disk)



    def reload_from_disk(self):
        self.stop_playback()
        self.load_transcript()



    def update_boundary_control(self, group_index, field):
        control = self.boundary_controls.get((group_index, field))
        if control is None:
            return
        group = self.groups[group_index]
        word_index = group.start_index if field == "start" else group.end_index - 1
        value = self.words[word_index][field]
        formatted_value = f"{value:.2f}"
        if control.GetValue() != formatted_value:
            control.ChangeValue(formatted_value)



    def sync_boundary_controls(self):
        for group_index in range(len(self.groups)):
            self.update_boundary_control(group_index, "start")
            self.update_boundary_control(group_index, "end")



    def commit_boundary_control(self, control):
        if control is None:
            return
        self.commit_boundary_value(
            control.boundary_group_index,
            control.boundary_field,
            control.GetValue().strip(),
        )



    def on_boundary_kill_focus(self, event, control):
        raw_value = control.GetValue().strip() if control is not None else ""
        group_index = getattr(control, "boundary_group_index", None)
        field = getattr(control, "boundary_field", None)
        self.call_after_if_alive(self.commit_boundary_value, group_index, field, raw_value)
        event.Skip()



    def commit_boundary_value(self, group_index, field, raw_value):
        if group_index is None or field is None:
            return
        if group_index < 0 or group_index >= len(self.groups):
            return

        group = self.groups[group_index]
        word_index = group.start_index if field == "start" else group.end_index - 1
        current_value = self.words[word_index][field]
        if raw_value == f"{current_value:.2f}":
            return

        try:
            new_value = float(raw_value)
        except ValueError:
            wx.MessageBox("Digite um número válido.", "Valor inválido", wx.OK | wx.ICON_ERROR)
            self.update_boundary_control(group_index, field)
            return

        self.apply_group_boundary_edit(group_index, field, new_value)



    def move_word_to_previous_group(self, group_index):
        if not self.can_move_word_to_previous_group(group_index):
            wx.Bell()
            return

        self.stop_playback()
        source_group = self.groups[group_index]
        affected_groups = [source_group]
        if group_index == 0:
            new_group = GroupRange(
                source_group.start_index,
                source_group.start_index + 1,
                source_group.displayed,
                "",
            )
            source_group.start_index += 1
            self.groups.insert(0, new_group)
            affected_groups.append(new_group)
            selected_index = 1 if len(self.groups) > 1 else 0
        else:
            destination_group = self.groups[group_index - 1]
            destination_group.end_index += 1
            source_group.start_index += 1
            affected_groups.append(destination_group)
            selected_index = group_index - 1

        if group_index > 0 and source_group.start_index >= source_group.end_index:
            self.groups.pop(group_index)
            selected_index = min(selected_index, len(self.groups) - 1)

        self.clear_runtime_group_clips()
        self.save_transcript()
        self.refresh_affected_group_rows(affected_groups, selected_index=selected_index)



    def move_word_to_next_group(self, group_index):
        if not self.can_move_word_to_next_group(group_index):
            wx.Bell()
            return

        self.stop_playback()
        was_last_group = group_index == len(self.groups) - 1
        source_group = self.groups[group_index]
        affected_groups = [source_group]
        if was_last_group:
            source_group.end_index -= 1
            new_group = GroupRange(
                source_group.end_index,
                source_group.end_index + 1,
                source_group.displayed,
                "",
            )
            self.groups.append(new_group)
            affected_groups.append(new_group)
            selected_index = group_index
        else:
            destination_group = self.groups[group_index + 1]
            source_group.end_index -= 1
            destination_group.start_index -= 1
            affected_groups.append(destination_group)
            selected_index = group_index + 1

        if source_group.start_index >= source_group.end_index:
            self.groups.pop(group_index)
            if was_last_group:
                selected_index = min(group_index - 1, len(self.groups) - 1)
            else:
                selected_index = max(0, selected_index - 1)

        self.clear_runtime_group_clips()
        self.save_transcript()
        self.refresh_affected_group_rows(affected_groups, selected_index=selected_index)



    def validate_group_boundary(self, group_index, field, new_value):
        group = self.groups[group_index]
        first_word = self.words[group.start_index]
        last_word = self.words[group.end_index - 1]
        current_start = first_word["start"]
        current_end = last_word["end"]

        if field == "start":
            if new_value < 0 or new_value >= current_end:
                return False, "O start deve ser maior ou igual a 0 e menor que o end do grupo."
            if new_value > first_word["end"]:
                return False, "O start não pode ser maior que o end da primeira palavra do grupo."
        else:
            if new_value > self.audio_length:
                return False, f"O end não pode ser maior que a duração do áudio ({self.audio_length:.2f}s)."
            if new_value <= current_start:
                return False, "O end deve ser maior que o start do grupo."
            if new_value < last_word["start"]:
                return False, "O end não pode ser menor que o start da última palavra do grupo."

        return True, None



    def apply_group_boundary_edit(self, group_index, field, new_value):
        is_valid, error_message = self.validate_group_boundary(group_index, field, new_value)
        if not is_valid:
            wx.MessageBox(error_message, "Valor inválido", wx.OK | wx.ICON_ERROR)
            self.update_boundary_control(group_index, field)
            return False

        group = self.groups[group_index]
        if field == "start":
            self.words[group.start_index]["start"] = self.clamp_time(new_value)
        else:
            last_word = self.words[group.end_index - 1]
            last_word["end"] = self.clamp_time(new_value)
            if group_index + 1 < len(self.groups):
                next_group = self.groups[group_index + 1]
                next_first_word = self.words[next_group.start_index]
                if last_word["end"] > next_first_word["start"]:
                    next_first_word["start"] = last_word["end"]

        self.stop_playback()
        self.current_time = self.clamp_time(self.current_time)
        self.normalize_groups()
        self.sync_boundary_controls()
        self.update_selected_word_details()
        self.save_transcript()
        return True

    # ---------------- AUDIO CONTROL ----------------
