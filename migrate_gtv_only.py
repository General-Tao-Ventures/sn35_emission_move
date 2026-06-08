#!/usr/bin/env python3
"""
One-time, idempotent migration: make the SN35 Distribution sheet GTV-only.

Why this exists:
  The live `Config` tab used named keys (GTV_Share / PTN_Share) and had no
  `Partner_Count`, but utils/sheets_logger.py reads `Partner_Count` + `P{i}_*`.
  Because none of the expected keys matched, the runtime silently fell back to
  its default of 2 partners / 50-50 / names "P1","P2" / empty wallets — so
  editing GTV_Share / PTN_Share in the sheet did nothing.

What this does (all in the Google Sheet, no VM code changes required):
  1. Config tab        -> Partner_Count=1, P1_*=GTV (share 1.0), drop PTN.
  2. Distributions tab -> single-partner layout (drop PTN Amount / PTN Tx Link),
                          keep completed rows, set the 2 still-Pending rows to
                          GTV amount = Total Balance (100% GTV), re-apply
                          formatting + Status data-validation for N=1.
  3. Dashboard tab     -> rebuild formulas for status column F and a single GTV
                          partner row (drop "PTN Total Received").
  4. Daily Sweeps tab  -> untouched.

Run once on the VM (where the service-account JSON and .env live):
    cd /opt/stake-move-automation && sudo python3 migrate_gtv_only.py

Safe to re-run: it detects the current layout from the header / keys.
"""

import os
import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env (same file used by daily_stake_move.py / setup_sheets.py)
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


SA_FILE  = _require("GOOGLE_SERVICE_ACCOUNT_JSON")
SHEET_ID = _require("GOOGLE_SHEET_ID")
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"

# Default GTV wallet (used only if it cannot be read from the existing Config)
GTV_WALLET_FALLBACK = "5EQvqYFsPijkS5V32vqzcMmQDV4Q167MEofmzFk6qH8W7byh"

TAB_DASHBOARD     = "Dashboard"
TAB_SWEEPS        = "Daily Sweeps"
TAB_DISTRIBUTIONS = "Distributions"
TAB_CONFIG        = "Config"

CYCLE_DAYS_DEFAULT = 14


# ---------------------------------------------------------------------------
# Small helpers (copied from setup_sheets.py so this script is self-contained
# and does not trigger setup_sheets.py's module-level _require() calls)
# ---------------------------------------------------------------------------
def parse_float(value) -> float:
    """Parse a cell value that may contain currency symbols, commas, or alpha."""
    if value is None:
        return 0.0
    cleaned = str(value).replace("\u03b1", "").replace(",", "").replace("\xa0", "").strip()
    return float(cleaned) if cleaned else 0.0


def col_letter(idx: int) -> str:
    """Convert 0-based column index to A, B, ..., Z, AA, AB, ..."""
    result = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        result = chr(65 + r) + result
    return result


def hex_to_color(hex_str: str) -> dict:
    hex_str = hex_str.lstrip("#")
    r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


def bold_header_request(sheet_id: int, num_cols: int, bg_hex: str, fg_hex: str = "#FFFFFF") -> list:
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


def col_width_request(sheet_id: int, col_widths: list) -> list:
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
# Connect
# ---------------------------------------------------------------------------
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


def read_config_raw(sh: gspread.Spreadsheet) -> dict:
    rows = sh.worksheet(TAB_CONFIG).get_all_values()
    return {row[0].strip(): row[1].strip()
            for row in rows if len(row) >= 2 and row[0].strip()}


# ---------------------------------------------------------------------------
# 1. Config tab -> single GTV partner (generic P{i} scheme the code reads)
# ---------------------------------------------------------------------------
def migrate_config(sh: gspread.Spreadsheet, raw: dict):
    print("\n[1] Rewriting Config tab (Partner_Count=1, P1=GTV)...")
    ws = sh.worksheet(TAB_CONFIG)

    gtv_wallet = (raw.get("GTV_Wallet") or raw.get("P1_Wallet") or GTV_WALLET_FALLBACK).strip()
    starting_balance = parse_float(raw.get("Starting_Balance", "0"))
    opening_date = raw.get("Opening_Date", "2026-03-31").strip()
    cycle_days = int(parse_float(raw.get("Cycle_Days", str(CYCLE_DAYS_DEFAULT))) or CYCLE_DAYS_DEFAULT)
    first_dist = raw.get("First_Distribution_Date", "2026-04-10").strip()
    sheet_url = raw.get("Sheet_URL", SHEET_URL).strip()
    dashboard_url = raw.get("Dashboard_URL", "").strip()
    distributions_url = raw.get("Distributions_URL", "").strip()
    daily_sweeps_url = raw.get("Daily_Sweeps_URL", "").strip()

    rows = [
        ["Key", "Value", "Notes"],
        ["", "", ""],
        ["--- Partners ---", "", ""],
        ["Partner_Count", 1, "Number of partners sharing distributions"],
        ["P1_Name", "GTV", ""],
        ["P1_Share", 1, "Decimal (0.5 = 50%)"],
        ["P1_Wallet", gtv_wallet, ""],
        ["", "", "To add a partner: set Partner_Count=2 and add P2_Name / P2_Share / P2_Wallet (shares must sum to 1.0)"],
        ["--- Distribution ---", "", ""],
        ["Cycle_Days", cycle_days, "Days between distributions"],
        ["First_Distribution_Date", first_dist, "YYYY-MM-DD"],
        ["Distribution_Day", "Friday", "Day of week for distributions"],
        ["", "", ""],
        ["--- Ledger ---", "", ""],
        ["Starting_Balance", starting_balance, "Alpha already in wallet at launch"],
        ["Opening_Date", opening_date, "Date of opening balance entry"],
        ["", "", ""],
        ["--- Links ---", "", ""],
        ["Sheet_URL", sheet_url, ""],
        ["Dashboard_URL", dashboard_url, ""],
        ["Distributions_URL", distributions_url, ""],
        ["Daily_Sweeps_URL", daily_sweeps_url, ""],
    ]

    ws.clear()
    ws.update(rows, range_name="A1", value_input_option="USER_ENTERED")

    sid = ws.id
    batch = bold_header_request(sid, 3, "#1a73e8") + col_width_request(sid, [220, 360, 360])
    sh.batch_update({"requests": batch})
    print(f"  Config: P1_Name=GTV  P1_Share=1  P1_Wallet={gtv_wallet}")
    print(f"  Preserved: Starting_Balance={starting_balance}  Opening_Date={opening_date}  "
          f"Cycle_Days={cycle_days}  First_Distribution_Date={first_dist}")


# ---------------------------------------------------------------------------
# 2. Distributions tab -> single-partner layout (GTV only)
# ---------------------------------------------------------------------------
def migrate_distributions(sh: gspread.Spreadsheet):
    print("\n[2] Rebuilding Distributions tab (GTV-only, pending rows -> 100%)...")
    ws = sh.worksheet(TAB_DISTRIBUTIONS)
    dv = ws.get_all_values()
    if not dv:
        print("  Distributions tab empty — nothing to migrate.")
        return

    header = dv[0]
    try:
        status_idx = header.index("Status")
    except ValueError:
        # Fallback: assume legacy 2-partner layout
        status_idx = 6
    gtv_amount_idx = 4               # first partner amount column
    gtv_tx_idx = status_idx + 1      # first Tx Link column
    notes_idx = len(header) - 1      # Notes is always the last column

    new_rows = []
    for r in dv[1:]:
        if not any(c.strip() for c in r):
            continue
        date_v = r[0] if len(r) > 0 else ""
        period_start = r[1] if len(r) > 1 else ""
        period_end = r[2] if len(r) > 2 else ""
        total = parse_float(r[3]) if len(r) > 3 else 0.0
        gtv_amount = parse_float(r[gtv_amount_idx]) if len(r) > gtv_amount_idx else 0.0
        status = r[status_idx].strip() if len(r) > status_idx else ""
        gtv_tx = r[gtv_tx_idx].strip() if len(r) > gtv_tx_idx else ""
        notes = r[notes_idx].strip() if len(r) > notes_idx else ""

        # Pending rows become 100% GTV (PTN removed effective these distributions)
        if status.lower() == "pending":
            gtv_amount = total

        new_rows.append([date_v, period_start, period_end, total, gtv_amount, status, gtv_tx, notes])

    new_header = [
        "Distribution Date", "Period Start", "Period End", "Total Balance (\u03b1)",
        "GTV Amount (\u03b1)", "Status", "GTV Tx Link", "Notes",
    ]

    ws.clear()
    ws.update([new_header] + new_rows, range_name="A1", value_input_option="USER_ENTERED")

    sid = ws.id
    N = 1
    status_col_idx = 4 + N        # 5 -> col F
    tx_start_col_idx = status_col_idx + 1  # 6 -> col G
    total_cols = 4 + 2 * N + 2    # 8

    status_cell_ref = f"{col_letter(status_col_idx)}2"
    tx_cell_ref = f"{col_letter(tx_start_col_idx)}2"
    validation_formula = (
        f'=OR({status_cell_ref}="Pending",'
        f'AND({status_cell_ref}="Completed",{tx_cell_ref}<>""))'
    )
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
                "inputMessage": "Add the GTV transaction link before marking as Completed.",
            },
        }
    }

    col_widths = [160, 130, 130, 180] + [180] * N + [110] + [280] * N + [220]
    batch = (
        bold_header_request(sid, total_cols, "#e65100")
        + col_width_request(sid, col_widths)
        + [
            date_format_request(sid, 0),
            date_format_request(sid, 1),
            date_format_request(sid, 2),
            number_format_request(sid, 3, 4 + N, 1, '#,##0.0000000000" \u03b1"'),
            status_validation_request,
        ]
    )
    sh.batch_update({"requests": batch})

    pend = [r for r in new_rows if r[5].strip().lower() == "pending"]
    comp = [r for r in new_rows if r[5].strip().lower() == "completed"]
    print(f"  Rebuilt {len(new_rows)} rows ({len(comp)} Completed kept, {len(pend)} Pending set to 100% GTV).")
    for r in pend:
        print(f"    Pending {r[0]}: GTV = {r[4]:,.4f} (= Total Balance)")


# ---------------------------------------------------------------------------
# 3. Dashboard tab -> rebuild for single GTV partner (status col F)
# ---------------------------------------------------------------------------
def migrate_dashboard(sh: gspread.Spreadsheet, gtv_wallet: str, cycle_days: int):
    print("\n[3] Rebuilding Dashboard tab (status col F, GTV only)...")
    ws = sh.worksheet(TAB_DASHBOARD)

    partners = [{"name": "GTV", "wallet": gtv_wallet}]
    N = len(partners)
    status_col = col_letter(4 + N)   # "F" for N=1

    conf_start_bal = 'INDEX(Config!B:B,MATCH("Starting_Balance",Config!A:A,0))'
    conf_first_dist = 'INDEX(Config!B:B,MATCH("First_Distribution_Date",Config!A:A,0))'

    rows = []
    section_rows = []
    alpha_rows = []
    date_rows = []

    def add(row):
        rows.append(row)
        return len(rows) - 1

    def add_section(title):
        idx = add([title, "", ""])
        section_rows.append(idx)
        return idx

    def add_alpha(label, formula, note=""):
        idx = add([label, formula, note])
        alpha_rows.append(idx)
        return idx

    add(["SN35 Distribution Dashboard", "", ""])
    add(["", "", ""])

    add_section("BALANCE")
    add_alpha(
        "Current Balance",
        f"={conf_start_bal}"
        f"+SUMIF('Daily Sweeps'!D:D,\"<>Opening balance\",'Daily Sweeps'!B:B)"
        f"-SUMIF(Distributions!{status_col}:{status_col},\"Completed\",Distributions!D:D)",
        "Starting balance + all sweeps - completed distributions",
    )
    add_alpha("Starting Balance", f"={conf_start_bal}", "")
    add_alpha(
        "Total Earned (all sweeps)",
        "=SUMIF('Daily Sweeps'!D:D,\"<>Opening balance\",'Daily Sweeps'!B:B)",
        "",
    )
    add_alpha(
        "Total Distributed",
        f"=SUMIF(Distributions!{status_col}:{status_col},\"Completed\",Distributions!D:D)",
        "Completed distributions only",
    )
    add(["", "", ""])

    add_section("NEXT DISTRIBUTION")
    d_idx = add([
        "Next Distribution Date",
        f"={conf_first_dist}+CEILING(TODAY()-{conf_first_dist},{cycle_days})",
        "Auto-calculated from first dist date + cycle",
    ])
    date_rows.append(d_idx)
    add([
        "Days Until Distribution",
        f"={conf_first_dist}+CEILING(TODAY()-{conf_first_dist},{cycle_days})-TODAY()",
        "",
    ])
    add([
        "Days Into Current Period",
        f"=MOD(TODAY()-{conf_first_dist},{cycle_days})",
        f"Out of {cycle_days} days",
    ])
    add_alpha(
        "Projected Distribution Amount",
        f"={conf_start_bal}"
        f"+SUMIF('Daily Sweeps'!D:D,\"<>Opening balance\",'Daily Sweeps'!B:B)"
        f"-SUMIF(Distributions!{status_col}:{status_col},\"Completed\",Distributions!D:D)"
        f"+(IFERROR(AVERAGE(QUERY('Daily Sweeps'!A:B,\"select B where A >= date '\"&TEXT(TODAY()-14,\"yyyy-mm-dd\")&\"' and B > 0\",0)),0)"
        f"*({cycle_days}-MOD(TODAY()-{conf_first_dist},{cycle_days})))",
        "Current balance + (14-day avg x days remaining)",
    )
    add(["", "", ""])

    add_section("PERFORMANCE")
    add_alpha(
        "All-Time Daily Average",
        "=IFERROR(SUMIF('Daily Sweeps'!D:D,\"<>Opening balance\",'Daily Sweeps'!B:B)/MAX(1,COUNTA('Daily Sweeps'!A:A)-2),0)",
        "Total earned / number of sweep days",
    )
    add_alpha(
        "7-Day Average",
        "=IFERROR(AVERAGEIFS('Daily Sweeps'!B:B,'Daily Sweeps'!A:A,\">=\"&(TODAY()-7),'Daily Sweeps'!D:D,\"<>Opening balance\"),0)",
        "",
    )
    add_alpha(
        "14-Day Average",
        "=IFERROR(AVERAGEIFS('Daily Sweeps'!B:B,'Daily Sweeps'!A:A,\">=\"&(TODAY()-14),'Daily Sweeps'!D:D,\"<>Opening balance\"),0)",
        "",
    )
    add_alpha(
        "30-Day Average",
        "=IFERROR(AVERAGEIFS('Daily Sweeps'!B:B,'Daily Sweeps'!A:A,\">=\"&(TODAY()-30),'Daily Sweeps'!D:D,\"<>Opening balance\"),0)",
        "",
    )
    add([
        "Consecutive Sweep Streak",
        "=IFERROR(MATCH(FALSE,EXACT(TEXT(TODAY()-ROW(INDIRECT(\"1:365\"))+1,\"yyyy-mm-dd\"),'Daily Sweeps'!A:A),0)-1,0)",
        "Days in a row with a successful sweep",
    ])
    add(["", "", ""])

    add_section("PARTNERS")
    for i, p in enumerate(partners):
        amount_col = col_letter(4 + i)
        add_alpha(
            f"{p['name']} Total Received",
            f'=SUMIF(Distributions!{status_col}:{status_col},"Completed",Distributions!{amount_col}:{amount_col})',
            f"Wallet: {p['wallet']}",
        )
    add(["", "", ""])

    add_section("LAST SWEEP")
    add([
        "Last Sweep Date",
        "=IFERROR(INDEX('Daily Sweeps'!A:A,MATCH(2,1/('Daily Sweeps'!A:A<>\"\"),1)),\"None\")",
        "",
    ])
    add_alpha(
        "Last Sweep Amount",
        "=IFERROR(INDEX('Daily Sweeps'!B:B,MATCH(2,1/('Daily Sweeps'!A:A<>\"\"),1)),0)",
        "",
    )
    add(["", "", ""])

    add_section("DISTRIBUTIONS")
    add([
        "Total Distributions Completed",
        f"=COUNTIF(Distributions!{status_col}:{status_col},\"Completed\")",
        "",
    ])
    add([
        "Total Distributions Pending",
        f"=COUNTIF(Distributions!{status_col}:{status_col},\"Pending\")",
        "",
    ])
    add(["", "", ""])

    last_updated_idx = add(["Last Updated", "=NOW()", "Auto-refreshes on sheet open"])

    ws.clear()
    ws.update(rows, range_name="A1", value_input_option="USER_ENTERED")

    sid = ws.id

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

    alpha_requests = []
    for r in alpha_rows:
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
                        "numberFormat": {"type": "NUMBER", "pattern": '#,##0.0000" \u03b1"'}
                    }
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        })

    date_requests = []
    for r in date_rows:
        date_requests.append({
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
                        "numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}
                    }
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        })

    last_updated_fmt = {
        "repeatCell": {
            "range": {
                "sheetId": sid,
                "startRowIndex": last_updated_idx,
                "endRowIndex": last_updated_idx + 1,
                "startColumnIndex": 1,
                "endColumnIndex": 2,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "DATE_TIME", "pattern": "yyyy-mm-dd hh:mm:ss"}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }

    batch = (
        [title_format, last_updated_fmt]
        + section_requests
        + alpha_requests
        + date_requests
        + col_width_request(sid, [240, 260, 420])
    )
    sh.batch_update({"requests": batch})
    print(f"  Dashboard rebuilt for N={N} (status column {status_col}).")


# ---------------------------------------------------------------------------
# Verification (read-only, after migration)
# ---------------------------------------------------------------------------
def verify(sh: gspread.Spreadsheet):
    print("\n[verify] Re-reading sheet...")
    raw = read_config_raw(sh)
    pc = raw.get("Partner_Count")
    p1n = raw.get("P1_Name")
    p1s = raw.get("P1_Share")
    print(f"  Config -> Partner_Count={pc}  P1_Name={p1n}  P1_Share={p1s}")
    if "PTN_Share" in raw or "PTN_Name" in raw:
        print("  WARNING: PTN_* keys still present in Config.")

    dv = sh.worksheet(TAB_DISTRIBUTIONS).get_all_values()
    print(f"  Distributions header: {dv[0] if dv else 'EMPTY'}")
    for r in dv[1:]:
        if any(c.strip() for c in r):
            print(f"    {r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 64)
    print("SN35 Distribution — Migrate to GTV-only")
    print("=" * 64)

    sh = connect()
    raw_before = read_config_raw(sh)

    gtv_wallet = (raw_before.get("GTV_Wallet") or raw_before.get("P1_Wallet")
                  or GTV_WALLET_FALLBACK).strip()
    cycle_days = int(parse_float(raw_before.get("Cycle_Days", str(CYCLE_DAYS_DEFAULT)))
                     or CYCLE_DAYS_DEFAULT)

    migrate_config(sh, raw_before)
    migrate_distributions(sh)
    migrate_dashboard(sh, gtv_wallet, cycle_days)
    verify(sh)

    print("\n" + "=" * 64)
    print("Migration complete — distribution is now GTV-only.")
    print(f"Sheet: {SHEET_URL}")
    print("=" * 64)


if __name__ == "__main__":
    main()
