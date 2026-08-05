# Release Audit Algorithm: wkdevops-release-audit-v1

The audit root is resolved to an absolute real path. Inventory includes every descendant directory, regular file, and symbolic link, but not the root itself. Other file types are rejected. Paths are root-relative POSIX paths, encoded as strict UTF-8 and sorted by ascending unsigned UTF-8 bytes.

Each JSON entry has exactly these inventory fields: `path`, `type`, `mode`, `uid`, `gid`, `size`, and `sha256`. `type` is `directory`, `file`, or `symlink`; `mode` is four lowercase octal digits; UID/GID are decimal integers. Directory size is normalized to zero and its SHA-256 is JSON null. File size is its byte length and file SHA-256 hashes raw bytes. Symlink size comes from `lstat`, and its SHA-256 hashes the raw UTF-8 link target without following it. Inode and `mtime_ns` are deliberately excluded because they change when an immutable release is copied without changing its security-relevant identity.

The metadata root is SHA-256 over all entries in inventory order. Each record is the UTF-8 encoding of `path`, `type`, `mode`, `uid`, `gid`, and decimal `size`, joined by byte `0x1f` and terminated by byte `0x1e`. The content root uses regular files and symbolic links and joins UTF-8 `path` with the lowercase ASCII raw-content (or raw link-target) SHA-256 using the same separators. No newline, Unicode, timestamp, or platform normalization is applied.

`release-audit.json` records the algorithm version, resolved root, rules, full inventory, and both roots. Recompute with the read-only tool:

```text
python3 scripts/release_audit.py --verify /project/devops-platform/shared/audit/task64/release-audit.json
```

A copied release can be checked with `--root COPY_PATH`; only the declared root field is rebased before exact comparison. The tool emits no file contents, environment variables, or secrets.
