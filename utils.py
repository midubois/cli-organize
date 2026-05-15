#!/usr/bin/env python3
import argparse
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

DB_PATH = Path.home() / ".file_tagger.db"
DOWNLOADS_DIR = Path.home() / "Downloads"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath      TEXT    UNIQUE NOT NULL,
            filename      TEXT    NOT NULL,
            downloaded_at TEXT    NOT NULL,
            tagged_at     TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tags (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES files(id),
            tag     TEXT    NOT NULL,
            UNIQUE(file_id, tag)
        );
        CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
        CREATE INDEX IF NOT EXISTS idx_files_downloaded ON files(downloaded_at);
    """)
    return conn


def get_last_download() -> Path:
    files = [f for f in DOWNLOADS_DIR.iterdir() if f.is_file()]
    if not files:
        sys.exit(f"No files found in {DOWNLOADS_DIR}")
    return max(files, key=lambda f: f.stat().st_mtime)


def parse_date(raw: str) -> datetime:
    for fmt in ("%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    sys.exit(f"Cannot parse date '{raw}'. Use formats like 'May 15 2022' or '2022-05-15'.")


def print_row(row: sqlite3.Row) -> None:
    dt = datetime.fromisoformat(row["downloaded_at"]).strftime("%B %d %Y %I:%M %p")
    tags = row["tags"] or "(no tags)"
    print(f"  {row['filename']}")
    print(f"    Path:       {row['filepath']}")
    print(f"    Downloaded: {dt}")
    print(f"    Tags:       {tags}")



def cmd_tag(args: argparse.Namespace) -> None:
    file = get_last_download()
    stat = file.stat()
    downloaded_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
    tagged_at = datetime.now().isoformat()

    conn = get_db()
    with conn:
        conn.execute(
            """
            INSERT INTO files (filepath, filename, downloaded_at, tagged_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(filepath) DO UPDATE SET tagged_at = excluded.tagged_at
            """,
            (str(file), file.name, downloaded_at, tagged_at),
        )
        file_id = conn.execute(
            "SELECT id FROM files WHERE filepath = ?", (str(file),)
        ).fetchone()["id"]
        for tag in args.tags:
            conn.execute(
                "INSERT OR IGNORE INTO tags (file_id, tag) VALUES (?, ?)",
                (file_id, tag.lower()),
            )

    applied = ", ".join(t.lower() for t in args.tags)
    print(f"Tagged '{file.name}' with: {applied}")


def cmd_find(args: argparse.Namespace) -> None:
    conn = get_db()

    base_query = """
        SELECT f.filepath, f.filename, f.downloaded_at,
               GROUP_CONCAT(t.tag, ', ') AS tags
        FROM files f
        LEFT JOIN tags t ON f.id = t.file_id
        {where}
        GROUP BY f.id
        ORDER BY f.downloaded_at DESC
    """

    if args.tag and args.date:
        date_prefix = parse_date(args.date).strftime("%Y-%m-%d")
        rows = conn.execute(
            base_query.format(where="""
                WHERE f.id IN (SELECT file_id FROM tags WHERE tag = ?)
                  AND f.downloaded_at LIKE ?
            """),
            (args.tag.lower(), f"{date_prefix}%"),
        ).fetchall()
    elif args.tag:
        rows = conn.execute(
            base_query.format(where="WHERE f.id IN (SELECT file_id FROM tags WHERE tag = ?)"),
            (args.tag.lower(),),
        ).fetchall()
    elif args.date:
        date_prefix = parse_date(args.date).strftime("%Y-%m-%d")
        rows = conn.execute(
            base_query.format(where="WHERE f.downloaded_at LIKE ?"),
            (f"{date_prefix}%",),
        ).fetchall()
    else:
        rows = conn.execute(base_query.format(where="")).fetchall()

    if not rows:
        print("No files found.")
        return

    print(f"Found {len(rows)} file(s):\n")
    for row in rows:
        print_row(row)
        print()


def cmd_list_tags(_args: argparse.Namespace) -> None:
    conn = get_db()
    rows = conn.execute(
        "SELECT tag, COUNT(*) AS count FROM tags GROUP BY tag ORDER BY count DESC, tag"
    ).fetchall()
    if not rows:
        print("No tags in database.")
        return
    print("Tags:\n")
    for row in rows:
        print(f"  {row['tag']}  ({row['count']} file{'s' if row['count'] != 1 else ''})")



def main() -> None:
    parser = argparse.ArgumentParser(
        prog="organize",
        description="Tag downloaded files and query them by tag or date.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    tag_p = sub.add_parser("tag", help="Tag the most recently downloaded file")
    tag_p.add_argument("tags", nargs="+", metavar="TAG", help="One or more tags to apply")

    find_p = sub.add_parser("find", help="Search tagged files")
    find_p.add_argument("--tag", "-t", metavar="TAG", help="Filter by tag")
    find_p.add_argument(
        "--date", "-d", metavar="DATE",
        help="Filter by download date, e.g. 'May 15 2022' or '2022-05-15'",
    )

    #tags
    sub.add_parser("tags", help="List all tags and how many files each has")

    args = parser.parse_args()

    dispatch = {"tag": cmd_tag, "find": cmd_find, "tags": cmd_list_tags}
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
