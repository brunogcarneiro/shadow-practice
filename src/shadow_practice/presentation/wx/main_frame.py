import inspect

import simpleaudio as sa
import wx
from pydub import AudioSegment

from ...application.generative_tasks import GenerativeTaskService
from ...application.transcript_controller import TranscriptController
from ...infrastructure.audio import AudioPlaybackService
from ...infrastructure.generative import GenerativeModelManager
from .playback_toolbar import PlaybackBehavior
from .speaks_tab import SpeaksBehavior
from .transcription_tab import TranscriptionBehavior
from .waveform_panel import WaveformBehavior


class _BehaviorAdapter:
    """Exposes a behavior's functions bound to a frame without inheritance."""

    def __init__(self, host, behavior_type):
        self.host = host
        self.behavior_type = behavior_type

    def supports(self, name):
        return callable(getattr(self.behavior_type, name, None))

    def bind(self, name):
        function = getattr(self.behavior_type, name)
        descriptor = inspect.getattr_static(self.behavior_type, name)
        if isinstance(descriptor, staticmethod):
            return function
        return lambda *args, **kwargs: function(self.host, *args, **kwargs)


class TranscriptPlayer(wx.Frame):
    SPEAKER_COLUMN_WIDTH = 100
    START_COLUMN_WIDTH = 80
    END_COLUMN_WIDTH = 80
    MOVE_COLUMN_WIDTH = 90
    SPEAK_SPEAKER_COLUMN_WIDTH = 110
    SPEAK_START_COLUMN_WIDTH = 85
    SPEAK_END_COLUMN_WIDTH = 85
    SPEAK_TEXT_COLUMN_MIN_WIDTH = 160
    TEXT_COLUMN_MIN_WIDTH = 120
    RESIZE_DEBOUNCE_MS = 180
    VISIBLE_ROW_BUFFER_PX = 240
    WORD_SELECTED_BORDER = 3
    WORD_UNSELECTED_BORDER = 1
    WORD_HORIZONTAL_MARGIN = 4
    TEXT_ROW_GAP = 2
    ROW_VERTICAL_PADDING = 8
    WAVEFORM_HEIGHT = 72
    WAVEFORM_BAR_COUNT = 384
    WAVEFORM_BAR_PIXEL_STEP = 1
    PLAYBACK_TIMER_MS = 20
    WAVEFORM_MARKER_SQUARE_SIZE = 5
    WAVEFORM_HIT_PADDING = 5

    _behavior_types = (
        WaveformBehavior,
        SpeaksBehavior,
        TranscriptionBehavior,
        PlaybackBehavior,
    )

    def __getattr__(self, name):
        """Delegate event handlers to composed presentation behaviors."""
        for behavior in self.__dict__.get("_behaviors", ()):
            if behavior.supports(name):
                return behavior.bind(name)
        raise AttributeError(name)

    @property
    def words(self):
        return self.transcript_session.words

    @words.setter
    def words(self, value):
        self.transcript_session.words = value

    @property
    def groups(self):
        return self.transcript_session.groups

    @groups.setter
    def groups(self, value):
        self.transcript_session.groups = value

    @property
    def runtime_group_clips(self):
        return self.transcript_session.runtime_group_clips

    @runtime_group_clips.setter
    def runtime_group_clips(self, value):
        self.transcript_session.runtime_group_clips = value

    def __init__(self, parent, title, transcript_file, audio_file):
        super().__init__(parent, title=title, size=(800, 400))
        self._behaviors = tuple(_BehaviorAdapter(self, item) for item in self._behavior_types)
        self.is_closing = False
        self.transcript_file = transcript_file
        self.audio_file = audio_file
        self.transcript_session = TranscriptController(transcript_file)
        self.generative_models = GenerativeModelManager()
        self.generative_tasks = GenerativeTaskService()
        self.speaks_file = self.get_speaks_file_path(transcript_file)
        self.words = []
        self.groups = []
        self.speaks = []
        self.selected_speak_index = None
        self.speaks_row_panels = {}
        self.speaks_rewrite_controls = {}
        self.selected_rewrite_paragraph = None
        self.selected_rewrite_paragraph_control = None
        self.rewrite_paragraph_controls = {}
        self.tts_in_progress_paragraphs = set()
        self.tts_status_check_in_progress = False
        self.tts_play_obj = None
        self.rewrite_in_progress = False
        self.speaks_resize_call = None
        self.selected_word_index = None
        self.is_playing = False
        self.current_time = 0  # track current playback time
        self.playback_end_time = None
        from ...config import get_settings

        self.debug_enabled = get_settings().debug
        self.updating_selected_word_controls = False
        self.updating_selected_group_controls = False
        self.current_text_column_width = self.TEXT_COLUMN_MIN_WIDTH
        self.row_panels = {}
        self.word_controls = {}
        self.word_wrappers = {}
        self.boundary_controls = {}
        self.group_text_controls = {}
        self.row_offsets = [0]
        self.row_heights = []
        self.total_rows_height = 0
        self.selected_row_index = None
        self.waveform_cache = {}
        self.waveform_drag_state = None
        self.editing_word_index = None
        self.skip_word_kill_focus_word_index = None
        self.loop_group_playback = False
        self.playback_loop_range = None
        self.runtime_group_clips = {}
        # Load audio with pydub for seeking
        self.audio_segment = AudioSegment.from_file(self.audio_file)
        self.audio_length = self.audio_segment.duration_seconds
        self.audio_playback = AudioPlaybackService(self.audio_segment, sa.play_buffer)

        self.init_ui()
        self.timer = wx.Timer(self)
        self.resize_timer = wx.Timer(self)
        self.visible_rows_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.Bind(wx.EVT_TIMER, self.on_resize_timer, self.resize_timer)
        self.Bind(wx.EVT_TIMER, self.on_visible_rows_timer, self.visible_rows_timer)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.slider_changing = False
        self.load_transcript()

    def is_ui_alive(self):
        if self.is_closing:
            return False
        try:
            return not self.IsBeingDeleted()
        except RuntimeError:
            return False

    def call_after_if_alive(self, callback, *args):
        wx.CallAfter(self._call_if_alive, callback, args)

    def _call_if_alive(self, callback, args):
        if self.is_ui_alive():
            callback(*args)

    def on_close(self, event):
        if self.is_closing:
            event.Skip()
            return
        self.is_closing = True
        for timer in (getattr(self, "timer", None), getattr(self, "resize_timer", None), getattr(self, "visible_rows_timer", None)):
            if timer is not None and timer.IsRunning():
                timer.Stop()
        resize_call = getattr(self, "speaks_resize_call", None)
        if resize_call is not None:
            resize_call.Stop()
        if hasattr(self, "audio_playback"):
            self.audio_playback.stop()
        if hasattr(self, "generative_tasks"):
            self.generative_tasks.close()
        if getattr(self, "tts_play_obj", None) is not None and self.tts_play_obj.is_playing():
            self.tts_play_obj.stop()
        event.Skip()

    def init_ui(self):
        self.panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        waveform_box = wx.StaticBox(self.panel, label="Trecho selecionado")
        waveform_sizer = wx.StaticBoxSizer(waveform_box, wx.VERTICAL)
        self.waveform_panel = wx.Panel(waveform_box, size=(-1, self.WAVEFORM_HEIGHT))
        self.waveform_panel.SetMinSize((-1, self.WAVEFORM_HEIGHT))
        self.waveform_panel.SetBackgroundColour(wx.Colour(255, 255, 255))
        self.waveform_panel.Bind(wx.EVT_PAINT, self.on_waveform_paint)
        self.waveform_panel.Bind(wx.EVT_LEFT_DOWN, self.on_waveform_left_down)
        self.waveform_panel.Bind(wx.EVT_LEFT_UP, self.on_waveform_left_up)
        self.waveform_panel.Bind(wx.EVT_MOTION, self.on_waveform_motion)
        self.waveform_panel.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self.on_waveform_capture_lost)
        waveform_sizer.Add(self.waveform_panel, 1, wx.EXPAND | wx.ALL, 4)
        vbox.Add(waveform_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Audio controls
        footer_sizer = wx.BoxSizer(wx.VERTICAL)
        self.slider = wx.Slider(
            self.panel,
            value=0,
            minValue=0,
            maxValue=max(1, int(self.audio_length)),
            style=wx.SL_HORIZONTAL,
        )
        self.slider.Bind(wx.EVT_SLIDER, self.on_slider_change)
        footer_sizer.Add(self.slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        audio_buttons = wx.BoxSizer(wx.HORIZONTAL)
        for seconds in (-10, -5, -1):
            button = wx.Button(self.panel, label=f"{seconds}s", size=(48, -1))
            button.Bind(wx.EVT_BUTTON, lambda event, delta=seconds: self.seek_relative(delta))
            audio_buttons.Add(button, 0, wx.ALL, 3)

        self.play_btn = wx.Button(self.panel, label="Play", size=(55, -1))
        self.pause_btn = wx.Button(self.panel, label="Pause", size=(55, -1))
        self.play_btn.Bind(wx.EVT_BUTTON, self.on_play)
        self.pause_btn.Bind(wx.EVT_BUTTON, self.on_pause)
        audio_buttons.Add(self.play_btn, 0, wx.ALL, 3)
        audio_buttons.Add(self.pause_btn, 0, wx.ALL, 3)

        for seconds in (1, 5, 10):
            button = wx.Button(self.panel, label=f"+{seconds}s", size=(48, -1))
            button.Bind(wx.EVT_BUTTON, lambda event, delta=seconds: self.seek_relative(delta))
            audio_buttons.Add(button, 0, wx.ALL, 3)

        self.time_label = wx.StaticText(self.panel, label="")
        self.time_label.SetMinSize((125, -1))
        audio_buttons.Add(self.time_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        footer_sizer.Add(audio_buttons, 0, wx.ALIGN_CENTER)
        vbox.Add(footer_sizer, 0, wx.EXPAND | wx.BOTTOM, 3)

        self.notebook = wx.Notebook(self.panel)
        vbox.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)

        self.transcription_tab = wx.Panel(self.notebook)
        self.transcription_tab_sizer = wx.BoxSizer(wx.VERTICAL)
        self.transcription_tab.SetSizer(self.transcription_tab_sizer)
        self.notebook.AddPage(self.transcription_tab, "Transcrição")

        selected_details_sizer = wx.BoxSizer(wx.HORIZONTAL)
        config_box = wx.StaticBox(self.transcription_tab, label="Configuração")
        config_sizer = wx.StaticBoxSizer(config_box, wx.HORIZONTAL)
        self.loop_group_playback_checkbox = wx.CheckBox(config_box, label="Loop do grupo")
        self.loop_group_playback_checkbox.Bind(wx.EVT_CHECKBOX, self.on_loop_group_playback_changed)
        config_sizer.Add(self.loop_group_playback_checkbox, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        selected_details_sizer.Add(config_sizer, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        selected_group_box = wx.StaticBox(self.transcription_tab, label="Grupo selecionado")
        selected_group_sizer = wx.StaticBoxSizer(selected_group_box, wx.HORIZONTAL)
        self.selected_group_displayed_checkbox = wx.CheckBox(selected_group_box, label="displayed")
        self.selected_group_displayed_checkbox.Bind(wx.EVT_CHECKBOX, self.on_selected_group_displayed_changed)
        selected_group_sizer.Add(self.selected_group_displayed_checkbox, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        self.selected_new_group_from_btn = wx.Button(selected_group_box, label="Novo grupo a partir de")
        self.selected_new_group_until_btn = wx.Button(selected_group_box, label="Novo grupo até")
        self.selected_new_group_from_btn.Bind(wx.EVT_BUTTON, self.on_split_group_from_selected_word)
        self.selected_new_group_until_btn.Bind(wx.EVT_BUTTON, self.on_split_group_until_selected_word)
        selected_group_sizer.Add(self.selected_new_group_from_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        selected_group_sizer.Add(self.selected_new_group_until_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 6)
        selected_details_sizer.Add(selected_group_sizer, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        selected_word_box = wx.StaticBox(self.transcription_tab, label="Palavra selecionada")
        selected_word_sizer = wx.StaticBoxSizer(selected_word_box, wx.HORIZONTAL)
        self.selected_prev_gap_btn = wx.Button(selected_word_box, label="<", size=(28, 26))
        self.selected_next_gap_btn = wx.Button(selected_word_box, label=">", size=(28, 26))
        self.selected_delete_btn = wx.Button(selected_word_box, label="Remover", size=(78, 26))
        self.selected_prev_gap_btn.Bind(wx.EVT_BUTTON, self.on_insert_gap_before_selected)
        self.selected_next_gap_btn.Bind(wx.EVT_BUTTON, self.on_insert_gap_after_selected)
        self.selected_delete_btn.Bind(wx.EVT_BUTTON, self.on_remove_selected_word)
        selected_word_sizer.Add(self.selected_prev_gap_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        selected_word_sizer.Add(self.selected_next_gap_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
        selected_word_sizer.Add(self.selected_delete_btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)

        self.selected_word_ctrl = self.create_selected_detail_control(selected_word_box, selected_word_sizer, "Text", 140)
        self.selected_speaker_ctrl = self.create_selected_detail_control(selected_word_box, selected_word_sizer, "Speaker", 120)
        self.selected_start_ctrl = self.create_selected_detail_control(selected_word_box, selected_word_sizer, "Start", 80)
        self.selected_end_ctrl = self.create_selected_detail_control(selected_word_box, selected_word_sizer, "End", 80)
        selected_details_sizer.Add(selected_word_sizer, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.transcription_tab_sizer.Add(selected_details_sizer, 0, wx.EXPAND)

        self.falas_tab = wx.Panel(self.notebook)
        self.falas_tab_sizer = wx.BoxSizer(wx.VERTICAL)
        self.falas_tab.SetSizer(self.falas_tab_sizer)
        speaks_toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self.rewrite_speak_btn = wx.Button(self.falas_tab, label="Reescreva")
        self.rewrite_speak_btn.Disable()
        self.rewrite_speak_btn.Bind(wx.EVT_BUTTON, self.on_rewrite_selected_speak)
        speaks_toolbar.Add(self.rewrite_speak_btn, 0, wx.ALL, 5)
        self.tts_status_label = wx.StaticText(self.falas_tab, label="TTS local: não verificado")
        speaks_toolbar.Add(self.tts_status_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.falas_tab_sizer.Add(speaks_toolbar, 0, wx.EXPAND)
        self.speaks_header = self.create_speaks_header_row()
        self.falas_tab_sizer.Add(self.speaks_header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.speaks_container = wx.ScrolledWindow(
            self.falas_tab,
            style=wx.VSCROLL | wx.BORDER_SUNKEN,
        )
        self.speaks_container.SetScrollRate(10, 10)
        self.speaks_container.SetBackgroundColour(wx.WHITE)
        self.speaks_rows_sizer = wx.BoxSizer(wx.VERTICAL)
        self.speaks_container.SetSizer(self.speaks_rows_sizer)
        self.speaks_container.Bind(wx.EVT_SIZE, self.on_speaks_container_size)
        self.falas_tab_sizer.Add(self.speaks_container, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        self.notebook.AddPage(self.falas_tab, "Falas")
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_notebook_page_changed)

        self.list_sizer = wx.BoxSizer(wx.VERTICAL)
        self.transcription_tab_sizer.Add(self.list_sizer, 1, wx.EXPAND)

        self.header_panel = self.create_header_row(self.transcription_tab)
        self.list_sizer.Add(self.header_panel, 0, wx.EXPAND)

        self.list_container = wx.ScrolledWindow(
            self.transcription_tab,
            style=wx.VSCROLL | wx.HSCROLL | wx.BORDER_SUNKEN,
        )
        self.list_container.SetScrollRate(10, 10)
        self.list_container.SetBackgroundColour(wx.WHITE)
        self.list_sizer.Add(self.list_container, 1, wx.EXPAND)
        self.list_container.Bind(wx.EVT_SIZE, self.on_list_container_resize)
        self.list_container.Bind(wx.EVT_SCROLLWIN, self.on_list_container_scrolled)
        self.list_container.Bind(wx.EVT_MOUSEWHEEL, self.on_list_container_mousewheel)

        self.measure_text_ctrl = wx.TextCtrl(self.transcription_tab, value="", style=wx.BORDER_NONE)
        self.measure_text_ctrl.Hide()
        self.base_text_ctrl_height = max(22, self.measure_text_ctrl.GetBestSize().height)
        self.base_row_height = max(self.base_text_ctrl_height + self.ROW_VERTICAL_PADDING, 32)
        self.panel.SetSizer(vbox)
        self.update_time_label()
        self.update_selected_word_controls_enabled()

MainFrame = TranscriptPlayer
