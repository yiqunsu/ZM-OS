# Chat Attachment Contract

## 1. Scope / Trigger

Use this contract whenever chat image upload, SSE turn events, message history, attachment download, session deletion, storage configuration, or deployment backup changes. An attachment belongs to the user message; Agent recognition and reply completion are later states and must not control composer cleanup.

## 2. Signatures

- Request: `POST /api/agent/chat` with `content`, `session_id`, optional `image_data_url`.
- Commit event: `user_message_committed` is emitted immediately after the user message and optional attachment metadata commit.
- History: `GET /api/agent/chat?session_id=...` returns each message with `attachments`.
- Media: `GET /api/agent/attachments/{attachment_id}` returns an owned JPG/PNG or safe `404`.
- Database: one `ChatMessage` has zero or one `ChatAttachment`; `message_id` is unique and uses `ON DELETE CASCADE`.

## 3. Contracts

Public attachment metadata is exactly:

```json
{"id":"opaque-id","mime_type":"image/jpeg","byte_size":1234}
```

The SSE commit payload is:

```json
{
  "type":"user_message_committed",
  "user_message_id":"message-id",
  "attachments":[{"id":"opaque-id","mime_type":"image/jpeg","byte_size":1234}]
}
```

Do not expose `storage_key`, filesystem paths, original filenames, or image data in history/SSE. `CHAT_ATTACHMENT_DIR` selects the private filesystem root; containers set it to `/app/data/chat-attachments` and mount a persistent volume. PostgreSQL stores metadata only.

The frontend renders persisted media through `/media/chat-attachments/{id}`. That Next.js Route Handler attaches the server-side backend token; FastAPI still authorizes by joining attachment → message → session → current user.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Unsupported MIME, invalid Base64/signature, empty or oversized image | SSE `error` without `user_message_id`; no message/file persists |
| File write fails | Safe pre-commit error; no message metadata persists |
| File write succeeds but database commit fails | Roll back and delete the written file |
| Message commits but vision/Agent work fails | Commit event precedes SSE `error`; message and attachment remain |
| Attachment missing, unknown, or owned by another user | `404` without path or ownership disclosure |
| Session deletion commits | Delete collected attachment files; log cleanup failure without restoring deleted DB state |
| MIME or byte size outside database constraints | Reject at database boundary (`image/jpeg` or `image/png`, `byte_size > 0`) |

## 5. Good / Base / Bad Cases

- Good: valid image moves from composer to optimistic message, receives commit metadata, survives refresh, and opens through authenticated media proxy.
- Base: text-only messages emit the same commit event with `attachments: []`, so every new turn uses one acceptance contract.
- Bad: keeping a data URL in a module global or waiting for `text_done` before clearing the composer. Both couple message ownership to page memory or Agent latency.

## 6. Tests Required

- Persistence/history: assert attachment metadata round-trips and `storage_key` never appears.
- Authorization: another user receives `404`; missing file also receives safe `404`.
- Compensation: database failure removes the file; file-write failure creates no message.
- Deletion: session, messages, metadata, and file are removed.
- Runner: commit event is first for successful user acceptance; invalid image has no commit ID; post-commit vision error keeps the ID/attachment.
- Frontend build/type guard: persisted metadata accepts only supported MIME and positive integer size.
- Browser smoke: assert composer attachment count becomes zero immediately, sent preview becomes one, full refresh keeps it, and lightbox loads `/media/chat-attachments/{id}`.
- Deployment: empty-database migration, `alembic check`, Compose config, database backup smoke test, and attachment tar validation.

## 7. Wrong vs Correct

### Wrong

```typescript
const result = await consumeAgentUntilDone()
if (result.succeeded) clearComposerImage()
```

This leaves the composer dirty for the entire Agent response and incorrectly restores an already accepted message after recognition failure.

### Correct

```typescript
detachComposerImageIntoOptimisticMessage()
const result = await consumeStream()
if (!result.userMessageCommitted) restoreComposer()
```

The backend must emit `user_message_committed` immediately after persistence; later Agent success or failure changes only the assistant/result state.
