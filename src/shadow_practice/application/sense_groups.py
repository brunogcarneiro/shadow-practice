import json
import os
from collections.abc import Callable

import requests

from ..config import get_settings

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b-instruct"
MAX_WORDS_PER_CALL = 50  # tamanho do pedaço enviado ao modelo local por chamada (pedaços menores mantêm a qualidade da segmentação)

MARKER = "|||"

PROMPT_TEMPLATE = """Você é um linguista especializado em preparar transcrições para a prática de shadowing (ouvir um trecho e repeti-lo em voz alta imediatamente).

Abaixo está um texto falado por UM ÚNICO falante em uma reunião. Copie o texto EXATAMENTE como está, palavra por palavra, na mesma ordem, sem adicionar, remover ou substituir nenhuma palavra inteira. A única coisa que você deve fazer é:
1) inserir o marcador {marker} nos pontos onde um novo "sense group" (grupo de sentido / thought group) deve começar;
2) ajustar apenas a pontuação e a capitalização de cada palavra.

Um "sense group" é uma unidade sintática, semântica e prosódica completa, que possa ser ouvida e repetida isoladamente. Regras para decidir onde colocar {marker}:
- Prefira uma oração independente completa por grupo.
- Orações subordinadas necessárias para completar o sentido devem ficar junto da oração principal.
- Nunca insira {marker} entre: sujeito e predicado; verbo e seus complementos; verbo auxiliar e verbo principal; preposição e complemento; determinante e substantivo; conjunção ou pronome relativo e a oração que introduzem; oração principal e subordinada necessária para completar o significado.
- Em períodos longos, quebre somente nos limites naturais entre orações ou grupos de sentido.
- Se uma sentença for longa demais para repetir confortavelmente, quebre em dois ou mais grupos sintaticamente completos.
- Nem todo grupo precisa ser uma sentença gramatical completa, mas deve ser compreensível e repetível sem terminar em uma expectativa sintática evidente.
- Preserve o texto efetivamente falado, incluindo características naturais da fala. Não reescreva para tornar mais formal. Só remova repetições ou fragmentos claramente causados por erro do sistema de transcrição.
- Seja generoso ao quebrar: a maioria dos grupos deve ter entre 3 e 10 palavras. Frases com mais de 12-15 palavras quase sempre podem ser divididas em pelo menos dois grupos sintaticamente completos (ex: separando orações coordenadas, cada complemento preposicional relevante, ou cláusulas relativas). Prefira mais grupos curtos a poucos grupos longos.

Exemplo (apenas ilustrativo, não use este conteúdo nem seu tamanho de grupo como teto — quebre mais se o texto real for mais longo):
Entrada: "yeah so basically what happened is the deployment failed last night and i had to roll it back manually because nobody was on call and then this morning marcus found the root cause which was a bad config value that got merged by accident"
Saída: "Yeah, so basically {marker}what happened is {marker}the deployment failed last night {marker}and I had to roll it back manually {marker}because nobody was on call, {marker}and then this morning {marker}Marcus found the root cause, {marker}which was a bad config value {marker}that got merged by accident."

Texto:
{text}

Responda APENAS com o texto reorganizado, com {marker} marcando o início de cada grupo (não coloque {marker} antes da primeira palavra). Não inclua nenhuma explicação, apenas o texto.
"""


def call_ollama(prompt):
    settings = get_settings()
    resp = requests.post(
        settings.ollama_url,
        json={
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": 8192, "temperature": 0.2},
        },
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["response"]


# Conjunções/pronomes coordenativos ou subordinativos usados como rede de segurança:
# se o modelo local deixar um grupo longo demais, tentamos quebrá-lo aqui perto do meio.
MAX_GROUP_WORDS = 14
SPLIT_WORDS = {"and", "but", "so", "because", "which", "that", "yet", "or", "since", "although", "though", "while"}


def split_long_group(tokens, words):
    """Quebra recursivamente um grupo longo demais em pontos de coordenação/subordinação
    próximos ao meio, mantendo o alinhamento 1:1 entre tokens de texto e palavras originais."""
    n = len(tokens)
    if n <= MAX_GROUP_WORDS:
        return [words]

    candidates = [i for i in range(2, n - 1) if tokens[i].strip(".,!?;:").lower() in SPLIT_WORDS]
    if not candidates:
        return [words]

    split_i = min(candidates, key=lambda i: abs(i - n // 2))
    left = split_long_group(tokens[:split_i], words[:split_i])
    right = split_long_group(tokens[split_i:], words[split_i:])
    return left + right


def assign_timestamps(chunk, group_texts):
    """Mapeia os grupos de texto retornados pelo modelo de volta às palavras
    originais (com timestamp) por contagem sequencial de palavras, de forma
    tolerante a pequenas diferenças (pontuação, maiúsculas) introduzidas pelo modelo."""
    groups = []
    pos = 0
    for text in group_texts:
        text = text.strip()
        if not text:
            continue
        tokens = text.split()
        n = len(tokens)
        if n <= 0:
            continue
        if pos + n > len(chunk):
            n = len(chunk) - pos
            tokens = tokens[:n]
        if n <= 0:
            break

        for sub_words in split_long_group(tokens, chunk[pos:pos + n]):
            if not sub_words:
                continue
            groups.append(sub_words)
        pos += n

    # Palavras que sobraram (modelo pode ter perdido algumas): anexa como grupo extra, verbatim
    if pos < len(chunk):
        leftover = chunk[pos:]
        groups.append(leftover)

    return groups


def fallback_group(chunk):
    return [chunk]


def with_default_discovered(word):
    normalized = dict(word)
    normalized.setdefault("discovered", False)
    return normalized


def group_chunk(chunk):
    text = " ".join(w["word"] for w in chunk)
    prompt = PROMPT_TEMPLATE.format(text=text, marker=MARKER)

    try:
        raw = call_ollama(prompt)
        group_texts = [g for g in raw.split(MARKER)]
        groups = assign_timestamps(chunk, group_texts)
        if groups:
            return groups
    except Exception:
        pass

    print("  aviso: modelo local não retornou uma resposta utilizável; usando o trecho inteiro como um único grupo.")
    return fallback_group(chunk)


def build_turns(words):
    turns = []
    for w in words:
        if turns and turns[-1]["speaker"] == w["speaker"]:
            turns[-1]["words"].append(w)
        else:
            turns.append({"speaker": w["speaker"], "words": [w]})
    return turns


def chunk_words(words, max_words):
    for i in range(0, len(words), max_words):
        yield words[i:i + max_words]


def group_words_file(
    words_path,
    progress_callback: Callable[[int, int], None] | None = None,
):
    """Atualiza um ``.words.json`` bruto com marcadores de grupos de sentido."""
    words_path = os.fspath(words_path)
    with open(words_path, encoding="utf-8") as source:
        words = json.load(source)
    if not isinstance(words, list):
        raise ValueError("O arquivo words.json deve conter uma lista.")

    turns = build_turns(words)
    output_words = []

    total_chunks = sum(
        len(list(chunk_words(turn["words"], MAX_WORDS_PER_CALL))) for turn in turns
    )
    completed_chunks = 0
    for t, turn in enumerate(turns, start=1):
        chunks = list(chunk_words(turn["words"], MAX_WORDS_PER_CALL))
        for c, chunk in enumerate(chunks, start=1):
            print(f"Processando fala {t}/{len(turns)}, trecho {c}/{len(chunks)}...")
            groups = group_chunk(chunk)
            for group_words in groups:
                output_words.append({"displayed": False, "human-transcription": ""})
                output_words.extend(with_default_discovered(word) for word in group_words)
            completed_chunks += 1
            if progress_callback is not None:
                progress_callback(completed_chunks, total_chunks)

    with open(words_path, "w", encoding="utf-8") as output:
        json.dump(output_words, output, ensure_ascii=False, indent=2)
    return words_path


def process_recording(audio_path):
    """Processa a transcrição bruta associada a um arquivo WAV."""
    audio_path = os.fspath(audio_path)
    if not audio_path.endswith(".wav"):
        raise ValueError("A gravação deve ser um arquivo .wav.")
    return group_words_file(audio_path[:-4] + ".words.json")


def main():
    recordings_dir = os.fspath(get_settings().recordings_dir)
    words_files = sorted(f for f in os.listdir(recordings_dir) if f.endswith(".words.json"))
    pending = []
    for filename in words_files:
        with open(os.path.join(recordings_dir, filename), encoding="utf-8") as handle:
            words = json.load(handle)
        if not any(isinstance(item, dict) and "displayed" in item for item in words):
            pending.append(filename)

    if not pending:
        raise SystemExit("Nenhuma transcrição pendente de reagrupamento em recordings/.")

    print("Transcrições ainda não reagrupadas em sense groups:")
    for index, filename in enumerate(pending, start=1):
        print(f"  {index}) {filename}")
    try:
        selected = pending[int(input("Escolha o número do arquivo para reagrupar: ").strip()) - 1]
    except (ValueError, IndexError):
        raise SystemExit("Escolha inválida.")

    output_path = group_words_file(os.path.join(recordings_dir, selected))

    print(f"Arquivo {output_path} atualizado com marcadores de grupos de sentido")


if __name__ == "__main__":
    main()
