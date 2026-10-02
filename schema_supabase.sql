-- =============================================================================
-- schema_supabase.sql — Schema for Nifty 50 Event Intelligence on Supabase
-- =============================================================================

-- 1. Pre-Market Night Predictions Table
CREATE TABLE IF NOT EXISTS public.night_predictions (
    id BIGSERIAL PRIMARY KEY,
    prediction_id TEXT UNIQUE,
    model_version TEXT DEFAULT '2.1.0',
    data_cutoff TIMESTAMPTZ,
    snapshot_hash TEXT,
    symbol TEXT NOT NULL,
    short_name TEXT,
    sector TEXT,
    target_trade_date DATE NOT NULL,
    base_price NUMERIC NOT NULL,
    predicted_1d_target NUMERIC NOT NULL,
    predicted_1d_pct NUMERIC NOT NULL,
    direction TEXT NOT NULL,
    action TEXT NOT NULL,
    conviction INTEGER NOT NULL,
    active_catalysts_json JSONB,
    factors_json JSONB,
    provenance_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, target_trade_date)
);

-- 2. Post-Market Daily Audits Table
CREATE TABLE IF NOT EXISTS public.daily_audits (
    id BIGSERIAL PRIMARY KEY,
    night_pred_id BIGINT,
    trade_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    short_name TEXT,
    sector TEXT,
    base_price NUMERIC NOT NULL,
    predicted_target NUMERIC NOT NULL,
    predicted_change_pct NUMERIC NOT NULL,
    predicted_direction TEXT NOT NULL,
    actual_open NUMERIC,
    actual_high NUMERIC,
    actual_low NUMERIC,
    actual_close NUMERIC NOT NULL,
    actual_change_pct NUMERIC NOT NULL,
    actual_direction TEXT NOT NULL,
    direction_correct INTEGER NOT NULL,
    hit_target_range INTEGER NOT NULL,
    abs_error_pct NUMERIC NOT NULL,
    simulated_pnl NUMERIC NOT NULL,
    attribution_category TEXT NOT NULL,
    diagnostic_explanation TEXT,
    refactoring_suggestion TEXT,
    factors_evaluated_json JSONB,
    audited_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, trade_date)
);

-- 3. Automated Job Execution Logs Table
CREATE TABLE IF NOT EXISTS public.job_execution_logs (
    id BIGSERIAL PRIMARY KEY,
    job_type TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    target_date DATE NOT NULL,
    records_stored INTEGER NOT NULL,
    log_summary TEXT
);

-- 4. Multi-Horizon Predictions Table
CREATE TABLE IF NOT EXISTS public.predictions (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    symbol TEXT NOT NULL,
    short_name TEXT,
    sector TEXT,
    base_price NUMERIC NOT NULL,
    sentiment_score NUMERIC NOT NULL,
    sentiment_label TEXT,
    sentiment_polarity TEXT,
    catalyst_score NUMERIC,
    target_1d NUMERIC NOT NULL,
    target_3d NUMERIC NOT NULL,
    target_7d NUMERIC NOT NULL,
    expected_1d_pct NUMERIC NOT NULL,
    expected_3d_pct NUMERIC NOT NULL,
    expected_7d_pct NUMERIC NOT NULL,
    action TEXT NOT NULL,
    conviction INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, date)
);

-- 5. Historical Evaluations Table
CREATE TABLE IF NOT EXISTS public.evaluations (
    id BIGSERIAL PRIMARY KEY,
    prediction_id BIGINT,
    eval_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    actual_price NUMERIC NOT NULL,
    predicted_target NUMERIC NOT NULL,
    predicted_change_pct NUMERIC NOT NULL,
    actual_change_pct NUMERIC NOT NULL,
    direction_correct INTEGER NOT NULL,
    hit_target_range INTEGER NOT NULL,
    simulated_pnl NUMERIC NOT NULL,
    evaluated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. News Archive Table
CREATE TABLE IF NOT EXISTS public.news_archive (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT,
    pub_date TIMESTAMPTZ,
    symbol TEXT,
    score NUMERIC,
    polarity TEXT,
    url TEXT UNIQUE,
    scraped_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable Row Level Security (RLS) & Grant Public Read Permissions
ALTER TABLE public.night_predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_audits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_execution_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.news_archive ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public Read Night Predictions" ON public.night_predictions FOR SELECT USING (true);
CREATE POLICY "Public Read Daily Audits" ON public.daily_audits FOR SELECT USING (true);
CREATE POLICY "Public Read Job Logs" ON public.job_execution_logs FOR SELECT USING (true);
CREATE POLICY "Public Read Predictions" ON public.predictions FOR SELECT USING (true);
CREATE POLICY "Public Read Evaluations" ON public.evaluations FOR SELECT USING (true);
CREATE POLICY "Public Read News" ON public.news_archive FOR SELECT USING (true);

-- Allow Service Role Full Access
CREATE POLICY "Service Role All Night Predictions" ON public.night_predictions FOR ALL USING (true);
CREATE POLICY "Service Role All Daily Audits" ON public.daily_audits FOR ALL USING (true);
CREATE POLICY "Service Role All Job Logs" ON public.job_execution_logs FOR ALL USING (true);
CREATE POLICY "Service Role All Predictions" ON public.predictions FOR ALL USING (true);
CREATE POLICY "Service Role All Evaluations" ON public.evaluations FOR ALL USING (true);
CREATE POLICY "Service Role All News" ON public.news_archive FOR ALL USING (true);

-- 7. Daily Automated Trade Reports Table (V3.7 Reporting Pipeline)
CREATE TABLE IF NOT EXISTS public.daily_trade_reports (
    id BIGSERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    job_run_id TEXT,
    status TEXT NOT NULL,

    total_trades INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    losing_trades INTEGER NOT NULL DEFAULT 0,
    win_rate NUMERIC NOT NULL DEFAULT 0.0,

    gross_pnl NUMERIC NOT NULL DEFAULT 0.0,
    charges NUMERIC NOT NULL DEFAULT 0.0,
    net_pnl NUMERIC NOT NULL DEFAULT 0.0,

    realized_pnl NUMERIC NOT NULL DEFAULT 0.0,
    unrealized_pnl NUMERIC NOT NULL DEFAULT 0.0,

    best_trade JSONB,
    worst_trade JSONB,

    best_strategy TEXT,
    best_agent TEXT,

    prediction_direction TEXT,
    actual_direction TEXT,
    prediction_correct BOOLEAN,

    ai_provider TEXT,
    ai_model TEXT,
    ai_request_id TEXT,
    ai_latency_ms INTEGER,
    ai_tokens JSONB,
    ai_status TEXT,

    voice_provider TEXT,
    voice_status TEXT,
    voice_duration_ms INTEGER,

    video_provider TEXT,
    video_render_id TEXT,
    video_status TEXT,
    video_url TEXT,

    youtube_video_id TEXT,
    youtube_url TEXT,
    youtube_status TEXT,
    youtube_upload_status TEXT,
    youtube_thumbnail_status TEXT,

    thumbnail_url TEXT,
    thumbnail_render_id TEXT,
    thumbnail_status TEXT,
    thumbnail_template TEXT,
    thumbnail_headline TEXT,
    video_duration_seconds NUMERIC,
    content_theme TEXT,
    content_score NUMERIC,
    content_data_hash TEXT,
    content_generated_at TIMESTAMPTZ,

    data_mode TEXT NOT NULL DEFAULT 'PAPER_RECONCILED',
    email_status TEXT,
    email_sent_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    provenance_hash TEXT NOT NULL,
    report_payload_json JSONB,
    UNIQUE(report_date)
);

ALTER TABLE public.daily_trade_reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public Read Daily Trade Reports" ON public.daily_trade_reports FOR SELECT USING (true);
CREATE POLICY "Service Role All Daily Trade Reports" ON public.daily_trade_reports FOR ALL USING (true);

-- 8. Authoritative Scheduler Invocations & Heartbeat Table (P0 Scheduler Architecture)
CREATE TABLE IF NOT EXISTS public.scheduler_invocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invocation_id TEXT UNIQUE NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NULL,
    status TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment IN ('PAPER', 'SHADOW', 'MICRO_LIVE', 'CONTROLLED_LIVE', 'PRODUCTION_LIVE')),
    git_commit TEXT NULL,
    config_hash TEXT NULL,
    workflow_run_id TEXT NULL,
    job_run_id TEXT NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- RLS: Operational telemetry is protected.
-- Direct anonymous public reads are disallowed.
-- The Netlify health_scheduler serverless function projects the controlled public view.
ALTER TABLE public.scheduler_invocations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Public Read Scheduler Invocations" ON public.scheduler_invocations;
CREATE POLICY "Service Role All Scheduler Invocations" ON public.scheduler_invocations FOR ALL USING (true);

-- =============================================================================
-- V4.2.1 CONTINUOUS EVENT SENTINEL TABLES
-- =============================================================================

-- 9. Dedicated Sentinel Invocations Table
CREATE TABLE IF NOT EXISTS public.sentinel_invocations (
    id BIGSERIAL PRIMARY KEY,
    scheduled_invocation_id TEXT NOT NULL,
    sentinel_invocation_id TEXT UNIQUE NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    sources_checked INTEGER NOT NULL DEFAULT 8,
    events_seen INTEGER NOT NULL DEFAULT 0,
    events_new INTEGER NOT NULL DEFAULT 0,
    events_duplicate INTEGER NOT NULL DEFAULT 0,
    events_material INTEGER NOT NULL DEFAULT 0,
    events_triggered INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'SUCCESS',
    error TEXT NULL,
    lineage_json JSONB NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.sentinel_invocations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service Role All Sentinel Invocations" ON public.sentinel_invocations FOR ALL USING (true);
CREATE POLICY "Public Read Sentinel Invocations" ON public.sentinel_invocations FOR SELECT USING (true);

-- 10. Continuous Event Ledger
CREATE TABLE IF NOT EXISTS public.event_ledger (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    raw_payload_hash TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    importance_score NUMERIC DEFAULT 0,
    india_relevance TEXT DEFAULT 'LOW',
    novelty TEXT DEFAULT 'HIGH',
    market_reaction_score NUMERIC DEFAULT 0,
    thesis_relation TEXT DEFAULT 'NEUTRAL',
    verdict TEXT NOT NULL DEFAULT 'STORE_ONLY',
    associated_thesis_id TEXT,
    event_data_json JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.event_ledger ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service Role All Event Ledger" ON public.event_ledger FOR ALL USING (true);
CREATE POLICY "Public Read Event Ledger" ON public.event_ledger FOR SELECT USING (true);

-- 11. Active NIFTY Market Thesis
CREATE TABLE IF NOT EXISTS public.active_theses (
    id BIGSERIAL PRIMARY KEY,
    thesis_id TEXT UNIQUE NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    bias TEXT NOT NULL,
    confidence NUMERIC NOT NULL,
    expected_move NUMERIC NOT NULL,
    valid_until TIMESTAMPTZ NOT NULL,
    invalidation_conditions_json JSONB,
    last_material_event_id TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    volatility_regime TEXT DEFAULT 'NORMAL',
    risk_multiplier NUMERIC DEFAULT 1.0,
    stop_multiplier NUMERIC DEFAULT 1.0,
    updated_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.active_theses ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service Role All Active Theses" ON public.active_theses FOR ALL USING (true);
CREATE POLICY "Public Read Active Theses" ON public.active_theses FOR SELECT USING (true);

-- 12. Deterministic Thesis Revisions
CREATE TABLE IF NOT EXISTS public.thesis_revisions (
    id BIGSERIAL PRIMARY KEY,
    thesis_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    parent_thesis_id TEXT,
    trigger_event_id TEXT NOT NULL,
    adjustment_reason TEXT NOT NULL,
    confidence_delta NUMERIC NOT NULL,
    expected_move_delta NUMERIC NOT NULL,
    volatility_regime TEXT NOT NULL,
    risk_multiplier NUMERIC NOT NULL,
    stop_multiplier NUMERIC NOT NULL,
    before_state_json JSONB NOT NULL,
    after_state_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(thesis_id, revision)
);
ALTER TABLE public.thesis_revisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service Role All Thesis Revisions" ON public.thesis_revisions FOR ALL USING (true);
CREATE POLICY "Public Read Thesis Revisions" ON public.thesis_revisions FOR SELECT USING (true);

-- 13. Economic Calendar Events
CREATE TABLE IF NOT EXISTS public.economic_calendar_events (
    id BIGSERIAL PRIMARY KEY,
    event_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    scheduled_time TIMESTAMPTZ NOT NULL,
    consensus_expectation TEXT,
    prior_value TEXT,
    actual_value TEXT,
    surprise_delta TEXT,
    current_stage TEXT NOT NULL,
    stage_updated_at TIMESTAMPTZ DEFAULT now(),
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.economic_calendar_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service Role All Calendar Events" ON public.economic_calendar_events FOR ALL USING (true);
CREATE POLICY "Public Read Calendar Events" ON public.economic_calendar_events FOR SELECT USING (true);

-- 14. Event Coverage Metrics (Decoupled Denominators)
CREATE TABLE IF NOT EXISTS public.event_coverage_metrics (
    id BIGSERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    scheduled_expected INTEGER NOT NULL DEFAULT 0,
    scheduled_detected INTEGER NOT NULL DEFAULT 0,
    scheduled_coverage_pct NUMERIC NOT NULL DEFAULT 100.0,
    source_available INTEGER NOT NULL DEFAULT 0,
    source_processed INTEGER NOT NULL DEFAULT 0,
    source_coverage_pct NUMERIC NOT NULL DEFAULT 100.0,
    material_detected INTEGER NOT NULL DEFAULT 0,
    material_processed INTEGER NOT NULL DEFAULT 0,
    material_processing_pct NUMERIC NOT NULL DEFAULT 100.0,
    recorded_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.event_coverage_metrics ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service Role All Coverage Metrics" ON public.event_coverage_metrics FOR ALL USING (true);
CREATE POLICY "Public Read Coverage Metrics" ON public.event_coverage_metrics FOR SELECT USING (true);

-- =============================================================================
-- V4.3 TRADE PERSISTENCE TABLES (Paper Arena Dual-Write)
-- =============================================================================

-- 15. Agent Decisions
CREATE TABLE IF NOT EXISTS public.agent_decisions (
    id BIGSERIAL PRIMARY KEY,
    decision_id TEXT UNIQUE NOT NULL,
    market_date TEXT NOT NULL,
    snapshot_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL DEFAULT '1.0',
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    instrument_type TEXT NOT NULL DEFAULT 'EQUITY',
    confidence NUMERIC NOT NULL DEFAULT 50.0,
    proposed_quantity INTEGER NOT NULL DEFAULT 0,
    proposed_price NUMERIC NOT NULL DEFAULT 0.0,
    stop_loss NUMERIC,
    target NUMERIC,
    planned_risk NUMERIC NOT NULL DEFAULT 0.0,
    risk_approved INTEGER NOT NULL DEFAULT 1,
    rejection_reasons_json TEXT,
    decision_reason TEXT,
    diagnostic_type TEXT DEFAULT 'AI_DECISION',
    agent_ai_status TEXT DEFAULT 'AVAILABLE',
    ai_thesis TEXT DEFAULT 'GENERATED',
    deterministic_screen TEXT DEFAULT 'PASSED',
    reporting_status TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_decisions_date ON public.agent_decisions(market_date);
CREATE INDEX IF NOT EXISTS idx_decisions_agent ON public.agent_decisions(agent_id);
ALTER TABLE public.agent_decisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public Read Agent Decisions" ON public.agent_decisions FOR SELECT USING (true);
CREATE POLICY "Service Role All Agent Decisions" ON public.agent_decisions FOR ALL USING (true);

-- 16. Paper Orders
CREATE TABLE IF NOT EXISTS public.paper_orders (
    order_id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL DEFAULT 'DEFAULT',
    agent_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    order_type TEXT NOT NULL DEFAULT 'MARKET',
    requested_price NUMERIC NOT NULL DEFAULT 0.0,
    limit_price NUMERIC,
    stop_price NUMERIC,
    submitted_at TIMESTAMPTZ,
    fill_price NUMERIC,
    fill_quantity INTEGER DEFAULT 0,
    slippage NUMERIC DEFAULT 0.0,
    estimated_charges NUMERIC DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'PENDING',
    rejection_reason TEXT,
    strategy_id TEXT,
    trade_proposal_id TEXT,
    execution_mode TEXT NOT NULL DEFAULT 'BROKER_SANDBOX',
    broker_adapter TEXT DEFAULT 'UPSTOX SANDBOX',
    broker_order_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_orders_agent ON public.paper_orders(agent_id);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON public.paper_orders(symbol);
ALTER TABLE public.paper_orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public Read Paper Orders" ON public.paper_orders FOR SELECT USING (true);
CREATE POLICY "Service Role All Paper Orders" ON public.paper_orders FOR ALL USING (true);

-- 17. Agent Trades
CREATE TABLE IF NOT EXISTS public.agent_trades (
    id BIGSERIAL PRIMARY KEY,
    trade_id TEXT UNIQUE NOT NULL,
    market_date TEXT NOT NULL,
    cycle_id TEXT,
    snapshot_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL DEFAULT '1.0',
    symbol TEXT NOT NULL,
    instrument_type TEXT NOT NULL DEFAULT 'EQUITY',
    action TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price NUMERIC NOT NULL,
    stop_loss NUMERIC DEFAULT 0.0,
    target NUMERIC DEFAULT 0.0,
    transaction_costs NUMERIC NOT NULL DEFAULT 0.0,
    net_amount NUMERIC NOT NULL DEFAULT 0.0,
    risk_amount NUMERIC NOT NULL DEFAULT 0.0,
    confidence NUMERIC NOT NULL DEFAULT 50.0,
    decision_reason TEXT,
    hedge_decision TEXT DEFAULT 'NO',
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trades_date ON public.agent_trades(market_date);
CREATE INDEX IF NOT EXISTS idx_trades_agent ON public.agent_trades(agent_id);
ALTER TABLE public.agent_trades ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public Read Agent Trades" ON public.agent_trades FOR SELECT USING (true);
CREATE POLICY "Service Role All Agent Trades" ON public.agent_trades FOR ALL USING (true);

-- 18. Agent Positions
CREATE TABLE IF NOT EXISTS public.agent_positions (
    id BIGSERIAL PRIMARY KEY,
    position_id TEXT UNIQUE NOT NULL,
    agent_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL DEFAULT '1.0',
    symbol TEXT NOT NULL,
    short_name TEXT,
    sector TEXT,
    instrument_type TEXT NOT NULL DEFAULT 'EQUITY',
    direction TEXT NOT NULL DEFAULT 'LONG',
    quantity INTEGER NOT NULL,
    entry_price NUMERIC NOT NULL,
    current_price NUMERIC NOT NULL DEFAULT 0.0,
    cost_basis NUMERIC NOT NULL DEFAULT 0.0,
    market_value NUMERIC NOT NULL DEFAULT 0.0,
    stop_loss NUMERIC,
    target NUMERIC,
    unrealized_pnl NUMERIC NOT NULL DEFAULT 0.0,
    unrealized_pnl_pct NUMERIC NOT NULL DEFAULT 0.0,
    is_hedged INTEGER DEFAULT 0,
    hedge_details_json TEXT,
    contract_expiry TEXT,
    option_strike NUMERIC,
    option_type TEXT,
    status TEXT DEFAULT 'OPEN',
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    exit_price NUMERIC,
    realized_pnl NUMERIC,
    exit_reason TEXT,
    brokerage_costs NUMERIC,
    position_side TEXT DEFAULT 'LONG',
    order_intent TEXT DEFAULT 'OPEN',
    underlying_symbol TEXT,
    option_symbol TEXT,
    multiplier INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_positions_agent ON public.agent_positions(agent_id);
CREATE INDEX IF NOT EXISTS idx_positions_status ON public.agent_positions(status);
ALTER TABLE public.agent_positions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public Read Agent Positions" ON public.agent_positions FOR SELECT USING (true);
CREATE POLICY "Service Role All Agent Positions" ON public.agent_positions FOR ALL USING (true);
