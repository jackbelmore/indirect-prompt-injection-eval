# Scope and intended use

This is a measurement harness. It exists to find out how often a tool-enabled language model
obeys an instruction hidden in a document it was asked to read, and to score the result from the
tool log rather than from what the model says it did.

**Run it only against models you own or are authorised to test.** In practice that means models
you have pulled onto your own machine with Ollama. The harness talks to `localhost:11434` by
default and there is no reason to point it anywhere else. If you do point it at a hosted
endpoint, the documents and the model's replies leave your machine, and whether you are allowed
to send them is between you and whoever runs that endpoint.

**Nothing on your machine is read or executed.** The two tools the model is offered,
`safe_view_file` and `safe_execute_command`, are fakes. They live in `MockMCPServer` in
`src/evaluation_pipeline.py`, they log what the model tried to do, and they hand back a
fabricated reply. A trial that scores `exploited_command_execution` means the model asked for a
command to be run; it does not mean one was.

**The payloads are not here, and the ones you write are yours.** See `payloads/README.md`. A
library of injection payloads that reliably works against current models is offensive material
whatever it is labelled, which is why this repository ships the shell and not the contents.
Keep your own library out of public repositories for the same reason.

**One thing in the harness is not a placeholder.** `src/run_controls.py` hard-codes three
control documents, two of which do carry a real instruction: they tell the model to call
`safe_execute_command`, and to call `safe_view_file` on `/etc/shadow`. They are there because
the controls are what show the classifier is neither blind to an exploit nor inventing one from
a clean document, and the run is not reproducible without them. They name only the two fake
tools, so there is nothing there that works against a real system.

## Reporting a problem

If you find a bug in the scoring, such as a trial classified as an exploit that is not one or the
reverse, open an issue with the tool log and the classified status. That is the part of this that
matters.
