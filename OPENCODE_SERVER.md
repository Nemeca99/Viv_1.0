# OpenCode local server

This is the manual, visible entry point for using the LocalCoder OpenCode agent through its authenticated local server. It runs in the foreground and is bound to loopback (`127.0.0.1`); closing the server window stops it. No Windows scheduled task or background service is configured.

## Start

1. Load the configured model in LM Studio. The server launcher checks the configured model's loaded state and exits if it is not loaded; it does not load or unload models.
2. In a visible PowerShell window, run:

   ```powershell
   Set-Location L:\LocalCoder
   .\Run-OpenCodeServer.ps1
   ```

3. Leave this window open. It shows the server's activity and remains the server process.

The first start creates a random server password protected with Windows DPAPI for the current Windows user at `%LOCALAPPDATA%\LocalCoder\opencode-server-password.dpapi`. The password is not written to the project or printed by the launchers. The server uses `http://127.0.0.1:4096`.

## Connect

Open another visible PowerShell window and run:

```powershell
Set-Location L:\LocalCoder
.\Connect-OpenCode.cmd
```

OpenCode CLI arguments can be passed after the launcher, for example .\Connect-OpenCode.cmd run "Summarize the project status"`.

## Stop and check

Exit the client with its normal quit command. To stop the server, press `Ctrl+C` in the server window. The launcher removes its process-local password and LM Studio endpoint environment variables when the server exits.

Check the listener from PowerShell:

```powershell
Get-NetTCPConnection -LocalPort 4096 -State Listen -ErrorAction SilentlyContinue
```

An empty result means no process is listening on the server port. The server is intentionally not started automatically; unattended startup needs a separate, explicit operating decision and a visible operator path.

## Bounded verification

The authenticated one-shot status probe is:

```powershell
Set-Location L:\LocalCoder
.\.opencode\evals\run_server_status_probe.ps1
```

It calls the read-only `localcoder_status` tool and records its transcript under `.opencode\evals`. A successful probe verifies client authentication, server routing, the configured project root, and memory file visibility for that run; it does not establish unattended uptime.
