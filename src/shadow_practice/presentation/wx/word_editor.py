"""Seleção e edição inline de palavras e transcrições humanas."""

import wx


class WordEditorBehavior:
    def update_selected_word_controls_enabled(self):
        has_selection = self.selected_word_index is not None and 0 <= self.selected_word_index < len(self.words)
        text_visible = has_selection and self.is_word_displayed(self.selected_word_index)
        for control in (
            getattr(self, "selected_speaker_ctrl", None),
            getattr(self, "selected_start_ctrl", None),
            getattr(self, "selected_end_ctrl", None),
            getattr(self, "selected_prev_gap_btn", None),
            getattr(self, "selected_next_gap_btn", None),
            getattr(self, "selected_delete_btn", None),
        ):
            if control is not None:
                control.Enable(has_selection)
        if getattr(self, "selected_word_ctrl", None) is not None:
            self.selected_word_ctrl.Enable(text_visible)
        self.update_selected_group_controls()



    def get_active_group_index(self):
        if self.selected_word_index is not None:
            group_index = self.get_group_index_for_word_index(self.selected_word_index)
            if group_index is not None:
                return group_index
        if self.selected_row_index is not None and 0 <= self.selected_row_index < len(self.groups):
            return self.selected_row_index
        return None



    def refresh_transcript_view(self, selected_index=None):
        self.debug_log(
            f"refresh_transcript_view(start) selected_index={selected_index} {self.debug_word_snapshot()}"
        )
        self.build_list_ctrl()

        if selected_index is not None and 0 <= selected_index < len(self.groups):
            self.select_row(selected_index)
        else:
            self.highlight_current_line(self.current_time)

        self.debug_log(
            f"refresh_transcript_view(end) selected_index={selected_index} {self.debug_word_snapshot()}"
        )



    def calculate_text_column_width(self):
        container_width = self.list_container.GetClientSize().width
        if container_width <= 0:
            return self.current_text_column_width

        fixed_columns_width = (
            self.SPEAKER_COLUMN_WIDTH + 8 +
            self.START_COLUMN_WIDTH + 8 +
            self.END_COLUMN_WIDTH + 8 +
            self.MOVE_COLUMN_WIDTH + 8
        )
        text_column_spacing = 8
        calculated_width = container_width - fixed_columns_width - text_column_spacing
        return max(self.TEXT_COLUMN_MIN_WIDTH, calculated_width)



    def get_word_control_width(self, word):
        text_width, _ = self.measure_text_ctrl.GetTextExtent(word or " ")
        return max(12, min(180, text_width + 6))



    def create_text_controls(self, row_index, parent=None, width=None):
        group_panel = wx.Panel(parent or self.list_container)
        available_width = width or self.current_text_column_width
        vertical_sizer = wx.BoxSizer(wx.VERTICAL)
        current_row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        current_row_width = 0
        row_has_controls = False
        row_count = 0

        def finish_current_row():
            nonlocal current_row_sizer, current_row_width, row_has_controls, row_count
            if not row_has_controls:
                return
            vertical_sizer.Add(current_row_sizer, 0, wx.BOTTOM, 2)
            row_count += 1
            current_row_sizer = wx.BoxSizer(wx.HORIZONTAL)
            current_row_width = 0
            row_has_controls = False

        group = self.groups[row_index]
        group_displayed = bool(group.displayed)
        for word_index in range(group.start_index, group.end_index):
            word_info = self.words[word_index]
            token = word_info["word"]
            wrapper = wx.Panel(group_panel)
            wrapper.is_word_wrapper = True
            wrapper.group_index = row_index
            wrapper.word_index = word_index
            wrapper.word_border_width = 3 if word_index == self.selected_word_index else 1
            wrapper_sizer = wx.BoxSizer(wx.VERTICAL)
            control = wx.TextCtrl(
                wrapper,
                value=token if group_displayed else "",
                size=(self.get_word_control_width(token), -1),
                style=wx.BORDER_NONE | wx.TE_PROCESS_ENTER,
            )
            control.SetEditable(False)
            control.SetForegroundColour(wx.Colour(0, 0, 0))
            control.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
            wrapper_sizer.Add(
                control,
                1,
                wx.EXPAND | wx.ALL,
                wrapper.word_border_width,
            )
            wrapper.SetSizerAndFit(wrapper_sizer)

            control.group_index = row_index
            control.word_index = word_index
            control.Bind(wx.EVT_LEFT_DOWN, self.on_word_selected)
            control.Bind(wx.EVT_LEFT_DCLICK, self.on_word_double_click_play)
            control.Bind(wx.EVT_TEXT_ENTER, self.on_inline_word_text_enter)
            control.Bind(wx.EVT_KEY_DOWN, self.on_inline_word_key_down)
            control.Bind(wx.EVT_KILL_FOCUS, self.on_inline_word_kill_focus)
            wrapper.Bind(wx.EVT_LEFT_DOWN, self.on_word_selected)
            wrapper.Bind(wx.EVT_LEFT_DCLICK, self.on_word_double_click_play)
            self.word_controls[word_index] = control
            self.word_wrappers[word_index] = wrapper
            self.set_word_wrapper_selected(
                wrapper,
                word_index == self.selected_word_index,
            )

            control_width = wrapper.GetSize().width + 4
            if row_has_controls and current_row_width + control_width > available_width:
                finish_current_row()

            current_row_sizer.Add(
                wrapper,
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT,
                2,
            )
            current_row_width += control_width
            row_has_controls = True

        finish_current_row()

        human_ctrl = wx.TextCtrl(
            group_panel,
            value=str(group.human_transcription or ""),
            style=wx.TE_PROCESS_ENTER | wx.BORDER_SIMPLE,
        )
        human_ctrl.group_index = row_index
        human_ctrl.human_group_index = row_index
        human_ctrl.Bind(wx.EVT_KILL_FOCUS, self.on_group_human_transcription_kill_focus)
        self.group_text_controls[row_index] = human_ctrl
        vertical_sizer.Add(
            human_ctrl,
            0,
            wx.TOP | wx.EXPAND,
            self.TEXT_ROW_GAP if row_count > 0 else 0,
        )

        group_panel.SetSizer(vertical_sizer)
        content_height = max(1, vertical_sizer.CalcMin().height)
        group_panel.SetMinSize(wx.Size(available_width, content_height))
        group_panel.SetSize(wx.Size(available_width, content_height))
        group_panel.Layout()
        self.debug_log(
            f"text layout group={row_index} rows={row_count} "
            f"width={available_width} height={content_height}"
        )
        return group_panel



    def set_word_wrapper_selected(self, wrapper, selected):
        if wrapper is None:
            return
        colour = wx.Colour(0, 150, 0) if selected else wx.Colour(120, 120, 120)
        border_width = 3 if selected else 1
        if getattr(wrapper, "word_border_width", None) != border_width:
            wrapper.word_border_width = border_width
            sizer = wrapper.GetSizer()
            if sizer is not None and sizer.GetItemCount() > 0:
                sizer.GetItem(0).SetBorder(border_width)
                wrapper.SetSizerAndFit(sizer)
        wrapper.SetBackgroundColour(colour)
        wrapper.Layout()
        wrapper.Refresh()



    def on_word_selected(self, event):
        widget = event.GetEventObject()
        word_index = getattr(widget, "word_index", None)
        if word_index is None or not (0 <= word_index < len(self.words)):
            event.Skip()
            return

        self.select_word(word_index)
        self.activate_inline_word_edit(word_index)
        event.StopPropagation()



    def on_word_double_click_play(self, event):
        widget = event.GetEventObject()
        word_index = getattr(widget, "word_index", None)
        if word_index is not None and 0 <= word_index < len(self.words):
            self.select_word(word_index)
            self.activate_inline_word_edit(word_index)
            self.play_word(word_index)
            self.call_after_if_alive(self.activate_inline_word_edit, word_index)
        event.StopPropagation()



    def select_word(self, word_index):
        previous_wrapper = self.word_wrappers.get(self.selected_word_index)
        self.set_word_wrapper_selected(previous_wrapper, False)
        self.selected_word_index = word_index
        self.set_word_wrapper_selected(self.word_wrappers.get(word_index), True)
        self.update_selected_word_details()



    def deactivate_inline_word_edit(self, word_index):
        control = self.word_controls.get(word_index)
        if control is not None:
            control.SetEditable(False)
        if self.editing_word_index == word_index:
            self.editing_word_index = None



    def activate_inline_word_edit(self, word_index):
        if not self.is_word_displayed(word_index):
            self.deactivate_inline_word_edit(self.editing_word_index) if self.editing_word_index is not None else None
            return

        if self.editing_word_index is not None and self.editing_word_index != word_index:
            self.deactivate_inline_word_edit(self.editing_word_index)

        control = self.word_controls.get(word_index)
        if control is None:
            group_index = self.get_group_index_for_word_index(word_index)
            if group_index is not None:
                self.scroll_row_into_view(group_index)
            control = self.word_controls.get(word_index)
            if control is None:
                return

        self.editing_word_index = word_index
        control.SetEditable(True)
        control.SetFocus()
        control.SetSelection(-1, -1)



    def commit_inline_word_edit(self, word_index, move_to_next=False):
        control = self.word_controls.get(word_index)
        if control is None or not (0 <= word_index < len(self.words)):
            return

        raw_value = control.GetValue().strip()
        next_word_index = word_index + 1 if move_to_next and word_index + 1 < len(self.words) else None
        self.deactivate_inline_word_edit(word_index)
        self.apply_selected_word_text_edit(word_index, raw_value)

        if next_word_index is not None:
            self.select_word(next_word_index)
            self.call_after_if_alive(self.activate_inline_word_edit, next_word_index)



    def on_inline_word_text_enter(self, event):
        word_index = getattr(event.GetEventObject(), "word_index", None)
        if word_index is None:
            event.Skip()
            return
        self.skip_word_kill_focus_word_index = word_index
        self.commit_inline_word_edit(word_index, move_to_next=True)



    def on_inline_word_key_down(self, event):
        control = event.GetEventObject()
        word_index = getattr(control, "word_index", None)
        key_code = event.GetKeyCode()
        if word_index is not None and key_code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_TAB, wx.WXK_SPACE):
            self.skip_word_kill_focus_word_index = word_index
            self.commit_inline_word_edit(word_index, move_to_next=True)
            return
        event.Skip()



    def on_inline_word_kill_focus(self, event):
        control = event.GetEventObject()
        word_index = getattr(control, "word_index", None)
        if word_index is not None:
            if self.skip_word_kill_focus_word_index == word_index:
                self.skip_word_kill_focus_word_index = None
            elif self.editing_word_index == word_index:
                self.call_after_if_alive(self.commit_inline_word_edit, word_index, False)
        event.Skip()



    def on_group_human_transcription_kill_focus(self, event):
        control = event.GetEventObject()
        if control is not None:
            self.call_after_if_alive(self.commit_group_human_transcription, control)
        event.Skip()



    def commit_group_human_transcription(self, control):
        if control is None:
            return
        group_index = getattr(control, "group_index", None)
        if group_index is None or not (0 <= group_index < len(self.groups)):
            return

        new_value = control.GetValue()
        group = self.groups[group_index]
        if group.human_transcription == new_value:
            return

        group.human_transcription = new_value
        self.save_transcript()



    def update_selected_word_details(self):
        values = ("", "", "", "")
        if self.selected_word_index is not None and 0 <= self.selected_word_index < len(self.words):
            word = self.words[self.selected_word_index]
            values = (
                str(word.get("word", "")) if self.is_word_displayed(self.selected_word_index) else "",
                str(word.get("speaker", "")),
                f"{float(word.get('start', 0.0)):.2f}",
                f"{float(word.get('end', 0.0)):.2f}",
            )

        self.updating_selected_word_controls = True
        for control, value in zip(
            (self.selected_word_ctrl, self.selected_speaker_ctrl, self.selected_start_ctrl, self.selected_end_ctrl),
            values,
        ):
            if control.GetValue() != value:
                control.ChangeValue(value)
        self.updating_selected_word_controls = False
        self.update_selected_word_controls_enabled()
        self.refresh_waveform_panel()



    def on_selected_word_detail_commit(self, event):
        self.commit_selected_word_detail(event.GetEventObject())



    def on_selected_word_detail_kill_focus(self, event):
        control = event.GetEventObject()
        if control is not None:
            self.call_after_if_alive(self.commit_selected_word_detail, control)
        event.Skip()



    def commit_selected_word_detail(self, control):
        if self.updating_selected_word_controls or control is None:
            return
        word_index = self.selected_word_index
        if word_index is None or not (0 <= word_index < len(self.words)):
            return

        field = getattr(control, "detail_field", "")
        raw_value = control.GetValue().strip()
        if field == "text":
            self.apply_selected_word_text_edit(word_index, raw_value)
            return
        if field == "speaker":
            self.apply_selected_word_speaker_edit(word_index, raw_value)
            return
        if field in ("start", "end"):
            self.apply_selected_word_time_edit(word_index, field, raw_value)



    def apply_selected_word_text_edit(self, word_index, raw_value):
        new_value = raw_value or "?"
        if self.words[word_index]["word"] == new_value:
            return
        self.words[word_index]["word"] = new_value
        group_index = self.get_group_index_for_word_index(word_index)
        self.save_transcript()
        if group_index is not None:
            self.refresh_single_group_row(group_index)
        self.select_word(word_index)



    def apply_selected_word_speaker_edit(self, word_index, raw_value):
        new_speaker = raw_value.strip()
        if not new_speaker:
            wx.MessageBox("Speaker não pode ficar vazio.", "Valor inválido", wx.OK | wx.ICON_ERROR)
            self.update_selected_word_details()
            return
        group_index = self.get_group_index_for_word_index(word_index)
        if group_index is None:
            return
        group = self.groups[group_index]
        current_speaker = self.words[word_index]["speaker"]
        if current_speaker == new_speaker:
            return
        for index in range(group.start_index, group.end_index):
            self.words[index]["speaker"] = new_speaker
        self.save_transcript()
        self.refresh_affected_group_rows([group], selected_index=group_index)
        self.select_word(word_index)



    def apply_selected_word_time_edit(self, word_index, field, raw_value):
        word = self.words[word_index]
        current_value = float(word[field])
        if raw_value == f"{current_value:.2f}":
            return

        try:
            new_value = float(raw_value)
        except ValueError:
            wx.MessageBox("Digite um número válido.", "Valor inválido", wx.OK | wx.ICON_ERROR)
            self.update_selected_word_details()
            return

        previous_end = 0.0 if word_index == 0 else float(self.words[word_index - 1]["end"])
        next_start = self.audio_length if word_index == len(self.words) - 1 else float(self.words[word_index + 1]["start"])
        current_start = float(word["start"])
        current_end = float(word["end"])

        if field == "start":
            if new_value < previous_end or new_value > current_end:
                wx.MessageBox(
                    f"O start deve ficar entre {previous_end:.2f} e {current_end:.2f}.",
                    "Valor inválido",
                    wx.OK | wx.ICON_ERROR,
                )
                self.update_selected_word_details()
                return
            word["start"] = self.clamp_time(new_value)
        else:
            if new_value < current_start or new_value > next_start or new_value > self.audio_length:
                wx.MessageBox(
                    f"O end deve ficar entre {current_start:.2f} e {min(next_start, self.audio_length):.2f}.",
                    "Valor inválido",
                    wx.OK | wx.ICON_ERROR,
                )
                self.update_selected_word_details()
                return
            word["end"] = self.clamp_time(new_value)

        group_index = self.get_group_index_for_word_index(word_index)
        self.stop_playback()
        self.current_time = self.clamp_time(self.current_time)
        self.normalize_groups()
        self.save_transcript()
        if group_index is not None:
            self.refresh_affected_group_rows([self.groups[group_index]], selected_index=group_index)
        self.select_word(word_index)



    def insert_gap_word(self, insert_index, start_time, end_time):
        if end_time <= start_time:
            wx.Bell()
            return
        if self.selected_word_index is None or not (0 <= self.selected_word_index < len(self.words)):
            return

        selected_word = self.words[self.selected_word_index]
        new_word = {
            "word": "?",
            "start": self.clamp_time(start_time),
            "end": self.clamp_time(end_time),
            "speaker": selected_word["speaker"],
            "discovered": selected_word.get("discovered", False),
        }

        group_index = self.get_group_index_for_word_index(self.selected_word_index)
        if group_index is None:
            return
        affected_group = self.groups[group_index]
        self.words.insert(insert_index, new_word)
        self.shift_group_indexes_after_insert(insert_index)
        self.clear_runtime_group_clips()
        self.save_transcript()
        self.refresh_affected_group_rows([affected_group], selected_index=group_index)
        self.select_word(insert_index)



    def on_insert_gap_before_selected(self, event):
        word_index = self.selected_word_index
        if word_index is None or word_index <= 0:
            wx.Bell()
            return
        previous_word = self.words[word_index - 1]
        current_word = self.words[word_index]
        self.insert_gap_word(word_index, previous_word["end"], current_word["start"])



    def on_insert_gap_after_selected(self, event):
        word_index = self.selected_word_index
        if word_index is None or word_index >= len(self.words) - 1:
            wx.Bell()
            return
        current_word = self.words[word_index]
        next_word = self.words[word_index + 1]
        self.insert_gap_word(word_index + 1, current_word["end"], next_word["start"])



    def on_remove_selected_word(self, event):
        word_index = self.selected_word_index
        if word_index is None or not (0 <= word_index < len(self.words)):
            wx.Bell()
            return

        group_index = self.get_group_index_for_word_index(word_index)
        if group_index is None:
            return

        affected_groups = []
        current_group = self.groups[group_index]
        affected_groups.append(current_group)
        if group_index > 0:
            affected_groups.append(self.groups[group_index - 1])
        if group_index + 1 < len(self.groups):
            affected_groups.append(self.groups[group_index + 1])

        self.stop_playback()
        del self.words[word_index]
        self.shift_group_indexes_after_delete(word_index)
        self.clear_runtime_group_clips()
        self.current_time = self.clamp_time(self.current_time)

        if self.words:
            self.normalize_groups()
            self.save_transcript()
            new_selected_index = min(word_index, len(self.words) - 1)
            selected_group_index = self.get_group_index_for_word_index(new_selected_index)
            self.selected_word_index = None
            self.refresh_affected_group_rows(affected_groups, selected_index=selected_group_index)
            self.select_word(new_selected_index)
        else:
            self.selected_word_index = None
            self.save_transcript()
            self.load_transcript()
