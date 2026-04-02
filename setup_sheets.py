#!/usr/bin/env python3
"""
One-time setup script for SN35 Distribution Google Sheet.

What this does:
1. Archives the 3 old tabs by renaming them to [Archive] ...
2. Creates 4 new tabs: Dashboard, Daily Sweeps, Distributions, Config
3. Populates headers, formulas, formatting, and opening balance row
4. Applies data validation to the Status column in Distributions

Run this once locally:
    python3 setup_sheets.py
"""

import os
import sys
from datetime import date
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env (same file used by daily_stake_move.py)
# ---------------------------------------------------------------------------
for _p in [
    Path(__file__).parent / ".env",
    Path("/opt/stake-move-automation") / ".env",
    Path.cwd() / ".env",
]:
    if _p.exists():
        load_dotenv(_p)
        break


def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        print(f"ERROR: '{key}' is required but not set in your .env file.", file=sys.stderr)
        sys.exit(1)
    return val


# ---------------------------------------------------------------------------
# Config — all values from .env
# ---------------------------------------------------------------------------
SA_FILE   = _require("GOOGLE_SERVICE_ACCOUNT_JSON")
SHEET_ID  = _require("GOOGLE_SHEET_ID")
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"

OPENING_BALANCE = float(_require("OPENING_BALANCE"))
OPENING_DATE    = _require("OPENING_DATE")

PARTNER_COUNT = int(os.environ.get("PARTNER_COUNT", "2"))
PARTNERS: list[dict] = []
for _i in range(1, PARTNER_COUNT + 1):
    _name   = os.environ.get(f"PARTNER_{_i}_NAME", f"Partner{_i}").strip()
    _share  = float(os.environ.get(f"PARTNER_{_i}_SHARE", str(round(1 / PARTNER_COUNT, 6))))
    _wallet = _require(f"PARTNER_{_i}_WALLET")
    PARTNERS.append({"name": _name, "share": _share, "wallet": _wallet})

FIRST_DIST_DATE = _require("FIRST_DIST_DATE")
CYCLE_DAYS      = int(os.environ.get("CYCLE_DAYS", "14"))

# Tabs to rename as [Archive] before setup (comma-separated in env, empty = none)
ARCHIVE_MAP: dict[str, str] = {}
for _name in os.environ.get("ARCHIVE_TAB_NAMES", "").split(","):
    _name = _name.strip()
    if _name:
        ARCHIVE_MAP[_name] = f"[Archive] {_name}"

# New tab names (in display order)
TAB_DASHBOARD     = "Dashboard"
TAB_SWEEPS        = "Daily Sweeps"
TAB_DISTRIBUTIONS = "Distributions"
TAB_CONFIG        = "Config"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def col_letter(idx: int) -> str:
    """Convert 0-based column index to A, B, ..., Z, AA, AB, ..."""
    result = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        result = chr(65 + r) + result
    return result


def connect() -> gspread.Spreadsheet:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(SA_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    print(f"Connected to: {sh.title}")
    return sh


def get_or_create_tab(sh: gspread.Spreadsheet, title: str, index: int = None) -> gspread.Worksheet:
    """Return existing tab or create it (appended at end, then repositioned)."""
    try:
        ws = sh.worksheet(title)
        print(f"  Tab already exists: '{title}'")
        return ws
    except gspread.WorksheetNotFound:
        # Always add at end to avoid index-out-of-range errors
        ws = sh.add_worksheet(title=title, rows=1000, cols=30)
        print(f"  Created tab: '{title}'")
        return ws


def hex_to_color(hex_str: str) -> dict:
    """Convert #RRGGBB to gspread color dict (0-1 range)."""
    hex_str = hex_str.lstrip("#")
    r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


def bold_header_request(sheet_id: int, num_cols: int, bg_hex: str, fg_hex: str = "#FFFFFF") -> list:
    """Returns batch update requests to format row 1 as a bold header."""
    return [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": num_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": hex_to_color(bg_hex),
                        "textFormat": {
                            "bold": True,
                            "foregroundColor": hex_to_color(fg_hex),
                            "fontSize": 10,
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
    ]


def col_width_request(sheet_id: int, col_widths: list[int]) -> list:
    """col_widths: list of pixel widths, one per column starting at col 0."""
    requests = []
    for i, width in enumerate(col_widths):
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": i,
                    "endIndex": i + 1,
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        })
    return requests


def number_format_request(sheet_id: int, start_col: int, end_col: int,
                           start_row: int, pattern: str) -> dict:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": start_row,
                "endRowIndex": 1000,
                "startColumnIndex": start_col,
                "endColumnIndex": end_col,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "NUMBER", "pattern": pattern}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }


def date_format_request(sheet_id: int, col: int) -> dict:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": 1000,
                "startColumnIndex": col,
                "endColumnIndex": col + 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }


# ---------------------------------------------------------------------------
# Step 1: Archive old tabs
# ---------------------------------------------------------------------------
def archive_old_tabs(sh: gspread.Spreadsheet):
    print("\n[1] Archiving old tabs...")
    existing = {ws.title: ws for ws in sh.worksheets()}
    for old_name, new_name in ARCHIVE_MAP.items():
        if old_name in existing:
            if new_name in existing:
                print(f"  Already archived: '{new_name}' (skipping)")
            else:
                ws = existing[old_name]
                ws.update_title(new_name)
                print(f"  Renamed: '{old_name}' → '{new_name}'")
        else:
            print(f"  Not found (already archived or deleted): '{old_name}'")


# ---------------------------------------------------------------------------
# Step 2: Config tab
# ---------------------------------------------------------------------------
def setup_config(sh: gspread.Spreadsheet) -> gspread.Worksheet:
    print("\n[2] Setting up Config tab...")
    ws = get_or_create_tab(sh, TAB_CONFIG, index=10)
    ws.clear()

    rows = [
        ["Key", "Value", "Notes"],
        ["", "", ""],
        ["--- Partners ---", "", ""],
        ["Partner_Count", PARTNER_COUNT, ""],
    ]
    for i, p in enumerate(PARTNERS, 1):
        rows += [
            [f"P{i}_Name",   p["name"],   ""],
            [f"P{i}_Share",  p["share"],  "Decimal (0.5 = 50%)"],
            [f"P{i}_Wallet", p["wallet"], ""],
        ]
    rows += [
        ["", "", ""],
        ["--- Distribution ---", "", ""],
        ["Cycle_Days", CYCLE_DAYS, "Days between distributions"],
        ["First_Distribution_Date", FIRST_DIST_DATE, "YYYY-MM-DD"],
        ["Distribution_Day", "Friday", "Day of week for distributions"],
        ["", "", ""],
        ["--- Ledger ---", "", ""],
        ["Starting_Balance", OPENING_BALANCE, "Alpha already in wallet at launch"],
        ["Opening_Date", OPENING_DATE, "Date of opening balance entry"],
        ["", "", ""],
        ["--- Links ---", "", ""],
        ["Sheet_URL", SHEET_URL, ""],
        ["Dashboard_URL", "", "Auto-filled at end of setup"],
        ["Distributions_URL", "", "Auto-filled at end of setup"],
        ["Daily_Sweeps_URL", "", "Auto-filled at end of setup"],
    ]

    ws.update(rows, range_name="A1")

    sid = ws.id
    batch = (
        bold_header_request(sid, 3, "#1a73e8")
        + col_width_request(sid, [220, 320, 280])
    )
    sh.batch_update({"requests": batch})
    print("  Config tab ready.")
    return ws


# ---------------------------------------------------------------------------
# Step 3: Daily Sweeps tab
# ---------------------------------------------------------------------------
def setup_daily_sweeps(sh: gspread.Spreadsheet) -> gspread.Worksheet:
    print("\n[3] Setting up Daily Sweeps tab...")
    ws = get_or_create_tab(sh, TAB_SWEEPS, index=1)
    ws.clear()

    headers = ["Date (UTC)", "Amount (α)", "Cumulative Total (α)", "Notes"]
    ws.update([headers], range_name="A1")

    # Opening balance row
    opening_row = [OPENING_DATE, OPENING_BALANCE, OPENING_BALANCE, "Opening balance"]
    ws.update([opening_row], range_name="A2")

    sid = ws.id
    batch = (
        bold_header_request(sid, 4, "#0f9d58")
        + col_width_request(sid, [160, 160, 200, 340])
        + [
            date_format_request(sid, 0),
            number_format_request(sid, 1, 3, 1, '#,##0.0000000000" α"'),
            number_format_request(sid, 2, 3, 1, '#,##0.0000000000" α"'),
        ]
    )
    sh.batch_update({"requests": batch})
    print("  Daily Sweeps tab ready (opening balance row inserted).")
    return ws


# ---------------------------------------------------------------------------
# Step 4: Distributions tab
# ---------------------------------------------------------------------------
def setup_distributions(sh: gspread.Spreadsheet) -> gspread.Worksheet:
    print("\n[4] Setting up Distributions tab...")
    ws = get_or_create_tab(sh, TAB_DISTRIBUTIONS, index=2)
    ws.clear()

    N = len(PARTNERS)
    status_col_idx  = 4 + N          # 0-based; "G" for N=2, "H" for N=3
    tx_start_col_idx = status_col_idx + 1
    total_cols = 4 + 2 * N + 2

    headers = (
        ["Distribution Date", "Period Start", "Period End", "Total Balance (α)"]
        + [f"{p['name']} Amount (α)" for p in PARTNERS]
        + ["Status"]
        + [f"{p['name']} Tx Link" for p in PARTNERS]
        + ["Notes"]
    )
    ws.update([headers], range_name="A1")

    sid = ws.id

    # Data validation: Status column only allows "Pending" freely;
    # "Completed" requires every Tx Link column to be non-empty.
    status_cell_ref = f"{col_letter(status_col_idx)}2"
    tx_conditions   = ", ".join(
        f'{col_letter(tx_start_col_idx + i)}2<>""'
        for i in range(N)
    )
    validation_formula = (
        f'=OR({status_cell_ref}="Pending",'
        f'AND({status_cell_ref}="Completed",{tx_conditions}))'
    )
    partner_names_str = " and ".join(p["name"] for p in PARTNERS)

    status_validation_request = {
        "setDataValidation": {
            "range": {
                "sheetId": sid,
                "startRowIndex": 1,
                "endRowIndex": 1000,
                "startColumnIndex": status_col_idx,
                "endColumnIndex": status_col_idx + 1,
            },
            "rule": {
                "condition": {
                    "type": "CUSTOM_FORMULA",
                    "values": [{"userEnteredValue": validation_formula}],
                },
                "showCustomUi": True,
                "strict": True,
                "inputMessage": (
                    f"Add all transaction links ({partner_names_str}) before "
                    "marking as Completed."
                ),
            },
        }
    }

    col_widths = (
        [160, 130, 130, 180]   # Date, Period Start, Period End, Total Balance
        + [180] * N             # Partner amount cols
        + [110]                 # Status
        + [280] * N             # Tx link cols
        + [220]                 # Notes
    )
    batch = (
        bold_header_request(sid, total_cols, "#e65100")
        + col_width_request(sid, col_widths)
        + [
            date_format_request(sid, 0),
            date_format_request(sid, 1),
            date_format_request(sid, 2),
            # Total Balance + all partner amount cols
            number_format_request(sid, 3, 4 + N, 1, '#,##0.0000000000" α"'),
            status_validation_request,
        ]
    )
    sh.batch_update({"requests": batch})
    print("  Distributions tab ready (status validation applied).")
    return ws


# ---------------------------------------------------------------------------
# Step 5: Dashboard tab
# ---------------------------------------------------------------------------
def setup_dashboard(sh: gspread.Spreadsheet):
    print("\n[5] Setting up Dashboard tab...")
    ws = get_or_create_tab(sh, TAB_DASHBOARD, index=0)
    ws.clear()

    N = len(PARTNERS)
    status_col = col_letter(4 + N)   # "G" for N=2, "H" for N=3, etc.

    # Use INDEX/MATCH for Config lookups so row positions don't break when
    # partner count changes.
    _conf_start_bal  = 'INDEX(Config!B:B,MATCH("Starting_Balance",Config!A:A,0))'
    _conf_first_dist = 'INDEX(Config!B:B,MATCH("First_Distribution_Date",Config!A:A,0))'

    rows: list = [
        # --- Title ---
        ["SN35 Distribution Dashboard", "", ""],
        ["", "", ""],

        # --- Balance ---
        ["BALANCE", "", ""],
        ["Current Balance",
         f"={_conf_start_bal}"
         f"+SUMIF('Daily Sweeps'!D:D,\"<>Opening balance\",'Daily Sweeps'!B:B)"
         f"-SUMIF(Distributions!{status_col}:{status_col},\"Completed\",Distributions!D:D)",
         "Starting balance + all sweeps - completed distributions"],
        ["Starting Balance", f"={_conf_start_bal}", ""],
        ["Total Earned (all sweeps)",
         "=SUMIF('Daily Sweeps'!D:D,\"<>Opening balance\",'Daily Sweeps'!B:B)",
         ""],
        ["Total Distributed",
         f"=SUMIF(Distributions!{status_col}:{status_col},\"Completed\",Distributions!D:D)",
         "Completed distributions only"],
        ["", "", ""],

        # --- Next Distribution ---
        ["NEXT DISTRIBUTION", "", ""],
        ["Next Distribution Date",
         f"={_conf_first_dist}+CEILING(TODAY()-{_conf_first_dist},{CYCLE_DAYS})",
         "Auto-calculated from first dist date + cycle"],
        ["Days Until Distribution",
         f"={_conf_first_dist}+CEILING(TODAY()-{_conf_first_dist},{CYCLE_DAYS})-TODAY()",
         ""],
        ["Days Into Current Period",
         f"=MOD(TODAY()-{_conf_first_dist},{CYCLE_DAYS})",
         f"Out of {CYCLE_DAYS} days"],
        ["Projected Distribution Amount",
         f"={_conf_start_bal}"
         f"+SUMIF('Daily Sweeps'!D:D,\"<>Opening balance\",'Daily Sweeps'!B:B)"
         f"-SUMIF(Distributions!{status_col}:{status_col},\"Completed\",Distributions!D:D)"
         f"+(IFERROR(AVERAGE(QUERY('Daily Sweeps'!A:B,\"select B where A >= date '\"&TEXT(TODAY()-14,\"yyyy-mm-dd\")&\"' and B > 0\",0)),0)"
         f"*({CYCLE_DAYS}-MOD(TODAY()-{_conf_first_dist},{CYCLE_DAYS})))",
         "Current balance + (14-day avg × days remaining)"],
        ["", "", ""],

        # --- Performance ---
        ["PERFORMANCE", "", ""],
        ["All-Time Daily Average",
         "=IFERROR(SUMIF('Daily Sweeps'!D:D,\"<>Opening balance\",'Daily Sweeps'!B:B)/MAX(1,COUNTA('Daily Sweeps'!A:A)-2),0)",
         "Total earned / number of sweep days"],
        ["7-Day Average",
         "=IFERROR(AVERAGEIFS('Daily Sweeps'!B:B,'Daily Sweeps'!A:A,\">=\"&(TODAY()-7),'Daily Sweeps'!D:D,\"<>Opening balance\"),0)",
         ""],
        ["14-Day Average",
         "=IFERROR(AVERAGEIFS('Daily Sweeps'!B:B,'Daily Sweeps'!A:A,\">=\"&(TODAY()-14),'Daily Sweeps'!D:D,\"<>Opening balance\"),0)",
         ""],
        ["30-Day Average",
         "=IFERROR(AVERAGEIFS('Daily Sweeps'!B:B,'Daily Sweeps'!A:A,\">=\"&(TODAY()-30),'Daily Sweeps'!D:D,\"<>Opening balance\"),0)",
         ""],
        ["Consecutive Sweep Streak",
         "=IFERROR(MATCH(FALSE,EXACT(TEXT(TODAY()-ROW(INDIRECT(\"1:365\"))+1,\"yyyy-mm-dd\"),'Daily Sweeps'!A:A),0)-1,0)",
         "Days in a row with a successful sweep"],
        ["", "", ""],

        # --- Partners (dynamic) ---
        ["PARTNERS", "", ""],
    ]
    for i, p in enumerate(PARTNERS):
        amount_col = col_letter(4 + i)
        rows.append([
            f"{p['name']} Total Received",
            f'=SUMIF(Distributions!{status_col}:{status_col},"Completed",Distributions!{amount_col}:{amount_col})',
            f"Wallet: {p['wallet']}",
        ])
    rows += [
        ["", "", ""],

        # --- Last Sweep ---
        ["LAST SWEEP", "", ""],
        ["Last Sweep Date",
         "=IFERROR(INDEX('Daily Sweeps'!A:A,MATCH(2,1/('Daily Sweeps'!A:A<>\"\"),1)),\"None\")",
         ""],
        ["Last Sweep Amount",
         "=IFERROR(INDEX('Daily Sweeps'!B:B,MATCH(2,1/('Daily Sweeps'!A:A<>\"\"),1)),0)",
         ""],
        ["", "", ""],

        # --- Distributions Summary ---
        ["DISTRIBUTIONS", "", ""],
        ["Total Distributions Completed",
         f"=COUNTIF(Distributions!{status_col}:{status_col},\"Completed\")",
         ""],
        ["Total Distributions Pending",
         f"=COUNTIF(Distributions!{status_col}:{status_col},\"Pending\")",
         ""],
        ["", "", ""],

        # --- Footer ---
        ["Last Updated", "=NOW()", "Auto-refreshes on sheet open"],
    ]

    ws.update(rows, range_name="A1")

    sid = ws.id

    # Title row formatting
    title_format = {
        "repeatCell": {
            "range": {
                "sheetId": sid,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": 3,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": hex_to_color("#1a1a2e"),
                    "textFormat": {
                        "bold": True,
                        "foregroundColor": hex_to_color("#e2b96f"),
                        "fontSize": 14,
                    },
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    }

    # Section header rows (rows 3, 9, 15, 22, 26, 31 — 0-indexed: 2, 8, 14, 21, 25, 30)
    section_rows = [2, 8, 14, 21, 25, 30]
    section_requests = []
    for r in section_rows:
        section_requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": r,
                    "endRowIndex": r + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 3,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": hex_to_color("#e8f0fe"),
                        "textFormat": {"bold": True, "fontSize": 9},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        })

    # Value column number formats
    alpha_format_rows = [3, 4, 5, 6, 9, 12, 15, 16, 17, 18, 22, 23, 26, 27]
    alpha_requests = []
    for r in alpha_format_rows:
        alpha_requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": r,
                    "endRowIndex": r + 1,
                    "startColumnIndex": 1,
                    "endColumnIndex": 2,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {
                            "type": "NUMBER",
                            "pattern": '#,##0.0000" α"',
                        }
                    }
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        })

    # Date/days format for rows 9 (date), 10 (days), 11 (days)
    date_fmt_req = {
        "repeatCell": {
            "range": {
                "sheetId": sid,
                "startRowIndex": 9,
                "endRowIndex": 10,
                "startColumnIndex": 1,
                "endColumnIndex": 2,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }

    # Last updated datetime format
    last_updated_fmt = {
        "repeatCell": {
            "range": {
                "sheetId": sid,
                "startRowIndex": 35,
                "endRowIndex": 36,
                "startColumnIndex": 1,
                "endColumnIndex": 2,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": "DATE_TIME",
                        "pattern": "yyyy-mm-dd hh:mm:ss",
                    }
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }

    batch = (
        [title_format, date_fmt_req, last_updated_fmt]
        + section_requests
        + alpha_requests
        + col_width_request(sid, [240, 260, 380])
    )
    sh.batch_update({"requests": batch})

    # Move Dashboard to first position
    ws.update_index(0)
    print("  Dashboard tab ready.")
    return ws


# ---------------------------------------------------------------------------
# Step 6: Back-fill tab URLs into Config (needs real GIDs from created tabs)
# ---------------------------------------------------------------------------
def update_config_urls(sh: gspread.Spreadsheet):
    """Write the correct per-tab URLs into Config after all tabs are created."""
    print("\n[6] Updating Config tab with tab URLs...")
    cfg = sh.worksheet(TAB_CONFIG)

    # Fetch real GIDs from the live spreadsheet
    tab_gids = {ws.title: ws.id for ws in sh.worksheets()}

    url_rows = {
        "Dashboard_URL": f"{SHEET_URL}/edit#gid={tab_gids.get(TAB_DASHBOARD, '')}",
        "Distributions_URL": f"{SHEET_URL}/edit#gid={tab_gids.get(TAB_DISTRIBUTIONS, '')}",
        "Daily_Sweeps_URL": f"{SHEET_URL}/edit#gid={tab_gids.get(TAB_SWEEPS, '')}",
    }

    # Find each key row and update col B in-place
    all_rows = cfg.get_all_values()
    for i, row in enumerate(all_rows, start=1):
        if row and row[0].strip() in url_rows:
            cfg.update_cell(i, 2, url_rows[row[0].strip()])
            print(f"  Updated {row[0].strip()} → {url_rows[row[0].strip()]}")

    print("  Config URLs updated.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("SN35 Distribution — Google Sheets Setup")
    print("=" * 60)

    sh = connect()

    archive_old_tabs(sh)
    setup_config(sh)
    setup_daily_sweeps(sh)
    setup_distributions(sh)
    setup_dashboard(sh)
    update_config_urls(sh)

    print("\n" + "=" * 60)
    print("Setup complete!")
    print(f"Sheet URL: {SHEET_URL}")
    print("=" * 60)


if __name__ == "__main__":
    main()
