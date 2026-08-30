-- =============================================================================
-- schema_supabase.sql — Schema for Nifty 50 Event Intelligence on Supabase
-- =============================================================================

-- 1. Pre-Market Night Predictions Table
CREATE TABLE IF NOT EXISTS public.night_predictions (
    id BIGSERIAL PRIMARY KEY,
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
