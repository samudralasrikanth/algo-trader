-- =============================================================================
-- create_trade_tables.sql — Missing Tables for Cloud Trade Persistence
-- Run this in Supabase Dashboard → SQL Editor → New Query → Run
-- =============================================================================

-- 1. Agent Decisions (records each agent's BUY/SELL/HOLD signal per cycle)
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
DROP POLICY IF EXISTS "Public Read Agent Decisions" ON public.agent_decisions;
CREATE POLICY "Public Read Agent Decisions" ON public.agent_decisions FOR SELECT USING (true);
DROP POLICY IF EXISTS "Service Role All Agent Decisions" ON public.agent_decisions;
CREATE POLICY "Service Role All Agent Decisions" ON public.agent_decisions FOR ALL USING (true);

-- 2. Paper Orders (tracks order execution lifecycle)
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
DROP POLICY IF EXISTS "Public Read Paper Orders" ON public.paper_orders;
CREATE POLICY "Public Read Paper Orders" ON public.paper_orders FOR SELECT USING (true);
DROP POLICY IF EXISTS "Service Role All Paper Orders" ON public.paper_orders;
CREATE POLICY "Service Role All Paper Orders" ON public.paper_orders FOR ALL USING (true);

-- 3. Agent Trades (records confirmed trade executions)
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
DROP POLICY IF EXISTS "Public Read Agent Trades" ON public.agent_trades;
CREATE POLICY "Public Read Agent Trades" ON public.agent_trades FOR SELECT USING (true);
DROP POLICY IF EXISTS "Service Role All Agent Trades" ON public.agent_trades;
CREATE POLICY "Service Role All Agent Trades" ON public.agent_trades FOR ALL USING (true);

-- 4. Agent Positions (current portfolio state)
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
DROP POLICY IF EXISTS "Public Read Agent Positions" ON public.agent_positions;
CREATE POLICY "Public Read Agent Positions" ON public.agent_positions FOR SELECT USING (true);
DROP POLICY IF EXISTS "Service Role All Agent Positions" ON public.agent_positions;
CREATE POLICY "Service Role All Agent Positions" ON public.agent_positions FOR ALL USING (true);
