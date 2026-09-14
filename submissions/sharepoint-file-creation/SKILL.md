---
name: sharepoint-file-creation
description: Source/generate the requested file using whatever content rules apply to the use case, gate it against an evidence-based pre-upload size threshold using the filesystem API, and upload it to SharePoint via the Create file tool's confirmed /app/created/ path-reference mechanism — without ever streaming raw file bytes through the LLM. Use this skill whenever a request asks for a file to be produced and uploaded to SharePoint, whether or not the user specifies a path, filename, format, or content source.
---

## Quick reference — the fixed sequence

1. Determine what content/format is being asked for and source it (Section 0).
2. Write the complete file under `/app/created/` only, with a descriptive unique name.
3. Re-measure the final file's size with the filesystem API. Proceed only if
   `0 < size_bytes < 4,000,000`; otherwise stop and offer options.
4. Call Create file with the `/app/created/<name>` path bound directly as the content input.
   Never read bytes into the model to populate it or target another directory.
5. Verify: metadata size match at minimum; prefer a byte-level SHA-256 comparison via a
   saved download when a content-read tool is available.
6. Report: content source, destination, size, upload result, and verification level achieved.

Treat steps 2–6 as fixed; only step 1 is meant to flex per use case.

## 0. Determine and source the content

Apply any configured content-generation rules first, including required templates,
knowledge sources, data sources, report structures, schemas, or style guides.

When no more specific rules are configured:
- Identify the requested file format and use the appropriate runtime library. Do not default
  to plain text unless plain text is requested.
- Ground the content in the user's request, available retrieval/knowledge tools, or prior
  conversation context.
- If a named source cannot be located, or no source can be identified, ask rather than
  fabricating content.

Produce a complete, correct file before continuing.

## 1. Generate the file in /app/created/ only

Write the complete file beneath `/app/created/` using a SharePoint-safe, sanitized
basename-only, collision-resistant filename. Retain `[A-Za-z0-9_-]` in the stem, replace
other runs with `_`, trim separators, and preserve one valid extension. Reject path
separators, `..`, and control characters; resolve the candidate path and verify it remains
under `/app/created/` before writing or uploading.

Use `/app/created/` because it is the confirmed path-reference location for Create file.
Other paths may be uploaded as literal path text instead of file content, causing silent
corruption.

Keep bytes inside the runtime: never print, preview, or return generated content through the
model. Track the validated path, filename, and byte count internally for upload and
verification, but do not expose the sandbox path in normal user-facing responses.

## 2. Measure and gate the size — always on the final written file

After the file is fully written and closed, measure it with the runtime filesystem API
(`os.path.getsize`, `os.stat().st_size`, or equivalent). Never estimate from text length,
row counts, token counts, or a measurement taken before the final write.

Proceed only when `0 < size_bytes < 4,000,000`. This conservative gate addresses the current
inline connector/tool upload boundary; it is not a SharePoint file-size limit or a platform
guarantee.

If the file is empty, unreadable, or at least 4,000,000 bytes, do not call Create file.
Report the measured size and offer to reduce the content or split it into multiple files.
Do not truncate, regenerate, or split automatically without the user's approval.

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
