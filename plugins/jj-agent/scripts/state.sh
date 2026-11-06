# Render recorded jj state. The caller snapshots first; every query here is read-only.
# Bash 3.2 arrays keep hooks usable without jq or another runtime.
read_jj_state() (
  cd -P "$1" || exit 1
  root=$PWD
  header='Where the jj working copy was at the latest user message or context reset. It is not refreshed after every tool call; run `jj st` or `jj log` for the current state.'
  mode=jj
  [ ! -e .git ] || mode='jj, colocated with Git'
  stage=$(mktemp -d "${TMPDIR:-/tmp}/jj-state.XXXXXX") || exit 1
  trap 'rm -rf -- "$stage"' EXIT

  state_error() {
    printf '%s\nRepository: %s.\njj failed: %s\n' "$header" "$root" "$1"
    case $1 in
      *stale*) printf '%s\n' 'The working copy is stale. Run `jj workspace update-stale` before anything else.' ;;
      *) printf '%s\n' 'Run `jj st` to see why.' ;;
    esac
  }

  if [ -n "${2:-}" ]; then state_error "$(printf '%s\n' "$2" | head -n 6)"; exit 0; fi

  sep=$'\034'
  local_names='local_bookmarks.map(|b| b.name())'
  remote_names='remote_bookmarks.filter(|b| b.remote() != "git").map(|b| stringify(b.name() ++ "@" ++ b.remote()))'
  labels="stringify(separate(\", \", $local_names.join(\", \"), $remote_names.join(\", \")))"
  names="stringify(if(local_bookmarks, $local_names.join(\"$sep\"), $remote_names.join(\"$sep\")))"
  tags='stringify(separate(", ", if(empty, "empty"), if(conflict, "conflict"), if(divergent, "divergent"), if(immutable, "immutable")))'
  describe='change_id.short(8) ++ " " ++ if(description, "\"" ++ description.first_line().replace("\t", " ") ++ "\"", "(no description)")'
  describe="$describe ++ if($labels, \" [\" ++ $labels ++ \"]\") ++ if($tags, \" (\" ++ $tags ++ \")\")"
  row='commit_id.short(12) ++ "\t" ++ if(parents.len() > 0, parents.map(|c| c.commit_id().short(12)).join(","), "-") ++ "\t" ++ change_id.short(8) ++ "\t"'
  row="$row ++ $describe ++ \"\t\" ++ if($names, $names, \"-\") ++ \"\t\" ++ if($labels, $labels, \"-\")"
  row="$row"' ++ "\t." ++ if(current_working_copy, "w") ++ if(self.contained_in("children(@)"), "c") ++ if(self.contained_in("::@"), "a") ++ if(self.contained_in("::trunk()"), "i") ++ if(self.contained_in("trunk()"), "t") ++ if(root, "r") ++ if(conflict, "f") ++ if(divergent, "d") ++ "\n"'
  if ! jj --no-pager --color=never log --ignore-working-copy --no-graph -n 120 -r 'ancestors(@, 40) | children(@)' -T "$row" > "$stage/rows" 2> "$stage/error"; then
    state_error "$(head -n 6 "$stage/error")"
    exit 0
  fi
  jj --no-pager --color=never diff --ignore-working-copy -r @ --summary > "$stage/files" 2> "$stage/diff-error" & p1=$!
  jj --no-pager --color=never log --ignore-working-copy --no-graph -n 101 -r 'trunk() | (@..trunk())' -T "$row" > "$stage/trunk" 2> "$stage/trunk-error" & p2=$!
  jj --no-pager --color=never workspace list --ignore-working-copy -T 'name ++ "\t" ++ root ++ "\t" ++ target.commit_id().short(12) ++ "\n"' > "$stage/workspaces" 2> "$stage/workspace-error" & p3=$!
  failed=0
  wait "$p1" || failed=1
  wait "$p2" || failed=1
  wait "$p3" || failed=1
  if [ "$failed" = 1 ]; then
    state_error "$(cat "$stage/diff-error" "$stage/trunk-error" "$stage/workspace-error" | head -n 6)"
    exit 0
  fi

  ids=() parents=() changes=() descriptions=() nearest=() bookmarks=() flags=() wc=
  while IFS=$'\t' read -r id ps change desc names labels bits; do
    i=${#ids[@]}
    ids[i]=$id parents[i]=$ps changes[i]=$change descriptions[i]=$desc nearest[i]=$names bookmarks[i]=$labels flags[i]=$bits
    case $bits in *w*) wc=$i ;; esac
  done < "$stage/rows"
  if [ -z "$wc" ]; then state_error 'jj did not report a working-copy commit for this workspace'; exit 0; fi
  index_of() {
    IDX=
    for ((j=0; j<${#ids[@]}; j++)); do
      if [ "${ids[j]}" = "$1" ]; then IDX=$j; return 0; fi
    done
    return 1
  }
  plural() { if [ "$1" = 1 ]; then printf '%s %s' "$1" "$2"; else printf '%s %s' "$1" "$3"; fi; }

  workspace='?' workspace_names=() matched=() workspace_targets=()
  while IFS=$'\t' read -r name location target; do
    workspace_names[${#workspace_names[@]}]=$name
    workspace_targets[${#workspace_targets[@]}]=$target
    [ "$location" != "$root" ] || workspace=$name
    [ "$target" != "${ids[wc]}" ] || matched[${#matched[@]}]=$name
  done < "$stage/workspaces"
  if [ "$workspace" = '?' ]; then
    if [ ${#matched[@]} = 1 ]; then workspace=${matched[0]};
    elif [ ${#workspace_names[@]} = 1 ]; then workspace=${workspace_names[0]}; fi
  fi
  printf '%s\nRepository: %s (%s).\nWorkspace: %s' "$header" "$root" "$mode" "$workspace"
  if [ ${#workspace_names[@]} -gt 1 ]; then
    joined=
    for name in "${workspace_names[@]}"; do joined="${joined:+$joined, }$name"; done
    printf ' (of %s)' "$joined"
  fi
  printf '\n'
  files=()
  while IFS= read -r file; do
    case $file in [A-Z]' '*) files[${#files[@]}]=$file ;; esac
  done < "$stage/files"
  count=${#files[@]}
  printf '@ (working copy): %s, ' "${descriptions[wc]}"
  if [ "$count" = 0 ]; then printf 'no file changes\n'; else plural "$count" 'file changed' 'files changed'; printf '\n'; fi
  for ((i=0; i<count && i<15; i++)); do printf '  %s\n' "${files[i]}"; done
  [ "$count" -le 15 ] || printf '  ... and %s more\n' "$((count-15))"
  IFS=, read -r -a ps <<< "${parents[wc]}"
  merge=
  for id in "${ps[@]}"; do
    index_of "$id" || continue
    printf '@- (parent): %s\n' "${descriptions[IDX]}"
    case ${parents[IDX]} in *,*) [ -n "$merge" ] || merge=$IDX ;; esac
  done
  if [ -n "$merge" ]; then
    IFS=, read -r -a ps <<< "${parents[merge]}"
    branches=
    for id in "${ps[@]}"; do
      index_of "$id" || continue
      name=${bookmarks[IDX]}
      if [ "$name" = - ]; then name=${changes[IDX]}; else name=${name%%, *}; fi
      branches="${branches:+$branches, }$name"
    done
    printf 'Mega merge: @- (%s) merges %s. Keep editing in @ and move edits into those branches; load the jj-workflow skill for how.\n' "${changes[merge]}" "$branches"
  fi

  bases=() distances=() queue=("$wc") seen=",${ids[wc]}," distance=0
  while [ ${#queue[@]} -gt 0 ] && [ ${#bases[@]} -lt 3 ]; do
    next=()
    for i in "${queue[@]}"; do
      if [ "${nearest[i]}" != - ] && [[ ${flags[i]} != *r* ]]; then
        IFS=$sep read -r -a names <<< "${nearest[i]}"
        for name in "${names[@]}"; do
          [ ${#bases[@]} -lt 3 ] || break
          bases[${#bases[@]}]=$name distances[${#distances[@]}]=$distance
        done
        continue
      fi
      IFS=, read -r -a ps <<< "${parents[i]}"
      for id in "${ps[@]}"; do
        case $seen in *",$id,"*) continue ;; esac
        index_of "$id" || continue
        seen="$seen$id," next[${#next[@]}]=$IDX
      done
    done
    queue=("${next[@]}")
    distance=$((distance+1))
  done
  if [ ${#bases[@]} = 0 ]; then
    printf 'Nearest bookmark: none among the ancestors of @ that were read\n'
  else
    printf 'Nearest bookmark: '
    for ((i=0; i<${#bases[@]}; i++)); do
      [ "$i" = 0 ] || printf ', '
      printf '%s' "${bases[i]}"
      if [ "${distances[0]}" != 0 ]; then printf ' (%s below @)' "$(plural "${distances[i]}" change changes)"; fi
    done
    [ "${distances[0]}" != 0 ] || printf ' (on @)'
    printf '\n'
  fi

  ahead=0 behind=0 capped=+ trunk= trunk_root= trunk_seen=
  for bits in "${flags[@]}"; do
    case $bits in *a*) case $bits in *i*) capped= ;; *) ahead=$((ahead+1)) ;; esac ;; esac
  done
  while IFS=$'\t' read -r id ps change desc names labels bits; do
    case $bits in *a*) ;; *) behind=$((behind+1)) ;; esac
    case $bits in *t*) trunk_seen=1; trunk=$labels; case $bits in *r*) trunk_root=1 ;; esac ;; esac
  done < "$stage/trunk"
  if [ -n "$trunk_seen" ] && [ -z "$trunk_root" ]; then
    [ "$trunk" != - ] || trunk='(unnamed)'
    behind_cap=
    if [ "$behind" -gt 100 ]; then behind=100; behind_cap=+; fi
    printf 'trunk(): %s; @ is %s%s ahead, %s%s behind\n' "$trunk" "$ahead" "$capped" "$behind" "$behind_cap"
  fi
  case ${flags[wc]} in *f*) printf '%s\n' 'Warning: @ has unresolved conflicts. Resolve them before other work (`jj resolve --list`).' ;; esac
  case ${flags[wc]} in *d*) printf '%s\n' "Warning: @ is divergent: its change ID names more than one commit. Check \`jj log -r 'change_id(<id>)'\` before editing." ;; esac
  children= child_count=0
  for ((i=0; i<${#ids[@]}; i++)); do
    case ${flags[i]} in *c*) children="${children:+$children, }${changes[i]}"; child_count=$((child_count+1)) ;; esac
  done
  if [ "$child_count" -gt 0 ]; then
    printf 'Warning: @ has %s (%s). Editing files rewrites @ and rebases them. Unless the user asked to change this change, run `jj new` first.\n' "$(plural "$child_count" child children)" "$children"
  fi
)

append_state() {
  [ "$JJ_AGENT_STATE" = 1 ] || return 0
  local root=$1 text previous= sf
  text=$(read_jj_state "$root" "${SNAPSHOT_ERROR:-}") || return 1
  state_file
  sf=$SF.state
  [ ! -f "$sf" ] || { IFS= read -r -d '' previous < "$sf" || :; }
  [ "$text" != "$previous" ] || return 0
  mkdir -p "${sf%/*}" || return 1
  printf '%s' "$text" > "$sf"
  NEW_CONTEXT="${NEW_CONTEXT:+$NEW_CONTEXT$'\n\n'}<context key=\"jj-state\">"$'\n'"$text"$'\n''</context>'
}
