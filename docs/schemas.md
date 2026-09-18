# JSON schemas

Machine-readable schemas live in `docs/schema/`.

A `.words.json` file is an array containing word objects and group-marker objects.
Word objects have `word`, `start`, `end`, and `speaker`; `discovered` is optional.
Markers use `displayed` and optional `human-transcription`. Legacy `linebreak` markers
are accepted. A `.speaks.json` file stores practice items with stable transcript/audio
ranges. Consumers must preserve unknown properties for forward compatibility.

Each completed processing run also contains a `metadata.json` validated by
`processing-metadata.schema.json`. It identifies the audio, model, provider, start and
completion timestamps, run status, artifacts, stage durations, and the pricing
snapshot used for any estimated API cost.
