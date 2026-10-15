# Coaching tasks: SwimMate-only management

2026-10-15: Jira integration retired at the user's request after the external
subscription was deactivated. This does not delete an Atlassian account/site.

- Existing `coach_action_items` rows, IDs, student/coach associations, descriptions,
  status, timestamps and historical Jira keys/URLs/sync history are retained.
- There is no data migration, DELETE, TRUNCATE or DROP in this change.
- New tasks use `sync_status=local_only`; no Jira call occurs.
- Completion checks task ownership and updates only local status/updated time.
  Historical Jira-linked tasks can be completed even when Jira is unavailable.
  Already-completed tasks remain idempotent. Historical deleted tasks remain
  stored and may be marked complete by their owner.
- The dashboard no longer requests external Jira analytics. The coach page no
  longer checks connection status, displays sync errors or opens Jira shortcuts.
- `/api/jira` routes are not mounted, including the webhook. Late Jira events
  therefore cannot overwrite local task status.
- Legacy integration modules/schema fields remain for historical compatibility;
  their presence does not enable synchronization. Existing environment credentials
  are not printed, replaced or removed by this code change.

The existing recent-task list and local create/complete workflow remain. This
change does not reconstruct Jira-only data already deleted by Atlassian or add
a task editing/deletion workflow. Deployment and authenticated production data
checks must be reported separately from local regression results.
