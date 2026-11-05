# Yield Workspace service authentication on Azure Container Apps

Yield private Workspace routes are disabled until a valid credential-to-scope map is configured. The deployment workflow currently cannot promote auth configuration. It only performs image deployments while both auth variables are unset; any auth configuration makes the run fail before it changes Azure resources. This keeps secret registration and revision updates closed until ACA updates can prevent concurrent deployments from overwriting a newer revision.

## Provisioning prerequisites

1. Generate a random Platform Workspace bearer with at least 32 bytes of entropy. Store only its lowercase SHA-256 digest in the version 1 map; keep the raw token in the Platform's approved secret store.
2. Store the map as a JSON Key Vault secret. Each digest maps to exactly one fixed organization and Workspace:

   ```json
   {"version":1,"credentials":[{"tokenSha256":"<lowercase SHA-256 hex>","organizationId":"org-id","workspaceId":"workspace-id"}]}
   ```

   During rotation, distinct token digests may map to the same scope. Duplicate digests and malformed maps are rejected. Verify every scope against the Platform provisioning record before storing the map; do not accept Workspace identity or role from a request body or header.
3. Assign the Yield Container App a system-assigned or user-assigned managed identity. Grant that identity `Key Vault Secrets User` on the vault, or equivalent secret-read access.
4. Keep these resource references and the identity in the reviewed deployment change record:
   - `YIELD_WORKSPACE_CREDENTIAL_MAP_SECRET_URI`: versionless Azure Key Vault secret URI for the map.
   - `YIELD_WORKSPACE_AUTH_IDENTITY`: `system` or the full resource ID of a user-assigned identity already attached to the app.

   Do not set these GitHub variables yet: any non-empty auth variable intentionally fails the deployment workflow before Azure changes. Never put the JSON map, raw bearer, or other secret values in GitHub variables, source control, command output, or workflow logs. Keep Yield's map and Key Vault reference independent from Reactor.

## Deployment behavior

The workflow deploys on pushes to `main`, `release`, and `develop`, and on manual dispatch. If both auth variables are unset, it deploys the image and leaves existing ACA authentication settings unchanged. If either auth variable is set, the workflow stops before checkout or any Azure mutation. With no Workspace map configured, private `/internal/workspace/v1/training-drafts` routes return `503`; a successful image deployment does not enable private access by itself.

The automated auth rollout is deliberately closed. Azure's documented [Container Apps Update API](https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/container-apps/update) uses JSON Merge Patch and does not document an `If-Match`/ETag precondition. Even a targeted environment-variable update can race another revision update because the deployment client builds its patch from a prior app snapshot. Do not treat a preflight snapshot or a GitHub workflow lock as protection from portal, IaC, or other out-of-band writers.

Auth promotion is a manual deployment prerequisite until an atomic conditional update or a shared deployment lock for every writer is available. The operator must serialize all writes to the Container App, including Actions, portal, IaC, and other deployment systems; inspect the current app/revision and secret-reference names; apply only the reviewed auth change; then verify the resulting internal, healthy revision. If the reviewed snapshot changes before the update, stop and re-review. Do not read or print Key Vault contents or ACA secret values.

The private alias supports scoped draft create/import, get, prepare, and start operations. Product derives the organization and Workspace from the server-side credential map and checks scope provenance for private resource reads and writes. The bearer identifies the calling Platform service; it does not establish an end user, member, or role.

Removing an active reference requires a separately reviewed, serialized revision update. Key Vault secret rotation should be followed by a Yield deployment so a fresh revision consumes the current reference; rotate the Platform caller and Product map in the intended overlap window.

## Failure recovery and cleanup

- An auth-configured Actions run is expected to fail before checkout or Azure changes. Keep both variables unset for image-only deployments; use the reviewed manual process for auth promotion.
- Before manual promotion, validate the map's digest and exact organization/Workspace assignments. A syntactically valid map can assign the wrong scope.
- If an operator's update fails or times out, inspect revision health, image, internal ingress, and the environment **secret reference name** only. Do not call `az containerapp secret list --show-values` or `listSecrets`.
- Remove an ACA secret only after confirming no active revision references it. Use name-only secret listing and the normal revision deactivation process; never print secret values.

## 中文说明

Yield 私有 Workspace 路由在有效的凭据到范围映射配置前保持禁用。当前部署工作流只在两个认证变量全部为空时执行镜像更新；只要任一变量非空，工作流便会在检出代码或修改 Azure 资源前失败。这样可避免缺少并发条件更新保护时，密钥注册和 revision 更新覆盖其他部署产生的较新 revision。

Platform Workspace bearer 至少需要 32 字节熵；Key Vault 映射只保存其小写 SHA-256 摘要及固定的组织/Workspace 范围。不同 token 摘要可在轮换期映射到同一范围；重复摘要和格式错误的映射会被拒绝。为 Yield 分配托管身份，并仅授予该身份读取映射所在 Key Vault secret 的权限。

认证配置必须由人工按变更流程部署。在整个变更期间，必须使用覆盖 Actions、Azure 门户、IaC 及其他发布系统的统一部署锁，检查当前应用、revision 和密钥引用名称，只提交审查过的认证配置，并验证更新后的内部入口和健康 revision。如果快照已变化，应停止并重新审查。当前官方 Container Apps Update API 文档没有说明 `If-Match`/ETag 条件更新；即使只修改环境变量，部署客户端也会依据先前读取的应用快照构造更新。预检快照或只锁 GitHub workflow 都不能防止外部写入者造成竞态。

所有 token 与 JSON 映射只保存在经批准的密钥管理系统中；工作流、变更记录和日志中不得出现密钥值。Workspace 映射必须由服务器端凭据确定组织与 Workspace 范围。bearer 只代表 Platform 服务身份，不代表最终用户、成员或角色。

认证变量未配置时，镜像发布不改变现有 ACA 认证配置，私有 `/internal/workspace/v1/training-drafts` 仍返回 `503`。移除引用或轮换密钥也需要单独审查并在统一部署锁下更新。检查和清理时只查看密钥引用名称，不读取或打印 Key Vault/ACA 密钥值。
