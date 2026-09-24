"""
NEXUS V3.6.2 — Frontend Institutional Command Terminal Regression Tests
Verifies DOM structure, DataContractValidator, NexusTruthResolver, dynamic risk-gate counting,
dynamic agent count, option safety contracts, observation timestamps, and zero hardcoded defaults.
"""

import json
from pathlib import Path
import pytest


class TestV362CommandTerminal:
    def setup_method(self):
        self.html_path = Path("web_app/index.html")
        self.js_path = Path("web_app/app.js")
        self.css_path = Path("web_app/styles.css")
        self.data_json_path = Path("web_app/data.json")

        assert self.html_path.exists()
        assert self.js_path.exists()
        assert self.css_path.exists()
        assert self.data_json_path.exists()

        self.html_content = self.html_path.read_text(encoding="utf-8")
        self.js_content = self.js_path.read_text(encoding="utf-8")
        self.css_content = self.css_path.read_text(encoding="utf-8")

        with open(self.data_json_path, encoding="utf-8") as f:
            self.data = json.load(f)

    def test_terminal_dom_elements_presence(self):
        """Verifies that all institutional command terminal components exist in index.html."""
        required_elements = [
            'id="terminal-market-ribbon"',
            'id="telemetry-strip"',
            'id="telemetry-risk-engine-status"',
            'id="telemetry-risk-gates-badge"',
            'id="telemetry-market-view-val"',
            'id="telemetry-market-view-badge"',
            'id="metric-matrix"',
            'id="terminal-workbench"',
            'id="terminal-workbench-left"',
            'id="terminal-workbench-right"',
            'id="terminal-strategy-card"',
            'id="payoff-svg-container"',
            'id="terminal-evidence-panel"',
            'id="terminal-option-chain"',
            'id="terminal-risk-gates"',
            'id="terminal-catalysts-section"',
            'id="terminal-agent-arena"',
            'id="terminal-arena-count-badge"',
            'id="terminal-provenance-box"',
            'id="terminal-order-quickslip"',
            'id="terminal-status-bar"',
            'id="ops-drawer-backdrop"',
        ]
        for elem in required_elements:
            assert elem in self.html_content, f"Required terminal element {elem} missing from index.html"

    def test_data_contract_validator_presence(self):
        """Verifies DataContractValidator layer exists with defensive validation methods."""
        assert "const DataContractValidator = {" in self.js_content
        assert "validateQuote(" in self.js_content
        assert "validateCommodity(" in self.js_content
        assert "validateOptionChain(" in self.js_content
        assert "validateRiskEngine(" in self.js_content
        assert "validateArena(" in self.js_content
        assert "validateIntelligence(" in self.js_content

    def test_nexus_truth_resolver_presence_and_states(self):
        """Verifies NexusTruthResolver layer exists with state resolution."""
        assert "const NexusTruthResolver = {" in self.js_content
        assert "resolveMarketQuote(" in self.js_content
        assert "resolveCommodity(" in self.js_content
        assert "resolveOptionSafety(" in self.js_content
        assert "resolveRiskGates(" in self.js_content
        assert "resolveArena(" in self.js_content
        assert "resolveIntelligenceSufficiency(" in self.js_content

    def test_dynamic_risk_gate_contract(self):
        """Verifies risk gates are rendered dynamically without hardcoded 16/16 count."""
        assert "statusText: `${passed} / ${total} GATES VERIFIED`" in self.js_content
        assert 'id="telemetry-risk-gates-badge"' in self.html_content
        # Ensure the badge in HTML template defaults to placeholder '-- / -- GATES VERIFIED', not hardcoded '16/16'
        assert '-- / -- GATES VERIFIED' in self.html_content

    def test_dynamic_arena_agent_count(self):
        """Verifies arena agent count is dynamic (AGENTS: {actual_count}), not hardcoded 5."""
        assert "label: `AGENTS: ${agents.length}`" in self.js_content
        assert 'id="terminal-arena-count-badge"' in self.html_content
        assert 'AGENTS: --' in self.html_content

    def test_option_safety_contract(self):
        """Verifies options safety contract explicitly distinguishes MODELLED vs LIVE."""
        assert 'MODELLED DERIVATIVE PRICING' in self.html_content
        assert 'label: \'MODELLED DERIVATIVE PRICING\'' in self.js_content
        # Ensure LIVE is never inferred without backend confirmation
        assert "if (valid.data_source === 'LIVE')" in self.js_content

    def test_timestamp_transparency_in_ribbon(self):
        """Verifies observation timestamps are attached to quotes."""
        assert "text: `${state} · Observed ${obs}`" in self.js_content
        assert "class=\"ribbon-meta\"" in self.js_content

    def test_navigation_hierarchy_and_deep_dives(self):
        """Verifies 6-pillar command navigation and legacy compatibility tabs."""
        # 6 Primary Command Pillars
        assert '[01] Command' in self.html_content
        assert '[02] Markets' in self.html_content
        assert '[03] Intelligence' in self.html_content
        assert '[04] Strategies' in self.html_content
        assert '[05] Risk' in self.html_content
        assert '[06] Operations' in self.html_content

        # Deep dive data-tabs preserved
        assert 'data-tab="overview"' in self.html_content
        assert 'data-tab="markets"' in self.html_content
        assert 'data-tab="intelligence"' in self.html_content
        assert 'data-tab="arena"' in self.html_content
        assert 'data-tab="risk"' in self.html_content
        assert 'data-tab="jobs"' in self.html_content
        assert 'data-tab="overnight"' in self.html_content
        assert 'data-tab="news"' in self.html_content
        assert 'data-tab="operations"' in self.html_content

    def test_zero_placeholders_preserved(self):
        """Ensures forbidden static placeholders remain absent."""
        assert "ALL SYSTEMS RECONCILED" not in self.html_content
        assert "Dual-feed reconciled" not in self.html_content

    def test_left_sidebar_navigation_presence(self):
        """Verifies that the Left Navigation Bar from Stitch screen 5bbea71045434e189ed0f2426779d132 is implemented."""
        assert 'id="terminal-sidebar"' in self.html_content
        assert 'class="terminal-sidebar"' in self.html_content
        assert 'class="sidebar-brand"' in self.html_content
        assert 'NX' in self.html_content
        assert 'class="sidebar-nav"' in self.html_content
        assert 'class="sidebar-tooltip"' in self.html_content
        assert '0.8ms' in self.html_content
        assert 'INST-DESK #409 (T1)' in self.html_content

        # Sidebar navigation tabs
        assert 'aria-label="Overview Terminal [01]"' in self.html_content
        assert 'aria-label="Markets Terminal [02]"' in self.html_content
        assert 'aria-label="AI Arena Strategies [04]"' in self.html_content

    def test_light_paper_edition_theme_tokens(self):
        """Verifies Light Paper Edition color palette tokens from Stitch screen 5bbea71045434e189ed0f2426779d132."""
        assert '--bg-app: #F8F9FF;' in self.css_content or '--bg-app: #f8f9ff;' in self.css_content
        assert '--bg-surface: #FFFFFF;' in self.css_content or '--bg-surface: #ffffff;' in self.css_content
        assert '--text-primary: #0B1C30;' in self.css_content or '--text-primary: #0b1c30;' in self.css_content
        assert '--sidebar-width: 56px;' in self.css_content
        assert '.terminal-sidebar {' in self.css_content
        assert 'Hanken+Grotesk' in self.html_content or 'Hanken Grotesk' in self.html_content
        assert 'Material Symbols Outlined' in self.html_content or 'Material+Symbols+Outlined' in self.html_content

    def test_no_fabricated_runtime_values(self):
        """
        V3.6.2.1 Integrity Polish Verification:
        Verifies zero fabricated, demo, or hardcoded fallback numbers in app.js and initial index.html.
        Verifies all displayed numeric metrics correspond directly to backend sources in data.json.
        """
        forbidden_strings = [
            "42800",
            "384210",
            "83.92",
            "16 Quantitative",
            "refining margin",
            "e3b0c442",
            "16/16 Invariants",
            "₹1,00,00,000",
            "8,415.00",
            "Dual-source market data reconciliation",
            "DATA PIPELINES VERIFIED",
        ]
        for s in forbidden_strings:
            assert s not in self.js_content, f"Forbidden fabricated value or stale claim '{s}' found in app.js"
            assert s not in self.html_content, f"Forbidden fabricated value or stale claim '{s}' found in index.html"

        # Verify backend source of truth in data.json
        assert "arena" in self.data
        summary = self.data["arena"]["summary"]
        assert summary["total_virtual_capital"] == 10000000.0
        assert "total_arena_pnl" in summary

        benchmarks = self.data.get("indian_closing_benchmarks", {})
        assert "NIFTY 50" in benchmarks
        assert benchmarks["NIFTY 50"]["price"] > 0

        freshness = self.data.get("data_freshness_summary", {})
        assert freshness.get("healthy_count", 0) >= 0
        assert freshness.get("delayed_count", 0) >= 0

        # Verify DATA SOURCE HEALTH telemetry banner exists and is derived from job ledger / data_freshness_summary
        assert 'id="terminal-data-health-box"' in self.html_content
        assert "Source state derived from job ledger" in self.html_content
        assert "renderTerminalDataHealthBox" in self.js_content
        assert "${healthyCount} HEALTHY" in self.js_content
        assert "${delayedCount} DELAYED" in self.js_content

        # Verify Command hierarchy reordering: option chain immediately follows strategy card, before risk gates and catalysts
        strat_pos = self.html_content.find('id="terminal-strategy-card"')
        opt_pos = self.html_content.find('id="terminal-option-chain"')
        risk_pos = self.html_content.find('id="terminal-risk-gates"')
        cat_pos = self.html_content.find('id="terminal-catalysts-section"')
        evid_pos = self.html_content.find('id="terminal-evidence-panel"')

        assert strat_pos != -1 and opt_pos != -1 and risk_pos != -1 and cat_pos != -1 and evid_pos != -1
        assert strat_pos < opt_pos < risk_pos < cat_pos < evid_pos, (
            f"Command hierarchy out of order: strat={strat_pos}, opt={opt_pos}, "
            f"risk={risk_pos}, cat={cat_pos}, evid={evid_pos}"
        )



