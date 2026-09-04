import time

from ...domain.playback import ensure_playable_range, resolve_seek
from ...domain.transcript import format_audio_time as domain_format_audio_time


class PlaybackBehavior:
    def stop_playback(self):
        self.audio_playback.stop()
        self.play_obj = None
        if self.tts_play_obj is not None and self.tts_play_obj.is_playing():
            self.tts_play_obj.stop()
        self.tts_play_obj = None
        self.is_playing = False
        self.playback_end_time = None
        self.playback_loop_range = None
        if self.timer.IsRunning():
            self.timer.Stop()


    def play_group(self, index):
        if index < 0 or index >= len(self.groups):
            return

        start, end = self.get_group_playback_range(index)
        self.current_time = self.clamp_time(start)
        self.update_slider_and_time()

        self.highlight_current_line(self.current_time)
        self.playback_loop_range = (start, end) if self.loop_group_playback else None
        self.play_from(self.current_time, end)
        if not self.timer.IsRunning():
            self.timer.Start(self.PLAYBACK_TIMER_MS)


    def play_word(self, word_index):
        if word_index < 0 or word_index >= len(self.words):
            return

        word = self.words[word_index]
        start = self.clamp_time(word["start"])
        end = self.clamp_time(word["end"])
        if end < start:
            end = start

        self.current_time = start
        self.update_slider_and_time()
        self.highlight_current_line(self.current_time)
        self.playback_loop_range = None
        self.play_from(self.current_time, end)
        if not self.timer.IsRunning():
            self.timer.Start(self.PLAYBACK_TIMER_MS)


    def format_audio_time(self, value):
        return domain_format_audio_time(value)


    def update_time_label(self):
        if not hasattr(self, "time_label"):
            return
        self.time_label.SetLabel(
            f"{self.format_audio_time(self.current_time)} / "
            f"{self.format_audio_time(self.audio_length)}"
        )


    def update_slider_and_time(self):
        self.slider_changing = True
        self.slider.SetValue(int(self.clamp_time(self.current_time)))
        self.slider_changing = False
        self.update_time_label()
        self.refresh_waveform_panel()


    def seek_relative(self, seconds):
        active_end_time = self.playback_end_time
        if self.is_playing:
            self.current_time = self.clamp_time(time.time() - self.start_time)

        target_time = resolve_seek(
            self.current_time,
            seconds,
            self.audio_length,
            active_end_time,
        )

        was_playing = self.is_playing
        self.current_time = target_time
        if was_playing:
            if self.current_time >= self.audio_length or (
                active_end_time is not None and self.current_time >= active_end_time
            ):
                self.stop_playback()
            else:
                self.play_from(self.current_time, active_end_time)

        self.update_slider_and_time()
        self.highlight_current_line(self.current_time)


    def play_from(self, pos, end_pos=None):
        """Play audio from a specific position using simpleaudio"""
        self.audio_playback.stop()
        if self.tts_play_obj is not None and self.tts_play_obj.is_playing():
            self.tts_play_obj.stop()
        self.tts_play_obj = None

        pos = self.clamp_time(pos)
        end_pos = self.clamp_time(end_pos) if end_pos is not None else None
        if end_pos is not None:
            pos, end_pos = ensure_playable_range(pos, end_pos, self.audio_length)
            self.current_time = pos
        self.play_obj = self.audio_playback.play(pos, end_pos)
        self.is_playing = True
        self.start_time = time.time() - pos
        self.playback_end_time = end_pos


    def on_play(self, event):
        active_group_index = self.get_active_group_index()
        clip_range = self.get_group_clip_range(active_group_index)
        if clip_range is not None:
            clip_start, clip_end = clip_range
            if not (clip_start <= self.current_time < clip_end):
                self.current_time = self.clamp_time(clip_start)
            self.playback_loop_range = (clip_start, clip_end) if self.loop_group_playback else None
            self.play_from(self.current_time, clip_end)
            if not self.timer.IsRunning():
                self.timer.Start(self.PLAYBACK_TIMER_MS)
            self.update_slider_and_time()
            self.highlight_current_line(self.current_time)
            return

        # O botão Play limita a reprodução ao grupo somente quando o loop está
        # ativo. Sem loop, depois de chegar ao fim de um grupo, Play continua
        # a partir do cursor para o restante do áudio.
        if (
            self.loop_group_playback
            and active_group_index is not None
            and 0 <= active_group_index < len(self.groups)
        ):
            start, end = self.get_group_playback_range(active_group_index)
            if self.is_playing:
                self.current_time = self.clamp_time(time.time() - self.start_time)
            if not (start <= self.current_time < end):
                self.current_time = start
            self.playback_loop_range = (start, end) if self.loop_group_playback else None
            self.play_from(self.current_time, end)
            if not self.timer.IsRunning():
                self.timer.Start(self.PLAYBACK_TIMER_MS)
            self.update_slider_and_time()
            self.highlight_current_line(self.current_time)
            return

        if not self.is_playing:
            self.playback_loop_range = None
            self.play_from(self.current_time)
            self.timer.Start(self.PLAYBACK_TIMER_MS)
        else:
            # resume by starting from current_time
            self.playback_loop_range = None
            self.play_from(self.current_time)
        self.update_slider_and_time()


    def on_pause(self, event):
        if self.is_playing:
            self.current_time = self.clamp_time(time.time() - self.start_time)
        self.stop_playback()
        self.update_slider_and_time()
        self.highlight_current_line(self.current_time)




    def on_slider_change(self, event):
        if self.slider_changing:
            return
        pos = self.slider.GetValue()
        self.current_time = self.clamp_time(pos)
        self.playback_end_time = None
        self.playback_loop_range = None
        if self.is_playing:
            self.play_from(self.current_time)
        else:
            self.highlight_current_line(self.current_time)
        self.update_time_label()
        self.refresh_waveform_panel()

    # ---------------- TIMER ----------------

    def on_timer(self, event):
        if self.is_playing:
            self.current_time = time.time() - self.start_time
            stop_time = self.playback_end_time if self.playback_end_time is not None else self.audio_length
            if self.current_time >= stop_time:
                loop_range = self.playback_loop_range
                if loop_range is not None and loop_range[1] > loop_range[0]:
                    self.current_time = loop_range[0]
                    self.play_from(loop_range[0], loop_range[1])
                else:
                    self.current_time = stop_time
                    if hasattr(self, 'play_obj') and self.play_obj.is_playing():
                        self.play_obj.stop()
                    self.is_playing = False
                    self.playback_end_time = None
                    self.timer.Stop()

        # Update slider and playback time safely
        self.update_slider_and_time()

        self.highlight_current_line(self.current_time)


    # ---------------- TRANSCRIPT HIGHLIGHT ----------------

    def highlight_current_line(self, current_time):
        target_index = None
        for idx in range(len(self.groups)):
            _, start, end, _ = self.get_group_data(idx)
            if start <= current_time <= end:
                target_index = idx
                break

        # Durante um intervalo entre grupos não existe uma linha que contenha
        # o cursor. Nesse caso, remova a seleção. O waveform passa a usar o
        # áudio completo como faixa de visualização e continua mostrando o
        # cursor de reprodução.
        if target_index is None:
            if self.selected_row_index is not None:
                self.clear_selection()
                self.refresh_waveform_panel()
            return

        if target_index != self.selected_row_index:
            self.select_row(target_index)
