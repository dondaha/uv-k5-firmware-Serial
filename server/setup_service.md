# UV-K5 Serial Server 服务配置指南

本文档介绍如何在 Linux 系统上使用 `systemd` 将 UV-K5 Serial Server 配置为后台守护进程 (Daemon)。这样配置后，程序不仅能开机自启，还能在崩溃后自动重启。

## 1. 创建 systemd 服务文件

使用管理员权限创建一个新的服务配置文件：

```bash
sudo vim /etc/systemd/system/uvk5-server.service
```

将以下内容粘贴进去：

```ini
[Unit]
Description=UV-K5 Serial Server Daemon
After=network.target

[Service]
Type=simple
User=orangepi
WorkingDirectory=/home/orangepi/uv-k5-firmware-Serial
# 增加环境变量，强制 Python 不进缓冲，实现日志实时输出
Environment=PYTHONUNBUFFERED=1
# 启动命令，使用你环境中的 miniconda python
ExecStart=/home/orangepi/miniconda3/bin/python -u /home/orangepi/uv-k5-firmware-Serial/server/main.py
# 如果程序退出或崩溃，总是自动重启
Restart=always
# 崩溃后等待 3 秒再重启
RestartSec=3

[Install]
WantedBy=multi-user.target
```

保存并退出（在 nano 中按 `Ctrl+O`，回车保存，然后 `Ctrl+X` 退出）。

## 2. 生效并启动服务

依次运行以下命令，让系统重新加载配置，并设置开机自启：

```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 设置开机自动启动
sudo systemctl enable uvk5-server.service

# 立即启动该程序
sudo systemctl start uvk5-server.service
```

## 3. 常用管理命令

你可以随时使用以下命令来监控和管理你的程序：

* **查看程序运行状态：**
  ```bash
  sudo systemctl status uvk5-server.service
  ```
* **实时查看程序输出的日志（相当于控制台输出）：**
  ```bash
  sudo journalctl -u uvk5-server.service -f
  ```
* **手动停止服务：**
  ```bash
  sudo systemctl stop uvk5-server.service
  ```
* **手动重启服务：**
  ```bash
  sudo systemctl restart uvk5-server.service
  ```
