#!/usr/bin/env bash
# Reclaim disposable inputs on the hosted runner after Abaqus installation.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" || "${RUNNER_ENVIRONMENT:-}" != "github-hosted" || "${RUNNER_OS:-}" != "Linux" ]]; then
  echo "Storage cleanup is restricted to GitHub-hosted Linux runners." >&2
  exit 1
fi

runner_temp="$(realpath -e "${RUNNER_TEMP:?}")"
case "$runner_temp" in
  /home/runner/*) ;;
  *) echo "Unexpected hosted runner temporary directory." >&2; exit 1 ;;
esac

echo "Storage before cleanup:"
df -h "$runner_temp"

# The installed solver lives in the honeycomb-install Docker volume. The ISO
# is no longer needed once install_runtime.sh has returned successfully.
mount_dir="$runner_temp/abaqus-mount"
media="$runner_temp/abaqus-media-inspection/iso/DS.SIMULIA.Suite.2020.Linux64_Softgozar.com.iso"
if mountpoint -q "$mount_dir"; then
  sudo umount -- "$mount_dir"
fi
if [[ -f "$media" && ! -L "$media" ]]; then
  rm -- "$media"
fi

# Abaqus does not use the image's preinstalled Android SDK. Remove only this
# fixed directory on the ephemeral hosted runner; preserve runtime and outputs.
if [[ -d /usr/local/lib/android && ! -L /usr/local/lib/android ]]; then
  sudo du -sh /usr/local/lib/android
  sudo rm -rf --one-file-system -- /usr/local/lib/android
fi

echo "Storage after cleanup (normal admission and reserve checks still apply):"
df -h "$runner_temp"
