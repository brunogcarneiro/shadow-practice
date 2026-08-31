"""Clientes para os modelos generativos usados pelo Transcript Player.

Este módulo não depende de wxPython nem de componentes de reprodução. As
operações são síncronas; a interface decide quando executá-las em threads.
"""

try:
    import requests
except ModuleNotFoundError:  # Allows unit tests to inject a fake HTTP client.
    requests = None


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_REWRITE_MODEL = "gpt-5.4-mini"
QWEN_TTS_SERVICE_URL = "http://127.0.0.1:8011"


class GenerativeModelError(RuntimeError):
    """Erro de comunicação ou validação de um modelo generativo."""


class GenerativeModelManager:
    """Facade síncrona para OpenAI Responses e Qwen3-TTS local."""

    def __init__(
        self,
        openai_responses_url=None,
        openai_rewrite_model=None,
        qwen_tts_service_url=None,
        http_client=None,
    ):
        from ...config import get_settings

        settings = get_settings()
        self.openai_responses_url = openai_responses_url or settings.openai_responses_url
        self.openai_rewrite_model = openai_rewrite_model or settings.openai_rewrite_model
        self.qwen_tts_service_url = (
            qwen_tts_service_url or settings.qwen_tts_service_url
        ).rstrip("/")
        if http_client is None:
            if requests is None:
                raise GenerativeModelError(
                    "A dependência requests não está instalada. Instale o projeto para usar modelos generativos."
                )
            http_client = requests
        self.http_client = http_client

    def rewrite_meeting_speech(self, original_text):
        original_text = str(original_text or "").strip()
        if not original_text:
            raise GenerativeModelError("O texto para reescrita não pode estar vazio.")

        from ...config import get_settings

        api_key = get_settings().openai_api_key
        if not api_key:
            raise GenerativeModelError(
                "A variável de ambiente OPENAI_API_KEY não está configurada."
            )

        prompt = self._build_rewrite_prompt(original_text)
        try:
            response = self.http_client.post(
                self.openai_responses_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.openai_rewrite_model,
                    "input": prompt,
                    "store": False,
                    "max_output_tokens": 500,
                },
                timeout=90,
            )
        except Exception as error:
            raise GenerativeModelError(f"Erro ao acessar a OpenAI: {error}") from error

        if not response.ok:
            raise GenerativeModelError(self._format_openai_error(response))

        try:
            payload = response.json()
        except ValueError as error:
            raise GenerativeModelError(
                "A OpenAI retornou uma resposta JSON inválida."
            ) from error

        output_parts = []
        for output_item in payload.get("output", []):
            for content_item in output_item.get("content", []):
                if content_item.get("type") == "output_text":
                    output_parts.append(content_item.get("text", ""))
        rewritten_text = "".join(output_parts).strip()
        if not rewritten_text:
            raise GenerativeModelError("O modelo retornou uma resposta vazia.")
        return rewritten_text

    def get_tts_health(self):
        try:
            response = self.http_client.get(
                f"{self.qwen_tts_service_url}/health", timeout=2
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            if isinstance(error, GenerativeModelError):
                raise
            raise GenerativeModelError(
                f"Não foi possível consultar o serviço TTS: {error}"
            ) from error

        if not isinstance(payload, dict):
            raise GenerativeModelError(
                "O serviço TTS retornou um status inválido."
            )
        return payload

    def synthesize_speech(self, text):
        text = str(text or "").strip()
        if not text:
            raise GenerativeModelError("O texto para síntese não pode estar vazio.")

        try:
            response = self.http_client.post(
                f"{self.qwen_tts_service_url}/synthesize",
                json={"text": text},
                timeout=300,
            )
        except Exception as error:
            raise GenerativeModelError(
                f"Não foi possível acessar o serviço TTS: {error}"
            ) from error

        if not response.ok:
            try:
                error_message = str(response.json().get("error", response.text))
            except (ValueError, AttributeError):
                error_message = response.text
            raise GenerativeModelError(
                f"Serviço TTS HTTP {response.status_code}: {error_message}"
            )

        audio_bytes = response.content
        if not audio_bytes:
            raise GenerativeModelError("O serviço TTS retornou um áudio vazio.")
        return audio_bytes

    @staticmethod
    def _build_rewrite_prompt(original_text):
        return f"""Rewrite the English meeting speech below so that it sounds professional, polite, and collaborative.

The rewritten speech MUST be in English. Never translate it into Portuguese or any other language.
Preserve the original meaning, intent, and first person when applicable. Keep it natural for spoken communication in a meeting. Do not invent facts, commitments, names, or details, and avoid excessive formality.
Split the rewritten speech into paragraphs only at natural points where the speaker could comfortably pause, such as after a complete thought or a clear transition. Separate paragraphs with a blank line. Do not create arbitrary breaks or split a sentence unnaturally.

Original English speech:
{original_text}

Return only the rewritten English speech, without explanations or quotation marks."""

    @staticmethod
    def _format_openai_error(response):
        error_code = ""
        error_message = response.text.strip()
        try:
            error_payload = response.json().get("error", {})
            error_code = str(
                error_payload.get("code") or error_payload.get("type") or ""
            )
            error_message = str(error_payload.get("message") or error_message)
        except (ValueError, AttributeError):
            pass

        request_id = response.headers.get("x-request-id")
        detail = f"OpenAI API HTTP {response.status_code}"
        if error_code:
            detail += f" ({error_code})"
        if error_message:
            detail += f": {error_message}"
        if request_id:
            detail += f"\nRequest ID: {request_id}"
        return detail
