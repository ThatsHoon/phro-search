#!/bin/sh
# PreToolUse hook for Agent, WebSearch and WebFetch: runs plan_line.py only in a session where the search skill ran, so
# other sessions start no Python. Any failure here lets the call through; plan_line.py says why.

input=$(cat)
path=$(printf '%s\n' "$input" | sed -n -E 's/.*"transcript_path"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)".*/\1/p' |
	sed -e 's/\\\\/\//g' -e 's/\\\//\//g')
grep -q "phro-search:search" "$path" 2>/dev/null || exit 0

case $0 in
*/* | *\\*) dir=${0%[/\\]*} ;;
*) dir=. ;;
esac
for py in "py -3" python3 python; do
	command -v "${py%% *}" >/dev/null 2>&1 || continue
	printf '%s' "$input" | $py -I -X utf8 "$dir/plan_line.py"
	rc=$?
	if [ "$rc" = 0 ] || [ "$rc" = 2 ]; then
		exit "$rc"
	fi
done
exit 0
