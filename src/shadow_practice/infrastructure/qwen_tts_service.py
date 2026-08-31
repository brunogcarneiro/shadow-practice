"""Serviço local para sintetizar áudio com Qwen3-TTS CustomVoice.

Execute este arquivo em um ambiente Python isolado que tenha qwen-tts, torch e
soundfile instalados. O serviço nunca fica exposto à rede: por padrão, escuta
somente em 127.0.0.1.
"""

import argparse
import hashlib
import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
DEFAULT_SPEAKER = "Aiden"
DEFAULT_LANGUAGE = "English"


class QwenTTSService:
    def __init__(self, model_name, device, cache_dir):
        import soundfile as sf
        import torch
        from qwen_tts import Qwen3TTSModel

        if device == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("MPS não está disponível neste computador.")

        self.sf = sf
        self.model_name = model_name
        self.device = device
        self.cache_dir = cache_dir
        self.generation_lock = threading.Lock()
        os.makedirs(self.cache_dir, exist_ok=True)

        dtype = torch.float16 if device == "mps" else torch.bfloat16
        print(f"Carregando {model_name} em {device}...")
        self.model = Qwen3TTSModel.from_pretrained(
            model_name,
            device_map=device,
            dtype=dtype,
            attn_implementation="eager",
        )
        supported_speakers = {speaker.lower() for speaker in self.model.get_supported_speakers()}
        if DEFAULT_SPEAKER.lower() not in supported_speakers:
            raise RuntimeError(f"A voz predefinida {DEFAULT_SPEAKER} não é suportada pelo modelo.")
        print("Modelo pronto.")

    def synthesize(self, text):
        normalized_text = " ".join(str(text).split())
        if not normalized_text:
            raise ValueError("O texto para síntese não pode estar vazio.")
        if len(normalized_text) > 12000:
            raise ValueError("O texto para síntese é longo demais.")

        fingerprint = "\0".join((self.model_name, DEFAULT_SPEAKER, DEFAULT_LANGUAGE, normalized_text))
        cache_path = os.path.join(self.cache_dir, hashlib.sha256(fingerprint.encode("utf-8")).hexdigest() + ".wav")
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as audio_file:
                return audio_file.read(), True

        with self.generation_lock:
            if not os.path.exists(cache_path):
                wavs, sample_rate = self.model.generate_custom_voice(
                    text=normalized_text,
                    language=DEFAULT_LANGUAGE,
                    speaker=DEFAULT_SPEAKER,
                )
                temporary_path = cache_path + ".tmp.wav"
                self.sf.write(temporary_path, wavs[0], sample_rate)
                os.replace(temporary_path, cache_path)
        with open(cache_path, "rb") as audio_file:
            return audio_file.read(), False


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format_string, *args):
            print(f"[{self.log_date_time_string()}] {format_string % args}")

        def send_json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/health":
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            self.send_json(HTTPStatus.OK, {
                "status": "ready",
                "model": service.model_name,
                "speaker": DEFAULT_SPEAKER,
                "language": DEFAULT_LANGUAGE,
            })

        def do_POST(self):
            if self.path != "/synthesize":
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                audio_bytes, cache_hit = service.synthesize(payload.get("text", ""))
            except (ValueError, json.JSONDecodeError) as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            except Exception as error:
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio_bytes)))
            self.send_header("X-TTS-Cache", "hit" if cache_hit else "miss")
            self.end_headers()
            self.wfile.write(audio_bytes)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Serviço local do Qwen3-TTS")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument(
        "--device",
        default=os.getenv("QWEN_TTS_DEVICE", "mps"),
        choices=("mps", "cpu", "cuda:0"),
    )
    parser.add_argument("--model", default=os.getenv("QWEN_TTS_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--cache-dir",
        default=os.getenv("QWEN_TTS_CACHE_DIR", "tts-cache"),
    )
    args = parser.parse_args()

    service = QwenTTSService(args.model, args.device, args.cache_dir)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    print(f"Serviço TTS disponível em http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServiço TTS encerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
