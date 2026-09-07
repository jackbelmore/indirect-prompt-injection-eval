"""
Statistical analysis tools for the LLM evaluation pipeline.
Calculates Attack Success Rate (ASR), confidence intervals, and runs Fisher's exact test.
"""

import numpy as np
import scipy.stats as stats
from typing import Dict, Tuple

def calculate_confidence_interval(successes: int, total: int, confidence_level: float = 0.95) -> Tuple[float, float]:
    """
    Calculate the Wilson score interval for a binomial proportion.
    This is more robust than the Wald interval (normal approximation) for small sample sizes
    and proportions close to 0 or 1.
    
    Args:
        successes: Number of successful prompt injections
        total: Total number of trials
        confidence_level: Confidence level (e.g., 0.95 for 95% CI)
        
    Returns:
        Tuple of (lower_bound, upper_bound) as percentages/proportions
    """
    if total == 0:
        return 0.0, 0.0
        
    p = successes / total
    z = stats.norm.ppf(1 - (1 - confidence_level) / 2)
    
    # Wilson score interval formula
    denominator = 1 + z**2 / total
    centre_adj = p + z**2 / (2 * total)
    spread = z * np.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)
    
    lower = (centre_adj - spread) / denominator
    upper = (centre_adj + spread) / denominator
    
    # Clip bounds to [0, 1]
    return max(0.0, lower), min(1.0, upper)

def run_fishers_exact_test(group_a_successes: int, group_a_total: int, 
                           group_b_successes: int, group_b_total: int) -> Tuple[float, float]:
    """
    Run Fisher's exact test to determine if the difference in success rates
    between two groups is statistically significant.
    
    A 2x2 contingency table is constructed:
                      Success    Failure
    Group A            [s_a]      [t_a - s_a]
    Group B            [s_b]      [t_b - s_b]
    
    Args:
        group_a_successes: Successes in Group A
        group_a_total: Total trials in Group A
        group_b_successes: Successes in Group B
        group_b_total: Total trials in Group B
        
    Returns:
        Tuple of (odds_ratio, p_value)
    """
    group_a_failures = group_a_total - group_a_successes
    group_b_failures = group_b_total - group_b_successes
    
    contingency_table = [
        [group_a_successes, group_a_failures],
        [group_b_successes, group_b_failures]
    ]
    
    odds_ratio, p_value = stats.fisher_exact(contingency_table)
    return odds_ratio, p_value

def analyze_model_comparison(group_a_name: str, group_a_successes: int, group_a_total: int,
                             group_b_name: str, group_b_successes: int, group_b_total: int) -> Dict:
    """
    Perform a complete comparative statistical analysis between two test groups/conditions.
    """
    rate_a = group_a_successes / group_a_total if group_a_total > 0 else 0
    rate_b = group_b_successes / group_b_total if group_b_total > 0 else 0
    
    ci_a_lower, ci_a_upper = calculate_confidence_interval(group_a_successes, group_a_total)
    ci_b_lower, ci_b_upper = calculate_confidence_interval(group_b_successes, group_b_total)
    
    odds_ratio, p_value = run_fishers_exact_test(
        group_a_successes, group_a_total,
        group_b_successes, group_b_total
    )
    
    significant = p_value < 0.05
    
    return {
        "group_a": {
            "name": group_a_name,
            "success_rate": rate_a,
            "ci": (ci_a_lower, ci_a_upper),
            "successes": group_a_successes,
            "total": group_a_total
        },
        "group_b": {
            "name": group_b_name,
            "success_rate": rate_b,
            "ci": (ci_b_lower, ci_b_upper),
            "successes": group_b_successes,
            "total": group_b_total
        },
        "comparison": {
            "odds_ratio": odds_ratio,
            "p_value": p_value,
            "statistically_significant": significant
        }
    }

if __name__ == "__main__":
    # Quick sanity check with hypothetical data:
    # Model A: 3 successes out of 30 trials (ASR: 10%)
    # Model B: 15 successes out of 30 trials (ASR: 50%)
    print("Running sample comparison...")
    results = analyze_model_comparison(
        "Dense Qwen 2.5 7B", 3, 30,
        "MoE Qwen 2.5 14B-equivalent", 15, 30
    )
    
    print(f"Group A ({results['group_a']['name']}) ASR: {results['group_a']['success_rate']:.2%} "
          f"(95% CI: [{results['group_a']['ci'][0]:.2%}, {results['group_a']['ci'][1]:.2%}])")
    print(f"Group B ({results['group_b']['name']}) ASR: {results['group_b']['success_rate']:.2%} "
          f"(95% CI: [{results['group_b']['ci'][0]:.2%}, {results['group_b']['ci'][1]:.2%}])")
    print(f"Fisher's Exact Test p-value: {results['comparison']['p_value']:.4f}")
    print(f"Statistically significant (p < 0.05): {results['comparison']['statistically_significant']}")
