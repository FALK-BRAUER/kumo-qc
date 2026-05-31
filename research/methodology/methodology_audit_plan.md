# Methodology Audit Plan for kumo-qc

**Date:** 2026-05-29  
**Purpose:** Assess backtest overfitting risk for BCT strategy experiments  
**Context:** B0d-honest baseline (0.831 Sharpe, 185 orders), all prior experiments vs deprecated E40d 1.442  
**Status:** Research/planning only — no strategy changes authorized  

---

## Executive Summary

This document outlines four statistical methods to audit backtest overfitting risk in the kumo-qc experiment pipeline: Deflated Sharpe Ratio (DSR), Probability of Backtest Overfitting (PBO), Combinatorial Purged Cross-Validation (CPCV), and Block Bootstrap confidence intervals. For each method, we identify: (1) what it corrects for, (2) required inputs, (3) what we already have, (4) what we need to generate, and (5) concrete application steps.

**Key Finding:** We have 50+ experiments in bt-results.csv but lack the daily equity curves / return series needed for rigorous overfitting analysis. The most actionable next step is to modify `main.py` to output daily strategy returns to a file/series for PBO/CPCV analysis.

---

## 1. Deflated Sharpe Ratio (DSR)

### 1.1 What It Corrects For
DSR (Bailey & Lopez de Prado, 2014) adjusts the observed Sharpe ratio for:
- **Selection bias:** choosing the best among N trials
- **Non-normality:** skewness and kurtosis of returns
- **Sample length:** shorter track records have higher variance
- **Multiple testing:** each additional trial increases false discovery probability

### 1.2 Formula

The DSR is essentially a Probabilistic Sharpe Ratio (PSR) where the rejection threshold is the *expected maximum Sharpe ratio under the null* (from False Strategy Theorem), rather than zero:

```
DSR = Z[ (SR_observed - E[max SR_null]) / sigma(SR) ]
```

Where:
- `E[max SR_null]` ≈ sqrt(V[SR_trials]) * ((1-γ)*Z⁻¹[1-1/N] + γ*Z⁻¹[1-1/(N*e)])
- γ = 0.5772 (Euler-Mascheroni constant)
- N = effective number of *independent* trials (not total trials M)
- V[SR_trials] = variance of Sharpe ratios across trials/clusters
- sigma(SR) = standard deviation of the Sharpe ratio estimate, accounting for skewness and kurtosis

### 1.3 Standard Error of Sharpe Ratio (Non-Normal)

```
sigma(SR_hat) = sqrt( (1/(T-1)) * (1 + 0.5*SR² - γ3*SR + (γ4-3)/4 * SR²) )
```

Where γ3 = skewness, γ4 = kurtosis, T = number of observations.

### 1.4 Inputs We Already Have

| Input | Source | Status |
|---|---|---|
| Observed Sharpe ratios per experiment | bt-results.csv | ✅ Available (50+ rows) |
| Experiment count (M) | bt-results.csv | ✅ ~50-60 experiments |
| Track record length (T) | bt-results.csv | ✅ 252 trading days (FY2025) |
| Return% per experiment | bt-results.csv | ✅ Available |

### 1.5 Inputs We Need to Generate

| Input | How to Generate | Effort |
|---|---|---|
| Daily return series per experiment | Modify `main.py` to log daily portfolio returns | **HIGH** — requires re-running experiments or adding series output |
| Skewness & kurtosis of daily returns | Compute from daily return series | Medium — depends on above |
| Effective independent trials (N) | Cluster experiments by correlation of equity curves | **HIGH** — requires all daily curves + ONC/hierarchical clustering |
| Variance of SR across clusters (V[SR]) | Compute after clustering | Medium — depends on above |

### 1.6 Concrete Application Steps

**Step 1: Record all daily returns**
- Modify `main.py` to append daily strategy returns (portfolio equity % change) to a file or `self.record_variable()`
- File: `daily_returns/<experiment_id>.csv` or ObjectStore key
- **CRITICAL:** Must do this BEFORE running new experiments; historical experiments lack this data

**Step 2: Estimate effective N (independent trials)**
- Load daily return matrix: rows = days, columns = experiments
- Compute correlation matrix between experiments
- Convert to distance matrix (angular distance: arccos(correlation))
- Apply clustering (ONC algorithm or hierarchical) to estimate number of clusters
- N = number of clusters (conservative lower bound)
- Alternative simple approach: N = M * average correlation + (1 - avg correlation) — fast but less accurate

**Step 3: Compute DSR per experiment**
- For each cluster (or for baseline B0d-honest):
  - Compute cluster IVP (inverse variance portfolio) return series
  - Compute SR, skewness, kurtosis, T
  - Compute E[max SR_null] using False Strategy Theorem
  - Compute sigma(SR) using non-normal formula
  - Compute DSR = PSR(E[max SR_null])

**Step 4: Decision rule**
- DSR ≥ 0.95 (95% confidence): Strategy is statistically significant
- DSR < 0.95: Strategy may be false discovery / overfit
- Compare DSR of B0d-honest vs prior experiments (E40d, etc.)

### 1.7 kumo-qc Specific Considerations

- **Experiment correlation is HIGH:** Most experiments are variants of the same BCT signal stack (same entry logic, different exits/gates). They will correlate strongly → N << M.
- **Sample length is SHORT:** 252 trading days is near minimum for SR significance. DSR will be sensitive to this.
- **Non-normality:** BCT strategies have positively skewed returns (trend following, cutting losers, letting winners run) → this actually *helps* DSR (increases it).
- **Expected outcome:** Given 50+ experiments on the same core signal, E[max SR_null] will be substantially > 0. DSR of baseline may be modest even if raw Sharpe looks good.

---

## 2. Probability of Backtest Overfitting (PBO)

### 2.1 What It Corrects For
PBO quantifies the probability that the best-performing configuration in-sample was selected by luck rather than true edge. Uses Combinatorially Symmetric Cross-Validation (CSCV).

### 2.2 CSCV Method Steps

1. **Aggregate PnLs:** Build matrix of daily returns, rows = days, columns = experiments (N trials)
2. **Split into S groups:** Divide time series into S sequential, non-overlapping subsets (S even, e.g., S=10)
3. **Generate combinations:** All C(S, S/2) combinations — each has S/2 groups as "training" and S/2 as "test"
4. **Train-test split:** For each combination, first half = IS (in-sample), second half = OOS (out-of-sample)
5. **Compute SR per trial:** For each combination, compute SR for each trial in IS and OOS
6. **Rank analysis:** For each combination, find best IS trial → measure its rank in OOS
   - omega = (rank - 0.5) / N  (relative rank, 0.5 = median)
   - lambda = log(omega / (1 - omega))  (logit)
7. **Estimate PBO:** PBO = probability(lambda < 0) = fraction of times best-IS trial underperforms median-OOS

### 2.3 Inputs We Already Have

| Input | Source | Status |
|---|---|---|
| Experiment Sharpe ratios | bt-results.csv | ✅ Point estimates only |
| Experiment count | bt-results.csv | ✅ ~50-60 |

### 2.4 Inputs We Need to Generate

| Input | How to Generate | Effort |
|---|---|---|
| **Daily PnL matrix (T × N)** | Modify `main.py` to output daily portfolio returns for each experiment | **HIGH** — requires code change + re-runs |
| S groups for time-series split | Automatic once matrix available | Low |
| Combinations C(S, S/2) | itertools.combinations | Low |

### 2.5 Concrete Application Steps

**Step 1: Build daily PnL matrix**
- Same as DSR Step 1 — need daily returns for ALL experiments
- Store as `research/pbo_matrix.csv` or similar
- If re-running is prohibitive: approximate using available equity curves from QC backtest exports (if available via API)

**Step 2: Implement CSCV in Python**
```python
import numpy as np
import pandas as pd
from itertools import combinations
from scipy.stats import gaussian_kde
from scipy.integrate import quad

def compute_pbo(returns_df, S=10):
    """
    returns_df: DataFrame, index=dates, columns=experiment_ids, values=daily returns
    S: number of groups (must be even)
    """
    T, N = returns_df.shape
    chunk = T // S
    groups = [returns_df.iloc[i*chunk:(i+1)*chunk] for i in range(S)]
    
    combinations_list = list(combinations(range(S), S//2))
    lambdas = []
    
    for combo in combinations_list:
        is_groups = [groups[i] for i in combo]
        oos_groups = [groups[i] for i in range(S) if i not in combo]
        
        is_returns = pd.concat(is_groups)
        oos_returns = pd.concat(oos_groups)
        
        # Compute Sharpe for each trial
        is_sr = is_returns.apply(lambda x: x.mean() / x.std() * np.sqrt(252))
        oos_sr = oos_returns.apply(lambda x: x.mean() / x.std() * np.sqrt(252))
        
        # Best IS trial
        best_idx = is_sr.idxmax()
        
        # Rank in OOS
        sorted_oos = oos_sr.sort_values(ascending=False)
        rank = sorted_oos.index.get_loc(best_idx) + 1
        omega = (rank - 0.5) / N
        
        # Logit
        lambda_c = np.log(omega / (1 - omega))
        lambdas.append(lambda_c)
    
    # KDE and PBO
    lambdas = np.array(lambdas)
    kde = gaussian_kde(lambdas)
    pbo, _ = quad(kde, -np.inf, 0)
    return pbo, lambdas
```

**Step 3: Interpretation**
- PBO < 0.3: Low overfitting risk
- PBO 0.3-0.7: Moderate concern
- PBO > 0.7: High overfitting risk — best IS config unlikely to generalize
- Plot IS SR vs OOS SR scatter to visualize degradation

### 2.6 kumo-qc Specific Considerations

- **Short time series:** FY2025 = ~252 trading days. With S=10, each group = ~25 days. This is short for reliable SR estimation.
- **Recommendation:** Use S=6 (groups of ~42 days) or focus on multi-year windows (W1-W6) to build a longer combined matrix.
- **High correlation across experiments:** All experiments share the same core BCT logic → in CSCV, they will degrade similarly → PBO may be artificially low (experiments correlate, so best-IS is also best-OOS by correlation). This is a feature, not a bug — it tells us the *core signal* is or is not overfit.
- **Key insight:** PBO should be computed on experiments that vary PARAMETERS (e.g., ADX period, stop types), not just gate variants. If we only have gate on/off variants, PBO is less informative.

---

## 3. Combinatorial Purged Cross-Validation (CPCV)

### 3.1 What It Corrects For
CPCV extends CSCV with two critical safeguards for financial time series:
- **Purging:** Removes overlapping observations between train and test to prevent look-ahead bias
- **Embargo:** Adds buffer period after test set to prevent leakage from auto-correlated features/market reactions

### 3.2 How It Applies to kumo-qc

Our data: FY2025 (Jan-Dec 2025, ~252 trading days), single path.

**Standard k-fold CV is invalid here because:**
- BCT signals use Ichimoku (26-day lookback), ADX (9-day), 200-day MA
- Today's signal depends on past 200 days → random train/test splits leak future information into training
- Purging must remove at least 200 days before/after each test fold

**CPCV for single-year data (N groups, k test groups):**
- N = 6 groups (each ~42 trading days)
- k = 2 test groups per combination
- Number of combinations = C(6,2) = 15
- For each combination:
  - Test = 2 groups (consecutive or combinatorial)
  - Train = remaining 4 groups
  - **Purge:** Remove 200 trading days (~9 months!) from train adjacent to test → with 252 total days, this leaves almost nothing
  - **Embargo:** Remove additional e.g., 10 days after test

### 3.3 Inputs We Already Have

| Input | Source | Status |
|---|---|---|
| Single path backtest data | bt-results.csv | ✅ One path per experiment |
| Date ranges per window | bt-results.csv | ✅ W1-W6 defined |

### 3.4 Inputs We Need to Generate

| Input | How to Generate | Effort |
|---|---|---|
| Multi-year daily returns | Combine W1-W6 into single series (2025 Q1-Q4) | Medium — need daily data, not just window aggregates |
| Purge/embargo period definition | Determined by max signal lookback (200 days) + market lag | Low — theoretical |
| Group structure with purge boundaries | Implement in Python | Medium |

### 3.5 Concrete Application Steps

**Step 1: Build multi-year daily return series**
- W1 (Q1) + W2 (Q2) + W3 (Q3) + W4 (Q4) = full FY2025
- OR use 2024 + 2025 if available (we don't have 2024 BT data yet)
- Daily portfolio equity % change needed

**Step 2: Define purge/embargo**
- Purge length = max(26-day Kijun lookback, 200-day MA lookback, ADX warm-up) = 200 trading days minimum
- Embargo = 5-10 trading days (market reaction lag)
- **Reality check:** With 252 days and 200-day purge, we can only have ~1-2 test folds. CPCV may be infeasible with single-year data.

**Step 3: Implement CPCV (simplified for short series)**
```python
def cpcv_purged(returns_df, n_groups=6, k_test=2, purge_days=200, embargo_days=10):
    """
    Simplified CPCV for single-year data.
    Returns: list of (train_idx, test_idx) tuples with purging applied.
    """
    dates = returns_df.index
    n = len(dates)
    group_size = n // n_groups
    
    groups = []
    for i in range(n_groups):
        start = i * group_size
        end = min((i+1) * group_size, n)
        groups.append((start, end))
    
    splits = []
    for test_combo in combinations(range(n_groups), k_test):
        # Test indices
        test_idx = []
        for g in test_combo:
            test_idx.extend(range(groups[g][0], groups[g][1]))
        
        # Train indices: all non-test
        train_idx = [i for i in range(n) if i not in test_idx]
        
        # Purge: remove purge_days before and after test
        test_start = min(test_idx)
        test_end = max(test_idx)
        train_idx = [i for i in train_idx 
                     if i < test_start - purge_days or i > test_end + purge_days]
        
        # Embargo: remove embargo_days after test
        train_idx = [i for i in train_idx if i > test_end + embargo_days or i < test_start]
        
        if len(train_idx) > 50:  # minimum viable training set
            splits.append((train_idx, test_idx))
    
    return splits
```

**Step 4: Run backtest per split**
- For each (train, test) split: re-run B0d-honest on train period, evaluate on test period
- This requires QC backtest API or local LEAN runs for each split
- **Computational cost:** 15 splits × ~1 minute per split = 15 minutes for one experiment

### 3.6 kumo-qc Specific Considerations

- **Feasibility concern:** Single-year data (252 days) with 200-day purge makes CPCV nearly impossible. We need multi-year data.
- **Alternative:** Use W1-W6 windows as "natural" train/test splits (Q1 train → Q2 test, etc.). This is walk-forward, not CPCV, but respects temporal ordering.
- **Recommendation:** Defer full CPCV until we have 2024+2025 multi-year backtest data. Use walk-forward W1→W2→W3→W4 as interim robustness check.

---

## 4. Block Bootstrap for Sharpe Confidence Intervals

### 4.1 What It Corrects For
Standard bootstrap assumes i.i.d. returns — invalid for financial time series with auto-correlation and volatility clustering. Block bootstrap preserves local time-series structure by resampling contiguous blocks.

### 4.2 Method

1. **Choose block size b:** Based on autocorrelation structure. Rule of thumb: b ≈ n^(1/3) or select via ACF (autocorrelation function) where ACF dies out.
   - For 252 daily returns: b ≈ 6-10 days
   - For weekly returns: b ≈ 2-4 weeks

2. **Circular block bootstrap (CBB):**
   - Arrange data in circle (wrap-around) to avoid endpoint bias
   - Randomly select starting points
   - Extract blocks of length b until bootstrap sample = original length

3. **Compute statistic per bootstrap sample:**
   - Calculate Sharpe ratio from bootstrapped returns
   - Repeat B times (B ≥ 1,000 for reliable CIs)

4. **Confidence interval:**
   - Percentile method: [2.5th percentile, 97.5th percentile] of bootstrapped SRs
   - Studentized method (more accurate): uses bootstrap standard error

### 4.3 Formula for Sharpe Variance (Asymptotic, Non-IID)

```
Var(SR_hat) ≈ (1/n) * (1 + SR²/2) + HAC correction for autocorrelation
```

Ledoit & Wolf (2008) recommend HAC (Heteroskedasticity and Autocorrelation Consistent) variance estimator for non-i.i.d. returns.

### 4.4 Inputs We Already Have

| Input | Source | Status |
|---|---|---|
| Daily returns for one experiment | Could extract from QC backtest | ⚠️ Partial — not systematically stored |
| Sample size (n) | bt-results.csv | ✅ ~252 days for FY2025 |

### 4.5 Inputs We Need to Generate

| Input | How to Generate | Effort |
|---|---|---|
| Daily return series | Modify `main.py` to log daily returns | **HIGH** |
| Block size selection | ACF analysis on return series | Medium |
| Bootstrap implementation | Python: `arch` package or custom CBB | Low |

### 4.6 Concrete Application Steps

**Step 1: Get daily returns**
- Same dependency as DSR/PBO

**Step 2: Implement block bootstrap in Python**
```python
import numpy as np

def circular_block_bootstrap(returns, block_size, n_bootstrap=1000):
    """
    returns: array of daily returns
    block_size: int, length of each block
    n_bootstrap: number of bootstrap samples
    """
    n = len(returns)
    n_blocks = int(np.ceil(n / block_size))
    
    sr_bootstraps = []
    
    for _ in range(n_bootstrap):
        # Circular: indices wrap around
        starts = np.random.randint(0, n, size=n_blocks)
        sample = []
        for start in starts:
            block = [returns[(start + j) % n] for j in range(block_size)]
            sample.extend(block)
        sample = np.array(sample[:n])  # truncate to original length
        
        # Compute Sharpe (annualized)
        sr = sample.mean() / sample.std() * np.sqrt(252)
        sr_bootstraps.append(sr)
    
    return np.array(sr_bootstraps)

# Usage
returns = load_daily_returns('b0d_honest')
sr_boot = circular_block_bootstrap(returns, block_size=10, n_bootstrap=5000)
ci_lower = np.percentile(sr_boot, 2.5)
ci_upper = np.percentile(sr_boot, 97.5)
print(f"B0d-honest SR: 0.831, 95% CI: [{ci_lower:.3f}, {ci_upper:.3f}]")
```

**Step 3: Block size selection**
- Compute ACF of returns up to lag 20
- Choose b where ACF drops below significance threshold (e.g., 2/sqrt(n))
- Alternative: use `arch.bootstrap.CircularBlockBootstrap` with automatic block size via Politis & Romano (1994) method

**Step 4: Hypothesis testing**
- Test H0: SR ≤ 0 vs Ha: SR > 0
- Reject H0 if lower bound of CI > 0
- Compare two experiments: test H0: SR1 = SR2 using difference of bootstrapped SRs

### 4.7 kumo-qc Specific Considerations

- **Short series = wide CIs:** With 252 days, even block bootstrap will produce wide confidence intervals. B0d-honest 0.831 may have 95% CI of [0.2, 1.4].
- **Positive autocorrelation:** Trend-following strategies have positive return autocorrelation (momentum persists) → block bootstrap with appropriate block size is ESSENTIAL. Independent bootstrap would underestimate variance.
- **Weekly vs daily:** We could bootstrap weekly returns (52 weeks) with block size 2-4 weeks. This reduces noise but loses daily resolution.

---

## 5. Unified Application Plan for kumo-qc

### 5.1 Priority Ranking (by actionability)

| Priority | Method | Actionability | Key Dependency | Effort |
|---|---|---|---|---|
| **P1** | Block Bootstrap | HIGH — can implement with minimal data | Daily returns for ONE experiment | 1-2 days |
| **P2** | PBO (CSCV) | MEDIUM — needs multi-experiment matrix | Daily returns for ALL experiments | 3-5 days |
| **P3** | DSR | MEDIUM — needs clustering + all returns | Daily returns + correlation matrix | 3-5 days |
| **P4** | CPCV | LOW — infeasible with single-year data | Multi-year (2+ years) daily returns | Defer to 2026 |

### 5.2 Immediate Next Step (P1: Block Bootstrap)

**Goal:** Compute 95% confidence interval for B0d-honest Sharpe ratio.

**Approach:**
1. Extract daily equity curve from existing QC backtest (if available via API)
2. OR: Run B0d-honest locally with `main.py` modified to log daily portfolio value
3. Apply circular block bootstrap (block size = 10 days)
4. Report 95% CI and whether it excludes zero

**Code location:** `scripts/bootstrap_sharpe.py`

### 5.3 Medium-Term: Build Daily Returns Database

**Goal:** Enable DSR, PBO, and future CPCV.

**Implementation:**
1. Modify `algorithm/performance_bct/main.py`:
   - Add `self.daily_returns = []` in `Initialize()`
   - In `OnEndOfDay()` or `_rebalance()`, append `self.portfolio.total_portfolio_value`
   - In `OnEndOfAlgorithm()`, write to `daily_returns/<experiment_id>.csv` or ObjectStore
2. Re-run B0d-honest + top 5 experiments with this logging enabled
3. Store in `research/daily_returns/` or QC ObjectStore

### 5.4 Long-Term: Multi-Year Data for CPCV

**Goal:** Enable rigorous purged cross-validation.

**Requirements:**
- 2024 + 2025 backtest data (504 trading days minimum)
- Or: 2023-2025 (756 trading days — ideal)
- Each experiment run across full multi-year period
- CPCV with S=10, purge=200 days becomes feasible with 750+ days

---

## 6. Data Inventory: What We Have vs What We Need

### 6.1 Already Have ✅

| Data | Location | Format |
|---|---|---|
| Experiment metadata (ID, branch, Sharpe, return%, orders, WR, DD) | `bt-results.csv` | CSV, ~60 rows |
| Window-level results (W1-W6) | `bt-results.csv` | Aggregated per window |
| QC backtest IDs | `bt-results.csv` | Can fetch via API |

### 6.2 Need to Generate 🔧

| Data | Priority | Generation Method | Estimated Effort |
|---|---|---|---|
| Daily portfolio equity/value per experiment | **CRITICAL** | Modify `main.py` + re-run | 2-3 days |
| Daily returns (derived from equity) | **CRITICAL** | Compute from equity | 1 hour |
| Per-trade timestamps + P&L | Medium | QC backtest export / API | 1 day |
| Multi-year (2024-2025) backtests | Medium | Run BT on extended date range | 2-3 days |
| Signal timestamps (entry/exit dates) | Low | Log in `main.py` | 4 hours |

### 6.3 Quick Win: Fetch Existing QC Data

Some data MAY already exist in QC cloud backtest results:
- QC API endpoint: `/backtests/<project_id>/<backtest_id>/read` returns equity curve, orders, statistics
- We have BT IDs for B0d-honest and experiments
- **Action:** Use `scripts/fetch_specific_backtest.py` to download equity curves from QC API
- **Risk:** QC may not store daily equity for all backtests; may only store summary statistics

---

## 7. Implementation Timeline

| Phase | Task | Duration | Deliverable |
|---|---|---|---|
| **Phase 1** (Week 1) | Modify `main.py` to log daily equity; run B0d-honest | 2-3 days | `daily_returns/b0d_honest_fy2025.csv` |
| **Phase 1b** | Block bootstrap CI for B0d-honest | 1 day | `scripts/bootstrap_sharpe.py` + CI report |
| **Phase 2** (Week 2) | Re-run top 5 experiments with logging | 3 days | `daily_returns/*.csv` for 6 experiments |
| **Phase 2b** | PBO analysis on 6-experiment matrix | 2 days | `research/pbo_analysis.py` + report |
| **Phase 3** (Week 3) | Cluster all 50 experiments; compute DSR | 3 days | `research/dsr_analysis.py` + report |
| **Phase 4** (Month 2) | Multi-year backtest (2024-2025); CPCV | 2 weeks | `research/cpcv_analysis.py` + report |

---

## 8. Risk Assessment & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| QC API doesn't store daily equity curves | HIGH — blocks all analysis | Modify `main.py` to log locally; re-run experiments |
| Re-running 50 experiments is prohibitive | HIGH — time/compute cost | Focus on B0d + top 5; approximate rest using available Sharpe only |
| Single-year data too short for robust CIs | MEDIUM — wide CIs | Acknowledge in report; use W1-W6 as pseudo-independent samples |
| Experiments are highly correlated (same core signal) | MEDIUM — N << M | Use clustering to estimate N; report as conservative bound |
| Daily logging impacts BT performance | LOW | Logging is negligible overhead vs signal computation |

---

## 9. References

1. Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality." *Journal of Portfolio Management*, 40(5), 94-107.
2. Bailey, D.H. et al. (2016). "The Probability of Backtest Overfitting." *Journal of Computational Finance*, 20(4), 39-69.
3. López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
4. López de Prado, M. (2020). *Machine Learning for Asset Managers*. Cambridge.
5. Ledoit, O. & Wolf, M. (2008). "Robust Performance Hypothesis Testing with the Sharpe Ratio." *Journal of Empirical Finance*, 15(5), 850-859.
6. Politis, D.N. & Romano, J.P. (1992). "A Circular Block-Resampling Procedure for Stationary Data." *Exploring the Limits of Bootstrap*, Wiley.
7. Riondato, M. (2018). "Sharpe Ratio: Estimation, Confidence Intervals, and Hypothesis Testing." Two Sigma Technical Report.
8. Andrews, D.W.K. (1991). "Heteroskedasticity and Autocorrelation Consistent Covariance Matrix Estimation." *Econometrica*, 59(3), 817-858.

---

**Document status:** Research complete, ready for fintrack/strategic review before implementation.
**Next action:** Await authorization to modify `main.py` for daily logging (Phase 1).
