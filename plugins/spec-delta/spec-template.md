# <feature name>

> Template. Copy to `YYYY-MM-DD-<slug>-design.md` in the specs directory.

## Why

The problem in two or three sentences: what hurts today and for whom. Measurements as
numbers, not "often". Link the ticket or issue.

## Scope

What this spec does not solve, and why.

## Delta

**A list, not prose:** a diff can be subtracted from a list, never from prose. One line per
name, with its justification from the task in one sentence. All five subsections are
mandatory; if a surface does not change, say so in one line — that is a checkable claim, and
the review checks it against the diff.

Rule: an entity that does not have to be created is not created. If an existing one already
does the job, name it here instead of a new one.

The delta is shown in chat section by section while the design is discussed, and only then
copied here verbatim — by the time anyone reads this file the decisions are already made.

Implementation almost always adjusts something. The amendment goes into the delta in the same
branch and is **said out loud**: "adding X because Y". A delta extended silently is a record
kept after the fact, not a contract.

### Domain

New and changed entities, value objects and interfaces, with their fields.

- `Order.cancel_reason: CancelReason | None` — records why an order was cancelled instead of
  re-deriving it on every read (#42).

### Storage

Tables, columns, indexes, migrations; keys added to stored JSON documents.

- `orders.cancel_reason varchar NULL` + migration — stores the same field; nullable because
  live orders have none.

### Contract

Everything visible outside the service: API schema fields and endpoints, query parameters,
enum members, generated client types, message shapes, UI elements.

- `GET /api/orders?cancelled=` — the filter the requester asked for.
- a "Cancel reason" column in the orders table — **no**, nobody asked for it.

### Flow

Who calls whom and what flows between layers. ASCII, not mermaid.

```
  router ──► CancelOrder command ──► handler (transaction)
                                        │
                                        ├─► OrderRepository.get_by_id(order_id)
                                        └─► order.cancel(reason)   ← entity owns the change
                                     ──► OrderCancelled event (after commit)
```

### Rejected

What was considered and is not taken, with the reason. This section keeps a killed entity
from coming back during implementation, after the conversation's context is gone.

- `cancelled_at` — not needed: the audit event already carries the timestamp.

## Tests

Which contracts, at which layer: through the highest public entry point first, a thin
HTTP test per endpoint, unit tests only for pure logic.

## Open questions

What to ask the feature's owner before implementation.
