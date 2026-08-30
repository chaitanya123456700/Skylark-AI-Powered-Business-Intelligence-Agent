"""
Run this after importing your CSVs into monday.com to find each column's real ID.

Usage:
    python discover_columns.py <board_id>

The board_id is the number in the board's URL, e.g.
https://yourteam.monday.com/boards/1234567890 -> board_id = 1234567890
"""
import sys
from monday_client import list_board_columns


def main():
    if len(sys.argv) != 2:
        print("Usage: python discover_columns.py <board_id>")
        sys.exit(1)

    board_id = sys.argv[1]
    columns = list_board_columns(int(board_id))

    print(f"\nColumns for board {board_id}:\n")
    print(f"{'COLUMN ID':<22} {'TITLE':<32} {'TYPE':<15}")
    print("-" * 70)
    for c in columns:
        print(f"{c['id']:<22} {c['title']:<32} {c['type']:<15}")
    print("\nCopy the COLUMN ID values you need into backend/column_mapping.json\n")


if __name__ == "__main__":
    main()
