import wx

from ...domain.waveform import sample_peaks, time_from_x


class WaveformBehavior:
    def get_selected_segment_range(self):
        group_index = self.get_active_group_index()
        if group_index is not None and 0 <= group_index < len(self.groups):
            _, start, end, _ = self.get_group_data(group_index)
            start, end = self.clamp_time(start), self.clamp_time(end)
            if not self.is_playing or start <= self.current_time <= end:
                return start, end

        # Durante a reprodução pode existir um intervalo entre grupos sem
        # qualquer grupo selecionado. Renderize somente esse gap, evitando
        # carregar e processar o áudio completo a cada atualização do timer.
        if self.is_playing:
            for index in range(len(self.groups) - 1):
                _, _, previous_end, _ = self.get_group_data(index)
                _, next_start, _, _ = self.get_group_data(index + 1)
                gap_start = self.clamp_time(previous_end)
                gap_end = self.clamp_time(next_start)
                if gap_end > gap_start and gap_start <= self.current_time <= gap_end:
                    return gap_start, gap_end

        return None


    def get_group_clip_range(self, group_index):
        if group_index is None or not (0 <= group_index < len(self.groups)):
            return None
        clip_range = self.runtime_group_clips.get(group_index)
        if clip_range is None:
            return None
        return self.clamp_time(clip_range[0]), self.clamp_time(clip_range[1])


    def get_group_playback_range(self, group_index):
        segment_range = self.get_selected_segment_range() if group_index == self.get_active_group_index() else None
        if segment_range is None:
            _, start, end, _ = self.get_group_data(group_index)
            segment_range = (self.clamp_time(start), self.clamp_time(end))
        clip_range = self.get_group_clip_range(group_index)
        if clip_range is None:
            return segment_range
        clip_start, clip_end = clip_range
        group_start, group_end = segment_range
        clip_start = max(group_start, min(clip_start, group_end))
        clip_end = max(clip_start, min(clip_end, group_end))
        return clip_start, clip_end


    def get_active_group_words(self):
        group_index = self.get_active_group_index()
        if group_index is None or not (0 <= group_index < len(self.groups)):
            return []
        group = self.groups[group_index]
        return [
            (word_index, self.words[word_index])
            for word_index in range(group.start_index, group.end_index)
        ]


    def get_waveform_bars(self, start_time, end_time, bar_count=None):
        bar_count = bar_count or self.WAVEFORM_BAR_COUNT
        start_time = self.clamp_time(start_time)
        end_time = self.clamp_time(end_time)
        cache_key = (round(start_time, 3), round(end_time, 3), int(bar_count))
        cached = self.waveform_cache.get(cache_key)
        if cached is not None:
            return cached

        if end_time <= start_time:
            bars = [0.0] * bar_count
            self.waveform_cache[cache_key] = bars
            return bars

        segment = self.audio_segment[int(start_time * 1000):int(end_time * 1000)]
        samples = segment.get_array_of_samples()
        sample_count = len(samples)
        if sample_count <= 0:
            bars = [0.0] * bar_count
            self.waveform_cache[cache_key] = bars
            return bars

        bars = sample_peaks(samples, segment.channels, segment.sample_width, bar_count)

        self.waveform_cache[cache_key] = bars
        if len(self.waveform_cache) > 256:
            self.waveform_cache.pop(next(iter(self.waveform_cache)))
        return bars


    def refresh_waveform_panel(self):
        if hasattr(self, "waveform_panel"):
            self.waveform_panel.Refresh()


    def get_waveform_word_markers(self, width, height):
        segment_range = self.get_selected_segment_range()
        if segment_range is None:
            return [], None

        start_time, end_time = segment_range
        if end_time <= start_time:
            return [], segment_range

        base_y = height - 8
        markers = []
        for word_index, word in self.get_active_group_words():
            start_progress = (self.clamp_time(word["start"]) - start_time) / (end_time - start_time)
            end_progress = (self.clamp_time(word["end"]) - start_time) / (end_time - start_time)
            start_x = max(0, min(width - 1, int(start_progress * (width - 1))))
            end_x = max(0, min(width - 1, int(end_progress * (width - 1))))
            if end_x < start_x:
                start_x, end_x = end_x, start_x
            markers.append({
                "word_index": word_index,
                "start_x": start_x,
                "end_x": end_x,
                "base_y": base_y,
            })
        return markers, segment_range


    def get_waveform_clip_markers(self, width, height):
        group_index = self.get_active_group_index()
        segment_range = self.get_selected_segment_range()
        clip_range = self.get_group_clip_range(group_index)
        if group_index is None or segment_range is None or clip_range is None:
            return None

        start_time, end_time = segment_range
        clip_start, clip_end = clip_range
        if end_time <= start_time:
            return None

        base_y = max(6, height - 14)
        start_progress = (clip_start - start_time) / (end_time - start_time)
        end_progress = (clip_end - start_time) / (end_time - start_time)
        start_x = max(0, min(width - 1, int(start_progress * (width - 1))))
        end_x = max(0, min(width - 1, int(end_progress * (width - 1))))
        if end_x < start_x:
            start_x, end_x = end_x, start_x
        return {
            "group_index": group_index,
            "start_x": start_x,
            "end_x": end_x,
            "base_y": base_y,
            "segment_start": start_time,
            "segment_end": end_time,
            "width": max(1, width),
        }


    def hit_test_waveform_marker(self, x, y):
        width, height = self.waveform_panel.GetClientSize()
        markers, segment_range = self.get_waveform_word_markers(width, height)
        if segment_range is None:
            return None

        hit_size = self.WAVEFORM_MARKER_SQUARE_SIZE + (self.WAVEFORM_HIT_PADDING * 2)
        ordered_markers = sorted(
            markers,
            key=lambda marker: 0 if marker["word_index"] == self.selected_word_index else 1,
        )
        for marker in ordered_markers:
            square_half = self.WAVEFORM_MARKER_SQUARE_SIZE // 2
            base_y = marker["base_y"]
            for boundary_field, marker_x in (("start", marker["start_x"]), ("end", marker["end_x"])):
                rect_x = marker_x - square_half - self.WAVEFORM_HIT_PADDING
                rect_y = base_y - square_half - self.WAVEFORM_HIT_PADDING
                if rect_x <= x <= rect_x + hit_size and rect_y <= y <= rect_y + hit_size:
                    return {
                        "word_index": marker["word_index"],
                        "field": boundary_field,
                        "segment_start": segment_range[0],
                        "segment_end": segment_range[1],
                        "width": max(1, width),
                    }
        return None


    def hit_test_waveform_clip_marker(self, x, y):
        width, height = self.waveform_panel.GetClientSize()
        clip_markers = self.get_waveform_clip_markers(width, height)
        if clip_markers is None:
            return None

        hit_size = self.WAVEFORM_MARKER_SQUARE_SIZE + (self.WAVEFORM_HIT_PADDING * 2)
        square_half = self.WAVEFORM_MARKER_SQUARE_SIZE // 2
        for marker_x in (clip_markers["start_x"], clip_markers["end_x"]):
            rect_x = marker_x - square_half - self.WAVEFORM_HIT_PADDING
            rect_y = 0
            rect_height = max(hit_size, height)
            if rect_x <= x <= rect_x + hit_size and rect_y <= y <= rect_y + rect_height:
                return clip_markers["group_index"]
        return None


    def update_group_clip_from_waveform_click(self, x):
        group_index = self.get_active_group_index()
        segment_range = self.get_selected_segment_range()
        if group_index is None or segment_range is None:
            return

        group_start, group_end = segment_range
        if group_end <= group_start:
            return

        min_duration = 0.01
        clicked_time = self.time_from_waveform_x(x, group_start, group_end, max(1, self.waveform_panel.GetClientSize().width))
        clicked_time = max(group_start, min(clicked_time, group_end))
        clip_start, clip_end = self.runtime_group_clips.get(group_index, (None, None))

        if clip_start is None or clip_end is None:
            clip_start = min(clicked_time, max(group_start, group_end - min_duration))
            clip_end = group_end
        else:
            if abs(clicked_time - clip_start) <= abs(clicked_time - clip_end):
                clip_start = min(clicked_time, max(group_start, clip_end - min_duration))
            else:
                clip_end = max(clicked_time, min(group_end, clip_start + min_duration))

        self.runtime_group_clips[group_index] = (clip_start, clip_end)
        self.normalize_groups()
        self.refresh_waveform_panel()


    def time_from_waveform_x(self, x, segment_start, segment_end, width):
        return time_from_x(x, segment_start, segment_end, width)


    def apply_word_time_drag(self, word_index, field, new_value):
        if not (0 <= word_index < len(self.words)):
            return False
        word = self.words[word_index]
        previous_end = 0.0 if word_index == 0 else float(self.words[word_index - 1]["end"])
        next_start = self.audio_length if word_index == len(self.words) - 1 else float(self.words[word_index + 1]["start"])
        current_start = float(word["start"])
        current_end = float(word["end"])

        if field == "start":
            clamped_value = max(previous_end, min(float(new_value), current_end))
            if clamped_value == current_start:
                return False
            word["start"] = self.clamp_time(clamped_value)
        else:
            clamped_value = min(next_start, self.audio_length, max(float(new_value), current_start))
            if clamped_value == current_end:
                return False
            word["end"] = self.clamp_time(clamped_value)

        self.normalize_groups()
        group_index = self.get_group_index_for_word_index(word_index)
        if group_index is not None:
            self.update_boundary_control(group_index, "start")
            self.update_boundary_control(group_index, "end")
        if self.selected_word_index == word_index:
            self.update_selected_word_details()
        self.refresh_waveform_panel()
        return True


    def on_waveform_left_down(self, event):
        hit = self.hit_test_waveform_marker(event.GetX(), event.GetY())
        if hit is None:
            clip_group_index = self.hit_test_waveform_clip_marker(event.GetX(), event.GetY())
            if clip_group_index is not None:
                self.runtime_group_clips.pop(clip_group_index, None)
                if self.get_active_group_index() == clip_group_index:
                    self.playback_loop_range = None
                self.refresh_waveform_panel()
                return
            self.update_group_clip_from_waveform_click(event.GetX())
            return

        self.waveform_drag_state = hit
        self.select_word(hit["word_index"])
        self.waveform_panel.CaptureMouse()


    def on_waveform_motion(self, event):
        if self.waveform_drag_state is None or not event.Dragging() or not event.LeftIsDown():
            event.Skip()
            return

        drag = self.waveform_drag_state
        new_time = self.time_from_waveform_x(
            event.GetX(),
            drag["segment_start"],
            drag["segment_end"],
            drag["width"],
        )
        self.apply_word_time_drag(drag["word_index"], drag["field"], new_time)


    def finish_waveform_drag(self):
        if self.waveform_drag_state is None:
            return
        self.waveform_drag_state = None
        if self.waveform_panel.HasCapture():
            self.waveform_panel.ReleaseMouse()
        self.save_transcript()


    def on_waveform_left_up(self, event):
        if self.waveform_drag_state is None:
            event.Skip()
            return
        self.finish_waveform_drag()


    def on_waveform_capture_lost(self, event):
        self.waveform_drag_state = None


    def on_waveform_paint(self, event):
        panel = self.waveform_panel
        width, height = panel.GetClientSize()
        dc = wx.PaintDC(panel)
        dc.SetBackground(wx.Brush(panel.GetBackgroundColour()))
        dc.Clear()

        if width <= 0 or height <= 0:
            return

        segment_range = self.get_selected_segment_range()
        if segment_range is None:
            dc.SetPen(wx.Pen(wx.Colour(210, 210, 210), 1))
            dc.DrawLine(0, height // 2, width, height // 2)
            return

        start_time, end_time = segment_range
        bar_count = max(self.WAVEFORM_BAR_COUNT, width // self.WAVEFORM_BAR_PIXEL_STEP)
        bars = self.get_waveform_bars(start_time, end_time, bar_count=bar_count)
        if not bars:
            return

        dc.SetPen(wx.Pen(wx.Colour(30, 30, 30), 1))
        dc.SetBrush(wx.Brush(wx.Colour(30, 30, 30)))
        center_y = height // 2
        usable_height = max(8, height - 10)
        bar_width = max(1, width // max(1, len(bars)))

        for index, amplitude in enumerate(bars):
            bar_height = max(2, int(amplitude * usable_height))
            x = index * bar_width
            y = center_y - (bar_height // 2)
            draw_width = max(1, bar_width - 1)
            dc.DrawRectangle(x, y, draw_width, bar_height)

        if end_time > start_time:
            clip_markers = self.get_waveform_clip_markers(width, height)
            if clip_markers is not None:
                clip_colour = wx.Colour(0, 140, 255)
                dc.SetPen(wx.Pen(clip_colour, 2))
                dc.SetBrush(wx.Brush(clip_colour))
                dc.DrawLine(clip_markers["start_x"], 2, clip_markers["start_x"], height - 2)
                dc.DrawLine(clip_markers["end_x"], 2, clip_markers["end_x"], height - 2)

            base_y = height - 8
            square_size = 5
            active_group_words = self.get_active_group_words()
            active_group_words.sort(
                key=lambda item: 1 if item[0] == self.selected_word_index else 0
            )
            for word_index, word in active_group_words:
                start_progress = (self.clamp_time(word["start"]) - start_time) / (end_time - start_time)
                end_progress = (self.clamp_time(word["end"]) - start_time) / (end_time - start_time)
                start_x = max(0, min(width - 1, int(start_progress * (width - 1))))
                end_x = max(0, min(width - 1, int(end_progress * (width - 1))))
                if end_x < start_x:
                    start_x, end_x = end_x, start_x

                colour = wx.Colour(0, 160, 0) if word_index == self.selected_word_index else wx.Colour(210, 0, 0)
                dc.SetPen(wx.Pen(colour, 1))
                dc.SetBrush(wx.Brush(colour))
                dc.DrawLine(start_x, 2, start_x, base_y)
                dc.DrawLine(end_x, 2, end_x, base_y)
                dc.DrawLine(start_x, base_y, end_x, base_y)
                dc.DrawRectangle(start_x - (square_size // 2), base_y - (square_size // 2), square_size, square_size)
                dc.DrawRectangle(end_x - (square_size // 2), base_y - (square_size // 2), square_size, square_size)

        if start_time <= self.current_time <= end_time and end_time > start_time:
            progress = (self.current_time - start_time) / (end_time - start_time)
            marker_x = max(0, min(width - 1, int(progress * (width - 1))))
            dc.SetPen(wx.Pen(wx.Colour(0, 140, 255), 1))
            dc.DrawLine(marker_x, 2, marker_x, height - 2)
