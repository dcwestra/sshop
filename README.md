# sshop

A keyboard-driven terminal UI for [okssh](https://github.com/dcwestra/okssh) — the POSIX SSH connection manager.

sshop wraps the okssh CLI in a visual interface built with [Textual](https://github.com/Textualize/textual), giving you a live alias list, detail panel, and quick access to every okssh feature without leaving your terminal.

<img width="1911" height="994" alt="Screenshot_20260430_113724" src="https://github.com/user-attachments/assets/ca5c748e-5197-4392-8205-7933e5450d9b" />

---

## What okssh brings to the table

sshop is a front-end. The interesting parts live in [okssh](https://github.com/dcwestra/okssh) — a single POSIX shell script with no runtime dependencies beyond OpenSSH. A few highlights that are worth knowing about before you decide whether to try either tool:

**Your snippet library follows you into every SSH session.**
okssh lets you build a library of reusable shell commands (snippets). Bootstrap a remote host once and `Ctrl+X s` opens a fuzzy picker of your snippets directly in the remote shell — in both bash and zsh, without installing anything heavy on the server.

**Run a snippet across a whole group of hosts at once.**
Tag your aliases into groups (`homelab`, `prod`, `pi-cluster`). From sshop's Snippets screen, run any snippet against every host in a group in parallel and collect the output — handy for rolling restarts, config pushes, or health checks.

**Named SSH tunnels you can start and stop by name.**
Instead of remembering `ssh -L 5432:db:5432 jumphost`, define a tunnel once (`okssh tunnel add`) and start or stop it by name from the Tunnels screen. Tunnels persist across sessions and can be set to auto-start on connect.

**SSH key rotation that actually does the work.**
`k` on any alias rotates the key: generates a new key pair, copies the public key to the remote, updates `~/.ssh/config`, and optionally syncs the new key to your sync folder — all in one step.

**Your entire SSH setup syncs across machines.**
Point okssh at a shared folder (NAS, Syncthing, Dropbox) and your aliases, snippets, and preferences stay in sync across every machine you work from. Key files can optionally be included as an AES-256 encrypted archive.

---

## Requirements

- **[okssh](https://github.com/dcwestra/okssh)** installed at `/usr/local/bin/okssh`
- Python 3.11+
- Textual 0.89+

---

## Install

```sh
pip install --user git+https://github.com/dcwestra/sshop.git
sshop
```

Or clone and install in editable mode for development:

```sh
git clone https://github.com/dcwestra/sshop.git
pip install --user -e sshop/
sshop
```

---

## Screens

| Screen | Key | Description |
|--------|-----|-------------|
| Home | *(default)* | Alias list with live ping, detail panel, and all alias actions — click any column header to sort |
| SFTP | `f` | Dual-pane file browser (upload / download) |
| Add Alias | `a` | Native form — alias, host, port, user, key source, note, group, jump host |
| Import Key | `I` | Register a private key sent to you — browse or drag-and-drop the key file |
| Edit Alias | `e` | Opens okssh interactive edit wizard in the terminal |
| Tunnels | `t` | Named port-forward profiles — start / stop |
| Snippets | `s` | Reusable remote commands — run on alias or group |
| SSH Agent | `G` | Key list — add / remove / clear |
| Log | `l` | Connection history with alias filter |
| Backups | `b` | Config backup list + one-click restore |
| Templates | `m` | Saved alias templates |
| Bootstrap | `B` | Install / sync snippet widget (`Ctrl+X s`) on remote hosts |

### Home screen — alias actions (right panel)

| Key | Action |
|-----|--------|
| `↵` | Connect (keyboard) |
| double-click | Connect (mouse) |
| `P` | Connect with ephemeral profile |
| `f` | SFTP browser |
| `a` | Add new alias (native form) |
| `I` | Import a key file |
| `e` | Edit alias (okssh wizard) |
| `k` | Rotate SSH key |
| `p` | Pin / unpin |
| `n` | Rename |
| `C` | Clone |
| `g` | Add / remove group tag |
| `x` | Run one-off remote command |
| `w` | Wake-on-LAN |
| `B` | Snippet sync |
| `D` | Delete |

---

## Design

- **Tokyo Night** colour palette throughout
- All mutations go through the `okssh` CLI — sshop never writes config files directly
- The Add and Import Key screens are fully native Textual forms — no terminal handoff. The Add screen includes a `Select` to choose between generating a new key (collects key type and password for `ssh-copy-id`) or importing an existing one (file picker, supports drag-and-drop from a file manager)
- Blocking terminal ops (connect, SFTP, rotate, edit) use `app.suspend()` so the TUI cleanly hands the terminal over and reclaims it on exit
- Read-only config parsing (aliases, tunnels, snippets, history) done directly in Python for speed

---

## License

MIT — see [LICENSE](LICENSE)
