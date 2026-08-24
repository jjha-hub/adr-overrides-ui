"""ADR platinum overrides UI for Streamlit Community Cloud.

Talks only to ClickHouse Cloud via secrets. Supports override + precedence
workflows (hold / approve / reject) and an append-only History screen.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Optional

import clickhouse_connect
import pandas as pd
import streamlit as st

TABLE = "adr.adr_platinum"
OVERRIDES = "adr.manual_adr_overrides"
CONFIG = "adr.adr_platinum_config"
HISTORY = "adr.adr_ui_history"
PREC_REQ = "adr.adr_precedence_requests"

PRECEDENCE_KEY = "custodian_precedence"
PRECEDENCE_SCOPE_KEY = "custodian_precedence_scope"
DEFAULT_ORDER = ("BNY", "CITI", "JPM", "DB")
KNOWN = list(DEFAULT_ORDER)
HOLD_STATUSES = ("hold", "pending_approval", "draft")

ADR_PLATINUM_COLUMNS: list[str] = [
    "date",
    "dr_sym",
    "dr_cusip",
    "dr_sedol",
    "dr_isin",
    "dr_fx",
    "dr_mic",
    "ord_sym",
    "ord_cusip",
    "ord_sedol",
    "ord_isin",
    "ord_fx",
    "ord_mic",
    "ord_country",
    "name",
    "source",
    "effective_date",
    "dr_ratio",
    "dr_custodian",
    "dr_fx_close",
    "ord_fx_close",
    "dr_close",
    "ord_close",
    "create_closed",
    "cancel_closed",
    "closed_special",
    "next_open_date",
    "next_close_date",
    "prev_open_date",
    "prev_close_date",
    "dsf_fee",
    "dr_divamt",
    "dr_divfx",
    "dr_divfee",
    "dr_div_fx_close",
    "ord_divamt",
    "ord_divfx",
    "ord_divfee",
    "ord_div_fx_close",
    "dr_splitratio",
    "ord_splitratio",
    "dr_sharesout",
    "ord_sharesout",
    "dr_shareslimit",
    "manual_override_flag",
    "override_doc_url",
]

OVERRIDEABLE_FIELDS: tuple[str, ...] = tuple(
    sorted(
        {
            "dr_sym",
            "dr_cusip",
            "dr_sedol",
            "dr_isin",
            "ord_sym",
            "ord_cusip",
            "ord_sedol",
            "ord_isin",
            "ord_fx",
            "ord_mic",
            "ord_country",
            "name",
            "effective_date",
            "dr_ratio",
            "dr_custodian",
            "create_closed",
            "cancel_closed",
            "closed_special",
            "next_open_date",
            "next_close_date",
            "prev_open_date",
            "prev_close_date",
            "dsf_fee",
            "dr_divamt",
            "dr_divfx",
            "dr_divfee",
            "dr_div_fx_close",
            "ord_divamt",
            "ord_divfx",
            "ord_divfee",
            "ord_div_fx_close",
            "dr_splitratio",
            "ord_splitratio",
            "dr_sharesout",
            "ord_sharesout",
            "dr_shareslimit",
        }
    )
)

FIELD_HINTS: dict[str, str] = {
    "dr_ratio": "Float — DR:ORD ratio",
    "create_closed": "0 or 1",
    "cancel_closed": "0 or 1",
    "closed_special": "0 or 1",
    "effective_date": "YYYY-MM-DD",
    "next_open_date": "YYYY-MM-DD",
    "next_close_date": "YYYY-MM-DD",
    "prev_open_date": "YYYY-MM-DD",
    "prev_close_date": "YYYY-MM-DD",
    "dr_custodian": "BNY, CITI, JPM, or DB",
}

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

HISTORY_DDL = f"""
CREATE TABLE IF NOT EXISTS {HISTORY}
(
    event_id String,
    event_type String,
    entity_id String,
    action String,
    status String,
    summary String,
    detail String,
    actor String,
    event_at DateTime,
    updated_at DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (event_at, event_id)
"""

PREC_REQ_DDL = f"""
CREATE TABLE IF NOT EXISTS {PREC_REQ}
(
    request_id String,
    precedence_order String,
    field_scope String,
    status String,
    reason String,
    created_by String,
    created_at DateTime,
    decided_by Nullable(String),
    decided_at Nullable(DateTime),
    updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (request_id)
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
    """Cached ClickHouse Cloud client; ensure UI tables exist."""
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
    for ddl in (
        PLATINUM_DDL,
        OVERRIDES_DDL,
        CONFIG_DDL,
        HISTORY_DDL,
        PREC_REQ_DDL,
    ):
        client.command(ddl)
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


def platinum_select_list() -> str:
    """Comma-separated platinum column list for SELECT."""
    return ", ".join(ADR_PLATINUM_COLUMNS)


def now_utc() -> datetime:
    """UTC timestamp for ledger rows."""
    return datetime.utcnow()


def log_history(
    *,
    event_type: str,
    entity_id: str,
    action: str,
    status: str,
    summary: str,
    detail: dict[str, Any] | str,
    actor: str,
) -> None:
    """Append one UI history event (approve / hold / reject / save)."""
    detail_text = detail if isinstance(detail, str) else json.dumps(detail, default=str)
    ts = now_utc()
    get_client().insert_df(
        HISTORY,
        pd.DataFrame(
            [
                {
                    "event_id": f"hist-{uuid.uuid4().hex[:12]}",
                    "event_type": event_type,
                    "entity_id": entity_id,
                    "action": action,
                    "status": status,
                    "summary": summary,
                    "detail": detail_text,
                    "actor": actor or "ui",
                    "event_at": ts,
                    "updated_at": ts,
                }
            ]
        ),
    )


def load_precedence() -> tuple[str, ...]:
    """Load active (approved) custodian precedence from config."""
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


def load_precedence_scope() -> list[str]:
    """Load approved field scope for precedence (``*`` = all)."""
    df = query_df(
        f"""
        SELECT config_value FROM {CONFIG} FINAL
        WHERE config_key = '{PRECEDENCE_SCOPE_KEY}' LIMIT 1
        """
    )
    if df.empty:
        return ["*"]
    raw = str(df.iloc[0]["config_value"]).strip()
    if raw in {"*", "ALL", ""}:
        return ["*"]
    return [p for p in raw.split("|") if p]


def lookup_platinum_row(dr_sym: str, as_of: date) -> Optional[pd.Series]:
    """Return one platinum row for pre-filling the override form."""
    df = query_df(
        f"""
        SELECT {platinum_select_list()}
        FROM {TABLE}
        WHERE date = '{as_of.isoformat()}' AND dr_sym = '{escape(dr_sym)}'
        LIMIT 1
        """
    )
    if df.empty:
        return None
    return df.iloc[0]


def fetch_override(override_id: str) -> Optional[dict[str, Any]]:
    """Load one override row by id."""
    df = query_df(
        f"""
        SELECT * FROM {OVERRIDES} FINAL
        WHERE override_id = '{escape(override_id)}'
        LIMIT 1
        """
    )
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def save_override_row(row: dict[str, Any]) -> None:
    """Upsert one override ledger row."""
    get_client().insert_df(OVERRIDES, pd.DataFrame([row]))


def set_override_status(
    override_id: str,
    status: str,
    actor: str,
) -> None:
    """Hold / approve / reject an existing override and log history."""
    row = fetch_override(override_id)
    if row is None:
        st.error(f"Override `{override_id}` not found")
        return
    ts = now_utc()
    row["status"] = status
    row["updated_at"] = ts
    if status == "approved":
        row["approved_by"] = actor
        row["approved_at"] = ts
    else:
        row["approved_by"] = None
        row["approved_at"] = None
    save_override_row(row)
    log_history(
        event_type="override",
        entity_id=override_id,
        action=status,
        status=status,
        summary=(
            f"{status}: {row.get('dr_sym')} "
            f"{row.get('field_name')}={row.get('override_value')}"
        ),
        detail=row,
        actor=actor,
    )
    st.success(f"`{override_id}` → **{status}**")


def fetch_prec_request(request_id: str) -> Optional[dict[str, Any]]:
    """Load one precedence request."""
    df = query_df(
        f"""
        SELECT * FROM {PREC_REQ} FINAL
        WHERE request_id = '{escape(request_id)}'
        LIMIT 1
        """
    )
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def save_prec_request(row: dict[str, Any]) -> None:
    """Upsert one precedence request."""
    get_client().insert_df(PREC_REQ, pd.DataFrame([row]))


def apply_approved_precedence(order: str, field_scope: str, actor: str) -> None:
    """Write approved precedence (+ field scope) into live config for ETL."""
    ts = now_utc()
    get_client().insert_df(
        CONFIG,
        pd.DataFrame(
            [
                {
                    "config_key": PRECEDENCE_KEY,
                    "config_value": order,
                    "updated_by": actor or "ui",
                    "updated_at": ts,
                },
                {
                    "config_key": PRECEDENCE_SCOPE_KEY,
                    "config_value": field_scope,
                    "updated_by": actor or "ui",
                    "updated_at": ts,
                },
            ]
        ),
    )


def set_prec_status(request_id: str, status: str, actor: str) -> None:
    """Hold / approve / reject a precedence request and log history."""
    row = fetch_prec_request(request_id)
    if row is None:
        st.error(f"Precedence request `{request_id}` not found")
        return
    ts = now_utc()
    row["status"] = status
    row["updated_at"] = ts
    row["decided_by"] = actor
    row["decided_at"] = ts
    save_prec_request(row)
    if status == "approved":
        apply_approved_precedence(
            str(row["precedence_order"]),
            str(row["field_scope"]),
            actor,
        )
    log_history(
        event_type="precedence",
        entity_id=request_id,
        action=status,
        status=status,
        summary=(
            f"{status}: {row.get('precedence_order')} "
            f"on fields={row.get('field_scope')}"
        ),
        detail=row,
        actor=actor,
    )
    st.success(f"Precedence `{request_id}` → **{status}**")


def status_decision_dropdown(
    *,
    key_prefix: str,
    entity_label: str,
    on_hold,
    on_approve,
    on_reject,
    actions: tuple[str, ...] = ("Hold", "Approve", "Reject"),
) -> None:
    """Render a status dropdown + Apply for hold / approve / reject."""
    st.markdown(f"**Decide {entity_label}**")
    c1, c2 = st.columns([3, 1])
    with c1:
        choice = st.selectbox(
            "Action",
            list(actions),
            key=f"{key_prefix}_action",
            label_visibility="collapsed",
        )
    with c2:
        apply = st.button("Apply", key=f"{key_prefix}_apply", type="primary")
    if apply:
        selected = str(choice).strip().lower()
        if selected == "hold":
            on_hold()
        elif selected == "approve":
            on_approve()
        elif selected == "reject":
            on_reject()
        else:
            st.error(f"Unknown action: {choice}")
            return
        st.rerun()


def page_review() -> None:
    """Review platinum + override ledger with full column contract."""
    st.subheader("Review & Search")
    c1, c2, c3 = st.columns(3)
    with c1:
        start = st.date_input("Start date", value=date(2026, 8, 21))
    with c2:
        end = st.date_input("End date", value=date(2026, 8, 21))
    with c3:
        symbol = st.text_input("DR symbol", value="").strip().upper()

    only_ov = st.checkbox("Manual override only", value=False)
    sym = f"AND dr_sym = '{escape(symbol)}'" if symbol else ""
    flag = "AND manual_override_flag = 1" if only_ov else ""

    plat = query_df(
        f"""
        SELECT {platinum_select_list()}
        FROM {TABLE}
        WHERE date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
        {sym} {flag}
        ORDER BY date DESC, dr_sym
        LIMIT 500
        """
    )
    st.caption(
        f"Platinum rows: {len(plat)} · columns: {len(ADR_PLATINUM_COLUMNS)}"
    )
    st.dataframe(plat, use_container_width=True, height=420)

    st.markdown("### Override ledger")
    ov = query_df(
        f"""
        SELECT override_id, dr_sym, field_name, auto_value, override_value,
               status, effective_start, effective_end, evidence_url,
               created_by, approved_by, reason, created_at
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
    """Create overrides; decide with Hold / Approve / Reject."""
    st.subheader("Manual Override Form")
    st.caption(
        "Save creates an override on **hold**. Then Hold / Approve / Reject. "
        "Only **approved** overrides are applied by the next `adr_platinum` run."
    )

    with st.expander("Lookup current platinum row (optional)", expanded=False):
        lc1, lc2, lc3 = st.columns(3)
        with lc1:
            lookup_sym = st.text_input("DR symbol", key="lookup_sym").strip().upper()
        with lc2:
            lookup_date = st.date_input(
                "As-of date", value=date(2026, 8, 21), key="lookup_date"
            )
        with lc3:
            st.write("")
            st.write("")
            do_lookup = st.button("Load row into form")
        if do_lookup and lookup_sym:
            row = lookup_platinum_row(lookup_sym, lookup_date)
            if row is None:
                st.warning(f"No platinum row for {lookup_sym} on {lookup_date}")
            else:
                st.session_state["form_dr_sym"] = lookup_sym
                st.session_state["form_dr_cusip"] = row.get("dr_cusip") or ""
                st.session_state["form_dr_isin"] = row.get("dr_isin") or ""
                st.session_state["form_ord_sym"] = row.get("ord_sym") or ""
                st.session_state["form_ord_isin"] = row.get("ord_isin") or ""
                st.session_state["form_field"] = "dr_ratio"
                st.session_state["form_auto"] = str(row.get("dr_ratio") or "")
                st.success(f"Loaded {lookup_sym}")
                st.dataframe(
                    pd.DataFrame([row])[ADR_PLATINUM_COLUMNS],
                    use_container_width=True,
                )

    with st.form("override_form"):
        st.markdown("**Identifiers**")
        id1, id2, id3 = st.columns(3)
        with id1:
            dr_sym = st.text_input(
                "DR symbol *",
                value=st.session_state.get("form_dr_sym", ""),
            ).strip().upper()
            dr_cusip = (
                st.text_input(
                    "DR CUSIP",
                    value=st.session_state.get("form_dr_cusip", ""),
                ).strip().upper()
                or None
            )
            dr_isin = (
                st.text_input(
                    "DR ISIN",
                    value=st.session_state.get("form_dr_isin", ""),
                ).strip().upper()
                or None
            )
        with id2:
            ord_sym = (
                st.text_input(
                    "ORD symbol",
                    value=st.session_state.get("form_ord_sym", ""),
                ).strip().upper()
                or None
            )
            ord_isin = (
                st.text_input(
                    "ORD ISIN",
                    value=st.session_state.get("form_ord_isin", ""),
                ).strip().upper()
                or None
            )
        with id3:
            default_field = st.session_state.get("form_field", "dr_ratio")
            field_idx = (
                OVERRIDEABLE_FIELDS.index(default_field)
                if default_field in OVERRIDEABLE_FIELDS
                else OVERRIDEABLE_FIELDS.index("dr_ratio")
            )
            field_name = st.selectbox(
                "Field to override *",
                OVERRIDEABLE_FIELDS,
                index=field_idx,
            )
            hint = FIELD_HINTS.get(field_name, "")
            if hint:
                st.caption(hint)

        st.markdown("**Override**")
        ov1, ov2 = st.columns(2)
        with ov1:
            auto_value = (
                st.text_input(
                    "Auto value (pipeline today)",
                    value=st.session_state.get("form_auto", ""),
                )
                or None
            )
            override_value = st.text_input("Override value *")
        with ov2:
            reason = st.text_area("Reason *")
            evidence_url = st.text_input("Evidence URL (Confluence)") or None

        st.markdown("**Effective dates**")
        wf1, wf2 = st.columns(2)
        with wf1:
            effective_start = st.date_input("Effective start *", value=date.today())
            use_end = st.checkbox("Set effective end", value=False)
            effective_end = (
                st.date_input(
                    "Effective end", value=date.today(), disabled=not use_end
                )
                if use_end
                else None
            )
        with wf2:
            created_by = st.text_input("Created by *", value="")

        submitted = st.form_submit_button("Save override (starts on Hold)", type="primary")

    if submitted:
        if not dr_sym or not override_value or not reason or not created_by:
            st.error("DR symbol, override value, reason, and created by are required.")
        else:
            ts = now_utc()
            oid = f"ui-{uuid.uuid4().hex[:12]}"
            row = {
                "override_id": oid,
                "dr_sym": dr_sym,
                "dr_cusip": dr_cusip,
                "dr_isin": dr_isin,
                "ord_sym": ord_sym,
                "ord_isin": ord_isin,
                "field_name": field_name,
                "auto_value": auto_value,
                "override_value": override_value,
                "reason": reason,
                "evidence_url": evidence_url,
                "status": "hold",
                "effective_start": effective_start,
                "effective_end": effective_end if use_end else None,
                "created_by": created_by,
                "created_at": ts,
                "approved_by": None,
                "approved_at": None,
                "updated_at": ts,
            }
            try:
                save_override_row(row)
                log_history(
                    event_type="override",
                    entity_id=oid,
                    action="save",
                    status="hold",
                    summary=f"saved on hold: {dr_sym} {field_name}={override_value}",
                    detail=row,
                    actor=created_by,
                )
                st.session_state["last_override_id"] = oid
                st.session_state["last_override_actor"] = created_by
                st.success(
                    f"Saved `{oid}` on **hold**. Choose Hold / Approve / Reject below."
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Save failed: {exc}")

    last_oid = st.session_state.get("last_override_id")
    if last_oid:
        actor = st.session_state.get("last_override_actor") or "ui"
        st.info(f"Last saved override: `{last_oid}`")
        status_decision_dropdown(
            key_prefix=f"ov_{last_oid}",
            entity_label=f"override `{last_oid}`",
            on_hold=lambda: set_override_status(last_oid, "hold", actor),
            on_approve=lambda: set_override_status(last_oid, "approved", actor),
            on_reject=lambda: set_override_status(last_oid, "rejected", actor),
        )

    st.markdown("### Pending approvals (on hold)")
    pending = query_df(
        f"""
        SELECT override_id, dr_sym, field_name, auto_value, override_value,
               reason, evidence_url, created_by, created_at, status
        FROM {OVERRIDES} FINAL
        WHERE status IN ('hold', 'pending_approval', 'draft')
        ORDER BY created_at DESC
        LIMIT 100
        """
    )
    st.dataframe(pending, use_container_width=True)
    if not pending.empty:
        pick = st.selectbox(
            "Select pending override_id",
            pending["override_id"].tolist(),
            key="pending_override_pick",
        )
        actor2 = st.text_input("Actor", value="", key="pending_override_actor")
        status_decision_dropdown(
            key_prefix=f"pend_ov_{pick}",
            entity_label=f"override `{pick}`",
            on_hold=lambda: set_override_status(pick, "hold", actor2 or "ui"),
            on_approve=lambda: set_override_status(pick, "approved", actor2 or "ui"),
            on_reject=lambda: set_override_status(pick, "rejected", actor2 or "ui"),
        )

    st.markdown("### Re-open approved overrides (to undo)")
    st.caption(
        "Only **approved** overrides appear here. Reject one so the next "
        "`adr_platinum` run stops applying it (undo). Hold moves it back to Pending."
    )
    approved_ov = query_df(
        f"""
        SELECT override_id, dr_sym, field_name, override_value, status,
               created_by, updated_at
        FROM {OVERRIDES} FINAL
        WHERE status = 'approved'
        ORDER BY updated_at DESC
        LIMIT 200
        """
    )
    st.dataframe(approved_ov, use_container_width=True)
    if not approved_ov.empty:
        pick_any = st.selectbox(
            "Select approved override_id",
            approved_ov["override_id"].tolist(),
            key="reopen_override_pick",
        )
        actor3 = st.text_input("Actor", value="", key="reopen_override_actor")
        cur = fetch_override(pick_any)
        if cur:
            st.caption(
                f"Current status: **{cur.get('status')}** · "
                f"{cur.get('dr_sym')} · {cur.get('field_name')}="
                f"{cur.get('override_value')}"
            )
        status_decision_dropdown(
            key_prefix=f"reopen_ov_{pick_any}",
            entity_label=f"override `{pick_any}`",
            on_hold=lambda: set_override_status(pick_any, "hold", actor3 or "ui"),
            on_approve=lambda: set_override_status(
                pick_any, "approved", actor3 or "ui"
            ),
            on_reject=lambda: set_override_status(
                pick_any, "rejected", actor3 or "ui"
            ),
            actions=("Reject", "Hold", "Approve"),
        )
    else:
        st.info("No approved overrides to re-open.")


def page_precedence() -> None:
    """Propose custodian precedence for selected fields; hold/approve/reject."""
    st.subheader("Custodian Precedence")
    current = load_precedence()
    scope = load_precedence_scope()
    st.info(
        f"Active approved order: **{' > '.join(current)}** · "
        f"field scope: `{', '.join(scope)}`"
    )
    st.caption(
        "Saving creates a precedence **request on hold**. Approve to publish into "
        "`adr.adr_platinum_config` for the next ETL. Field scope is stored for "
        "UI/audit; pipeline currently applies the approved bank order globally "
        "to custodian-precedence fields until field-scoped ETL lands."
    )

    select_all = st.checkbox("Select all overridable fields", value=False)
    if select_all:
        selected_fields = list(OVERRIDEABLE_FIELDS)
        st.multiselect(
            "Fields this precedence applies to",
            list(OVERRIDEABLE_FIELDS),
            default=selected_fields,
            disabled=True,
            key="prec_fields_locked",
        )
    else:
        selected_fields = st.multiselect(
            "Fields this precedence applies to (checkbox multi-select)",
            list(OVERRIDEABLE_FIELDS),
            default=[],
            key="prec_fields",
        )

    if selected_fields or select_all:
        shown = list(OVERRIDEABLE_FIELDS) if select_all else selected_fields
        st.markdown("**Selected fields**")
        st.write(", ".join(f"`{f}`" for f in shown))

    cols = st.columns(4)
    picks: list[str] = []
    for i, label in enumerate(("1st", "2nd", "3rd", "4th")):
        with cols[i]:
            idx = KNOWN.index(current[i]) if current[i] in KNOWN else i
            picks.append(st.selectbox(label, KNOWN, index=idx, key=f"p{i}"))

    reason = st.text_area("Reason for precedence change", value="")
    created_by = st.text_input("Requested by", value="", key="prec_actor")

    if st.button("Save", type="primary"):
        if not selected_fields and not select_all:
            st.error("Select at least one field, or use Select all.")
        elif len(set(picks)) != 4:
            st.error("Each custodian must appear once")
        else:
            fields = list(OVERRIDEABLE_FIELDS) if select_all else selected_fields
            scope_val = (
                "*"
                if select_all or set(fields) == set(OVERRIDEABLE_FIELDS)
                else "|".join(fields)
            )
            order = "|".join(picks)
            rid = f"prec-{uuid.uuid4().hex[:12]}"
            ts = now_utc()
            row = {
                "request_id": rid,
                "precedence_order": order,
                "field_scope": scope_val,
                "status": "hold",
                "reason": reason or "precedence change",
                "created_by": created_by or "ui",
                "created_at": ts,
                "decided_by": None,
                "decided_at": None,
                "updated_at": ts,
            }
            save_prec_request(row)
            log_history(
                event_type="precedence",
                entity_id=rid,
                action="save",
                status="hold",
                summary=f"saved on hold: {order} scope={scope_val}",
                detail=row,
                actor=created_by or "ui",
            )
            st.session_state["last_prec_id"] = rid
            st.session_state["last_prec_actor"] = created_by or "ui"
            st.success(f"Saved precedence request `{rid}` on **hold**.")

    last_prec = st.session_state.get("last_prec_id")
    if last_prec:
        actor = st.session_state.get("last_prec_actor") or "ui"
        st.info(f"Last saved precedence request: `{last_prec}`")
        status_decision_dropdown(
            key_prefix=f"prec_{last_prec}",
            entity_label=f"precedence `{last_prec}`",
            on_hold=lambda: set_prec_status(last_prec, "hold", actor),
            on_approve=lambda: set_prec_status(last_prec, "approved", actor),
            on_reject=lambda: set_prec_status(last_prec, "rejected", actor),
        )

    st.markdown("### Pending approvals (on hold)")
    pending = query_df(
        f"""
        SELECT request_id, precedence_order, field_scope, status, reason,
               created_by, created_at
        FROM {PREC_REQ} FINAL
        WHERE status IN ('hold', 'pending_approval', 'draft')
        ORDER BY created_at DESC
        LIMIT 100
        """
    )
    st.dataframe(pending, use_container_width=True)
    if not pending.empty:
        pick = st.selectbox(
            "Select request_id",
            pending["request_id"].tolist(),
            key="pending_prec_pick",
        )
        actor2 = st.text_input("Actor", value="", key="pending_prec_actor")
        # Show fields for selected request
        req = fetch_prec_request(pick)
        if req:
            st.caption(
                f"Order: `{req.get('precedence_order')}` · "
                f"Fields: `{req.get('field_scope')}`"
            )
        status_decision_dropdown(
            key_prefix=f"pend_prec_{pick}",
            entity_label=f"precedence `{pick}`",
            on_hold=lambda: set_prec_status(pick, "hold", actor2 or "ui"),
            on_approve=lambda: set_prec_status(pick, "approved", actor2 or "ui"),
            on_reject=lambda: set_prec_status(pick, "rejected", actor2 or "ui"),
        )


def page_history() -> None:
    """Append-only history of override + precedence decisions."""
    st.subheader("History")
    st.caption(
        "Every save / hold / approve / reject for overrides and custodian "
        "precedence is logged here with date/time."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        event_type = st.selectbox(
            "Type",
            ["All", "override", "precedence"],
            index=0,
        )
    with c2:
        status = st.selectbox(
            "Status / action",
            ["All", "hold", "approved", "rejected", "save"],
            index=0,
        )
    with c3:
        limit = st.number_input("Limit", min_value=50, max_value=2000, value=200)

    clauses = []
    if event_type != "All":
        clauses.append(f"event_type = '{event_type}'")
    if status != "All":
        clauses.append(f"(action = '{status}' OR status = '{status}')")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    hist = query_df(
        f"""
        SELECT event_at, event_type, entity_id, action, status,
               summary, actor, detail
        FROM {HISTORY}
        {where}
        ORDER BY event_at DESC
        LIMIT {int(limit)}
        """
    )
    st.caption(f"Events: {len(hist)}")
    st.dataframe(hist, use_container_width=True, height=480)


def main() -> None:
    """App entrypoint."""
    st.set_page_config(page_title="ADR Manual Overrides", layout="wide")
    try:
        get_client()
        active = load_precedence()
        scope = load_precedence_scope()
    except Exception as exc:  # noqa: BLE001
        st.error(f"ClickHouse unavailable: {exc}")
        st.stop()
        return

    st.title("ADR Platinum Manual Overrides")
    st.caption(
        f"Connected to ClickHouse Cloud. Active precedence: "
        f"{' > '.join(active)} (scope: {', '.join(scope)})."
    )
    page = st.sidebar.radio(
        "Screen",
        [
            "Review & Search",
            "Manual Override Form",
            "Custodian Precedence",
            "History",
        ],
    )
    if page == "Review & Search":
        page_review()
    elif page == "Manual Override Form":
        page_override()
    elif page == "Custodian Precedence":
        page_precedence()
    else:
        page_history()


if __name__ == "__main__":
    main()
