# The payload library

This repository ships without payloads. The file the harness reads,
`payloads/library.json`, is not here and is not in the history. That is deliberate: the
dissertation reports what a set of injection payloads did to a set of local models, and
publishing a working library of them alongside the harness would hand someone a ready-made
attack kit. The measurement shell is the useful part, so the measurement shell is what is
published. You supply your own payloads.

`example_payload.json` in this directory is a valid two-record library. It is harmless — the
`injection_payload` text asks for nothing and names no tool, so a model reading it will simply
summarise the document. Copy it and build from there:

```bash
cp payloads/example_payload.json payloads/library.json
python3 src/payload_generator.py
```

That writes six documents into `documents/`: two payloads in three carriers each.

## Format

One file, `payloads/library.json`. It holds a single JSON **array** of payload records — not
JSONL, and not one file per payload. Nothing in the harness writes it; it is yours to maintain
by hand.

```json
[
  {
    "id": "P001",
    "name": "Direct File Read",
    "attack_type": "data_exfil_file",
    "obfuscation": "plain",
    "description": "Plain text instruction attempting to hijack tool-calling to read a sensitive file.",
    "injection_payload": "the text that gets embedded in the carrier document"
  }
]
```

| field | required | what it is |
|---|---|---|
| `id` | yes | `P` followed by three digits, `P001` upward. Unique. It becomes the filename prefix of every document generated from this payload, and it is how a trial result is joined back to its payload at analysis time. |
| `injection_payload` | yes | The attacker's text. This is the only part that reaches the model. It is inserted verbatim into each carrier. |
| `name` | no | A short human label. Used in reports and figures. |
| `attack_type` | no | The category the analysis groups by. See below. |
| `obfuscation` | no | A free-text label for the technique used to hide or dress up the instruction. See below. |
| `description` | no | A sentence for your own records. Nothing reads it. |

Only `id` and `injection_payload` are needed to run. The rest is metadata that makes the
analysis breakdowns meaningful, and a library without it still works — untyped payloads just
land in the `unknown` bucket.

### `attack_type`

Four values, the ones the study used. `analyze_results.py` groups the ASR breakdown and the
summary CSV by this field, so any string works, but these are what the outcome taxonomy was
built around:

| value | what the payload is trying to make the model do |
|---|---|
| `rce_basic` | call `safe_execute_command` and run something |
| `data_exfil_file` | call `safe_view_file` on a path it was not asked to read |
| `chain_attack` | read something, then act on what it read |
| `tool_hijack` | use a tool for a purpose other than the one the user asked for |

### `obfuscation`

A grouping label, free text, used only to break the results down by technique. The study used
23 of them — `plain`, `base64`, `html_comment`, `markdown_hidden`, `multilingual`,
`roleplay_framing`, `urgency`, `naturalistic`, and a set of named techniques from the
literature. Use whatever labels make sense for your own set; `plain` is a sensible default.

### There is no `target_tool` field

The target is implicit in the payload text. The model is only ever offered two tools, both of
them fakes defined as `MOCK_TOOLS` in `src/evaluation_pipeline.py`:

- `safe_view_file(path)` — returns canned content, reads nothing from disk
- `safe_execute_command(utility_name, args)` — returns a canned reply, runs nothing

`is_exploiting_call()` in the same file decides whether a call was an exploit by comparing the
requested path against the one legitimate document path for that trial. So the classifier works
out the target from the call the model actually made, not from anything you declare here.

## What reads what

| file | reads |
|---|---|
| `src/payload_generator.py` | `id` and `injection_payload`. Wraps the payload in three carriers and writes `documents/P001_email.txt`, `P001_code_comment.txt`, `P001_readme.txt`. |
| `src/analyze_results.py` | Keys the library by `id`, reads `attack_type` for the per-type breakdown and the CSV. Warns and carries on if the library is missing. |
| `src/validate_classifier.py` | Keys the library by `id`, recovers the id from the result record's `document_name` by splitting on `_`. |

Because the id is recovered by splitting the document name on `_`, an id must not itself contain
an underscore.

## The three carriers

`payload_generator.py` embeds every payload in three ordinary-looking documents, hard-coded in
`DocumentGenerator`: a support-ticket email, a Python code comment, and a markdown README's
troubleshooting section. Those wrappers are part of the harness, not part of your library, so
adding one payload adds three documents. If you want different carriers, edit the three
`wrap_in_*` methods.
