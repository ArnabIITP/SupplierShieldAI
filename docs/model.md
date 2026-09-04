# Model documentation

The local benchmark uses a versioned synthetic dataset (`supplier-risk-dataset-v1-synthetic`) and a supplier-risk feature set: logged amount, advance percentage, quote deviation, payment-destination change, document mismatch, missing information count, and delivery period.

Training uses a deterministic seed and creates a held-out test report at `backend/artifacts/model_metrics.json`. Threshold selection is `0.5` for the initial balanced policy. Results are synthetic benchmarks only and must not be portrayed as real-world fraud performance.

Known limitations: synthetic labels, no authoritative government/bank verification, possible distribution shift, and incomplete evidence. Human review remains accountable for consequential actions.
