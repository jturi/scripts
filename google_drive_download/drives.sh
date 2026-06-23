#!/usr/bin/env bash
# List local drives with free space and write speed; optionally pick one.
#
# Usage:
#   drives.sh list   Print a table of drives (default).
#   drives.sh pick   Print a numbered table (to stderr), prompt for a choice,
#                    and echo the selected mount point (to stdout).
#
# Env:
#   SPEED_MB   Size in MiB of the write-speed test file (default 256).
set -euo pipefail

SPEED_MB="${SPEED_MB:-256}"

# Measure write speed at a mount by writing/syncing a temp file, then removing it.
measure_speed() {
	local mount="$1" tmp speed
	tmp="$mount/.drive_write_test.$$"
	speed=$(dd if=/dev/zero of="$tmp" bs=1M count="$SPEED_MB" conv=fdatasync 2>&1 \
		| awk -F, '/copied|bytes/{gsub(/^ /,"",$NF); print $NF}') || true
	rm -f "$tmp" 2>/dev/null || true
	[[ -z "$speed" ]] && speed="n/a (no write access)"
	printf '%s' "$speed"
}

mode="${1:-list}"
[[ "$mode" == "pick" ]] && out=/dev/stderr || out=/dev/stdout

# Collect unique physical drives as: dev<TAB>mount<TAB>freeGB
mapfile -t drives < <(df -B1G --output=source,target,avail \
	-x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null \
	| awk '/^\/dev/ && !seen[$1]++ {print $1"\t"$2"\t"$3}')

printf '%-4s %-20s %-25s %-8s %s\n' "#" "DRIVE" "MOUNT" "FREE" "WRITE SPEED" >"$out"
i=0
mounts=()
for line in "${drives[@]}"; do
	IFS=$'\t' read -r dev mount free <<<"$line"
	i=$((i + 1))
	mounts[i]="$mount"
	speed=$(measure_speed "$mount")
	printf '\033[36m%-4s\033[0m \033[32m%-20s\033[0m %-25s %-8s \033[33m%s\033[0m\n' \
		"$i" "$dev" "$mount" "${free}G" "$speed" >"$out"
done

if [[ "$mode" == "pick" ]]; then
	(( i == 0 )) && { echo "No drives found." >&2; exit 1; }
	printf 'Select a drive [1-%s]: ' "$i" >&2
	read -r choice
	[[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= i )) \
		|| { echo "Invalid selection: $choice" >&2; exit 1; }
	printf '%s\n' "${mounts[choice]}"
fi
