# GitHub Actions 自动部署

这个仓库现在有一个部署 workflow：

```text
.github/workflows/deploy-main.yml
```

触发方式：

- push 到 `main`
- 在 GitHub Actions 页面手动运行 `Deploy main to GCP VM`

部署流程：

1. checkout 代码
2. `go test ./...`
3. `go vet ./...`
4. 使用 GitHub OIDC + GCP Workload Identity Federation 登录
5. 打包当前 main branch 的源码
6. 上传到 GCP VM `misarch-compose`
7. 在 VM 上构建 Docker 镜像
8. 重启 `misarch-agent-gateway` 容器
9. 检查公网 `/readyz`

## GCP 认证

当前项目禁用了 service account JSON key：

```text
constraints/iam.disableServiceAccountKeyCreation
```

所以 workflow 不使用 `GCP_SA_KEY`，而是使用 GitHub OIDC + GCP Workload Identity Federation。

已经配置的资源：

```text
Workload Identity Pool: github-actions
Provider: github
Provider resource:
projects/170116153285/locations/global/workloadIdentityPools/github-actions/providers/github

Service account:
github-actions-deployer@project-b04b8a42-0a18-46d0-bc6.iam.gserviceaccount.com
```

provider 只允许这个仓库的 `main` 分支认证：

```text
attribute.repository == 'muzhi-hac/agent_mpv_misarch'
attribute.ref == 'refs/heads/main'
```

因此不需要在 GitHub 里配置 `GCP_SA_KEY` secret。

## GCP 权限

这个 service account 至少需要能：

- 查看 VM 信息
- 通过 `gcloud compute scp` 上传文件
- 通过 `gcloud compute ssh` 在 VM 上执行部署命令
- 使用 VM 当前绑定的 Compute Engine default service account

实验环境可以先给这个 service account：

```text
Compute Instance Admin (v1)
```

此外，service account 上已经给 GitHub principal 绑定：

```text
roles/iam.workloadIdentityUser
```

因为 `gcloud compute ssh/scp` 会检查 VM 绑定的 service account，部署账号还需要在当前 VM 使用的 default Compute Engine service account 上拥有：

```text
roles/iam.serviceAccountUser
```

当前绑定对象：

```text
170116153285-compute@developer.gserviceaccount.com
```

如果项目启用了 OS Login 或更严格 IAM，再补对应的 SSH/OS Login 权限。

## 部署目标

默认目标写在 workflow 的 `env` 里：

```text
GCP_PROJECT_ID=project-b04b8a42-0a18-46d0-bc6
GCP_WORKLOAD_IDENTITY_PROVIDER=projects/170116153285/locations/global/workloadIdentityPools/github-actions/providers/github
GCP_SERVICE_ACCOUNT=github-actions-deployer@project-b04b8a42-0a18-46d0-bc6.iam.gserviceaccount.com
GCP_ZONE=europe-west3-b
GCP_VM_NAME=misarch-compose
DEPLOY_DIR=/opt/misarch/misarch-agent-gateway-go
CONTAINER_NAME=misarch-agent-gateway
DOCKER_NETWORK=infrastructure-docker_default
```

部署完成后会检查：

```text
http://34.40.117.201:8001/readyz
```

workflow 里实际会从 VM 动态读取公网 IP，所以 VM IP 改了也能检查新的地址。

## 注意

GitHub Actions runner 的出口 IP 会变化。如果以后把 VM 的 SSH 或 `8001` firewall rule 改成固定 IP 白名单，自动部署可能会因为连不上 VM 而失败。

这次 workflow 沿用当前手动部署方式：源码上传到 VM，在 VM 上 `docker build`，然后替换同名容器。
