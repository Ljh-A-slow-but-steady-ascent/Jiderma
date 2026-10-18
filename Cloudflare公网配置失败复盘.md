# Cloudflare 公网配置失败复盘

## 目标与安全边界

原计划使用免费 Cloudflare Quick Tunnel，只将 Streamlit 演示页面暴露为临时 HTTPS 地址。FastAPI、模型、RAG、SQLite、密钥和原始图片均保持本机访问。

当时的公网链路为：

```text
外部浏览器 -> Cloudflare Quick Tunnel -> 127.0.0.1:8501 同源网关
                                            |-> Streamlit 127.0.0.1:8502
                                            `-> FastAPI 127.0.0.1:8000 白名单接口
```

## 已完成的尝试

1. 检查项目端口与调用方式，确认 FastAPI 使用 8000，Streamlit 默认使用 8501。
2. 安装官方 `cloudflared 2026.10.0` 到用户目录。
3. 建立受限同源网关，公网只转发 Streamlit 和聊天白名单接口，不直接暴露 FastAPI 8000。
4. 编写一键启动、停止、PID 和日志管理，停止时只处理项目记录的进程。
5. Quick Tunnel 曾成功分配临时 `trycloudflare.com` 地址，本地 FastAPI、Streamlit 和同源网关也曾通过健康检查。
6. QUIC 连接中断后，尝试将边缘传输改为 HTTP/2。
7. 为 Quick Tunnel 申请增加三次重试，并修复过将 `api.trycloudflare.com` 误识别为演示地址的正则匹配问题。
8. 分别测试 Cloudflare 控制接口、QUIC、HTTP/2、IPv6 和手动申请临时隧道凭据。

## 失败现象

- QUIC 初始能注册，但数分钟后反复出现 `timeout: no recent network activity`，公网端返回 HTTP 530。
- 改用 HTTP/2 后，`cloudflared` 请求 `https://api.trycloudflare.com/tunnel` 多次出现 `context deadline exceeded`。
- 同一时刻，`curl` 通过本机 `127.0.0.1:7890` 代理可对该接口完成 GET/POST，说明项目服务和 Cloudflare HTTPS 接口并非始终完全不可达。
- 禁用 Go HTTP/2 客户端后，连接改为直连 IPv6，出现 `network is unreachable`。
- 手动申请隧道凭据可以成功，但 `cloudflared` 与 Cloudflare 边缘的持久连接仍无法稳定建立。

## 原因结论

直接故障不在 DermaGuard、Streamlit 或 FastAPI。本地三个服务均曾成功启动并通过健康检查。

失败点是当前主机网络、本地 HTTP 代理与 `cloudflared` 连接模式之间不兼容或不稳定：

- Cloudflare QUIC/UDP 边缘通道持续超时；
- HTTP/2/TCP 边缘通道未稳定建立；
- `cloudflared` 的控制面 HTTPS 请求与当前本机代理行为不一致；
- Quick Tunnel 是临时演示服务，本身不提供可用性保证。

因此，继续修改 DermaGuard 业务代码无法解决该网络问题。

## 本次清理

已移除：

- Cloudflare 公网启动和停止脚本；
- 公网同源网关与对应测试；
- Cloudflare 和公网网关日志、PID 与临时 URL；
- README 中的公网启动说明；
- `.env.example` 和 UI 中的公网专用环境变量；
- 用户级 `cloudflared` 可执行文件。

项目恢复为纯本地启动：

```bash
bash scripts/run_mock_demo.sh
```

本地页面地址：`http://127.0.0.1:8501`。
