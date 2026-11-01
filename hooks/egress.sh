#!/bin/sh
# PreToolUse hook for WebSearch and WebFetch: runs egress.py only where a term list exists.
# A list is ~/.claude/phro-search/forbidden.txt under HOME or USERPROFILE, or a .phro/project.json in the working
# folder or above it (the shell's and the event's cwd, also with links resolved). No list: exit 0 at once, without
# starting Python. A list: py -3, python3 and python are tried in turn, and the first that exits 0 (allow) or 2
# (block) decides; when none does, exit 2 with a repair hint, so a missing Python never lets a call through.
# POSIX sh with cat and sed only, so it runs the same in Git Bash on Windows.

input=$(cat)

listed() {  # true when a .phro/project.json sits in folder $1 or above it
	d=$1
	while [ -n "$d" ]; do
		[ -f "$d/.phro/project.json" ] && return 0
		case $d in
		*/*) d=${d%/*} ;;
		*) d= ;;
		esac
	done
	[ -f /.phro/project.json ]
}

found=
for h in "$HOME" "$USERPROFILE"; do
	[ -n "$h" ] && [ -f "$h/.claude/phro-search/forbidden.txt" ] && found=1
done
if [ -z "$found" ]; then
	# the event's cwd, JSON-unescaped enough for a path: \\ and \/ become /
	cwds=$(printf '%s\n' "$input" | sed -n -E 's/.*"cwd"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)".*/\1/p' |
		sed -e 's/\\\\/\//g' -e 's/\\\//\//g')
	while IFS= read -r c; do
		[ -n "$c" ] || continue
		listed "$c" && found=1
		r=$(cd "$c" 2>/dev/null && pwd -P) && listed "$r" && found=1
	done <<END
$cwds
END
	listed "$PWD" && found=1
	listed "$(pwd -P)" && found=1
fi
[ -n "$found" ] || exit 0

case $0 in
*/* | *\\*) dir=${0%[/\\]*} ;;
*) dir=. ;;
esac
for py in "py -3" python3 python; do
	command -v "${py%% *}" >/dev/null 2>&1 || continue
	printf '%s' "$input" | $py -I -X utf8 "$dir/egress.py"
	rc=$?
	if [ "$rc" = 0 ] || [ "$rc" = 2 ]; then
		exit "$rc"
	fi
done
echo "phro-search egress: a term list exists, but no Python 3 ran this guard (tried py -3, python3, python), so web searches and fetches are blocked. Tell the user to install Python 3 or put it on PATH." >&2
exit 2
