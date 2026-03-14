import os
import time
import logging
import json
from typing import Optional, List, Dict, Tuple, Any

from src.utils.token_budget import ContextWindowBudget, ModelTier, ModelConfig

logger = logging.getLogger(__name__)

class LLMClient:
    """
    A unified LLM client wrapper that supports calling Gemini with automatic retry, 
    timeout, and budget tracking constraints.
    """
    
    def __init__(self, budget: ContextWindowBudget, api_key: Optional[str] = None):
        self._budget = budget
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._available = True
        
        if not self._api_key:
            self._available = False
            logger.warning("No Gemini API key found in environment or kwargs. LLMClient will not make API calls.")

    def is_available(self) -> bool:
        """Return whether an API key was found and the client can make calls."""
        return self._available

    def _call_gemini_sdk(self, model_name: str, prompt: str, system_instruction: str,
                         max_output_tokens: int, temperature: float) -> Tuple[str, int, int]:
        """Call Gemini via google.generativeai SDK."""
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google.generativeai is not installed.")

        genai.configure(api_key=self._api_key)
        
        kwargs = {}
        if system_instruction:
             kwargs["system_instruction"] = system_instruction
             
        model = genai.GenerativeModel(model_name, **kwargs)
        
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
        
        response = model.generate_content(prompt, generation_config=generation_config)
        
        input_token_count = 0
        output_token_count = 0
        if hasattr(response, "usage_metadata"):
            input_token_count = getattr(response.usage_metadata, "prompt_token_count", 0)
            output_token_count = getattr(response.usage_metadata, "candidates_token_count", 0)
            
        return response.text, input_token_count, output_token_count


    def _call_gemini_rest(self, model_name: str, prompt: str, system_instruction: str,
                          max_output_tokens: int, temperature: float) -> Tuple[str, int, int]:
        """Fallback to call Gemini via REST API."""
        try:
            import requests
        except ImportError:
            raise ImportError("requests is not installed.")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self._api_key}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        body: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_output_tokens,
                "temperature": temperature
            }
        }
        
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
            
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        
        data = resp.json()
        
        text = ""
        if "candidates" in data and len(data["candidates"]) > 0:
            if "content" in data["candidates"][0] and "parts" in data["candidates"][0]["content"]:
                parts = data["candidates"][0]["content"]["parts"]
                text = "".join([p.get("text", "") for p in parts])
                
        input_token_count = 0
        output_token_count = 0
        if "usageMetadata" in data:
            input_token_count = data["usageMetadata"].get("promptTokenCount", 0)
            output_token_count = data["usageMetadata"].get("candidatesTokenCount", 0)
            
        # Optional fallback token estimation if omitted by the API
        if input_token_count == 0:
            input_token_count = self._budget.estimate_tokens(prompt + (system_instruction or ""))
        if output_token_count == 0:
            output_token_count = self._budget.estimate_tokens(text)
            
        return text, input_token_count, output_token_count


    def generate(self, prompt: str, tier: ModelTier = ModelTier.BULK, 
                 system_instruction: str = "", max_output_tokens: int = 1024,
                 temperature: float = 0.3, task_description: str = "") -> Optional[str]:
        """Full LLM call with budget tracking."""
        if not self.is_available():
            return None
            
        # a) Estimate input tokens
        estimated_input_tokens = self._budget.estimate_tokens(prompt + (system_instruction or ""))
        
        # b + c) Check budget and skip if necessary
        should_skip, reason = self._budget.should_skip(estimated_input_tokens, tier)
        if should_skip:
            logger.warning(f"Skipping LLM call. Reason: {reason}")
            return None
            
        # d) Select model based on budget tracking parameters
        model_config = self._budget.select_model(tier)
        model_name = model_config.name
        
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                # e) Make the API call, trying Python SDK first followed by REST fallback
                try:
                    text, in_tokens, out_tokens = self._call_gemini_sdk(
                        model_name, prompt, system_instruction, max_output_tokens, temperature
                    )
                except ImportError:
                    text, in_tokens, out_tokens = self._call_gemini_rest(
                        model_name, prompt, system_instruction, max_output_tokens, temperature
                    )
                    
                # In case extraction didn't populate tokens, ensure we have an estimate for logging
                if in_tokens == 0:
                    in_tokens = estimated_input_tokens
                if out_tokens == 0:
                    out_tokens = self._budget.estimate_tokens(text)
                    
                # f) Record successfully completed usage in budget tracker
                self._budget.record_usage(model_config, in_tokens, out_tokens, task_description)
                
                logger.info(f"LLM Call successful. Model: {model_name}, In: {in_tokens}, Out: {out_tokens}, Task: {task_description}")
                
                # Enforce minimum time interval between active requests
                time.sleep(1.0)
                
                # g) Return generated text
                return text
                
            except Exception as e:
                logger.error(f"Error calling LLM (attempt {attempt + 1}/{max_retries + 1}): {e}")
                if attempt < max_retries:
                    time.sleep(2.0)
                else:
                    return None
                    
        return None

    def generate_batch(self, prompts: List[Dict[str, str]], tier: ModelTier = ModelTier.BULK,
                       delay_seconds: float = 1.0) -> List[Optional[str]]:
        """Process a batch of prompts sequentially with a delay between calls to respect rate limits."""
        results = []
        for i, item in enumerate(prompts):
            if i > 0 and i % 10 == 0:
                logger.info(f"Batch generation progress: {i}/{len(prompts)} completed.")
                
            prompt = item.get("prompt", "")
            task_description = item.get("task_description", "")
            
            result = self.generate(
                prompt=prompt,
                tier=tier,
                task_description=task_description
            )
            results.append(result)
            
            if i < len(prompts) - 1:
                time.sleep(delay_seconds)
                
        return results
