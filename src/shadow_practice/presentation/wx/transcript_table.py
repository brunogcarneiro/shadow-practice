"""Tabela virtualizada dos grupos de transcrição."""

import bisect

import wx


class TranscriptTableBehavior:
    def on_list_container_resize(self, event):
        self.resize_timer.StartOnce(self.RESIZE_DEBOUNCE_MS)
        event.Skip()



    def on_resize_timer(self, event):
        new_width = self.calculate_text_column_width()
        if abs(new_width - self.current_text_column_width) >= 2:
            self.current_text_column_width = new_width
            self.refresh_transcript_view(selected_index=self.get_selected_group_index())
        else:
            self.schedule_visible_rows_refresh()



    def on_list_container_scrolled(self, event):
        event.Skip()
        self.call_after_if_alive(self.render_visible_rows)



    def on_list_container_mousewheel(self, event):
        event.Skip()
        self.call_after_if_alive(self.render_visible_rows)



    def on_visible_rows_timer(self, event):
        self.render_visible_rows()



    def schedule_visible_rows_refresh(self):
        self.visible_rows_timer.StartOnce(1)



    def get_selected_group_index(self):
        if self.selected_word_index is None:
            return None
        return self.get_group_index_for_word_index(self.selected_word_index)



    def build_list_ctrl(self):
        self.clear_virtual_row_widgets()
        self.list_sizer.Detach(self.header_panel)
        self.header_panel.Destroy()
        self.header_panel = self.create_header_row(self.transcription_tab)
        self.list_sizer.Insert(0, self.header_panel, 0, wx.EXPAND)
        self.rebuild_row_metrics()
        self.list_container.SetVirtualSize((self.get_total_row_width(), self.total_rows_height))
        self.render_visible_rows()
        self.transcription_tab.Layout()
        self.panel.Layout()



    def clear_virtual_row_widgets(self):
        for panel in list(self.row_panels.values()):
            panel.Destroy()
        self.row_panels = {}
        self.word_controls = {}
        self.word_wrappers = {}
        self.boundary_controls = {}



    def refresh_affected_group_rows(self, affected_groups, selected_index=None):
        indexes = [
            self.groups.index(group)
            for group in affected_groups
            if group in self.groups
        ]
        if not indexes:
            return

        first_index = min(indexes)
        for row_index in list(self.row_panels):
            if row_index >= first_index:
                self.row_panels[row_index].Destroy()
                del self.row_panels[row_index]
        self.rebuild_row_metrics_from(first_index)
        self.list_container.SetVirtualSize((self.get_total_row_width(), self.total_rows_height))
        self.render_visible_rows()
        if selected_index is not None and 0 <= selected_index < len(self.groups):
            self.select_row(selected_index)



    def refresh_single_group_row(self, group_index):
        if group_index is None or not (0 <= group_index < len(self.groups)):
            return

        existing_panel = self.row_panels.pop(group_index, None)
        if existing_panel is not None:
            existing_panel.Destroy()

        self.rebuild_row_metrics_from(group_index)
        self.list_container.SetVirtualSize((self.get_total_row_width(), self.total_rows_height))
        self.render_visible_rows()



    def create_header_row(self, parent):
        panel = wx.Panel(parent)
        panel.SetBackgroundColour(wx.Colour(235, 235, 235))
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        def add_header(label, width):
            text = wx.StaticText(panel, label=label)
            sizer.Add(text, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
            text.SetMinSize((width, -1))

        add_header("Speaker", self.SPEAKER_COLUMN_WIDTH)
        add_header("Start", self.START_COLUMN_WIDTH)
        add_header("End", self.END_COLUMN_WIDTH)
        add_header("Text", self.current_text_column_width)
        add_header("Move", self.MOVE_COLUMN_WIDTH)
        panel.SetSizer(sizer)
        return panel



    def get_total_row_width(self):
        return (
            self.SPEAKER_COLUMN_WIDTH +
            self.START_COLUMN_WIDTH +
            self.END_COLUMN_WIDTH +
            self.current_text_column_width +
            self.MOVE_COLUMN_WIDTH +
            40
        )



    def estimate_text_panel_height(self, row_index, width):
        available_width = max(1, width)
        current_row_width = 0
        row_count = 0
        wrapper_height = self.base_text_ctrl_height + (self.WORD_SELECTED_BORDER * 2)
        group = self.groups[row_index]

        for word_index in range(group.start_index, group.end_index):
            token = self.words[word_index]["word"]
            wrapper_width = self.get_word_control_width(token) + (self.WORD_SELECTED_BORDER * 2)
            total_width = wrapper_width + self.WORD_HORIZONTAL_MARGIN
            if current_row_width and current_row_width + total_width > available_width:
                row_count += 1
                current_row_width = 0
            current_row_width += total_width

        if group.start_index < group.end_index:
            row_count += 1

        word_rows_height = 0
        if row_count > 0:
            word_rows_height = (row_count * wrapper_height) + ((row_count - 1) * self.TEXT_ROW_GAP)

        human_transcription_height = self.base_text_ctrl_height + 4
        top_gap = self.TEXT_ROW_GAP if row_count > 0 else 0
        return word_rows_height + top_gap + human_transcription_height



    def rebuild_row_metrics(self):
        self.row_offsets = [0]
        self.row_heights = []
        for row_index in range(len(self.groups)):
            text_height = self.estimate_text_panel_height(row_index, self.current_text_column_width)
            row_height = max(self.base_row_height, text_height + self.ROW_VERTICAL_PADDING)
            self.row_heights.append(row_height)
            self.row_offsets.append(self.row_offsets[-1] + row_height)
        self.total_rows_height = self.row_offsets[-1] if self.row_offsets else 0



    def rebuild_row_metrics_from(self, start_index):
        if start_index <= 0 or not self.row_heights or not self.row_offsets:
            self.rebuild_row_metrics()
            return

        start_index = min(start_index, len(self.groups))
        self.row_heights = self.row_heights[:start_index]
        self.row_offsets = self.row_offsets[:start_index + 1]

        for row_index in range(start_index, len(self.groups)):
            text_height = self.estimate_text_panel_height(row_index, self.current_text_column_width)
            row_height = max(self.base_row_height, text_height + self.ROW_VERTICAL_PADDING)
            self.row_heights.append(row_height)
            self.row_offsets.append(self.row_offsets[-1] + row_height)

        self.total_rows_height = self.row_offsets[-1] if self.row_offsets else 0



    def get_visible_row_range(self):
        _, scroll_y = self.list_container.GetViewStart()
        _, pixels_y = self.list_container.GetScrollPixelsPerUnit()
        top = scroll_y * pixels_y
        bottom = top + self.list_container.GetClientSize().height
        visible_top = max(0, top - self.VISIBLE_ROW_BUFFER_PX)
        visible_bottom = bottom + self.VISIBLE_ROW_BUFFER_PX
        start_index = max(0, bisect.bisect_right(self.row_offsets, visible_top) - 1)
        end_index = min(len(self.groups), bisect.bisect_left(self.row_offsets, visible_bottom))
        if end_index <= start_index and start_index < len(self.groups):
            end_index = start_index + 1
        return start_index, end_index



    def collect_row_controls(self, panel, group_index):
        stack = [panel]
        while stack:
            widget = stack.pop()
            word_index = getattr(widget, "word_index", None)
            if word_index is not None and isinstance(widget, wx.TextCtrl):
                self.word_controls[word_index] = widget
            if word_index is not None and getattr(widget, "is_word_wrapper", False):
                self.word_wrappers[word_index] = widget
            boundary_field = getattr(widget, "boundary_field", None)
            if boundary_field is not None:
                self.boundary_controls[(group_index, boundary_field)] = widget
            human_group_index = getattr(widget, "human_group_index", None)
            if human_group_index is not None and isinstance(widget, wx.TextCtrl):
                self.group_text_controls[human_group_index] = widget
            stack.extend(widget.GetChildren())



    def render_visible_rows(self):
        start_index, end_index = self.get_visible_row_range()
        needed_indexes = set(range(start_index, end_index))

        for row_index in list(self.row_panels.keys()):
            if row_index not in needed_indexes:
                self.row_panels[row_index].Destroy()
                del self.row_panels[row_index]

        self.word_controls = {}
        self.word_wrappers = {}
        self.boundary_controls = {}
        self.group_text_controls = {}
        row_width = self.get_total_row_width()

        for row_index in range(start_index, end_index):
            row_panel = self.row_panels.get(row_index)
            if row_panel is None:
                row_panel = self.create_group_row(row_index, parent=self.list_container)
                self.row_panels[row_index] = row_panel
            pos_x, pos_y = self.list_container.CalcScrolledPosition(0, self.row_offsets[row_index])
            row_panel.SetPosition((pos_x, pos_y))
            row_panel.SetSize((row_width, self.row_heights[row_index]))
            row_panel.Show()
            self.collect_row_controls(row_panel, row_index)



    def create_group_row(self, row_index, parent=None):
        speaker, start, end, _ = self.get_group_data(row_index)
        panel = wx.Panel(parent or self.list_container)
        panel.group_index = row_index
        panel.group_ref = self.groups[row_index]
        panel.SetBackgroundColour(wx.WHITE)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        speaker_label = wx.StaticText(panel, label=speaker)
        speaker_label.SetMinSize((self.SPEAKER_COLUMN_WIDTH, -1))
        speaker_label.SetMaxSize((self.SPEAKER_COLUMN_WIDTH, -1))
        sizer.Add(speaker_label, 0, wx.ALL | wx.ALIGN_TOP, 4)

        start_ctrl = wx.TextCtrl(panel, value=f"{start:.2f}", size=(self.START_COLUMN_WIDTH, -1), style=wx.TE_PROCESS_ENTER | wx.BORDER_SIMPLE)
        start_ctrl.boundary_group_index = row_index
        start_ctrl.boundary_field = "start"
        self.boundary_controls[(row_index, "start")] = start_ctrl
        start_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda event, ctrl=start_ctrl: self.commit_boundary_control(ctrl))
        start_ctrl.Bind(wx.EVT_KILL_FOCUS, lambda event, ctrl=start_ctrl: self.on_boundary_kill_focus(event, ctrl))
        start_ctrl.SetMinSize((self.START_COLUMN_WIDTH, -1))
        start_ctrl.SetMaxSize((self.START_COLUMN_WIDTH, -1))
        sizer.Add(start_ctrl, 0, wx.ALL | wx.ALIGN_TOP, 4)

        end_ctrl = wx.TextCtrl(panel, value=f"{end:.2f}", size=(self.END_COLUMN_WIDTH, -1), style=wx.TE_PROCESS_ENTER | wx.BORDER_SIMPLE)
        end_ctrl.boundary_group_index = row_index
        end_ctrl.boundary_field = "end"
        self.boundary_controls[(row_index, "end")] = end_ctrl
        end_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda event, ctrl=end_ctrl: self.commit_boundary_control(ctrl))
        end_ctrl.Bind(wx.EVT_KILL_FOCUS, lambda event, ctrl=end_ctrl: self.on_boundary_kill_focus(event, ctrl))
        end_ctrl.SetMinSize((self.END_COLUMN_WIDTH, -1))
        end_ctrl.SetMaxSize((self.END_COLUMN_WIDTH, -1))
        sizer.Add(end_ctrl, 0, wx.ALL | wx.ALIGN_TOP, 4)

        text_panel = self.create_text_controls(row_index, parent=panel, width=self.current_text_column_width)
        text_panel.SetMinSize((self.current_text_column_width, -1))
        sizer.Add(text_panel, 1, wx.ALL | wx.EXPAND, 4)

        move_panel = self.create_move_buttons(row_index, parent=panel)
        move_panel.SetMinSize((self.MOVE_COLUMN_WIDTH, -1))
        move_panel.SetMaxSize((self.MOVE_COLUMN_WIDTH, -1))
        sizer.Add(move_panel, 0, wx.ALL | wx.ALIGN_TOP, 4)

        panel.SetSizer(sizer)
        panel.Layout()
        best_size = panel.GetBestSize()
        panel.SetMinSize(best_size)
        panel.SetSize(best_size)

        for widget in (panel, speaker_label, text_panel, move_panel):
            widget.group_index = row_index
            widget.Bind(wx.EVT_LEFT_DOWN, self.on_group_click)
            widget.Bind(wx.EVT_LEFT_DCLICK, self.on_group_double_click)

        return panel



    def create_move_buttons(self, row_index, parent=None):
        button_panel = wx.Panel(parent or self.list_container)
        hbox = wx.BoxSizer(wx.HORIZONTAL)

        left_btn = wx.Button(button_panel, label="<", size=(28, 24))
        right_btn = wx.Button(button_panel, label=">", size=(28, 24))
        left_btn.group_index = row_index
        right_btn.group_index = row_index
        left_btn.move_direction = "previous"
        right_btn.move_direction = "next"

        left_btn.Enable(self.can_move_word_to_previous_group(row_index))
        right_btn.Enable(self.can_move_word_to_next_group(row_index))

        left_btn.Bind(wx.EVT_BUTTON, self.on_move_previous_clicked)
        right_btn.Bind(wx.EVT_BUTTON, self.on_move_next_clicked)

        hbox.Add(left_btn, 0, wx.RIGHT, 4)
        hbox.Add(right_btn, 0)
        button_panel.SetSizerAndFit(hbox)
        button_panel.Layout()
        button_panel.SetMinSize(button_panel.GetBestSize())
        return button_panel



    def on_group_double_click(self, event):
        group_index = getattr(event.GetEventObject(), "group_index", None)
        if group_index is not None:
            if self.selected_word_index is not None:
                selected_word_group_index = self.get_group_index_for_word_index(self.selected_word_index)
                if selected_word_group_index != group_index:
                    previous_wrapper = self.word_wrappers.get(self.selected_word_index)
                    self.set_word_wrapper_selected(previous_wrapper, False)
                    self.selected_word_index = None
                    self.update_selected_word_details()
            self.select_row(group_index)
            self.play_group(group_index)



    def on_group_click(self, event):
        group_index = getattr(event.GetEventObject(), "group_index", None)
        if group_index is not None:
            if self.selected_word_index is not None:
                selected_word_group_index = self.get_group_index_for_word_index(self.selected_word_index)
                if selected_word_group_index != group_index:
                    previous_wrapper = self.word_wrappers.get(self.selected_word_index)
                    self.set_word_wrapper_selected(previous_wrapper, False)
                    self.selected_word_index = None
                    self.update_selected_word_details()
            self.select_row(group_index)
        event.Skip()



    def on_move_previous_clicked(self, event):
        group_index = getattr(event.GetEventObject(), "group_index", None)
        if group_index is not None:
            self.move_word_to_previous_group(group_index)



    def on_move_next_clicked(self, event):
        group_index = getattr(event.GetEventObject(), "group_index", None)
        if group_index is not None:
            self.move_word_to_next_group(group_index)



    def select_row(self, row_index):
        if not (0 <= row_index < len(self.groups)):
            return

        self.clear_selection()
        row_panel = self.row_panels.get(row_index)
        if row_panel is None:
            self.scroll_row_into_view(row_index)
            row_panel = self.row_panels.get(row_index)
            if row_panel is None:
                return
        row_panel.SetBackgroundColour(wx.Colour(220, 235, 255))
        row_panel.Refresh()
        self.selected_row_index = row_index
        self.update_selected_group_controls()



    def clear_selection(self):
        for row_panel in getattr(self, "row_panels", {}).values():
            row_panel.SetBackgroundColour(wx.WHITE)
            row_panel.Refresh()
        self.selected_row_index = None
        self.update_selected_group_controls()



    def scroll_row_into_view(self, row_index):
        if not (0 <= row_index < len(self.groups)):
            return
        scroll_x, scroll_y = self.list_container.GetViewStart()
        _, pixels_y = self.list_container.GetScrollPixelsPerUnit()
        viewport_top = scroll_y * pixels_y
        viewport_bottom = viewport_top + self.list_container.GetClientSize().height
        row_top = self.row_offsets[row_index]
        row_bottom = self.row_offsets[row_index + 1]

        target_top = None
        if row_top < viewport_top:
            target_top = row_top
        elif row_bottom > viewport_bottom:
            target_top = max(0, row_bottom - self.list_container.GetClientSize().height)

        if target_top is not None and pixels_y > 0:
            self.list_container.Scroll(scroll_x, int(target_top / pixels_y))
        self.render_visible_rows()
