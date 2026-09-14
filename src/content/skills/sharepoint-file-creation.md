---
name: SharePoint File Creation
description: "Generate a requested file, enforce a safe pre-upload size gate, upload it to SharePoint without streaming bytes through the model, and verify the result."
agentDescription: "Source/generate the requested file using whatever content rules apply to the use case, gate it against an evidence-based pre-upload size threshold using the filesystem API, and upload it to SharePoint via the Create file tool's confirmed /app/created/ path-reference mechanism — without ever streaming raw file bytes through the LLM. Use this skill whenever a request asks for a file to be produced and uploaded to SharePoint, whether or not the user specifies a path, filename, format, or content source."
platforms: [Copilot Studio]
tags: [sharepoint, files, upload, microsoft-365, verification]
author: Lewis Baybutt
authorUrl: "https://github.com/lewisdoesdev"
authorGithub: lewisdoesdev
version: 1.0.0
createdAt: 2026-09-14
updatedAt: 2026-09-14
---
## Quick reference — the fixed sequence

1. Determine what content/format is being asked for and source it (Section 0).
2. Write the complete file under `/app/created/` only, with a descriptive unique name.
3. Re-measure the final file's size with the filesystem API. Gate: proceed only if
   `0 < size_bytes < 4,000,000`. Above that, stop and offer options — do not upload.
4. Call Create file with the `/app/created/<name>` path bound directly as the content input.
   Never read bytes into the model to populate it. Never target a path outside
   `/app/created/`.
5. Verify: metadata size match at minimum; prefer a byte-level SHA-256 comparison via a
   saved download when a content-read tool is available.
6. Report: content source, destination, size, upload result, verification level achieved.

Treat steps 2–6 as fixed; only step 1 is meant to flex per use case.

## 0. Determine and source the content

Apply any configured content-generation rules first, including required templates,
knowledge sources, data sources, report structures, schemas, or style guides.

When no more specific rules are configured:
- Identify the target file type/format from the request (e.g. docx, xlsx, pdf, html, csv,
  md, txt) and use the runtime library appropriate to that format. Do not default to plain
  text unless that is genuinely what's being asked for.
- Identify what the content should be based on: something explicitly referenced in the
  request (a named document, dataset, or process), something available via whatever
  retrieval/search/knowledge tools are already configured, or prior conversation context.
  Use whichever of those is actually available in the current setup.
- If the request names a source that can't be located, or no source can be identified at
  all, say so and ask, rather than fabricating plausible-looking but ungrounded content.

Whatever the source, the output of this step is the same for every use case: a complete,
correct file, ready to be written in Section 1.

## 1. Generate the file in /app/created/ only

Write the complete file beneath `/app/created/` using a SharePoint-safe, sanitized basename-only, collision-resistant filename (retain `[A-Za-z0-9_-]` in the stem, replace other runs with `_`, trim separators, and preserve one valid extension). Before writing, reject path separators, `..`, and control characters, resolve the candidate path, and verify it remains under `/app/created/`; use only that validated absolute path for writing and upload.

**This location is not a convention of convenience — it is the only path the Create file
tool's reference resolution is confirmed to support.** A path under any other directory
(e.g. `/app/workspace/`) is not resolved: the tool instead uploads the *literal text of the
path string itself* as file content, with no error. That is a silent-corruption failure
mode, not a clean failure, so treat "write outside /app/created/" as forbidden for anything
you intend to upload.

Keep bytes inside the runtime: never print, preview, or return generated content through the
model. Track the absolute path, filename, and byte count internally — these are needed to
bind the upload and run verification — but treat the raw sandbox path (e.g. `/app/created/...`)
as an internal implementation detail, not user-facing information (see Section 5).

## 2. Measure and gate the size — always on the final written file

After the file is fully written (and closed), re-measure it with the runtime filesystem API
(`os.path.getsize` / `os.stat().st_size` or equivalent) — never estimate from text length,
row counts, or token counts, and never trust a size computed before the last write.

Gate at **4,000,000 bytes** by default before attempting any upload call. This number is not
arbitrary: prior testing (two sessions, two independent connectors — SharePoint `create_file`
and Azure `CreateblobV2`) found:
- **4,146,095 bytes** — largest size **confirmed to succeed**.
- **4,194,304 bytes exactly (4 × 1024 × 1024 = 4 MiB)** — the point at which the tool starts
  rejecting uploads with `"file too large for inline connector upload (> 4194304 bytes);
  streamed connector upload is not supported"`.
- **4,217,157 bytes** — smallest size **confirmed to fail**, with identical error text on both
  connectors, plus an identical non-native `"verified": false` field in both — evidence this is
  a shared pre-flight guard in the tool/harness layer, not a native SharePoint/Blob backend
  limit (both backends natively support much larger files via resumable/chunked APIs the
  agent's tools do not currently expose).
- Nothing in the 4,146,096–4,194,303-byte range has actually been tested; do not assume it
  is safe just because it is below 4,194,304.

Treat this threshold as an **empirical, environment-specific observation**, not a documented
platform guarantee. If an upload unexpectedly fails below the gate, report the measured size
and exact error. If the requested file cannot be regenerated below the gate without
compromising the user's requirements, tell the user to report the limitation to the agent
owner.

If size is 0, unreadable, or ≥ 4,000,000 bytes: do not call Create file. Report the measured
size plus the gate. Offer concrete options rather than a dead stop — e.g. reduce the
generated content's scope (fewer rows/sections/pages) and regenerate once with the user's
explicit go-ahead, or split the content into multiple sequentially named files that each pass
the gate. Do not truncate or split automatically without the user choosing that path.

## 3. Hand the reference to SharePoint Create file

Use the configured Create file tool's existing input schema. Site and folder come from
whatever is already fixed/configured for this tool; do not ask the user to restate config
that is pre-set, only ask if the destination is genuinely undetermined.

Bind the validated `/app/created/` path as the tool's content input directly (e.g. the file
input value is the absolute `/app/created/<name>` path). Do not wrap it in JSON, do not
base64-encode it, do not read it into the model to populate the argument — the runtime/tool
resolves that path to real bytes server-side. This is the confirmed mechanism, not a
hypothesis: verified across two connectors, two sessions, and re-verified with byte-for-byte
hash matches on 1 MB and 2 MB files.

**Authorization model:** when the user's original request already asks for both generation
and upload in one instruction, treat that as authorization to proceed through the upload
without a second blocking confirmation round-trip. Still surface the destination, filename,
measured size, and content source in the final report for transparency. Fall back to an
explicit pre-upload confirmation step only when the request is ambiguous about whether upload
was actually wanted, the destination is not already fixed/configured, or the content touches
anything sensitive.

Never overwrite an existing file; if the chosen filename collides, generate a new unique name
rather than setting overwrite unless the user explicitly asked to replace a named file.

## 4. Verify after upload

Prefer byte-level verification over metadata-only comparison:
1. Call a read-only metadata action (e.g. GetFileMetadataByPath) and confirm the returned
   size matches the source file's measured size exactly.
2. Only when a content-read tool can save the result to runtime storage without returning raw bytes to the model, fetch the uploaded file's content. Hash that saved copy against the original `/app/created/` file locally. If no such safe saved-copy mode is available, skip the content read and fall back to metadata-only agreement (size match without hash), stating that byte fidelity was not independently proven.
3. Size or hash mismatch: stop, report the mismatch, and do not silently retry.

## 5. Report

State clearly: what was generated (type, content source), the destination in SharePoint
(site/library/folder path or URL, and filename), the measured size, whether the upload
succeeded, and the verification level actually achieved (byte-hash-verified vs.
metadata-size-only vs. unverified). Never claim an upload succeeded without tool evidence, and
never claim byte-level integrity without an actual hash match.

**Do not surface the internal sandbox path** (e.g. `/app/created/<name>`) in a normal
user-facing report — it is a runtime implementation detail, not something a user asking to
"generate and upload a file" needs or expects to see, and exposing it looks like an internal
leak rather than useful information. Refer to the file by its name only, plus where it landed
in SharePoint. Only include the raw sandbox path when the user is explicitly debugging or
testing the skill itself (e.g. developing/validating this skill, as opposed to using its
end result), and say so if asked directly.

## 6. Failure handling

- Permission/DLP/authentication/unsupported-operation errors: stop and report; not a sizing
  issue, don't reinterpret it as one.
- Size-boundary errors even under the 4,000,000-byte gate: stop, report the exact error text
  and byte count, and treat it as new evidence the threshold needs tightening — do not retry
  with a slightly smaller guess. Communicate it to the user as you having hit a limitation and that they should reach out to the agent owner to report the issue.
- Ambiguous/timeout outcomes: check destination metadata if possible; otherwise report the
  outcome as unknown. Never blindly retry a write whose outcome is unclear.
