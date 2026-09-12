# Kernel canonical base

The immutable generic control-plane input for this Product revision is:

- repository: Cyrene-Platform
- commit: c59be6f2bd82489fbe933dadff84fc589e00afd9

Do not add training payloads, Plugin method schemas, argv or environment fields
to Platform contracts. Yield and the selected Plugin own those values.

Production `KernelTrainingExecutor` talks to `KernelAuthorityService`:

AcquireLease → StartWorker(execution_ref) → CancelOperation / StopWorker

Yield has no in-process or local execution fallback. Missing Platform authority
is reported as `YIELD_EXECUTION_NOT_CONFIGURED`.
