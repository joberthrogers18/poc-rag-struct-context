import argparse
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path("sample_projects")
SUPPORTED_SUFFIXES = {".js", ".ts", ".prisma"}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Ref base para comparar o PR.",
    )
    parser.add_argument(
        "--head-ref",
        default="HEAD",
        help="Ref head para comparar o PR.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Forca reindexacao mesmo sem mudanca de hash.",
    )
    return parser.parse_args()


def collect_changed_files(base_ref: str, head_ref: str) -> tuple[list[str], list[str]]:
    cmd = [
        "git",
        "diff",
        "--name-status",
        f"{base_ref}...{head_ref}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    changed_files = []
    deleted_files = []

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        status, path = line.split("\t", 1)
        file_path = Path(path)
        if file_path.suffix not in SUPPORTED_SUFFIXES:
            continue
        if BASE_DIR not in file_path.parents and file_path.parts[:1] != BASE_DIR.parts:
            continue

        if status.startswith("D"):
            deleted_files.append(path)
        else:
            changed_files.append(path)

    return changed_files, deleted_files


def main():
    args = parse_args()
    changed_files, deleted_files = collect_changed_files(args.base_ref, args.head_ref)

    if not changed_files and not deleted_files:
        print("Nenhum arquivo relevante do PR para indexar.")
        return

    cmd = [sys.executable, "ingest.py"]
    if changed_files:
        cmd.append("--files")
        cmd.extend(changed_files)
    if deleted_files:
        cmd.append("--deleted-files")
        cmd.extend(deleted_files)
    if args.force:
        cmd.append("--force")

    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
