# Environment options work with plugin caches and APM without another configuration parser.
# Detection needs turn/tool snapshots to retain the baseline and recovery points.
JJ_AGENT_PREAMBLE=${JJ_AGENT_PREAMBLE:-1}
JJ_AGENT_STATE=${JJ_AGENT_STATE:-1}
JJ_AGENT_SNAPSHOTS=${JJ_AGENT_SNAPSHOTS:-0}
JJ_AGENT_GUARD=${JJ_AGENT_GUARD:-0}
JJ_AGENT_DETECT=${JJ_AGENT_DETECT:-0}
JJ_AGENT_ADOPT_WORKTREES=${JJ_AGENT_ADOPT_WORKTREES:-0}
[ -z "${MUSE_PLUGIN_ID:-}" ] || JJ_AGENT_STATE=0
if [ "$JJ_AGENT_DETECT" = 1 ]; then JJ_AGENT_SNAPSHOTS=1; fi
