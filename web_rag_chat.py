#!/usr/bin/env python3
"""
Enhanced Chat Mode for Web-RAG System
Adds conversation memory, source browsing, and better UX
"""

import requests
import subprocess
import json
import time
import hashlib
import pickle
import argparse
import sys
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

# ============================================================================
# Configuration
# ============================================================================

@dataclass
class Config:
    searxng_url: str = "http://127.0.0.1:8888/search"
    max_sources: int = 50
    cache_enabled: bool = True
    cache_dir: str = "./cache"
    conversation_history_limit: int = 10
    parallel_engines: bool = True
    model: str = "joe-speedboat/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b"
    engines: List[str] = None
    
    def __post_init__(self):
        if self.engines is None:
            self.engines = ['google', 'bing', 'duckduckgo', 'wikipedia', 'arxiv']

# ============================================================================
# Cache System
# ============================================================================

class SearchCache:
    def __init__(self, cache_dir: str, enabled: bool = True):
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        if enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_key(self, query: str) -> str:
        return hashlib.md5(query.encode()).hexdigest()
    
    def get(self, query: str) -> Optional[Dict]:
        if not self.enabled:
            return None
        key = self._get_key(query)
        cache_file = self.cache_dir / key
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    cached = pickle.load(f)
                    if time.time() - cached['timestamp'] < 3600:
                        return cached['data']
            except Exception:
                pass
        return None
    
    def set(self, query: str, data: Dict):
        if not self.enabled:
            return
        key = self._get_key(query)
        with open(self.cache_dir / key, 'wb') as f:
            pickle.dump({'timestamp': time.time(), 'data': data}, f)

# ============================================================================
# SearXNG Client
# ============================================================================

class SearXNGClient:
    def __init__(self, config: Config, cache: SearchCache):
        self.config = config
        self.cache = cache
    
    def search_single_engine(self, query: str, engine: str) -> List[Dict]:
        try:
            encoded = quote_plus(query)
            url = f"{self.config.searxng_url}?q={encoded}&format=json&engines={engine}"
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            return data.get('results', [])
        except Exception:
            return []
    
    def search_parallel(self, query: str) -> List[Dict]:
        all_results = []
        
        with ThreadPoolExecutor(max_workers=len(self.config.engines)) as executor:
            future_to_engine = {
                executor.submit(self.search_single_engine, query, engine): engine 
                for engine in self.config.engines
            }
            
            for future in as_completed(future_to_engine):
                engine = future_to_engine[future]
                try:
                    results = future.result()
                    if results:
                        print(f"  ✓ {engine}: {len(results)} results", file=sys.stderr)
                    all_results.extend(results)
                except Exception:
                    print(f"  ✗ {engine}: failed", file=sys.stderr)
        
        # Remove duplicates
        seen_urls = set()
        unique_results = []
        for result in all_results:
            url = result.get('url', '')
            if url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)
        
        return unique_results
    
    def search(self, query: str) -> List[Dict]:
        cached = self.cache.get(query)
        if cached:
            print(f"📦 Using cached results", file=sys.stderr)
            return cached.get('results', [])
        
        print(f"🔍 Searching for: {query[:50]}...", file=sys.stderr)
        
        if self.config.parallel_engines:
            results = self.search_parallel(query)
        else:
            results = self.search_single_engine(query, 'all')
        
        results = results[:self.config.max_sources]
        self.cache.set(query, {'results': results, 'timestamp': time.time()})
        
        print(f"✅ Found {len(results)} unique sources", file=sys.stderr)
        return results

# ============================================================================
# Ollama Client
# ============================================================================

class OllamaClient:
    def __init__(self, model: str):
        self.model = model
    
    def generate(self, prompt: str) -> str:
        try:
            result = subprocess.run(
                ["ollama", "run", self.model, "--hidethinking"],
                input=prompt.encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            if result.returncode == 0:
                return result.stdout.decode()
            else:
                return f"Error: {result.stderr.decode()[:200]}"
        except Exception as e:
            return f"Error: {str(e)}"

# ============================================================================
# Conversation Manager with Enhanced Features
# ============================================================================

class ConversationManager:
    def __init__(self, limit: int = 10):
        self.history: List[Dict] = []
        self.limit = limit
    
    def add_exchange(self, question: str, answer: str, sources: List[str]):
        self.history.append({
            'question': question,
            'answer': answer,
            'sources': sources,
            'timestamp': datetime.now().strftime("%H:%M:%S")
        })
        if len(self.history) > self.limit:
            self.history.pop(0)
    
    def get_context(self) -> str:
        """Get recent conversation for context"""
        if not self.history:
            return ""
        
        context_parts = []
        for exchange in self.history[-3:]:  # Last 3 exchanges
            context_parts.append(f"Previous Q: {exchange['question']}")
            context_parts.append(f"Previous A: {exchange['answer'][:200]}")
        
        return "\n".join(context_parts)
    
    def display_history(self):
        """Show conversation history"""
        if not self.history:
            print("\n📜 No conversation history yet.")
            return
        
        print("\n" + "="*60)
        print("📜 CONVERSATION HISTORY")
        print("="*60)
        for i, exchange in enumerate(self.history, 1):
            print(f"\n[{i}] {exchange['timestamp']}")
            print(f"Q: {exchange['question']}")
            print(f"A: {exchange['answer'][:150]}...")
            print(f"📚 Sources: {len(exchange['sources'])}")
        print("="*60)
    
    def get_last_sources(self) -> List[str]:
        """Get sources from last response"""
        if self.history:
            return self.history[-1]['sources']
        return []

# ============================================================================
# Main Chat System
# ============================================================================

class WebRAGChat:
    def __init__(self, config: Config):
        self.config = config
        self.cache = SearchCache(config.cache_dir, config.cache_enabled)
        self.searxng = SearXNGClient(config, self.cache)
        self.ollama = OllamaClient(config.model)
        self.conversation = ConversationManager(config.conversation_history_limit)
    
    def _format_sources(self, results: List[Dict], max_sources: int = 15) -> Tuple[str, List[str]]:
        """Format sources for prompt"""
        source_lines = []
        source_urls = []
        
        for i, r in enumerate(results[:max_sources], 1):
            url = r.get('url', '')
            title = r.get('title', 'Untitled')[:100]
            
            # Skip obvious junk
            if any(x in url.lower() for x in ['pdf24', 'ilovepdf', 'adobe.com/reader', 'tools.pdf']):
                continue
            
            source_lines.append(f"{i}. {title}\n   {url}")
            source_urls.append(url)
        
        return "\n\n".join(source_lines), source_urls
    
    def _build_prompt(self, question: str, sources_text: str, context: str) -> str:
        """Build prompt with conversation context"""
        if context:
            context_section = f"Previous conversation context:\n{context}\n\n"
        else:
            context_section = ""
        
        prompt = f"""{context_section}Answer the question using ONLY these sources:

{sources_text}

Question: {question}

Guidelines:
- Base your answer ONLY on the sources above
- If the sources don't contain enough information, say so clearly
- Reference specific sources when possible (e.g., "According to source 1...")
- Be concise but thorough

Answer:"""
        
        return prompt
    
    def process_question(self, question: str) -> Dict[str, Any]:
        """Process a single question and return response"""
        start_time = time.time()
        
        # Get conversation context
        context = self.conversation.get_context()
        
        # Search for sources
        results = self.searxng.search(question)
        
        if not results:
            answer = "I couldn't find any relevant sources to answer your question. Please try rephrasing or asking about a different topic."
            self.conversation.add_exchange(question, answer, [])
            return {
                'answer': answer,
                'sources': [],
                'num_sources': 0,
                'response_time': time.time() - start_time
            }
        
        # Format sources
        sources_text, source_urls = self._format_sources(results, max_sources=15)
        
        if not sources_text:
            answer = "Found sources but couldn't format them properly."
            self.conversation.add_exchange(question, answer, [])
            return {
                'answer': answer,
                'sources': [],
                'num_sources': len(results),
                'response_time': time.time() - start_time
            }
        
        # Generate answer
        print("🤔 Generating answer...", file=sys.stderr)
        prompt = self._build_prompt(question, sources_text, context)
        answer = self.ollama.generate(prompt)
        
        # Store in conversation
        self.conversation.add_exchange(question, answer, source_urls)
        
        return {
            'answer': answer,
            'sources': source_urls[:10],
            'num_sources': len(results),
            'response_time': time.time() - start_time,
            'sources_text': sources_text
        }
    
    def display_sources(self, sources: List[str], max_display: int = 10):
        """Display sources nicely"""
        if not sources:
            print("\n📚 No sources available for this response.")
            return
        
        print("\n📚 SOURCES USED:")
        print("-" * 40)
        for i, url in enumerate(sources[:max_display], 1):
            # Truncate long URLs for display
            display_url = url if len(url) < 80 else url[:77] + "..."
            print(f"{i}. {display_url}")
        
        if len(sources) > max_display:
            print(f"... and {len(sources) - max_display} more")
    
    def interactive_chat(self):
        """Main interactive chat loop"""
        print("\n" + "="*70)
        print("🤖 WEB-RAG CHAT ASSISTANT - Enhanced Chat Mode")
        print("="*70)
        print(f"📚 Search Engines: {', '.join(self.config.engines)}")
        print(f"🧠 Model: {self.config.model}")
        print(f"💾 Cache: {'ON' if self.config.cache_enabled else 'OFF'}")
        print(f"📝 Memory: Last {self.config.conversation_history_limit} exchanges")
        print("\nCOMMANDS:")
        print("  /history    - Show conversation history")
        print("  /sources    - Show sources from last response")
        print("  /clear      - Clear conversation history")
        print("  /status     - Show system status")
        print("  /help       - Show this help")
        print("  /quit       - Exit chat")
        print("="*70)
        
        while True:
            try:
                # Get user input
                user_input = input("\n💭 You: ").strip()
                
                if not user_input:
                    continue
                
                # Handle commands
                if user_input.lower() == '/quit':
                    print("\n👋 Goodbye! Thanks for chatting.")
                    break
                
                elif user_input.lower() == '/history':
                    self.conversation.display_history()
                    continue
                
                elif user_input.lower() == '/sources':
                    sources = self.conversation.get_last_sources()
                    self.display_sources(sources)
                    continue
                
                elif user_input.lower() == '/clear':
                    self.conversation = ConversationManager(self.config.conversation_history_limit)
                    print("✅ Conversation history cleared!")
                    continue
                
                elif user_input.lower() == '/status':
                    print("\n📊 SYSTEM STATUS")
                    print(f"  Memory usage: {len(self.conversation.history)}/{self.config.conversation_history_limit} exchanges")
                    print(f"  Cache: {'Enabled' if self.config.cache_enabled else 'Disabled'}")
                    print(f"  Parallel search: {'ON' if self.config.parallel_engines else 'OFF'}")
                    print(f"  Model: {self.config.model}")
                    continue
                
                elif user_input.lower() == '/help':
                    print("\n📖 COMMAND REFERENCE")
                    print("  /history    - View full conversation history")
                    print("  /sources    - Show sources from last response")
                    print("  /clear      - Start a fresh conversation")
                    print("  /status     - Check system health and settings")
                    print("  /help       - Show this help")
                    print("  /quit       - Exit the chat")
                    continue
                
                # Process normal question
                print("\n🔍 Processing your question...", file=sys.stderr)
                result = self.process_question(user_input)
                
                # Display answer
                print(f"\n🤖 Assistant: {result['answer']}")
                
                # Display metadata
                print(f"\n📊 [Sources: {result['num_sources']} | Time: {result['response_time']:.2f}s]")
                
                # Ask if user wants to see sources
                if result['sources']:
                    show_sources = input("\n📚 Show sources? (y/n): ").strip().lower()
                    if show_sources in ['y', 'yes']:
                        self.display_sources(result['sources'])
                
            except KeyboardInterrupt:
                print("\n\n👋 Interrupted. Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ Error: {str(e)}")
                print("Please try again or rephrase your question.")

# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Enhanced Web-RAG Chat System")
    
    parser.add_argument("--model", default="joe-speedboat/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b",
                        help="Ollama model to use")
    parser.add_argument("--max-sources", type=int, default=50,
                        help="Maximum sources to retrieve")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable search caching")
    parser.add_argument("--no-parallel", action="store_true",
                        help="Disable parallel search")
    parser.add_argument("--engines", default="google,bing,duckduckgo,wikipedia,arxiv",
                        help="Comma-separated search engines")
    
    args = parser.parse_args()
    
    config = Config(
        max_sources=args.max_sources,
        cache_enabled=not args.no_cache,
        parallel_engines=not args.no_parallel,
        model=args.model,
        engines=args.engines.split(',')
    )
    
    chat = WebRAGChat(config)
    chat.interactive_chat()

if __name__ == "__main__":
    main()
