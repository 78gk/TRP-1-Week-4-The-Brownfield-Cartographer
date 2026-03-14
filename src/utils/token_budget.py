import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

class ModelTier(str, Enum):
    """Enumeration of model tiers based on their intended use case."""
    BULK = "bulk"         # For repetitive tasks: module summaries, purpose statements
    SYNTHESIS = "synthesis"  # For complex reasoning: Day-One answers, domain clustering labels

@dataclass
class ModelConfig:
    """Configuration for a specific LLM model."""
    name: str                    # e.g., "gemini-1.5-flash", "gemini-1.5-pro"
    tier: ModelTier
    cost_per_1k_input: float     # cost in USD per 1K input tokens
    cost_per_1k_output: float    # cost in USD per 1K output tokens
    max_context_window: int      # max tokens the model accepts

class ContextWindowBudget:
    """Tracks cumulative token usage across LLM calls, enforces budget limits, 
    and aids in selecting appropriate models based on budget constraints."""

    def __init__(self, total_budget_usd: float = 1.0, models: Optional[Dict[ModelTier, ModelConfig]] = None):
        """
        Initialize the budget tracker.
        
        Args:
            total_budget_usd: Total allowable budget in USD.
            models: Dictionary mapping ModelTier to ModelConfig. If None, uses defaults.
        """
        self.total_budget_usd = total_budget_usd
        
        if models is None:
            self.models = {
                ModelTier.BULK: ModelConfig("gemini-1.5-flash", ModelTier.BULK, 0.000075, 0.0003, 1_000_000),
                ModelTier.SYNTHESIS: ModelConfig("gemini-1.5-pro", ModelTier.SYNTHESIS, 0.00125, 0.005, 2_000_000)
            }
        else:
            self.models = models

        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cost_usd: float = 0.0
        self._call_count: int = 0
        self._call_log: List[Dict] = []

    def estimate_tokens(self, text: str) -> int:
        """
        Roughly estimate the number of tokens in a text string.
        Good enough for budgeting purposes.
        
        Args:
            text: The input text.
        
        Returns:
            int: Estimated token count.
        """
        return max(1, len(text) // 4)

    def select_model(self, tier: ModelTier) -> ModelConfig:
        """
        Select the configured model for the given tier.
        If remaining budget < 10% of total, always return BULK model regardless of requested tier.
        
        Args:
            tier: The requested model tier.
            
        Returns:
            ModelConfig: The selected model configuration.
        """
        budget_utilization = self._total_cost_usd / self.total_budget_usd if self.total_budget_usd > 0 else 1.0
        
        # Fall back to BULK if remaining budget is less than 10%
        if budget_utilization > 0.9:
            logger.warning(f"Budget utilization is at {budget_utilization*100:.1f}%. Forcing BULK tier fallback.")
            return self.models.get(ModelTier.BULK, self.models[tier])
            
        return self.models[tier]

    def record_usage(self, model: ModelConfig, input_tokens: int, output_tokens: int, task_description: str = "") -> None:
        """
        Update cumulative tracking with usage from an LLM call.
        
        Args:
            model: The model configuration used.
            input_tokens: Number of input tokens consumed.
            output_tokens: Number of output tokens consumed.
            task_description: Optional description of the task performed.
        """
        cost = (input_tokens / 1000.0) * model.cost_per_1k_input + (output_tokens / 1000.0) * model.cost_per_1k_output
        
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._total_cost_usd += cost
        self._call_count += 1
        
        utilization = self._total_cost_usd / self.total_budget_usd if self.total_budget_usd > 0 else 0
        if utilization > 0.8:
            logger.warning(f"Budget utilization has exceeded 80% ({utilization*100:.1f}%)")
        
        self._call_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_name": model.name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
            "task_description": task_description
        })

    def check_budget(self, estimated_input_tokens: int, tier: ModelTier) -> bool:
        """
        Check if the estimated cost fits within remaining budget.
        
        Args:
            estimated_input_tokens: Estimated number of input tokens.
            tier: The target model tier.
            
        Returns:
            bool: True if the estimated cost is within budget, False otherwise.
        """
        model = self.select_model(tier)
        estimated_cost = (estimated_input_tokens / 1000.0) * model.cost_per_1k_input
        return (self.total_budget_usd - self._total_cost_usd) >= estimated_cost

    def get_remaining_budget(self) -> float:
        """
        Get the remaining budget in USD.
        
        Returns:
            float: Remaining budget.
        """
        return max(0.0, self.total_budget_usd - self._total_cost_usd)

    def get_usage_summary(self) -> Dict[str, Any]:
        """
        Get a summary of usage metrics.
        
        Returns:
            Dict[str, Any]: Usage summary statistics.
        """
        calls_by_model = {}
        for entry in self._call_log:
            name = entry["model_name"]
            calls_by_model[name] = calls_by_model.get(name, 0) + 1
            
        return {
            "total_calls": self._call_count,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_cost_usd": self._total_cost_usd,
            "remaining_budget_usd": self.get_remaining_budget(),
            "calls_by_model": calls_by_model,
            "budget_utilization_pct": (self._total_cost_usd / self.total_budget_usd * 100) if self.total_budget_usd > 0 else 0.0,
        }

    def get_call_log(self) -> List[Dict]:
        """
        Get the full call log.
        
        Returns:
            List[Dict]: History of all LLM calls.
        """
        return list(self._call_log)

    def should_skip(self, estimated_tokens: int, tier: ModelTier) -> Tuple[bool, str]:
        """
        Determine if an operation should be skipped due to constraints.
        
        Args:
            estimated_tokens: Estimated number of input tokens.
            tier: The model tier to use.
            
        Returns:
            Tuple[bool, str]: (should_skip, reason)
        """
        model = self.select_model(tier)
        
        if self._total_cost_usd >= self.total_budget_usd:
            return True, "Budget exhausted."
            
        if estimated_tokens > model.max_context_window:
            return True, f"Estimated tokens ({estimated_tokens}) exceed model context window ({model.max_context_window})."
            
        return False, ""
