#!/bin/bash
# Räumt alte Fedora-PC-Backups auf (läuft auf Unraid, da der PC nur anhängen darf).
REPO_DIR=/mnt/user/backup/Fedora-PC
REPO=$REPO_DIR/repo
LOG=$REPO_DIR/prune.log
[ -d "$REPO" ] && [ -s /boot/config/borg/fedora-pc-pass ] || exit 0
mkdir -p "$REPO_DIR/.borg-state"
{
  echo "== $(date)"
  docker run --rm --network none --entrypoint borg \
    -e BORG_PASSCOMMAND="cat /pass" -e BORG_BASE_DIR=/state \
    -v /boot/config/borg/fedora-pc-pass:/pass:ro \
    -v "$REPO_DIR/.borg-state:/state" -v "$REPO_DIR:$REPO_DIR" \
    local/borgbackup:1.4-alpine3.22 prune --list --keep-weekly 8 --keep-monthly 6 "$REPO" &&
  docker run --rm --network none --entrypoint borg \
    -e BORG_PASSCOMMAND="cat /pass" -e BORG_BASE_DIR=/state \
    -v /boot/config/borg/fedora-pc-pass:/pass:ro \
    -v "$REPO_DIR/.borg-state:/state" -v "$REPO_DIR:$REPO_DIR" \
    local/borgbackup:1.4-alpine3.22 compact "$REPO"
  echo "rc=$?"
} >>"$LOG" 2>&1
