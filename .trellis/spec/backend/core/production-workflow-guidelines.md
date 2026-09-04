# Production Workflow Contracts

## 1. Scope / Trigger

Use this contract when changing collaborative order submission, production-task state, Kanban drag/touch actions, machine compatibility, or rule-based scheduling. These paths write several related rows and cross UI → API → Service → PostgreSQL boundaries, so the backend action is the atomic unit.

## 2. Signatures

- `POST /api/orders/from-draft` accepts `OrderDraftCreate` and creates a new formula plus order in one transaction when `formula_mode=new`.
- `POST /api/agent/chat/confirm` accepts `{session_id, order_draft?}`. For `submit_order_form`, it creates the order, consumes the pending message, closes the workspace, and persists the success message in one transaction.
- `POST /api/production-tasks/actions/move-order` accepts `{order_id, source_task_id?, target_task_id?, target_machine_id?}`.
- `POST /api/production-tasks/actions/move-task` accepts `{task_id, target_machine_id, target_index}`.
- `POST /api/production-tasks/actions/reorder` accepts `{machine_id, ordered_task_ids}`.
- `PUT /api/production-tasks/{task_id}` is status-only: `WAITING -> PRODUCING -> DONE`.

## 3. Contracts

- Order confirmation returns SSE `order_created`, closes `order_form`, then returns the persisted assistant success message. The frontend must not issue a second order-creation request.
- Kanban action endpoints commit once and return the complete authoritative `KanbanOut` snapshot.
- Manual and Agent scheduling both call `validate_machine_batch`: active machine, supported category, optional pattern capability, recognized width, width range, and identical complete production signature for merged orders.
- New tasks are `WAITING`; an order assigned to a waiting or producing task remains `OrderStatus.PRODUCING` because it has entered production planning.
- Schedule scoring is lexicographic: material/formula, category, thickness, pattern, width change, unused-width ratio, projected queued kilograms, then deterministic name/ID order.
- A schedule plan fingerprints every input order, the complete pending-order ID set, active-machine ID set, and each machine's capabilities plus unfinished queue.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Missing/invalid customer, product, quantity, unit, or formula | `409`/`400`; formula and order both roll back |
| Duplicate order confirmation | no pending row after lock; reject without a second order |
| Inactive/incompatible machine or invalid merged signature | `409`; no task/order mutation |
| Source order/task changed since UI snapshot | `409`; frontend reloads authoritative Kanban |
| Reorder list is duplicated or not the exact active queue | `400`/`409`; no positions change |
| Illegal task-state jump or another producing task exists | `409`; orders remain unchanged |
| Pending orders, active machines, capabilities, or queue changed after draft | `409`; regenerate the schedule plan |

## 5. Good / Base / Bad Cases

- Good: one `move-order` request transfers an order between tasks, validates both remaining and target batches, deletes an empty source task, normalizes positions, and commits once.
- Base: a single compatible pending order becomes a `WAITING` task and the UI replaces local state with returned `KanbanOut`.
- Bad: frontend sends remove-from-source and add-to-target requests in parallel, or creates a formula before separately creating an order.

## 6. Tests Required

- Assert atomic draft submission creates formula snapshot + order, and invalid input leaves no orphan formula.
- Assert repeated confirmation creates exactly one order and consumes exactly one pending message.
- Assert incompatible category/pattern/width/signature keeps orders pending.
- Assert status order, one-producing-task rule, exact reorder set, cross-machine validation, and rollback persistence state.
- Assert scheduler prefers width utilization and lower queued kilograms only after changeover keys tie.
- Assert new pending orders or changed machine queues make a stored plan stale.
- Run full backend tests, frontend lint/build, Docker rebuild, and browser checks for desktop drag plus mobile non-drag assignment.

## 7. Wrong vs Correct

### Wrong

```text
UI drag -> PUT source task + POST target task -> optimistic local patch
UI confirm -> SSE form_submit -> browser POST order
```

Either second request can fail after the first write, and retries can duplicate orders.

### Correct

```text
UI intent -> one action endpoint -> lock + validate + one commit -> full snapshot
UI confirm + current draft -> backend lock -> formula/order/message/workspace one commit -> success SSE
```
