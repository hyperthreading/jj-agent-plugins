# Shared helpers for jj-agent hooks. Sourced, not executed. bash 3.2 compatible (macOS /bin/bash).
# Expects HOOK_INPUT to hold the hook's stdin JSON.

# First value of a string field anywhere in the input (top-level fields come first).
json_get() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$HOOK_INPUT" | jq -r --arg k "$1" 'first(.. | objects | select(has($k)) | .[$k] | strings) // empty' 2>/dev/null
  else
    printf '%s' "$HOOK_INPUT" | grep -o "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -n 1 |
      sed -e 's/^[^:]*:[[:space:]]*"//' -e 's/"$//'
  fi
}

json_str() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk 'BEGIN{ORS="\\n"} {print}' | sed 's/\\n$//'; }

# Print the jj workspace root containing $1 (walks up looking for .jj; no jj process). Fails if none.
find_jj_root() {
  local d
  [ -n "$1" ] || return 1
  d=$(cd "$1" 2>/dev/null && pwd -P) || return 1
  while :; do
    if [ -d "$d/.jj" ]; then printf '%s\n' "$d"; return 0; fi
    [ "$d" = "/" ] && return 1
    d=$(dirname "$d")
  done
}

# Per-session record of which jj roots Claude has already been told about.
state_file() {
  local dir="${CLAUDE_PLUGIN_DATA:-${TMPDIR:-/tmp}/jj-agent}/sessions"
  mkdir -p "$dir" 2>/dev/null
  printf '%s/%s' "$dir" "$(printf '%s' "${SESSION_ID:-default}" | tr -c 'A-Za-z0-9_-' '_')"
}
announced() { grep -qxF "$1" "$(state_file)" 2>/dev/null; }
mark_announced() { printf '%s\n' "$1" >> "$(state_file)"; }

context_for() {
  local root=$1 mode=jj ver
  [ -d "$root/.git" ] && mode=jj-colocated
  ver=$(jj --version 2>/dev/null | awk '{print $2}' | cut -d- -f1)
  printf 'vcs=%s at %s (jj %s). This directory is a Jujutsu repository: use the jj skill for every version-control action in it. Do not run git commands that change state there: they are blocked where possible, and any git change is reported with a recovery point. Read-only git still works, but prefer jj.' \
    "$mode" "$root" "${ver:-not found on PATH}"
}

# --- Detecting git changes around a Bash command (pre-tool.sh records, post-tool.sh checks) ---

# Baseline file for one tool call, keyed by tool_use_id so parallel calls don't collide.
baseline_file() {
  printf '%s/baselines/%s' "${CLAUDE_PLUGIN_DATA:-${TMPDIR:-/tmp}/jj-agent}" \
    "$(printf '%s' "${1:-${SESSION_ID:-default}}" | tr -c 'A-Za-z0-9_-' '_')"
}

# Content hash of the colocated git index (empty if none), to skip the per-path check when unchanged.
index_hash() { [ -f "$1/.git/index" ] && cksum < "$1/.git/index" | awk '{print $1 "-" $2}'; }

# Copy the git index of repo $1 to $2 (copy-on-write where the filesystem supports it).
save_index() {
  [ -f "$1/.git/index" ] || return 1
  cp -c "$1/.git/index" "$2" 2>/dev/null || cp --reflink=auto "$1/.git/index" "$2" 2>/dev/null ||
    cp "$1/.git/index" "$2" 2>/dev/null
}

# "path<TAB>stat" for each entry of index file $2 (absolute) in repo $1.
index_stats() {
  GIT_INDEX_FILE=$2 git -C "$1" -c core.quotePath=false ls-files --debug 2>/dev/null |
    awk '/^[^ ]/ { if (p != "") print p "\t" s; p = $0; s = ""; next }
         { gsub(/\t/, " "); s = s $0 }
         END { if (p != "") print p "\t" s }'
}

# Paths whose stat git filled in since index copy $2 was taken. jj writes index entries with a
# zeroed stat; git fills it only for entries whose file matches the index: when it refreshes
# (status, describe) and when it rewrites the file (checkout --, restore, stash, reset).
# Read the current index before any jj command runs: importing a moved HEAD rewrites it.
git_filled_paths() {
  awk -F'\t' 'NR == FNR { pre[$1] = $2; next } $2 !~ /mtime: 0:0/ && pre[$1] != $2 { print $1 }' \
    <(index_stats "$1" "$2") <(index_stats "$1" "$1/.git/index")
}

current_op() { (cd "$1" && jj op log --ignore-working-copy --no-graph -n 1 -T 'id' 2>/dev/null); }

# First-line descriptions of the operations after op $2 in repo $1, newest first.
# Prints nothing if $2 is not among the last 50 operations.
ops_since() {
  (cd "$1" && jj op log --ignore-working-copy --no-graph -n 50 \
    -T 'id ++ "\t" ++ description.first_line() ++ "\n"' 2>/dev/null) |
    awk -F'\t' -v b="$2" '$1 == b { for (i = 1; i <= n; i++) print a[i]; exit } { a[++n] = $2 }'
}

# Print a report if git changed repo $1 since baseline op $2. $3 lists the paths whose index stat
# git filled in (git_filled_paths). Call after snapshotting.
git_report() {
  local root=$1 op=$2 filled=$3 why='' files ignore='' short
  [ -n "$op" ] || return 0
  ops_since "$root" "$op" | grep -q '^import git ' && why='git moved HEAD or refs'
  if [ -n "$filled" ]; then
    # Of the paths git filled in, the ones whose content changed during the command: git wrote
    # them. A refresh alone leaves content unchanged; an edit leaves the stat unfilled.
    files=$( (cd "$root" && jj diff --ignore-working-copy --from "at_operation($op, @)" --to @ --name-only 2>/dev/null) |
      grep -Fx -f <(printf '%s\n' "$filled") | head -n 20 | tr '\n' ' ' | sed 's/ $//')
    if [ -n "$files" ]; then
      why="${why:+$why; }git rewrote these files: $files"
      ignore=' If you put those files back yourself (e.g. with jj restore), ignore this.'
    fi
  fi
  [ -n "$why" ] || return 0
  short=$(printf '%s' "$op" | cut -c1-12)
  printf 'jj-agent: during the last command in %s, %s. The repo state from just before it is jj operation %s.%s Check with `jj op log -n 5` and `jj op show <op-id>`, then restore files with `jj restore --from '"'"'at_operation(%s, @)'"'"' <paths>`, or the whole repo with `jj op restore %s` (this also undoes everything else the command did). Use jj instead of git in this repo (jj skill).' \
    "$root" "$why" "$short" "$ignore" "$short" "$short"
}

# Emit additionalContext for hook event $1 with text $2.
emit_context() {
  printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' "$1" "$(json_str "$2")"
}

# For each directory argument: find its jj root, and collect a context message for roots not yet announced.
# Sets NEW_CONTEXT and JJ_ROOTS (newline-separated, unique).
scan_dirs() {
  local d r
  NEW_CONTEXT='' JJ_ROOTS=''
  for d in "$@"; do
    r=$(find_jj_root "$d") || continue
    case "
$JJ_ROOTS
" in *"
$r
"*) continue ;; esac
    JJ_ROOTS="${JJ_ROOTS:+$JJ_ROOTS
}$r"
    if ! announced "$r"; then
      mark_announced "$r"
      NEW_CONTEXT="${NEW_CONTEXT:+$NEW_CONTEXT }$(context_for "$r")"
    fi
  done
}
