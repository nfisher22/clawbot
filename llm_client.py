#!/usr/bin/env python3
"""
Hatfield LLM Client — auto-fallback chain
Primary: gpt-4o-mini
Fallback: gpt-3.5-turbo
"""
import os
from openai import OpenAI

FALLBACK_CHAIN = ["gpt-4o-mini", "gpt-3.5-turbo"]

def chat_with_fallback(messages, model=None, max_tokens=2000, temperature=0.7):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    primary = model or os.getenv("MODEL_NAME", "gpt-4o-mini")
    chain = [primary] + [m for m in FALLBACK_CHAIN if m != primary]
    last_error = None
    for attempt_model in chain:
        try:
            response = client.chat.completions.create(
                model=attempt_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            if attempt_model != primary:
                print(f"[llm_client] Fell back to {attempt_model} after primary failed")
            return response.choices[0].message.content
        except Exception as e:
            print(f"[llm_client] {attempt_model} failed: {e}")
            last_error = e
            continue
    raise Exception(f"All models in fallback chain failed. Last error: {last_error}")
