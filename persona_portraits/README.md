# DREAM portraits for Persona Modality

This adapter adds portrait generation to DREAM for the 200 personas in Persona
Modality. It reads only the original persona ID and short persona text.

- DREAM upstream commit: `9391ff124fa8b6ae2b7332a735fa82c80c74d322`
- [Persona Modality dataset](https://github.com/claws-lab/persona-modality/blob/main/src/datasets/full-dataset.json), source blob `14ac2a996d6c5650997c2d6bb7dfa5bddf381bfe`
- `personas.json` contains the ID and text extracted from that blob. The original license is in `LICENSE-persona-modality`.

The adapter uses the DREAM demographic configuration and fallback sampler.
The templates in `expand.txt` and `portrait.txt` adapt the original
`1000/prompts_profile_extension.py` and `1000/prompts_profile_images.py`
from two dialogue participants to one text-only persona. The original age,
gender, occupation and city are retained. In the source's one joined word
`maleretail`, the prompt instructs the model to read it as “male retail”.
Profile details added by the model are synthetic. The sampled fallback
values are saved separately from the source record.

## Run

Use Python 3.10 or later from the repository root. The runner uses the Python
standard library. Set `OPENAI_API_KEY` in your environment before running
generation. Validate all inputs without API access, then run the ten-persona
pilot with these commands.

```powershell
python persona_portraits/run.py --all --dry-run
python persona_portraits/run.py
```

After reviewing the pilot, run the complete set in the same output directory.

```powershell
python persona_portraits/run.py --all
```

The pilot uses IDs 0, 20, …, 180. Use `--ids` to select explicit IDs.
The default is 1024 × 1024 at `medium`. Use `--quality high --output <directory>`
for a separate high-quality run.

Each persona uses GPT-5.6 Terra in two calls (expanded profile and portrait
prompt), followed by one GPT Image 2.5 Sunburst generation request.
Outputs default to `persona_portraits/out/<id>/portrait.png`
with the source, profile, prompt, model settings, and available usage data
in `metadata.json`. Use one process per output directory. Running the same
command again skips completed portraits and reuses saved intermediate results.

Each API attempt is recorded in `usage.jsonl` with its stage, persona ID,
request ID when available, and the token usage returned by OpenAI. Run the
report without calling the API.

```powershell
python persona_portraits/usage.py persona_portraits/out/usage.jsonl
```

The report estimates USD at OpenAI Standard rates and lists attempts with
unavailable usage separately. Reasoning tokens are already included in text
output tokens. The report covers recorded usage and may differ from the
provider invoice, for example if a connection drops before usage is returned.
