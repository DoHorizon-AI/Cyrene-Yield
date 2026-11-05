# 5 分钟端到端 Linux NVIDIA 快速部署与训练验证指南 (5-Minute Quickstart E2E)

本文档面向 Linux x86_64 + NVIDIA GPU 生产与本地开发环境，提供在依赖与模型已下载就绪的前提下，5 分钟内完成端到端 Kernel 托管训练验证的标准 SOP（对应 Issue `Yield#16` 与 `Platform#65`）。

---

## 1. 目标与前提条件

### 部署时效目标
- **冷启动与就绪**：下载就绪后，从服务拓扑启动到完成 1-step Kernel-managed 最小 LoRA 验证 **< 5 分钟**。
- **状态透明度**：各组件构建耗时、启动状态及执行器链路可用性（`apiReady` / `executionReady`）明确区分。

### 前提依赖
- OS：Linux x86_64，NVIDIA 驱动正常（`nvidia-smi` 可用）
- 工具链：Rust (`cargo`), Python 3.12, `uv`
- 预下载产物：测试用微型基座模型（如 `qwen-0.5b` 或测试模型权重），下载耗时不计入部署耗时。

---

## 2. 部署与启动步骤（分步耗时基准）

### 步骤一：启动 Cyrene-Platform 本地 GPU Runtime（约 15 ~ 30 秒）
进入 `Cyrene-Platform` 根目录拉起本地 GPU 运行时拓扑：

```bash
cd Cyrene-Platform

# 1. 首次冷启动（自动编译 native 二进制，包括 system-adapter, nvidia-adapter, sandboxd, kernel）
python3 tooling/runtime/cyrene_runtime.py up --runtime-home /tmp/cyrene-runtime

# 注：若在非 root、且未配置 CAP_BPF / CAP_SYS_ADMIN 的本地普通用户环境验证：
# 可附加 --dev-mode 选项，以软隔离模式运行：
# python3 tooling/runtime/cyrene_runtime.py up --runtime-home /tmp/cyrene-runtime --dev-mode
```

验证运行时状态：
```bash
python3 tooling/runtime/cyrene_runtime.py status --runtime-home /tmp/cyrene-runtime
```
*预期输出*：
```json
{
  "profile": "CYRENE_PLATFORM_RUNTIME_V1_LOCAL_GPU",
  "status": "READY",
  "components": {
    "systemAdapter": "READY",
    "nvidiaAdapter": "READY",
    "sandboxd": "READY",
    "kernel": "READY"
  }
}
```

### 步骤二：校验 Trainer Runtime 探针（约 5 秒）
进入 `Cyrene-Yield/trainer-runtime` 运行就绪探针：

```bash
cd Cyrene-Services/Cyrene-Yield/trainer-runtime

# 执行环境导入探测（--repository 指向 Cyrene-Yield 仓库根路径）
uv run python probe.py --repository ..
```
*预期输出*：包含 `PROFILE: CYRENE_YIELD_TRAINER_V1_CUDA128`，所有依赖（包含 `packaging==26.3`、`torch`、`grpcio` 等）均导入校验通过。

### 步骤三：启动 Cyrene-Yield 训练服务（约 5 秒）
使用刚刚拉起的 Platform Kernel 运行 Yield API：

```bash
cd Cyrene-Services/Cyrene-Yield

# 启动服务
uv run cyrene-yield \
  --kernel-socket /tmp/cyrene-runtime/run/kernel.sock \
  --state-directory /tmp/cyrene-yield/state \
  --artifact-root /tmp/cyrene-runtime/artifacts &
```

验证 API 与执行链路就绪状态：
```bash
curl -s http://127.0.0.1:8000/healthz | jq .
```
*预期输出*：
```json
{
  "status": "READY",
  "apiReady": true,
  "executionReady": true,
  "trainingConfigured": true,
  "modelRegistryConfigured": false,
  "reconcileErrors": []
}
```
> [!NOTE]
> `apiReady: true` 表明 HTTP 控制面正常，`executionReady: true` 证明 Yield 已成功连通 Kernel 并完成预检。

### 步骤四：提交并运行 1-step 最小训练测试（约 10 ~ 20 秒）
创建并触发一个 1-step 的训练 Draft：

```bash
# 1. 创建训练 Draft
DRAFT_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/training-drafts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "5min-validation-run",
    "baseModel": "test-base-model",
    "parameters": {"maxSteps": 1, "learningRate": 0.0001}
  }' | jq -r .id)

# 2. 触发启动
curl -s -X POST "http://127.0.0.1:8000/api/v1/training-drafts/${DRAFT_ID}/actions/start" | jq .
```

检查训练执行状态直至完成，总计整体运行耗时稳定控制在 1 ~ 2 分钟之内，远优于 5 分钟上限要求。
