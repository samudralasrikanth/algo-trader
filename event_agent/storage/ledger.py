# =============================================================================
# event_agent/storage/ledger.py — SQLite Prediction & Performance Ledger
# =============================================================================

import sqlite3
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import yfinance as yf

from ..config import DB_PATH, ALLOCATION_PER_STOCK, HORIZONS


def get_connection() -> sqlite3.Connection:
    """Get SQLite database connection with row factory enabled and WAL mode."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    """Initialize database tables for predictions, evaluations, and news archive."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Predictions Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            short_name TEXT,
            sector TEXT,
            base_price REAL NOT NULL,
            direction TEXT NOT NULL,
            action TEXT NOT NULL,
            conviction REAL NOT NULL,
            stock_sentiment REAL,
            macro_sentiment REAL,
            news_count INTEGER,
            expected_1d_pct REAL,
            expected_3d_pct REAL,
            expected_7d_pct REAL,
            target_1d REAL,
            target_3d REAL,
            target_7d REAL,
            range_1d_low REAL,
            range_1d_high REAL,
            range_3d_low REAL,
            range_3d_high REAL,
            range_7d_low REAL,
            range_7d_high REAL,
            reasoning_json TEXT,
            status TEXT DEFAULT 'PENDING'
        )
        """)
        
        # 2. Evaluations Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            prediction_date TEXT NOT NULL,
            eval_date TEXT NOT NULL,
            horizon_days INTEGER NOT NULL,
            base_price REAL NOT NULL,
            predicted_target REAL NOT NULL,
            predicted_change_pct REAL NOT NULL,
            predicted_direction TEXT NOT NULL,
            actual_price REAL NOT NULL,
            actual_change_pct REAL NOT NULL,
            actual_direction TEXT NOT NULL,
            direction_correct INTEGER NOT NULL,
            hit_target_range INTEGER NOT NULL,
            abs_error_pct REAL NOT NULL,
            simulated_pnl REAL NOT NULL,
            FOREIGN KEY (prediction_id) REFERENCES predictions(id),
            UNIQUE(prediction_id, horizon_days)
        )
        """)
        
        # 3. News Archive Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS news_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT,
            pub_date TEXT,
            url TEXT,
            polarity REAL,
            event_type TEXT,
            ingestion_date TEXT
        )
        """)
        
        # 4. Night Predictions Table (Pre-Market locked forecasts for next trading session)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS night_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            forecast_date TEXT NOT NULL,
            target_trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            short_name TEXT,
            sector TEXT,
            base_price REAL NOT NULL,
            predicted_1d_target REAL NOT NULL,
            predicted_1d_pct REAL NOT NULL,
            predicted_low REAL,
            predicted_high REAL,
            direction TEXT NOT NULL,
            action TEXT NOT NULL,
            conviction REAL NOT NULL,
            stock_sentiment REAL,
            macro_sentiment REAL,
            active_catalysts_json TEXT,
            risk_factors_json TEXT,
            reasoning_json TEXT,
            status TEXT DEFAULT 'ACTIVE_FOR_TOMORROW'
        )
        """)
        
        # 5. Daily Audits & Factor Attribution Table (Post-market reconciliation and refactoring diagnosis)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            night_pred_id INTEGER,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            short_name TEXT,
            sector TEXT,
            base_price REAL NOT NULL,
            predicted_target REAL NOT NULL,
            predicted_change_pct REAL NOT NULL,
            predicted_direction TEXT NOT NULL,
            actual_open REAL,
            actual_high REAL,
            actual_low REAL,
            actual_close REAL NOT NULL,
            actual_change_pct REAL NOT NULL,
            actual_direction TEXT NOT NULL,
            direction_correct INTEGER NOT NULL,
            hit_target_range INTEGER NOT NULL,
            abs_error_pct REAL NOT NULL,
            simulated_pnl REAL NOT NULL,
            attribution_category TEXT NOT NULL,
            diagnostic_explanation TEXT,
            refactoring_suggestion TEXT,
            factors_evaluated_json TEXT,
            audited_at TEXT NOT NULL
        )
        """)
        
        # 6. Automated Job Execution Logs Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_execution_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            status TEXT NOT NULL,
            target_date TEXT NOT NULL,
            records_stored INTEGER NOT NULL,
            log_summary TEXT
        )
        """)
        
        # Create indexes for fast lookup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pred_date ON predictions(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pred_sym ON predictions(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_eval_date ON evaluations(eval_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_eval_sym ON evaluations(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_night_target_date ON night_predictions(target_trade_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_date ON daily_audits(trade_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_sym ON daily_audits(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_date ON job_execution_logs(started_at)")
        
        conn.commit()


def save_prediction(pred: Dict[str, Any]) -> int:
    """Save a generated stock prediction to the database."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        
        reasoning_json = json.dumps(pred.get("reasoning", {}))
        range_1d = pred.get("range_1d", {})
        range_3d = pred.get("range_3d", {})
        range_7d = pred.get("range_7d", {})
        
        cursor.execute("""
        INSERT INTO predictions (
            timestamp, date, symbol, short_name, sector, base_price,
            direction, action, conviction, stock_sentiment, macro_sentiment,
            news_count, expected_1d_pct, expected_3d_pct, expected_7d_pct,
            target_1d, target_3d, target_7d,
            range_1d_low, range_1d_high,
            range_3d_low, range_3d_high,
            range_7d_low, range_7d_high,
            reasoning_json, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pred.get("timestamp", datetime.now().isoformat()),
            pred.get("date", datetime.now().strftime("%Y-%m-%d")),
            pred.get("symbol"),
            pred.get("short_name"),
            pred.get("sector"),
            pred.get("base_price"),
            pred.get("direction"),
            pred.get("action"),
            pred.get("conviction"),
            pred.get("stock_sentiment_score"),
            pred.get("macro_sentiment_score"),
            pred.get("news_count", 0),
            pred.get("expected_1d_pct"),
            pred.get("expected_3d_pct"),
            pred.get("expected_7d_pct"),
            pred.get("target_1d"),
            pred.get("target_3d"),
            pred.get("target_7d"),
            range_1d.get("low", 0),
            range_1d.get("high", 0),
            range_3d.get("low", 0),
            range_3d.get("high", 0),
            range_7d.get("low", 0),
            range_7d.get("high", 0),
            reasoning_json,
            "PENDING"
        ))
        
        pred_id = cursor.lastrowid
        
        # Save news articles to news archive
        news_items = pred.get("news_articles", [])
        for item in news_items:
            cursor.execute("""
            INSERT INTO news_archive (
                symbol, title, source, pub_date, url, polarity, event_type, ingestion_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pred.get("symbol"),
                item.get("title", ""),
                item.get("source", ""),
                item.get("pub_date", ""),
                item.get("url", ""),
                item.get("polarity", 0.0),
                item.get("event_type", "NEUTRAL_UPDATE"),
                pred.get("date", datetime.now().strftime("%Y-%m-%d"))
            ))
            
        conn.commit()
        return pred_id


def save_news_article(symbol: str, title: str, source: str, pub_date: str, url: str, polarity: float, event_type: str) -> None:
    """Save an individual news article to the archive."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO news_archive (symbol, title, source, pub_date, url, polarity, event_type, ingestion_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, title, source, pub_date, url, polarity, event_type, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()


def get_latest_predictions(limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve the most recent batch of predictions."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Get the latest prediction date
        cursor.execute("SELECT MAX(date) FROM predictions")
        row = cursor.fetchone()
        latest_date = row[0] if row else None
        
        if not latest_date:
            return []
            
        cursor.execute("""
        SELECT * FROM predictions 
        WHERE date = ? 
        ORDER BY symbol ASC 
        LIMIT ?
        """, (latest_date, limit))
        
        rows = cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["reasoning"] = json.loads(d.get("reasoning_json") or "{}")
            except Exception:
                d["reasoning"] = {}
            results.append(d)
        return results


def get_historical_predictions(symbol: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    """Retrieve historical predictions list with filtering."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        if symbol:
            cursor.execute("SELECT * FROM predictions WHERE symbol = ? ORDER BY date DESC, id DESC LIMIT ?", (symbol, limit))
        else:
            cursor.execute("SELECT * FROM predictions ORDER BY date DESC, symbol ASC LIMIT ?", (limit,))
            
        rows = cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["reasoning"] = json.loads(d.get("reasoning_json") or "{}")
            except Exception:
                d["reasoning"] = {}
            results.append(d)
        return results


_PRICE_HISTORY_CACHE: Dict[str, Any] = {}

def get_symbol_price_df(symbol: str) -> Any:
    """Fetch and cache 1-year historical price DataFrame for a symbol."""
    if symbol not in _PRICE_HISTORY_CACHE:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1y")
            if not hist.empty:
                # Index by YYYY-MM-DD
                hist.index = hist.index.strftime("%Y-%m-%d")
                _PRICE_HISTORY_CACHE[symbol] = hist
        except Exception:
            pass
    return _PRICE_HISTORY_CACHE.get(symbol)


def fetch_historical_actual_price(symbol: str, target_date_str: str) -> Optional[float]:
    """Fetch closing price on or immediately after target_date_str from cache."""
    hist = get_symbol_price_df(symbol)
    if hist is not None and not hist.empty:
        # Check direct match
        if target_date_str in hist.index:
            return round(float(hist.loc[target_date_str]["Close"]), 2)
        # Otherwise find next available trading day
        future_dates = [d for d in hist.index if d >= target_date_str]
        if future_dates:
            closest_date = min(future_dates)
            return round(float(hist.loc[closest_date]["Close"]), 2)
        return round(float(hist["Close"].iloc[-1]), 2)
    return None


def reconcile_predictions(eval_reference_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Reconcile pending predictions whose horizon has elapsed against actual historical closing prices.
    Computes accuracy, hit rates, and simulated PnL.
    """
    init_db()
    if eval_reference_date is None:
        eval_reference_date = datetime.now().date()
        
    reconciled_count = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Find predictions not yet fully evaluated
        cursor.execute("SELECT * FROM predictions ORDER BY date ASC")
        predictions = cursor.fetchall()
        
        for pred in predictions:
            pred_id = pred["id"]
            symbol = pred["symbol"]
            pred_date_str = pred["date"]
            pred_date = datetime.strptime(pred_date_str, "%Y-%m-%d").date()
            base_price = pred["base_price"]
            action = pred["action"]
            
            # Check horizons 1D, 3D, 7D
            horizon_map = {
                1: (pred["target_1d"], pred["expected_1d_pct"], pred["range_1d_low"], pred["range_1d_high"]),
                3: (pred["target_3d"], pred["expected_3d_pct"], pred["range_3d_low"], pred["range_3d_high"]),
                7: (pred["target_7d"], pred["expected_7d_pct"], pred["range_7d_low"], pred["range_7d_high"]),
            }
            
            for horizon, (target_price, exp_pct, r_low, r_high) in horizon_map.items():
                target_eval_date = pred_date + timedelta(days=horizon)
                
                # Check if this evaluation already exists
                cursor.execute("SELECT id FROM evaluations WHERE prediction_id = ? AND horizon_days = ?", (pred_id, horizon))
                if cursor.fetchone() is not None:
                    continue
                    
                # If target eval date is today or in the past, we can evaluate
                if target_eval_date <= eval_reference_date:
                    actual_price = fetch_historical_actual_price(symbol, target_eval_date.strftime("%Y-%m-%d"))
                    if actual_price is None:
                        continue
                        
                    actual_change_pct = round(((actual_price - base_price) / base_price) * 100, 2)
                    actual_direction = "BULLISH" if actual_change_pct > 0.4 else ("BEARISH" if actual_change_pct < -0.4 else "NEUTRAL")
                    pred_direction = pred["direction"]
                    
                    # Directional Accuracy Logic:
                    # 1. Bullish predicted -> actual positive (>0.2%)
                    # 2. Bearish predicted -> actual negative (<-0.2%)
                    # 3. Neutral predicted -> actual range [-0.8%, +0.8%]
                    if pred_direction == "BULLISH" and actual_change_pct > 0:
                        direction_correct = 1
                    elif pred_direction == "BEARISH" and actual_change_pct < 0:
                        direction_correct = 1
                    elif pred_direction == "NEUTRAL" and abs(actual_change_pct) <= 0.8:
                        direction_correct = 1
                    else:
                        direction_correct = 0
                        
                    # Target Range Hit
                    hit_range = 1 if (r_low <= actual_price <= r_high) else 0
                    
                    # Absolute price error percentage
                    abs_error_pct = round(abs(actual_price - target_price) / base_price * 100, 2)
                    
                    # Simulated P&L Calculation (on ₹10,000 allocation)
                    if action in ["BUY", "STRONG_BUY"]:
                        pnl = round(ALLOCATION_PER_STOCK * ((actual_price - base_price) / base_price), 2)
                    elif action in ["SELL", "STRONG_SELL"]:
                        pnl = round(ALLOCATION_PER_STOCK * ((base_price - actual_price) / base_price), 2)
                    else:  # HOLD
                        pnl = 0.0
                        
                    cursor.execute("""
                    INSERT OR REPLACE INTO evaluations (
                        prediction_id, symbol, prediction_date, eval_date, horizon_days,
                        base_price, predicted_target, predicted_change_pct, predicted_direction,
                        actual_price, actual_change_pct, actual_direction,
                        direction_correct, hit_target_range, abs_error_pct, simulated_pnl
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pred_id, symbol, pred_date_str, target_eval_date.strftime("%Y-%m-%d"), horizon,
                        base_price, target_price, exp_pct, pred_direction,
                        actual_price, actual_change_pct, actual_direction,
                        direction_correct, hit_range, abs_error_pct, pnl
                    ))
                    reconciled_count += 1
                    
        conn.commit()
        
    return {"reconciled_evaluations": reconciled_count}


def get_performance_scorecard() -> Dict[str, Any]:
    """
    Compute comprehensive quantitative performance metrics from the evaluations ledger.
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM evaluations ORDER BY eval_date ASC")
        evals = [dict(r) for r in cursor.fetchall()]
        
        if not evals:
            return {
                "total_evaluations": 0,
                "directional_accuracy_pct": 0.0,
                "target_hit_rate_pct": 0.0,
                "mean_abs_error_pct": 0.0,
                "total_simulated_pnl": 0.0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 1.0,
                "by_horizon": {},
                "by_symbol": {},
                "by_month": {},
                "equity_curve": []
            }
            
        total = len(evals)
        dir_correct = sum(1 for e in evals if e["direction_correct"] == 1)
        range_hits = sum(1 for e in evals if e["hit_target_range"] == 1)
        mean_mae = round(sum(e["abs_error_pct"] for e in evals) / total, 2)
        total_pnl = round(sum(e["simulated_pnl"] for e in evals), 2)
        
        # Trades with actual actions (non-zero PnL or active signals)
        trades = [e for e in evals if e["simulated_pnl"] != 0]
        wins = [t for t in trades if t["simulated_pnl"] > 0]
        losses = [t for t in trades if t["simulated_pnl"] < 0]
        
        gross_profit = sum(w["simulated_pnl"] for w in wins) if wins else 0.0
        gross_loss = abs(sum(l["simulated_pnl"] for l in losses)) if losses else 1.0
        profit_factor = round(gross_profit / max(1.0, gross_loss), 2)
        win_rate = round((len(wins) / max(1, len(trades))) * 100, 1) if trades else 0.0
        
        # Performance by Horizon (1D, 3D, 7D)
        by_horizon = {}
        for h in [1, 3, 7]:
            h_evals = [e for e in evals if e["horizon_days"] == h]
            if h_evals:
                h_total = len(h_evals)
                h_dir = sum(1 for e in h_evals if e["direction_correct"] == 1)
                h_hit = sum(1 for e in h_evals if e["hit_target_range"] == 1)
                h_pnl = sum(e["simulated_pnl"] for e in h_evals)
                by_horizon[f"{h}D"] = {
                    "total": h_total,
                    "accuracy_pct": round((h_dir / h_total) * 100, 1),
                    "hit_rate_pct": round((h_hit / h_total) * 100, 1),
                    "pnl": round(h_pnl, 2)
                }
                
        # Performance by Symbol
        by_symbol = {}
        symbols = sorted(list(set(e["symbol"] for e in evals)))
        for s in symbols:
            s_evals = [e for e in evals if e["symbol"] == s]
            s_total = len(s_evals)
            s_dir = sum(1 for e in s_evals if e["direction_correct"] == 1)
            s_pnl = sum(e["simulated_pnl"] for e in s_evals)
            by_symbol[s] = {
                "total": s_total,
                "accuracy_pct": round((s_dir / s_total) * 100, 1),
                "pnl": round(s_pnl, 2)
            }
            
        # Monthly breakdown & Equity Curve
        cum_pnl = 0.0
        equity_curve = []
        by_month = {}
        
        for e in evals:
            cum_pnl += e["simulated_pnl"]
            equity_curve.append({
                "date": e["eval_date"],
                "symbol": e["symbol"],
                "pnl": e["simulated_pnl"],
                "cum_pnl": round(cum_pnl, 2),
                "portfolio_value": round(100_000.0 + cum_pnl, 2)
            })
            
            m_key = e["eval_date"][:7]  # YYYY-MM
            if m_key not in by_month:
                by_month[m_key] = {"total": 0, "correct": 0, "pnl": 0.0}
            by_month[m_key]["total"] += 1
            if e["direction_correct"] == 1:
                by_month[m_key]["correct"] += 1
            by_month[m_key]["pnl"] += e["simulated_pnl"]
            
        for m, d in by_month.items():
            d["accuracy_pct"] = round((d["correct"] / d["total"]) * 100, 1)
            d["pnl"] = round(d["pnl"], 2)
            
        return {
            "total_evaluations": total,
            "directional_accuracy_pct": round((dir_correct / total) * 100, 1),
            "target_hit_rate_pct": round((range_hits / total) * 100, 1),
            "mean_abs_error_pct": mean_mae,
            "total_simulated_pnl": total_pnl,
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "by_horizon": by_horizon,
            "by_symbol": by_symbol,
            "by_month": by_month,
            "equity_curve": equity_curve,
            "recent_evaluations": evals[-20:]
        }


def get_all_news(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve ingested news archive with sentiment tags."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM news_archive ORDER BY pub_date DESC, id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]


def save_night_prediction(pred: Dict[str, Any], target_trade_date: str) -> int:
    """Save tonight's pre-market prediction locked for tomorrow's trading session."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        
        reasoning = pred.get("reasoning", {})
        catalysts_json = json.dumps(reasoning.get("catalysts", []))
        risks_json = json.dumps(reasoning.get("risks", []))
        reasoning_json = json.dumps(reasoning)
        range_1d = pred.get("range_1d", {})
        
        cursor.execute("""
        INSERT INTO night_predictions (
            created_at, forecast_date, target_trade_date, symbol, short_name, sector,
            base_price, predicted_1d_target, predicted_1d_pct,
            predicted_low, predicted_high, direction, action, conviction,
            stock_sentiment, macro_sentiment, active_catalysts_json,
            risk_factors_json, reasoning_json, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            pred.get("date", datetime.now().strftime("%Y-%m-%d")),
            target_trade_date,
            pred.get("symbol"),
            pred.get("short_name"),
            pred.get("sector"),
            pred.get("base_price"),
            pred.get("target_1d"),
            pred.get("expected_1d_pct"),
            range_1d.get("low", 0),
            range_1d.get("high", 0),
            pred.get("direction"),
            pred.get("action"),
            pred.get("conviction"),
            pred.get("stock_sentiment_score"),
            pred.get("macro_sentiment_score"),
            catalysts_json,
            risks_json,
            reasoning_json,
            "ACTIVE_FOR_TOMORROW"
        ))
        
        conn.commit()
        last_id = cursor.lastrowid
        
        # Dual-sync to Supabase Cloud
        try:
            from event_agent.storage.supabase_ledger import save_night_prediction_supabase
            save_night_prediction_supabase(pred, target_trade_date)
        except Exception:
            pass
            
        return last_id


def get_active_night_predictions(target_trade_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve tonight's active predictions for tomorrow's trade date."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        if target_trade_date:
            cursor.execute("""
            SELECT * FROM night_predictions 
            WHERE target_trade_date = ? 
            ORDER BY symbol ASC
            """, (target_trade_date,))
        else:
            # Get latest target trade date
            cursor.execute("SELECT MAX(target_trade_date) FROM night_predictions")
            row = cursor.fetchone()
            latest_target = row[0] if row else None
            if not latest_target:
                return []
            cursor.execute("""
            SELECT * FROM night_predictions 
            WHERE target_trade_date = ? 
            ORDER BY symbol ASC
            """, (latest_target,))
            
        rows = cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["active_catalysts"] = json.loads(d.get("active_catalysts_json") or "[]")
                d["risk_factors"] = json.loads(d.get("risk_factors_json") or "[]")
                d["reasoning"] = json.loads(d.get("reasoning_json") or "{}")
            except Exception:
                d["active_catalysts"] = []
                d["risk_factors"] = []
                d["reasoning"] = {}
            results.append(d)
        return results


def save_daily_audit(audit: Dict[str, Any]) -> int:
    """Save post-market reconciliation audit with factor attribution."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        factors_json = json.dumps(audit.get("factors_active", []))
        
        cursor.execute("""
        INSERT INTO daily_audits (
            night_pred_id, trade_date, symbol, short_name, sector, base_price,
            predicted_target, predicted_change_pct, predicted_direction,
            actual_open, actual_high, actual_low, actual_close, actual_change_pct,
            actual_direction, direction_correct, hit_target_range, abs_error_pct,
            simulated_pnl, attribution_category, diagnostic_explanation,
            refactoring_suggestion, factors_evaluated_json, audited_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            audit.get("night_pred_id"),
            audit.get("trade_date"),
            audit.get("symbol"),
            audit.get("short_name"),
            audit.get("sector"),
            audit.get("base_price"),
            audit.get("predicted_target", 0.0),
            audit.get("predicted_change_pct", 0.0),
            audit.get("predicted_direction", "NEUTRAL"),
            audit.get("actual_open"),
            audit.get("actual_high"),
            audit.get("actual_low"),
            audit.get("actual_close"),
            audit.get("actual_change_pct"),
            audit.get("actual_direction"),
            audit.get("direction_correct", 0),
            audit.get("hit_target_range", 0),
            audit.get("abs_error_pct", 0.0),
            audit.get("simulated_pnl", 0.0),
            audit.get("attribution_category", "MARKET_NOISE_DRIFT"),
            audit.get("diagnostic_explanation", ""),
            audit.get("refactoring_suggestion", ""),
            factors_json,
            datetime.now().isoformat()
        ))
        
        conn.commit()
        last_id = cursor.lastrowid
        
        # Dual-sync to Supabase Cloud
        try:
            from event_agent.storage.supabase_ledger import save_daily_audit_supabase
            save_daily_audit_supabase(audit)
        except Exception:
            pass
            
        return last_id


def get_daily_audits(trade_date: Optional[str] = None, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieve daily audit logs with factor attribution and refactoring recommendations."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM daily_audits"
        params = []
        
        conditions = []
        if trade_date:
            conditions.append("trade_date = ?")
            params.append(trade_date)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
            
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
            
        query += " ORDER BY trade_date DESC, id DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["factors_evaluated"] = json.loads(d.get("factors_evaluated_json") or "[]")
            except Exception:
                d["factors_evaluated"] = []
            results.append(d)
        return results


def get_factor_attribution_summary() -> Dict[str, Any]:
    """Aggregate statistics on factor attribution categories and diagnostic efficacy."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM daily_audits")
        audits = [dict(r) for r in cursor.fetchall()]
        
        if not audits:
            return {
                "total_audits": 0,
                "captured_success_count": 0,
                "missed_catalyst_count": 0,
                "factor_miscalibrated_count": 0,
                "market_noise_count": 0,
                "captured_success_pct": 0.0,
                "category_breakdown": {},
                "refactoring_priorities": []
            }
            
        total = len(audits)
        cat_counts = {}
        for a in audits:
            cat = a.get("attribution_category", "MARKET_NOISE_DRIFT")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            
        success = cat_counts.get("CAPTURED_SUCCESS", 0)
        missed = cat_counts.get("MISSED_CATALYST", 0)
        miscal = cat_counts.get("FACTOR_MISCALIBRATED", 0)
        noise = cat_counts.get("MARKET_NOISE_DRIFT", 0)
        
        # Extract unique refactoring recommendations from recent audits
        refactorings = list(set([a.get("refactoring_suggestion") for a in audits if a.get("refactoring_suggestion")]))
        
        return {
            "total_audits": total,
            "captured_success_count": success,
            "missed_catalyst_count": missed,
            "factor_miscalibrated_count": miscal,
            "market_noise_count": noise,
            "captured_success_pct": round((success / total) * 100, 1),
            "category_breakdown": cat_counts,
            "refactoring_priorities": refactorings[:5]
        }


def log_job_execution(
    job_type: str,
    started_at: str,
    completed_at: str,
    status: str,
    target_date: str,
    records_stored: int,
    log_summary: str
) -> int:
    """Log an automated background job execution into the database ledger."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO job_execution_logs (
            job_type, started_at, completed_at, status, target_date, records_stored, log_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (job_type, started_at, completed_at, status, target_date, records_stored, log_summary))
        conn.commit()
        last_id = cursor.lastrowid
        
        # Dual-sync to Supabase Cloud
        try:
            from event_agent.storage.supabase_ledger import log_job_execution_supabase
            log_job_execution_supabase(job_type, started_at, completed_at, status, target_date, records_stored, log_summary)
        except Exception:
            pass
            
        return last_id


def get_job_execution_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve chronological job execution records."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM job_execution_logs ORDER BY started_at DESC, id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]

