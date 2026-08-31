from .transcript_document import TranscriptDocumentBehavior
from .transcript_table import TranscriptTableBehavior
from .word_editor import WordEditorBehavior


class TranscriptionBehavior(
    TranscriptDocumentBehavior,
    TranscriptTableBehavior,
    WordEditorBehavior,
):
    """Conjunto temporário de comportamentos da aba de transcrição."""

    pass
