# Safe Repository Mutation Design

**Status:** Approved during brainstorming on 2026-08-09.

## Purpose

613 Coding needs a precise patch tool so agents can make focused changes without replacing
whole files. Its existing `delete_file` implementation also has a parent-directory time-of-check
to time-of-use race. This design makes both mutation paths repository-bounded, schema-validated,
descriptor-relative, and independently testable.

## Scope

This subsystem adds a model-visible `apply_patch` tool and replaces the implementation of
`delete_file`. It does not add binary patching, file-mode changes, rename detection, directory
deletion, or a general shell patch command.

## Tool Contract

`apply_patch` uses a versioned Draft 2020-12 JSON Schema identified as
`coding613.tool.apply_patch.v1`. Its input is exactly:

```json
{"patch": "<unified diff>"}
```

The schema rejects missing, non-string, empty, oversized, and additional fields. Policy treats
the tool as a repository write, so strict mode asks, balanced mode allows configured writes, and
hard safety rules remain non-bypassable.

The patch format is strict unified diff. Version 1 supports adding, updating, and deleting regular
UTF-8 files. It rejects binary sections, renames, copies, mode-only changes, absolute paths,
parent traversal, duplicate targets, NUL bytes, symlink targets, and protected `.git` or
`.613-coding` paths.

## Patch Execution

Execution has two phases:

1. Parse every file section and hunk, normalize repository-relative POSIX paths, open source files
   without following symlinks, enforce file and aggregate patch limits, and apply all hunks in
   memory. A missing context line or any other semantic error ends the call before mutation.
2. Traverse target parents from a pinned repository-root descriptor using `dir_fd`,
   `O_DIRECTORY`, and `O_NOFOLLOW`. Create any allowed parent directories descriptor-relatively.
   Stage updated content in same-directory temporary files, flush and `fsync`, then replace the
   individual targets atomically. Delete operations are descriptor-relative.

Preflight guarantees that parse, path, and hunk errors cannot cause a partial write. Atomicity is
per target file. An unexpected I/O failure during the commit phase returns failure with the exact
files already changed rather than claiming a global transaction.

Successful output contains a concise add/update/delete count and a sorted, de-duplicated
`changed_files`. Errors use stable categories for invalid schema, invalid patch, conflict, unsafe
path, file limit, invalid UTF-8, and I/O failure. Persisted messages are redacted before storage.

## Descriptor-Relative Delete

`delete_file` validates a non-empty repository-relative path, opens the repository root once, and
walks each parent component with descriptor-relative no-follow directory opens. It then inspects
and unlinks the final entry using the held parent descriptor.

A final symlink is deleted as a link without touching its target. A symlink in any parent,
repository escape, missing entry, or real directory target is rejected. Renaming a checked parent
and replacing its pathname with a symlink cannot redirect deletion because the operation remains
anchored to the already-open directory descriptor.

## Testing And Acceptance

Tests must first fail against the current whole-file-only and pathname-based behavior. Coverage
includes schema rejection, all supported patch operations, malformed diffs, hunk conflicts,
duplicate paths, protected paths, traversal, symlink parents and targets, UTF-8 and size limits,
multi-file preflight, accurate partial-I/O reporting, and final-symlink deletion.

A deterministic race regression replaces a parent pathname after traversal and before unlink.
The held descriptor must ensure that no outside file is deleted. Focused tests, the complete
offline suite, Ruff, mypy, `uv lock --check`, and `git diff --check` must pass. Independent review
must find no unresolved Critical or Important path-safety issue.
