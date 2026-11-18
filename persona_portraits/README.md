# Enhanced DREAM profiles for Persona Modality

The runner expands the 200 short persona records using the DREAM profile
expansion template, demographic configuration and fallback sampler.
Each missing profile uses one GPT-5.6 Terra call with low reasoning effort
and a 4,000-token output limit.

The source ID and short persona text come from Persona Modality:
https://github.com/claws-lab/persona-modality/blob/main/src/datasets/full-dataset.json
Source blob: 14ac2a996d6c5650997c2d6bb7dfa5bddf381bfe
DREAM upstream commit: 9391ff124fa8b6ae2b7332a735fa82c80c74d322
Licenses and attribution remain in the repository.

## Run

Use Python 3.10 or later with OPENAI_API_KEY in your environment.

    python persona_portraits/run.py --all --dry-run
    python -u persona_portraits/run.py --all

Completed profiles from the ten-persona pilot are reused. Existing pilot
metadata, portraits and usage records are retained. New enhanced profiles
are saved in persona_portraits/out/<id>/metadata.json with source,
sampled synthetic fallbacks, profile and usage information.
Added narrative details are fictional enrichment.

Default selection is the ten pilot IDs. Use --all for 200 records or
--ids for explicit IDs. Use one process per output directory.
The legacy --quality argument is accepted for compatibility.

## Token and cost report

    python persona_portraits/usage.py persona_portraits/out/usage.jsonl

The report includes historical attempts grouped by expansion, portrait prompt
and image generation. For enhanced-only costs, use the expansion group.
OpenAI Standard USD prices are used. Missing usage is flagged.
Reasoning tokens are included in output tokens.

Occupation or location wording that is absent literally from personal_data is
recorded in metadata.json under validation_warnings for semantic review.
This lexical check is advisory because the expansion may use paraphrases.
ID, age, gender, allowed labels and narrative structure checks still stop
on invalid output. The original persona remains available in source.
