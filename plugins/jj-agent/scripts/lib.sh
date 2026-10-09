# Shared helpers for jj-agent hooks. Sourced, not executed. bash 3.2 compatible (macOS /bin/bash).
# Hooks run on every tool call, so the common paths use bash builtins only: no jq, no dirname,
# no command substitution. Functions return values in variables named by the caller or in
# globals (JJ_ROOT, SF, BF, CTX, REPORT) instead of printing them.

# HOOK_INPUT <- the hook's stdin JSON.
read_input() { IFS= read -r -d '' HOOK_INPUT || :; }

# json_get KEY VAR: VAR <- first string value of "KEY" in the input. Top-level fields come first
# in both Claude Code and Codex hook input. Unescapes \" \\ \/ \n \t.
json_get() {
  local _re="\"$1\"[[:space:]]*:[[:space:]]*\"(([^\"\\\\]|\\\\.)*)\"" _v=
  if [[ $HOOK_INPUT =~ $_re ]]; then
    _v=${BASH_REMATCH[1]}
    case $_v in *\\*)
      _v=${_v//\\\\/$'\001'}; _v=${_v//\\\"/\"}; _v=${_v//\\\//\/}; _v=${_v//\\n/$'\n'}; _v=${_v//\\t/$'\t'}
      _v=${_v//$'\001'/\\} ;;
    esac
  fi
  printf -v "$2" '%s' "$_v"
}

# json_str VAR TEXT: VAR <- TEXT escaped for a JSON string.
json_str() {
  local _s=$2
  _s=${_s//\\/\\\\}; _s=${_s//\"/\\\"}; _s=${_s//$'\n'/\\n}; _s=${_s//$'\t'/\\t}; _s=${_s//$'\r'/}
  printf -v "$1" '%s' "$_s"
}

# JJ_ROOT <- the jj workspace root containing directory $1 (walks up looking for .jj; no jj
# process). Fails if there is none.
find_jj_root() {
  local d=$1
  JJ_ROOT=
  [ -n "$d" ] || return 1
  case $d in /*) ;; *) d=$PWD/$d ;; esac
  # Walking up by string only works on normalized paths; harnesses pass absolute ones.
  case $d in */../*|*/..|*/./*|*/.) d=$(cd "$d" 2>/dev/null && pwd -P) || return 1 ;; esac
  d=${d%/}
  while :; do
    if [ -d "$d/.jj" ]; then JJ_ROOT=${d:-/}; return 0; fi
    [ -n "$d" ] || return 1
    d=${d%/*}
  done
}

# Per-session record of which jj roots the agent has already been told about.
state_file() {
  local id=${SESSION_ID:-default}
  SF=${CLAUDE_PLUGIN_DATA:-${TMPDIR:-/tmp}/jj-agent}/sessions/${id//[^A-Za-z0-9_-]/_}
}
announced() {
  local l
  [ -f "$SF" ] || return 1
  while IFS= read -r l; do [ "$l" = "$1" ] && return 0; done < "$SF"
  return 1
}
mark_announced() {
  [ -d "${SF%/*}" ] || mkdir -p "${SF%/*}" 2>/dev/null
  printf '%s\n' "$1" >> "$SF"
}

# CTX <- the notice for jj root $1.
context_for() {
  local root=$1 mode=jj ver
  [ -d "$root/.git" ] && mode=jj-colocated
  ver=$(jj --version 2>/dev/null); ver=${ver#jj }; ver=${ver%%-*}; ver=${ver%% *}
  printf -v CTX 'vcs=%s at %s (jj %s). This directory is a Jujutsu repository: use the jj skill for every version-control action in it. Do not run git commands that change state there: they are blocked where possible, and any git change is reported with a recovery point. Read-only git still works, but prefer jj.' \
    "$mode" "$root" "${ver:-not found on PATH}"
}

# For each directory argument: find its jj root, and collect a notice for roots not yet announced.
# Sets JJ_ROOTS (array, unique) and NEW_CONTEXT.
scan_dirs() {
  local d r seen
  NEW_CONTEXT='' JJ_ROOTS=()
  state_file
  for d in "$@"; do
    find_jj_root "$d" || continue
    r=$JJ_ROOT
    for seen in "${JJ_ROOTS[@]}"; do [ "$seen" = "$r" ] && continue 2; done
    JJ_ROOTS[${#JJ_ROOTS[@]}]=$r
    if ! announced "$r"; then
      mark_announced "$r"
      context_for "$r"
      NEW_CONTEXT="${NEW_CONTEXT:+$NEW_CONTEXT }$CTX"
    fi
  done
}

# Emit additionalContext for hook event $1 with text $2.
emit_context() {
  local _esc
  json_str _esc "$2"
  printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' "$1" "$_esc"
}

# --- Detecting git changes around a Bash command (pre-tool.sh records, post-tool.sh checks) ---

# BF <- baseline file for one tool call, keyed by tool_use_id so parallel calls don't collide.
baseline_path() {
  local id=${1:-${SESSION_ID:-default}}
  BF=${CLAUDE_PLUGIN_DATA:-${TMPDIR:-/tmp}/jj-agent}/baselines/${id//[^A-Za-z0-9_-]/_}
}

# Copy the git index of repo $1 to $2 (copy-on-write where the filesystem supports it).
save_index() {
  [ -f "$1/.git/index" ] || return 1
  case $OSTYPE in
    darwin*) cp -c "$1/.git/index" "$2" 2>/dev/null && return 0 ;;
    linux*) cp --reflink=auto "$1/.git/index" "$2" 2>/dev/null && return 0 ;;
  esac
  cp "$1/.git/index" "$2" 2>/dev/null
}

# "path<TAB>stat" for entries of index file $2 (absolute) in repo $1, limited to paths $3...
index_stats() {
  local root=$1 idx=$2; shift 2
  GIT_INDEX_FILE=$idx git --literal-pathspecs -C "$root" -c core.quotePath=false ls-files --debug -- "$@" 2>/dev/null |
    awk '/^[^ ]/ { if (p != "") print p "\t" s; p = $0; s = ""; next }
         { gsub(/\t/, " "); s = s $0 }
         END { if (p != "") print p "\t" s }'
}

# Of paths $4..., the ones whose index stat git filled in between index copies $2 (before the
# command) and $3 (after it, taken before any jj command ran). jj writes index entries with a
# zeroed stat; git fills it only for entries whose file matches the index: when it refreshes
# (status, describe) and when it rewrites the file (checkout --, restore, stash, reset).
git_filled_paths() {
  local root=$1 pre=$2 post=$3; shift 3
  awk -F'\t' 'NR == FNR { pre[$1] = $2; next } $2 !~ /mtime: 0:0/ && pre[$1] != $2 { print $1 }' \
    <(index_stats "$root" "$pre" "$@") <(index_stats "$root" "$post" "$@")
}

# Snapshot repo $1 and set REPORT if git changed it since baseline op $2. $3 and $4 are copies of
# the git index from before and after the command; $4 exists only if the index changed.
git_report() {
  local root=$1 op=$2 pre_idx=$3 post_idx=$4 ops newer='' why='' changed filled p files='' n=0 ignore='' short
  local paths=()
  REPORT=
  # `jj op log` snapshots the working copy first, so this is also the post-command snapshot.
  ops=$(jj -R "$root" op log --no-graph -n 50 -T 'id ++ "\t" ++ description.first_line() ++ "\n"' 2>/dev/null)
  case $ops in *"$op"*) newer=${ops%%"$op"*} ;; esac
  case $newer in *$'\t'"import git "*) why='git moved HEAD or refs' ;; esac
  if [ -f "$post_idx" ] && [ -f "$pre_idx" ]; then
    # Files whose content changed during the command, and of those, the ones whose index entry
    # git filled in: git wrote them. A refresh alone leaves content unchanged; an edit by anything
    # else leaves the stat unfilled. Only these paths are looked up in the index copies.
    changed=$(cd "$root" && jj diff --ignore-working-copy --from "at_operation($op, @)" --to @ --name-only 2>/dev/null)
    while IFS= read -r p; do [ -n "$p" ] && paths[${#paths[@]}]=$p; done <<__CHANGED__
$changed
__CHANGED__
    if [ ${#paths[@]} -gt 0 ]; then
      [ ${#paths[@]} -gt 500 ] && paths=()   # too many for argv: compare the whole index
      filled=$(git_filled_paths "$root" "$pre_idx" "$post_idx" "${paths[@]}")
      while IFS= read -r p; do
        [ -n "$p" ] || continue
        case $'\n'"$changed"$'\n' in *$'\n'"$p"$'\n'*)
          files="${files:+$files }$p"; n=$((n + 1)); [ $n -ge 20 ] && break ;;
        esac
      done <<__FILLED__
$filled
__FILLED__
    fi
    if [ -n "$files" ]; then
      why="${why:+$why; }git rewrote these files: $files"
      ignore=' If you put those files back yourself (e.g. with jj restore), ignore this.'
    fi
  fi
  [ -n "$why" ] || return 0
  short=${op:0:12}
  printf -v REPORT 'jj-agent: during the last command in %s, %s. The repo state from just before it is jj operation %s.%s Check with `jj op log -n 5` and `jj op show <op-id>`, then restore files with `jj restore --from '"'"'at_operation(%s, @)'"'"' <paths>`, or the whole repo with `jj op restore %s` (this also undoes everything else the command did). Use jj instead of git in this repo (jj skill).' \
    "$root" "$why" "$short" "$ignore" "$short" "$short"
}
