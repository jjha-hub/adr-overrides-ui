"""Minimal ADR platinum overrides UI for Streamlit Community Cloud.

Talks only to ClickHouse Cloud via secrets. No Lupine monorepo required.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

import clickhouse_connect
import pandas as pd
import streamlit as st

TABLE = "adr.adr_platinum"
OVERRIDES = "adr.manual_adr_overrides"
CONFIG = "adr.adr_platinum_config"
PRECEDENCE_KEY = "custodian_precedence"
DEFAULT_ORDER = ("BNY", "CITI", "JPM", "DB")
KNOWN = list(DEFAULT_ORDER)

OVERRIDEABLE_FIELDS = sorted(
    {
        "dr_ratio",
        "dr_cusip",
        "dr_isin",
        "ord_sym",
        "ord_isin",
        "ord_fx",
        "name",
        "dr_custodian",
        "create_closed",
        "cancel_closed",
    }
)
STATUSES = [
    "draft",
    "pending_approval",
    "approved",
    "rejected",
    "revoked",
    "expired",
]

PLATINUM_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE}
(
    date Date,
    dr_sym String,
    dr_cusip Nullable(String),
    dr_sedol Nullable(String),
    dr_isin Nullable(String),
    dr_fx Nullable(String),
    dr_mic Nullable(String),
    ord_sym Nullable(String),
    ord_cusip Nullable(String),
    ord_sedol Nullable(String),
    ord_isin Nullable(String),
    ord_fx Nullable(String),
    ord_mic Nullable(String),
    ord_country Nullable(String),
    name Nullable(String),
    source Nullable(String),
    effective_date Nullable(Date),
    dr_ratio Nullable(Float64),
    dr_custodian Nullable(String),
    dr_fx_close Nullable(Float64),
    ord_fx_close Nullable(Float64),
    dr_close Nullable(Float64),
    ord_close Nullable(Float64),
    create_closed Int8,
    cancel_closed Int8,
    closed_special Int8,
    next_open_date Nullable(Date),
    next_close_date Nullable(Date),
    prev_open_date Nullable(Date),
    prev_close_date Nullable(Date),
    dsf_fee Nullable(Float64),
    dr_divamt Nullable(Float64),
    dr_divfx Nullable(String),
    dr_divfee Nullable(Float64),
    dr_div_fx_close Nullable(Float64),
    ord_divamt Nullable(Float64),
    ord_divfx Nullable(String),
    ord_divfee Nullable(Float64),
    ord_div_fx_close Nullable(Float64),
    dr_splitratio Nullable(Float64),
    ord_splitratio Nullable(Float64),
    dr_sharesout Nullable(Float64),
    ord_sharesout Nullable(Float64),
    dr_shareslimit Nullable(Float64),
    manual_override_flag Int8,
    override_doc_url Nullable(String),
    loaded_at DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (date, dr_sym)
"""

OVERRIDES_DDL = f"""
CREATE TABLE IF NOT EXISTS {OVERRIDES}
(
    override_id String,
    dr_sym String,
    dr_cusip Nullable(String),
    dr_isin Nullable(String),
    ord_sym Nullable(String),
    ord_isin Nullable(String),
    field_name String,
    auto_value Nullable(String),
    override_value String,
    reason String,
    evidence_url Nullable(String),
    status String,
    effective_start Date,
    effective_end Nullable(Date),
    created_by String,
    created_at DateTime,
    approved_by Nullable(String),
    approved_at Nullable(DateTime),
    updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (override_id)
"""

CONFIG_DDL = f"""
CREATE TABLE IF NOT EXISTS {CONFIG}
(
    config_key String,
    config_value String,
    updated_by String,
    updated_at DateTime
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (config_key)
"""


def _secrets_ch() -> dict[str, Any]:
    """Read ``[clickhouse]`` from Streamlit secrets."""
    try:
        block = st.secrets["clickhouse"]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Missing Streamlit secrets [clickhouse]. "
            "Add host/user/password in App → Settings → Secrets."
        ) from exc
    return dict(block)


@st.cache_resource
def get_client():
    """Cached ClickHouse Cloud client."""
    ch = _secrets_ch()
    client = clickhouse_connect.get_client(
        host=str(ch.get("host", "so3us9c9hq.us-east-1.aws.clickhouse.cloud")),
        port=int(ch.get("port", 8443)),
        username=str(ch.get("user", "default")),
        password=str(ch.get("password", "")),
        secure=True,
        connect_timeout=60,
        send_receive_timeout=300,
    )
    client.command("CREATE DATABASE IF NOT EXISTS adr")
    client.command(PLATINUM_DDL)
    client.command(OVERRIDES_DDL)
    client.command(CONFIG_DDL)
    return client


def query_df(sql: str) -> pd.DataFrame:
    """Run a SELECT; show warning and return empty on failure."""
    try:
        return get_client().query_df(sql)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Query failed: {exc}")
        return pd.DataFrame()


def escape(value: str) -> str:
    """Escape SQL string literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def load_precedence() -> tuple[str, ...]:
    """Load custodian precedence from config table."""
    df = query_df(
        f"""
        SELECT config_value FROM {CONFIG} FINAL
        WHERE config_key = '{PRECEDENCE_KEY}' LIMIT 1
        """
    )
    if df.empty:
        return DEFAULT_ORDER
    parts = [
        p.strip().upper()
        for p in str(df.iloc[0]["config_value"]).replace(",", "|").split("|")
        if p.strip()
    ]
    if sorted(parts) != sorted(KNOWN):
        return DEFAULT_ORDER
    return tuple(parts)


def page_review() -> None:
    """Review platinum + override ledger."""
    c1, c2, c3 = st.columns(3)
    with c1:
        start = st.date_input("Start date", value=date.today())
    with c2:
        end = st.date_input("End date", value=date.today())
    with c3:
        symbol = st.text_input("DR symbol", value="").strip().upper()

    only_ov = st.checkbox("Manual override only", value=False)
    sym = f"AND dr_sym = '{escape(symbol)}'" if symbol else ""
    flag = "AND manual_override_flag = 1" if only_ov else ""

    plat = query_df(
        f"""
        SELECT date, dr_sym, ord_sym, dr_ratio, dr_custodian, source,
               create_closed, cancel_closed, manual_override_flag, override_doc_url
        FROM {TABLE}
        WHERE date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
        {sym} {flag}
        ORDER BY date DESC, dr_sym
        LIMIT 500
        """
    )
    st.caption(f"Platinum rows: {len(plat)}")
    st.dataframe(plat, use_container_width=True)

    st.markdown("### Override ledger")
    ov = query_df(
        f"""
        SELECT override_id, dr_sym, field_name, auto_value, override_value,
               status, effective_start, effective_end, evidence_url,
               created_by, approved_by, reason
        FROM {OVERRIDES} FINAL
        WHERE effective_start <= '{end.isoformat()}'
          AND (effective_end IS NULL OR effective_end >= '{start.isoformat()}')
        {sym}
        ORDER BY created_at DESC
        LIMIT 500
        """
    )
    st.dataframe(ov, use_container_width=True)


def page_override() -> None:
    """Create / approve field overrides."""
    st.subheader("Manual Override Form")
    dr_sym = st.text_input("DR symbol", value="").strip().upper()
    field_name = st.selectbox("Field", OVERRIDEABLE_FIELDS)
    override_value = st.text_input("Override value")
    reason = st.text_area("Reason")
    evidence_url = st.text_input("Evidence URL (Confluence)")
    status = st.selectbox("Status", STATUSES, index=2)
    effective_start = st.date_input("Effective start", value=date.today())
    use_end = st.checkbox("Set effective end", value=False)
    effective_end = st.date_input("Effective end", value=date.today()) if use_end else None
    created_by = st.text_input("Created by", value="adam")
    approved_by = st.text_input("Approved by", value="adam")

    if st.button("Save override", type="primary"):
        if not dr_sym or not override_value or not reason:
            st.error("dr_sym, override_value, and reason are required")
            return
        now = datetime.utcnow()
        row = {
            "override_id": f"ui-{uuid.uuid4().hex[:12]}",
            "dr_sym": dr_sym,
            "dr_cusip": None,
            "dr_isin": None,
            "ord_sym": None,
            "ord_isin": None,
            "field_name": field_name,
            "auto_value": None,
            "override_value": override_value,
            "reason": reason,
            "evidence_url": evidence_url or None,
            "status": status,
            "effective_start": effective_start,
            "effective_end": effective_end if use_end else None,
            "created_by": created_by,
            "created_at": now,
            "approved_by": approved_by if status == "approved" else None,
            "approved_at": now if status == "approved" else None,
            "updated_at": now,
        }
        try:
            get_client().insert_df(OVERRIDES, pd.DataFrame([row]))
            st.success(
                f"Saved `{row['override_id']}`. "
                "Re-run adr_platinum (or wait for 18:00 ET) to publish."
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Save failed: {exc}")

    pending = query_df(
        f"""
        SELECT override_id, dr_sym, field_name, override_value, reason, created_by
        FROM {OVERRIDES} FINAL
        WHERE status IN ('draft', 'pending_approval')
        ORDER BY created_at DESC LIMIT 100
        """
    )
    st.markdown("### Pending")
    st.dataframe(pending, use_container_width=True)
    if not pending.empty:
        pick = st.selectbox("Approve override_id", pending["override_id"].tolist())
        approver = st.text_input("Approver", value="adam", key="approver2")
        if st.button("Approve selected"):
            full = query_df(
                f"SELECT * FROM {OVERRIDES} FINAL "
                f"WHERE override_id = '{escape(pick)}' LIMIT 1"
            )
            if full.empty:
                st.error("Not found")
            else:
                row = full.iloc[0].to_dict()
                row["status"] = "approved"
                row["approved_by"] = approver
                row["approved_at"] = datetime.utcnow()
                row["updated_at"] = datetime.utcnow()
                get_client().insert_df(OVERRIDES, pd.DataFrame([row]))
                st.success(f"Approved {pick}")
                st.rerun()


def page_precedence() -> None:
    """Edit custodian precedence for the pipeline."""
    st.subheader("Custodian Precedence")
    current = load_precedence()
    st.info(f"Active: {' > '.join(current)}")
    cols = st.columns(4)
    picks: list[str] = []
    for i, label in enumerate(("1st", "2nd", "3rd", "4th")):
        with cols[i]:
            idx = KNOWN.index(current[i]) if current[i] in KNOWN else i
            picks.append(st.selectbox(label, KNOWN, index=idx, key=f"p{i}"))
    updated_by = st.text_input("Saved by", value="adam")
    if st.button("Save precedence", type="primary"):
        if len(set(picks)) != 4:
            st.error("Each custodian must appear once")
            return
        get_client().insert_df(
            CONFIG,
            pd.DataFrame(
                [
                    {
                        "config_key": PRECEDENCE_KEY,
                        "config_value": "|".join(picks),
                        "updated_by": updated_by or "ui",
                        "updated_at": datetime.utcnow(),
                    }
                ]
            ),
        )
        st.success(f"Saved {' > '.join(picks)}. Re-run adr_platinum to apply.")
        st.rerun()


def main() -> None:
    """App entrypoint."""
    st.set_page_config(page_title="ADR Manual Overrides", layout="wide")
    try:
        client = get_client()
        host = client.server_host if hasattr(client, "server_host") else "clickhouse"
        active = load_precedence()
    except Exception as exc:  # noqa: BLE001
        st.error(f"ClickHouse unavailable: {exc}")
        st.stop()
        return

    st.title("ADR Platinum Manual Overrides")
    st.caption(
        f"Connected for edits on Cloud platinum / overrides. "
        f"Precedence: {' > '.join(active)}."
    )
    page = st.sidebar.radio(
        "Screen",
        ["Review & Search", "Manual Override Form", "Custodian Precedence"],
    )
    if page == "Review & Search":
        page_review()
    elif page == "Manual Override Form":
        page_override()
    else:
        page_precedence()


if __name__ == "__main__":
    main()
