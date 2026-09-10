# Linux machine management

The server can manage Linux machines (e.g. a child's gaming PC) via SSH. It polls each machine on a 60-second cycle, accumulates active graphical-session time, and enforces a daily quota by locking the screen and — after a grace period — powering the machine off.

The `/linux-machines` web page lets you add machines, view today's usage, grant bonus minutes, and trigger a lock or power-off immediately.

**Requirements per managed machine**

**OS note:** The SSH commands rely on systemd-logind and D-Bus. Tested on Bazzite (Fedora Atomic, KDE Plasma 6). Adjust if the target machine uses a different desktop environment.

**1. Generate an SSH key pair**

Use the *Generate key* button on the `/linux-machines` add/edit form. Copy the public key to the target machine:

```bash
# On the target machine (run once)
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo '<paste public key here>' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

**2. Allow passwordless poweroff via sudo**

`systemctl poweroff` requires polkit admin authentication, which is unavailable over a non-interactive SSH session. Add a narrow sudoers rule so the SSH user can power off without a password.

Run the following on the target machine (either physically or via `ssh -t`):

```bash
echo 'suriel ALL=(ALL) NOPASSWD: /usr/bin/systemctl poweroff' | sudo tee /etc/sudoers.d/familylink-poweroff
sudo chmod 440 /etc/sudoers.d/familylink-poweroff
# Verify syntax before relying on it
sudo visudo -c -f /etc/sudoers.d/familylink-poweroff
```

Replace `suriel` with the actual SSH user configured for that machine.

> A helper script at `~/familylink-setup.sh` is written to the target machine during first-time setup and performs these three commands automatically — just run `sudo bash ~/familylink-setup.sh` once from a privileged terminal.

**How enforcement works**

| Condition                                      | Action                                                       |
| ----------------------------------------------- | ------------------------------------------------------------ |
| Active graphical session (seat-based) detected | Accumulate seconds toward the daily quota                    |
| Quota exceeded, not yet locked                 | Lock screen via D-Bus (`org.freedesktop.ScreenSaver.Lock`) |
| Locked, grace period elapsed                   | Power off via`sudo systemctl poweroff`                     |
| Bonus minutes granted while locked             | Kill`kscreenlocker_greet` to dismiss the lock screen       |

The daily quota and grace period (default 5 min) are configurable per machine.
