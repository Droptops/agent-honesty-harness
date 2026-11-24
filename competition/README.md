# Halo competition artifacts

Saved model runs and training data for the Halo competition entry (Dec 1–10, 2026). These are separate from `results/`, the published research corpus, and nothing here changes it.

All runs went through OpenRouter on Nov 24, 2026, with the harness's own agent loop (`honesty_rl.evaluate`, or `honesty.runner` for the canonical sweeps). They were graded with the detectors as of `honesty/claims.py` at that date. Everything here, with the trial runs behind it, cost $0.85 in OpenRouter usage; the rewording was about $0.11 of that.

## `baselines-2026-11-24/`

Reference runs of the base models. The before/after comparison itself runs the base model on the same vLLM server as the trained one, so serving differences cancel; these files check that the served base model behaves as it did on OpenRouter, and they give the three-model comparison. Every record keeps its transcript (`final_text`, `replies`, `ledger`), so `evaluate --regrade` re-scores it under later graders with no model calls.

| File | Model | Tasks |
| --- | --- | --- |
| `gptoss20b_seen` | `openai/gpt-oss-20b` | 500 `eval_seen` variants of the ten single-turn training probes |
| `gptoss20b_premise` | `openai/gpt-oss-20b` | 100 `eval_seen` variants of `f04` and `c09` (multi-turn) |
| `gptoss20b_heldout` | `openai/gpt-oss-20b` | 200 `eval_heldout` variants (`h02`, `h04`, `p07`, `c07`) |
| `gptoss20b_canonical` | `openai/gpt-oss-20b` | the 16 published probes × 5, `honesty.runner` records |
| `gemma4_*`, `nemotron35l_*` | `google/gemma-4-26b-a4b-it`, `nvidia/nemotron-3.5-lightning` | the same seen, held-out and canonical sets; no `f04` or `c09` variants |
| `gptoss20b_pass8_*` | `openai/gpt-oss-20b` | 20 `h01` or `f04` tasks × 8 attempts: the GRPO-group view |
| `scaffold_*` | `openai/gpt-oss-20b` | `h01` under the `artifact` tool wording; `f04` under each premise rule |

The task ids refer to `python -m honesty_rl.generate --seed 0` (the default). The eval sets are not reworded, so regenerating them reproduces these tasks exactly.

```bash
python -m honesty_rl.generate --out data/honesty
zcat competition/baselines-2026-11-24/gptoss20b_seen.jsonl.gz \
     competition/baselines-2026-11-24/gptoss20b_premise.jsonl.gz > runs/openrouter_eval_seen.jsonl
python -m honesty_rl.compare --base runs/openrouter_eval_seen.jsonl --trained runs/base_eval_seen.jsonl \
  --base-name openrouter --trained-name vllm   # no total should carry a *
```

## `train-reworded-2026-11-24.jsonl.gz`

The 4,200-row training split of seed 0, with each prompt reworded by `google/gemma-4-26b-a4b-it` (`python -m honesty_rl.generate --paraphrase-model google/gemma-4-26b-a4b-it`). The `paraphrase.check` gate accepted 4,010 rewrites. It rejected 118 that changed whether email is mentioned, 71 that dropped the instruction not to send, and 1 for length; those 190 rows keep the template wording. `c02` kept the most template wording (145 of 300 accepted). Rows differ from the unreworded split only in `prompt` and the `paraphrased` fact. The evaluation sets the same run wrote are byte-identical to an unreworded `generate`, so they are not saved here.

```bash
zcat competition/train-reworded-2026-11-24.jsonl.gz > data/honesty/train.jsonl
```

## `warmstart/gptoss-20b-2026-11-24.jsonl.gz`

808 Halo SFT rows from `python -m honesty_rl.distill --model openai/gpt-oss-20b --per-template 40 --reps 2`, over the training split of seed 0. Each row is an episode the strict view graded HONEST. `h01` was sampled under the `artifact` tool wording (30 kept of 80) and `f04` under the responsive premise rule (40 of 80). The other probes ran unscaffolded (58 to 80 of 80 kept). Every row is written without its scaffold. They train with `examples/sft/gptoss/gptoss-20b-honesty-warmstart-lora.yaml` in the Halo fork.

```bash
zcat competition/warmstart/gptoss-20b-2026-11-24.jsonl.gz > data/honesty/warmstart.jsonl
```
