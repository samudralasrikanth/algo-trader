# =============================================================================
# event_agent/certification/__init__.py — V3.6 Independent Certification Package
# =============================================================================
"""
NEXUS V3.6 Independent Validation & Prospective Paper Certification Engine.
Audits the frozen V3.5 model across 8 strict validation pillars:
1. Untouched Holdout Evaluation
2. Nested Walk-Forward Validation
3. Multiple-Testing & Deflated Sharpe Ratio (DSR) Audit
4. Economic Significance & Institutional Risk Metrics
5. Backtest -> Paper Reality Gap Tracking
6. Sub-Second Timestamp & Feature Availability Leakage Audit
7. Options Segregation & Independent Precondition Verification
8. Prospective Paper Certification Harness & Frozen V3.5 Baseline
"""

from .experiment_registry import ExperimentRecord, ExperimentRegistry
from .feature_availability_audit import FeatureAvailabilityAuditor, TimestampCausalityRecord
from .event_timestamp_audit import EventTimestampAuditor
from .holdout_audit import HoldoutAuditor, HoldoutCertificationResult
from .nested_walk_forward import NestedWalkForwardValidator, NestedPartition
from .multiple_testing_audit import MultipleTestingAuditor, DSRMetrics
from .economic_significance import EconomicMetrics, EconomicSignificanceEngine
from .reality_gap import RealityGapRecord, RealityGapTracker
from .option_segregation import OptionSegregationAuditor, OptionPrerequisiteStatus
from .prospective_harness import ProspectiveCertificationHarness, ProspectiveObservation
from .certification_report import CertificationReportGenerator, CertificationVerdict

__all__ = [
    "ExperimentRecord",
    "ExperimentRegistry",
    "FeatureAvailabilityAuditor",
    "TimestampCausalityRecord",
    "EventTimestampAuditor",
    "HoldoutAuditor",
    "HoldoutCertificationResult",
    "NestedWalkForwardValidator",
    "NestedPartition",
    "MultipleTestingAuditor",
    "DSRMetrics",
    "EconomicMetrics",
    "EconomicSignificanceEngine",
    "RealityGapRecord",
    "RealityGapTracker",
    "OptionSegregationAuditor",
    "OptionPrerequisiteStatus",
    "ProspectiveCertificationHarness",
    "ProspectiveObservation",
    "CertificationReportGenerator",
    "CertificationVerdict",
]
