# =============================================================================
# event_agent/engine/sentiment_analyzer.py — Financial Domain Sentiment Engine
# =============================================================================

import re
from typing import List, Dict, Any, Tuple

# Domain Lexicons for Indian Stock Market & Corporate News
BULLISH_KEYWORDS = {
    # Earnings & Growth
    "profit surge": 2.5, "profit surges": 2.5, "surges": 1.8, "surged": 1.8,
    "net profit rises": 2.2, "net profit jumps": 2.5, "jumps": 1.5, "jumped": 1.5,
    "margin expansion": 2.2, "operating margin expands": 2.2,
    "revenue up": 1.8, "revenue grows": 1.8, "double digit growth": 2.0,
    "beats estimate": 2.4, "beats estimates": 2.5, "beat street": 2.5,
    "record high": 2.0, "all time high": 2.0, "multi year high": 1.8,
    "strong earnings": 2.0, "strong results": 2.0, "robust earnings": 2.0,
    
    # Deals, Orders & Expansion
    "order win": 2.2, "bags order": 2.2, "secures contract": 2.2, "wins deal": 2.2,
    "large deal": 1.8, "tcv surge": 2.0, "deal inflows": 1.8,
    "expansion": 1.2, "capex plan": 1.4, "new facility": 1.3,
    "tariff hike": 2.2, "arpu rise": 2.0, "arpu expands": 2.0,
    
    # Corporate Actions & Capital
    "buyback": 2.0, "share buyback": 2.0, "special dividend": 1.8, "dividend hike": 1.6,
    "bonus issue": 1.5, "demerger": 1.8, "value unlocking": 2.0,
    "debt free": 2.2, "debt reduction": 1.8, "fundraising": 1.2,
    
    # Broker & Market Actions
    "target raised": 2.2, "price target raised": 2.5, "upgraded": 2.0, "upgrade": 2.0,
    "buy rating": 2.0, "outperform": 1.8, "overweight": 1.8, "accumulate": 1.4,
    "bullish": 1.6, "breakout": 1.8, "buying frenzy": 1.8, "rallies": 1.6, "rally": 1.6,
    
    # Macro & Policy
    "rate cut": 2.2, "repo rate cut": 2.5, "dovish stance": 1.8, "inflation cools": 1.8,
    "government capex boost": 2.0, "tax relief": 2.0, "fii buying": 1.8
}

BEARISH_KEYWORDS = {
    # Earnings & Performance
    "profit slump": -2.5, "profit falls": -2.0, "profit drops": -2.0, "plunges": -2.2,
    "net loss": -2.5, "loss widens": -2.5, "misses estimate": -2.4, "misses estimates": -2.5,
    "margin squeeze": -2.2, "margin contraction": -2.2, "margin pressure": -1.8,
    "revenue drops": -1.8, "weak earnings": -2.0, "weak results": -2.0, "subdued demand": -1.6,
    
    # Guidance & Business Risk
    "guidance cut": -2.5, "lowers guidance": -2.5, "guidance downgrade": -2.5,
    "order cancellation": -2.4, "deal delay": -1.8, "slowdown": -1.6,
    "attrition spike": -1.6, "tech spending cut": -2.0,
    
    # Regulatory & Legal
    "regulatory action": -2.5, "sebi probe": -2.8, "sebi notice": -2.5, "rbi penalty": -2.5,
    "rbi bar": -3.0, "tax notice": -2.0, "tax demand": -2.0, "fda observation": -2.2,
    "warning letter": -2.4, "litigation": -1.6, "fraud": -3.5, "investigation": -2.0,
    
    # Broker & Market Actions
    "target cut": -2.2, "price target cut": -2.5, "downgraded": -2.2, "downgrade": -2.2,
    "sell rating": -2.0, "underperform": -1.8, "underweight": -1.8, "reduce": -1.4,
    "bearish": -1.6, "breakdown": -1.8, "selloff": -2.0, "slides": -1.6, "crashes": -2.5,
    
    # Macro & Debt
    "rate hike": -2.0, "repo rate hike": -2.2, "hawkish stance": -1.8, "inflation spikes": -1.8,
    "crude surges": -1.8, "fii selling": -1.8, "credit rating downgrade": -2.5, "debt default": -3.5
}

NEGATION_TERMS = ["not", "no", "never", "without", "hardly", "unlikely", "failed to"]


def classify_event_type(text: str) -> str:
    """
    Classify text into a specific event category based on keywords.
    """
    t = text.lower()
    if re.search(r'\b(beat|beats|surpass|record profit|profit surges|q\d profit up)\b', t):
        return "EARNINGS_BEAT"
    elif re.search(r'\b(miss|misses|slump|net loss|profit drops|q\d profit down)\b', t):
        return "EARNINGS_MISS"
    elif re.search(r'\b(bags order|wins contract|secures order|order book|tcv)\b', t):
        return "LARGE_ORDER_WIN"
    elif re.search(r'\b(sebi|rbi penalty|show cause|probe|tax demand|warning letter|fda)\b', t):
        return "REGULATORY_ACTION"
    elif re.search(r'\b(tariff hike|tariff revision|arpu hike)\b', t):
        return "TARIFF_HIKE"
    elif re.search(r'\b(buyback|dividend|bonus issue|demerger)\b', t):
        return "DIVIDEND_BUYBACK"
    elif re.search(r'\b(ceo steps down|management change|md resigns|new ceo)\b', t):
        return "MANAGEMENT_CHANGE"
    elif re.search(r'\b(rbi repo rate hike|inflation surge|hawkish)\b', t):
        return "RBI_POLICY_HAWKISH"
    elif re.search(r'\b(rbi repo rate cut|rate pause|dovish|inflation cools)\b', t):
        return "RBI_POLICY_DOVISH"
    elif re.search(r'\b(target raised|upgrade|buy rating|rallies|breakout)\b', t):
        return "GENERAL_BULLISH_NEWS"
    elif re.search(r'\b(target cut|downgrade|selloff|slides|crude surge)\b', t):
        return "GENERAL_BEARISH_NEWS"
    else:
        return "NEUTRAL_UPDATE"


def analyze_text_sentiment(text: str) -> Dict[str, Any]:
    """
    Analyze financial sentiment score of a single news title or headline.
    Returns polarity (-1.0 to 1.0), intensity, confidence, detected event type, and keywords found.
    """
    if not text:
        return {
            "polarity": 0.0,
            "confidence": 50.0,
            "event_type": "NEUTRAL_UPDATE",
            "matched_keywords": []
        }
        
    lower_text = text.lower()
    total_score = 0.0
    matched_keywords = []
    
    # Check bullish keywords
    for kw, weight in BULLISH_KEYWORDS.items():
        if kw in lower_text:
            # Check negation in previous 3 words
            words = lower_text.split()
            kw_words = kw.split()
            if kw_words[0] in words:
                idx = words.index(kw_words[0])
                preceding = words[max(0, idx-3):idx]
                has_neg = any(neg in preceding for neg in NEGATION_TERMS)
                if has_neg:
                    total_score -= (weight * 0.8)
                    matched_keywords.append(f"NOT {kw} (negated)")
                else:
                    total_score += weight
                    matched_keywords.append(kw)
            else:
                total_score += weight
                matched_keywords.append(kw)
                
    # Check bearish keywords
    for kw, weight in BEARISH_KEYWORDS.items():
        if kw in lower_text:
            words = lower_text.split()
            kw_words = kw.split()
            if kw_words[0] in words:
                idx = words.index(kw_words[0])
                preceding = words[max(0, idx-3):idx]
                has_neg = any(neg in preceding for neg in NEGATION_TERMS)
                if has_neg:
                    total_score += (abs(weight) * 0.8)
                    matched_keywords.append(f"NOT {kw} (negated)")
                else:
                    total_score += weight
                    matched_keywords.append(kw)
            else:
                total_score += weight
                matched_keywords.append(kw)
                
    event_type = classify_event_type(text)
    
    # Normalize polarity to range [-1.0, 1.0] using hyperbolic tangent or bounded scale
    if total_score > 0:
        polarity = min(1.0, total_score / 4.0)
    elif total_score < 0:
        polarity = max(-1.0, total_score / 4.0)
    else:
        polarity = 0.0
        
    # Confidence is higher when strong matching financial keywords are present
    kw_count = len(matched_keywords)
    confidence = min(95.0, 50.0 + (kw_count * 12.0) + (abs(polarity) * 20.0))
    
    return {
        "polarity": round(polarity, 3),
        "score_raw": round(total_score, 2),
        "confidence": round(confidence, 1),
        "event_type": event_type,
        "matched_keywords": matched_keywords
    }


def analyze_news_sentiment(articles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate sentiment analysis across all articles collected for a stock.
    Computes weighted average sentiment, sentiment distribution, key catalysts, and dominant event type.
    """
    if not articles:
        return {
            "avg_polarity": 0.0,
            "overall_sentiment": "NEUTRAL",
            "confidence": 50.0,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "total_articles": 0,
            "key_catalysts": [],
            "risk_factors": [],
            "top_event_type": "NEUTRAL_UPDATE",
            "annotated_articles": []
        }
        
    annotated = []
    total_polarity = 0.0
    total_conf = 0.0
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    all_catalysts = []
    all_risks = []
    event_counts = {}
    
    for art in articles:
        res = analyze_text_sentiment(art["title"])
        pol = res["polarity"]
        ev = res["event_type"]
        
        event_counts[ev] = event_counts.get(ev, 0) + 1
        
        art_annotated = dict(art)
        art_annotated["polarity"] = pol
        art_annotated["confidence"] = res["confidence"]
        art_annotated["event_type"] = ev
        art_annotated["matched_keywords"] = res["matched_keywords"]
        annotated.append(art_annotated)
        
        total_polarity += pol
        total_conf += res["confidence"]
        
        if pol >= 0.15:
            bullish_count += 1
            if res["matched_keywords"]:
                all_catalysts.append(art["title"])
        elif pol <= -0.15:
            bearish_count += 1
            if res["matched_keywords"]:
                all_risks.append(art["title"])
        else:
            neutral_count += 1
            
    n = len(articles)
    avg_pol = round(total_polarity / n, 3)
    avg_conf = round(total_conf / n, 1)
    
    if avg_pol >= 0.15:
        overall = "BULLISH"
    elif avg_pol <= -0.15:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"
        
    top_event = max(event_counts.items(), key=lambda x: x[1])[0] if event_counts else "NEUTRAL_UPDATE"
    
    return {
        "avg_polarity": avg_pol,
        "overall_sentiment": overall,
        "confidence": avg_conf,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": neutral_count,
        "total_articles": n,
        "key_catalysts": all_catalysts[:3],
        "risk_factors": all_risks[:3],
        "top_event_type": top_event,
        "annotated_articles": annotated
    }
