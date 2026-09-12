# Glossary / 术语表

| English | 中文 | Meaning / 含义 |
|---|---|---|
| Yield | Yield 训练服务 | Cyrene product for training and fine-tuning / Cyrene 的训练与微调产品 |
| TrainingSpec | 训练规格 | Engine-agnostic declaration of model, dataset, outputs, and policy / 与引擎无关的模型、数据集、输出与策略声明 |
| TrainingRun | 训练运行 | Product-level job identity and lifecycle / 产品级作业身份与生命周期 |
| TrainingAttempt | 训练尝试 | One execution attempt under a run / 某次训练运行下的一次执行尝试 |
| TrainingRuntime | 训练运行时 | Coordinator for attempts, events, execution, and artifacts / 负责尝试、事件、执行与制品的协调器 |
| Tiny dry run | 小型试运行 | Minimal execution gate before full training / 完整训练前的最小执行门禁 |
| Preflight | 前置校验 | Static compatibility and safety checks / 静态兼容性与安全检查 |
| Engine adapter | 引擎适配器 | Boundary translating product intent to engine execution / 将产品意图转换为引擎执行的边界 |
| Executor | 执行器 | Starts and stops a controlled workload process tree / 启停受控工作负载进程树的组件 |
| Checkpoint | 检查点 | Saved model state produced during or after training / 训练中或训练后保存的模型状态 |
| CheckpointRef | 检查点引用 | Digest-backed reference to a verified checkpoint artifact / 指向已验证检查点制品的摘要引用 |
| Artifact Plane | 制品平面 | Platform boundary for immutable training outputs / 平台存储不可变训练输出的边界 |
| LLaMA Factory | LLaMA Factory | Plugins-owned training backend consumed by Yield / Yield 消费的 Plugins 所有训练后端 |
| LoRA / QLoRA | LoRA / QLoRA | Parameter-efficient fine-tuning methods / 参数高效微调方法 |
| Kernel authority | 内核权威 | Platform-owned execution and resource boundary / Platform 负责的执行与资源边界 |
| Contract candidate | 契约候选 | Documented seam awaiting final implementation or integration / 已记录但等待最终实现或集成的接缝 |
