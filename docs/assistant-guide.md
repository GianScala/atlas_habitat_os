# Talk to your habitat

ATLAS turns a crew question into a conversation with the habitat's records.
The model chooses tools to retrieve data, then explains the results. You can
ask a follow-up, inspect what it read, and compare the answer with the dashboard.

## Start a local model

1. Install [Ollama](https://ollama.com/download) on the backend computer.
2. Start the Ollama app or run `ollama serve`.
3. Open **Settings → AI & models** in ATLAS.
4. Select the local Ollama provider. Install a model from the list, or use one
   already installed. Check that it supports **tools**.
5. Select that model and return to the assistant to ask a question.

Model downloads need internet access and disk space. Once installed, local
inference can work offline as long as the habitat database and local services
are reachable. ATLAS does not need a cloud API key for Ollama.

![Local model provider and installed models in ATLAS](images/atlas-local-models.png)

The active model is shared by the ATLAS instance. A choice saved in settings
persists and overrides the environment's fallback model. It does not retrain
the model on your habitat: ATLAS supplies the habitat context and retrieves
relevant records when you ask.

### What “local” means

With the default `OLLAMA_HOST=http://127.0.0.1:11434`, the model processes the
question, conversation, and retrieved context on the backend computer.
The crew can use a browser on another device connected to that server.

If `OLLAMA_HOST` points to another computer, that computer receives the model
context. If you select Anthropic, the context goes to its cloud API instead.
The habitat database connection is configured separately from the model provider.

### Choosing a model

Use **tool support** as the first requirement: this is how the model requests
live readings instead of relying on its training data. The settings page shows
capabilities reported by Ollama for installed models.

Model size and context length affect memory use and latency. A longer context
can accommodate more conversation and tool results, but uses more memory.
The first question may take longer while the model loads and processes the
habitat context. Test your crew's real question types on the intended computer;
a model that writes fluent prose may still struggle to select the right tool.

The room-comparison example uses `ministral-3:8b`; the water trace and settings
example use `qwen3.5:9b`. These record the capture setup, rather than promising
identical answers from every model.

## Ask a useful first question

Include the resource or room, a period, and the comparison you want:

- “What is the latest temperature in the greenhouse, and when was it read?”
- “How much clean water did we use over the last three days? Show the daily breakdown.”
- “How does our water consumption compare with the saved mission plan?”
- “Using the crew meter log, which room used the most energy on MD-03?”

You do not need to name a database field or write SQL. ATLAS provides the model
with habitat names, units, available measurements, and tools for querying them.
When a reading is unavailable, the useful answer is an explanation of the gap.

![A local model comparing greenhouse and dormitory temperatures](images/atlas-ai-answer.png)

Continue in the same conversation to refine the result:

> “Separate refills from consumption.”
>
> “Which days are incomplete?”
>
> “Summarise that for the next crew handover.”

Follow-ups use conversation history, but the model may need another tool call
to retrieve a new period or comparison. Ask it to name the source and time
window when those are important to your interpretation.

## Refine the analysis

Use **Settings → AI & models → How ATLAS answers** to choose concise or detailed
responses. You can also ask for the format you need in the conversation:

- “Give me the result first, then a table of the supporting readings.”
- “Compare that with the saved mission allowance and flag coverage gaps.”
- “Write a short handover note for the next crew, separating findings from checks to perform.”

These preferences change presentation, not the available evidence. For a new
comparison or an updated figure, ask the assistant to query the relevant source
and check the trace to confirm it did so.
If a table leaves out a partial day or a conclusion seems unsupported, follow up
and check the returned records rather than accepting the wording alone.

## Understand the answer's evidence

There are three parts to inspect:

| Part | What it tells you |
| --- | --- |
| Answer | The model's explanation, tables, comparisons, and caveats |
| **what ATLAS read** | Tool requests, arguments, and whether each returned data or failed |
| **Source** | Query text or query summaries returned by the tools |

![Tool activity and source references expanded beneath the answer](images/atlas-ai-sources.png)

The trace is a record of tool activity, not a proof of the model's reasoning.
The Source panel carries the adapter's query reference. In the SQLite demo it
is a descriptive summary, not runnable SQL; the trace shows the tool arguments,
including sensor and filter choices.
Backend functions handle consumption arithmetic; the model still has to choose
the right question and interpret the result correctly.

Not every source has a telemetry query. Manual log results identify themselves
as crew-entered readings, and document search returns passages with their source
information. A manual-log answer should not present those values as sensor data.

Check units, dates, coverage, and the source used before acting on an answer.
A rolling three-day window may include partial calendar days; Mission plan uses
its configured day boundary. Compare matching windows and sources when checking
an answer against a chart.

## What the assistant can draw on

| Information | Configuration or location |
| --- | --- |
| Sensor readings and history | Active data-source adapter and habitat profile |
| Mission targets and tracked consumption | Saved Mission plan |
| Manual consumption by room or tap | Crew meter log |
| Procedures and reference material | Files attached in Settings → Connectors |

These records remain distinct. Manual entries do not fill sensor gaps, and a
planned extra reserves budget without recording actual consumption. The model
is instructed to preserve those distinctions and cite the relevant evidence.

For document questions, attach the reference material before asking about it.
Search retrieves relevant passages; it does not train new model weights.
Only the configured data and attached context are available to the assistant.

## Speak and listen

With the optional local voice tools configured, use the microphone to dictate
a question and **Read aloud** to hear an answer. Transcription and speech
synthesis run locally; the answer itself still uses the selected model provider.
See [offline voice setup](../atlas_backend/README.md#optional-offline-voice).

## Limits worth understanding

ATLAS reads telemetry; chat does not control habitat equipment. It can compare
recorded conditions and identify patterns worth investigating, but cannot confirm
a physical cause without supporting evidence. Tool failures, missing coverage,
and model interpretation errors can all limit an answer.

For a regular daily check or an exact table value, use the dashboard directly.
For a comparison, explanation, or follow-up investigation, use the assistant.
The [consumption guide](consumption-guide.md) covers the dashboard workflow.
