# Attachment lifecycle bug analysis

## 1. Symptom

- A sent image remains in the composer until the Agent finishes its full response.
- A full refresh loses the sent thumbnail and falls back to a placeholder.
- Recognition errors blur whether the user message was accepted and whether the image should be retried.

## 2. Root cause category

This is a cross-layer lifecycle and source-of-truth bug. The frontend treated one `File` as both composer selection and sent-message media, while the backend persisted only a text placeholder. The only real preview lived in a module-level array, and the only server ID arrived on a terminal Agent event.

## 3. Why the earlier fixes failed

Earlier changes improved preview rendering, remount retention, and the lightbox without changing the persistence contract. They optimized an intentionally ephemeral cache. The acceptance criteria also explicitly allowed a refresh placeholder, so local fixes could pass the written checks while still violating the expected messaging experience.

## 4. Prevention mechanism

- Define a message-commit event separately from Agent completion.
- Give composer, optimistic message, and persisted message distinct attachment ownership.
- Store attachment metadata in PostgreSQL and binary data in protected persistent storage.
- Make history replay and live SSE converge on the same typed attachment contract.
- Test the complete state matrix: success, refresh, pre-commit failure, post-commit Agent failure, unauthorized read, and session deletion.

## 5. Durable lesson

An attachment is part of the user message, not part of the Agent reply. UI cleanup must follow message acceptance, while Agent progress is a separate asynchronous state. Any feature that claims history must have a server-side source of truth; remount caches are presentation optimizations only.
