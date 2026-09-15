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


