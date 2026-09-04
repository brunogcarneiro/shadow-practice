"""Live processing details window."""

from __future__ import annotations

import json
from pathlib import Path

import wx


class ProcessingDetailsFrame(wx.Frame):
    def __init__(self, owner, recording: Path):
        super().__init__(None, title=f"Processing — {recording.name}", size=(980, 600))
        self.owner = owner
        self.recording = recording
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        header = wx.BoxSizer(wx.HORIZONTAL)
        self.progress = wx.Gauge(panel, range=100, size=(-1, 20))
        self.progress_label = wx.StaticText(panel, label="Preparing… 1%")
        self.stop_button = wx.Button(panel, label="Interromper")
        self.back_button = wx.Button(panel, label="Voltar")
        header.Add(self.progress, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
        header.Add(self.progress_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 8)
        header.Add(self.stop_button, 0, wx.ALL, 5)
        header.Add(self.back_button, 0, wx.ALL, 5)
        root.Add(header, 0, wx.EXPAND)

        self.log_table = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.log_table.InsertColumn(0, "Instante", width=105)
        self.log_table.InsertColumn(1, "Etapa", width=130)
        self.log_table.InsertColumn(2, "Dados estruturados", width=280)
        self.log_table.InsertColumn(3, "Descrição", width=420)
        root.Add(self.log_table, 1, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(root)

        self.stop_button.Bind(wx.EVT_BUTTON, self._on_stop)
        self.back_button.Bind(wx.EVT_BUTTON, self._on_back)
        self.Bind(wx.EVT_CLOSE, self._on_back)
        self.refresh()

    def refresh(self) -> None:
        percent, message = self.owner.processing_progress.get(
            self.recording, (0, "Not processing")
        )
        self.progress.SetValue(percent)
        self.progress_label.SetLabel(f"{message} {percent}%")
        self.stop_button.Enable(self.recording in self.owner.processing_recordings)
        logs = self.owner.processing_logs.get(self.recording, [])
        while self.log_table.GetItemCount() < len(logs):
            event = logs[self.log_table.GetItemCount()]
            timestamp = str(event.get("timestamp", ""))
            if "T" in timestamp:
                timestamp = timestamp.split("T", 1)[1][:8]
            index = self.log_table.InsertItem(self.log_table.GetItemCount(), timestamp)
            self.log_table.SetItem(index, 1, str(event.get("stage", "")))
            self.log_table.SetItem(
                index,
                2,
                json.dumps(event.get("data", {}), ensure_ascii=False, sort_keys=True),
            )
            self.log_table.SetItem(index, 3, str(event.get("description", "")))
            self.log_table.EnsureVisible(index)

    def _on_stop(self, _event) -> None:
        self.owner.interrupt_processing(self.recording)

    def _on_back(self, _event) -> None:
        self.owner.processing_detail_frames.pop(self.recording, None)
        self.owner.Show()
        self.owner.Raise()
        self.Destroy()
