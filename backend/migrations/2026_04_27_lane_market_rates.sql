-- ============================================================================
-- Migration: lane_market_rates  (run on aivn_datalake_gold as `avnadmin`)
-- Date:     2026-04-27
-- Purpose:  Persist SONAR + 123LoadBoard monthly historical rates per lane so
--           the eSavings from Carriers report can show benchmark prices for any
--           past month without re-hitting the external APIs.
--
-- Lane key:  (origin_city, origin_state, dest_city, dest_state, equipment, year_month, source)
-- Source:    'sonar' | 'lb123'
-- Equipment: 'VAN' for v1 (UNILINK is overwhelmingly van/dry-van)
--
-- Cache rule (enforced in app code, not DB):
--   - Closed months → permanent cache, never refetch
--   - Current MTD month → soft-expire after 24h, refetch on demand
--
-- Required role: avnadmin (sa_dfrodriguez has SELECT only).
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.lane_market_rates (
    origin_city     varchar(80)  NOT NULL,
    origin_state    varchar(2)   NOT NULL,
    dest_city       varchar(80)  NOT NULL,
    dest_state      varchar(2)   NOT NULL,
    equipment       varchar(10)  NOT NULL DEFAULT 'VAN',
    year_month      char(7)      NOT NULL,          -- 'YYYY-MM'
    source          varchar(8)   NOT NULL,          -- 'sonar' | 'lb123'

    avg_rate        numeric(10,2),                  -- per-load $
    min_rate        numeric(10,2),
    max_rate        numeric(10,2),
    avg_rpm         numeric(8,4),
    min_rpm         numeric(8,4),
    max_rpm         numeric(8,4),
    loads_included  integer,
    mileage         integer,
    raw_payload     jsonb,                          -- whole API row for audit
    fetched_at      timestamptz  NOT NULL DEFAULT NOW(),

    CONSTRAINT lane_market_rates_pkey PRIMARY KEY
        (origin_city, origin_state, dest_city, dest_state, equipment, year_month, source),
    CONSTRAINT lane_market_rates_source_chk CHECK (source IN ('sonar', 'lb123'))
);

-- Help the per-month bulk lookup (the report queries one month at a time).
CREATE INDEX IF NOT EXISTS idx_lane_market_rates_month_source
    ON public.lane_market_rates (year_month, source);

-- Helps the pre-warm cron pick "what's stale?" for the current MTD month.
CREATE INDEX IF NOT EXISTS idx_lane_market_rates_fetched
    ON public.lane_market_rates (year_month, fetched_at);

COMMENT ON TABLE public.lane_market_rates IS
    'Monthly market-rate cache from SONAR (TRAC Statistics) and 123LoadBoard (Rate History). '
    'Populated lazily by /api/custom/carriers-savings/lane-rates and pre-warmed nightly at 5 AM CST.';
