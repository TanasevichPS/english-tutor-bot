from __future__ import annotations

import logging
import asyncio
import functools
import os
import re
import random
import io
import difflib
import json
import html as _html
import sqlite3
import time
import torch
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

# Telegram bot libraries
try:
    from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
    from telegram.constants import ParseMode
except ImportError:
    logging.warning("telegram library not available")

# Transformers for local model loading
try:
    from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
    from trl import AutoModelForCausalLMWithValueHead
except ImportError:
    pipeline = None
    AutoTokenizer = None
    AutoModelForCausalLM = None
    AutoModelForCausalLMWithValueHead = None
    logging.warning("transformers or trl library not available")

# Configuration constants
MAX_CONVERSATION_HISTORY = 50
MAX_VOCABULARY_SIZE = 1000
MAX_RECENT_EXERCISES = 8
API_TIMEOUT = 30
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 1.0

# Validate and get environment variables
def get_env_var(var_name: str, required: bool = False) -> Optional[str]:
    """Safely get environment variable with validation"""
    value = os.getenv(var_name)
    if required and not value:
        logging.error(f"Required environment git remote add origin https://github.com/TanasevichPS/english-tutor-bot.gitvariable {var_name} is not set")
        return None
    if value and len(value.strip()) == 0:
        logging.warning(f"Environment variable {var_name} is empty")
        return None
    return value

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Model Configuration
MODEL_NAME = "microsoft/DialoGPT-medium"  # или любую другую модель, которую хотите использовать

# Speech recognition libraries
try:
    import speech_recognition as sr
    from pydub import AudioSegment
    from gtts import gTTS
except ImportError:
    sr = None
    AudioSegment = None
    gTTS = None
    logging.warning("speech libraries not available")

# Input validation and sanitization
def sanitize_user_input(text: str) -> str:
    """Sanitize user input to prevent injection attacks"""
    if not isinstance(text, str):
        return ""
    
    # Remove potentially dangerous characters
    sanitized = re.sub(r'[<>"\']', '', text)
    # Limit length
    sanitized = sanitized[:2000]
    # Remove excessive whitespace
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    
    return sanitized

def validate_user_input(text: str, max_length: int = 2000) -> bool:
    """Validate user input"""
    if not isinstance(text, str):
        return False
    if len(text.strip()) == 0:
        return False
    if len(text) > max_length:
        return False
    return True

@dataclass
class UserProfile:
    """User profile data structure"""
    user_id: int
    goal: str = ""
    current_level: str = "B1 (Intermediate)"
    target_level: str = "B2 (Upper-Intermediate)"
    timeframe: str = "6 months"
    schedule_days: List[str] = None
    schedule_time: str = ""
    generation_prompt: str = ""
    current_topic: str = ""
    
    def __post_init__(self):
        if self.schedule_days is None:
            self.schedule_days = []

@dataclass
class UserProgress:
    """User progress tracking"""
    user_id: int
    completed: int = 0
    correct: int = 0
    conversation_count: int = 0
    last_activity: float = 0
    
    def get_accuracy(self) -> float:
        return (self.correct / self.completed * 100) if self.completed > 0 else 0.0

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Improved LLM client with local model
class LLMClient:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self._model_loaded = False
        self._loading = False
        self._lock = asyncio.Lock()
        
    async def ensure_model_loaded(self):
        """Ensure model is loaded (thread-safe)"""
        if self._model_loaded:
            return
            
        async with self._lock:
            if self._model_loaded:
                return
                
            if self._loading:
                # Wait for other loading process to complete
                while self._loading:
                    await asyncio.sleep(0.1)
                return
                
            self._loading = True
            try:
                await self._load_model()
                self._model_loaded = True
                logging.info(f"Model {self.model_name} loaded successfully")
            except Exception as e:
                logging.error(f"Failed to load model {self.model_name}: {e}")
                self.model = None
                self.tokenizer = None
            finally:
                self._loading = False

    async def _load_model(self):
        """Load model in a separate thread to avoid blocking"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_model_sync)

    def _load_model_sync(self):
        """Synchronously load the model"""
        try:
            # Load tokenizer and model
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                trust_remote_code=True
            )
            
            # Add padding token if it doesn't exist
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            # Load model with value head (as requested)
            self.model = AutoModelForCausalLMWithValueHead.from_pretrained(
                self.model_name,
                torch_dtype=torch.float32,
                trust_remote_code=True,
                low_cpu_mem_usage=True
            )
            
            # Move to GPU if available
            if torch.cuda.is_available():
                self.model.cuda()
                logging.info("Model moved to GPU")
            else:
                logging.info("Model using CPU")
                
        except Exception as e:
            logging.error(f"Error loading model: {e}")
            raise

    def is_available(self) -> bool:
        return self._model_loaded and self.model is not None and self.tokenizer is not None

    async def generate(self, prompt: str, model: str | None = None, max_new_tokens: int = 256, temperature: float = 0.7) -> str | None:
        """Generate text using local model"""
        if not await self.ensure_model_loaded():
            logging.warning("Model not available - skipping generation")
            return None
        
        try:
            # Tokenize input
            inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)
            
            # Move to GPU if available
            if torch.cuda.is_available():
                inputs = {k: v.cuda() for k, v in inputs.items()}
            
            # Generate response
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    do_sample=True,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                )
            
            # Decode response
            generated_tokens = outputs[0][inputs['input_ids'].shape[1]:]
            response = self.tokenizer.decode(generated_tokens, skip_special_tokens=True)
            
            return response.strip()
            
        except Exception as e:
            logging.error(f"Local model generation failed: {e}")
            return None

    async def generate_json(self, prompt: str, model: str | None = None, max_new_tokens: int = 384, temperature: float = 0.7) -> dict | None:
        """Generate JSON response using local model"""
        json_prompt = prompt + "\n\nReturn ONLY valid JSON. Do not include any extra text or explanations."
        text = await self.generate(json_prompt, model=model, max_new_tokens=max_new_tokens, temperature=temperature)
        
        if not text:
            return None
        
        try:
            # Try to parse directly
            return json.loads(text)
        except Exception:
            # Try to extract JSON from text
            try:
                start = text.find('{')
                end = text.rfind('}')
                if start != -1 and end != -1:
                    json_str = text[start:end+1]
                    # Clean up string from possible artifacts
                    json_str = re.sub(r',\s*}', '}', json_str)  # Remove trailing commas
                    json_str = re.sub(r',\s*\]', ']', json_str)
                    return json.loads(json_str)
            except Exception as e:
                logger.error(f"Failed to parse JSON from model output: {e}. Output was: {text[:200]}")
        return None

    async def generate_async(self, prompt: str, model: str | None = None, max_new_tokens: int = 256, temperature: float = 0.7) -> str | None:
        """Alias for generate for compatibility"""
        return await self.generate(prompt, model, max_new_tokens, temperature)

    async def generate_json_async(self, prompt: str, model: str | None = None, max_new_tokens: int = 384, temperature: float = 0.7) -> dict | None:
        """Alias for generate_json for compatibility"""
        return await self.generate_json(prompt, model, max_new_tokens, temperature)

# Global LLM client with local model
llm_client = LLMClient(MODEL_NAME)

# Default generator prompt if user hasn't provided one
DEFAULT_GENERATOR_PROMPT = (
    "You are an experienced ESL teacher. Create level-appropriate, safe, diverse English-learning content. "
    "Follow the requested schema exactly and be concise."
)

# Predefined prompt presets for common tasks
GRAMMAR_CORRECTION_PROMPT = (
    "The user will write text in English. Your task is to: "
    "1. Correct any grammatical, spelling, or punctuation errors. "
    "2. Provide the corrected version. "
    "3. Briefly and clearly explain the main errors (1-2 key points). "
    "4. Be encouraging and focus on the positive aspects of their writing. "
    "Example: 'Great attempt! Here's a small correction: [corrected sentence]. We use 'he is' because...'"
)

CONVERSATION_PROMPT = (
    "Engage the user in a natural English conversation. "
    "Choose a neutral and interesting topic (e.g., hobbies, travel, food, a recent film). "
    "Ask open-ended questions to encourage longer responses. "
    "Respond naturally to their answers and share a little about yourself to keep the conversation flowing. "
    "Gently incorporate new vocabulary or phrases when relevant."
)

GRAMMAR_EXPLAINER_PROMPT = (
    "The user will ask about an English grammar rule. "
    "Explain it in simple, clear terms. "
    "Provide a formula or structure (e.g., 'Present Perfect: have/has + past participle'). "
    "Give 3-5 clear, level-appropriate examples. "
    "Avoid overly technical jargon unless the user is at an advanced level."
)

VOCABULARY_PROMPT = (
    "The user will provide a word or ask to learn new words on a specific topic. "
    "For a given word: provide the definition, part of speech, an example sentence, and a simple synonym/antonym. "
    "For a topic (e.g., 'weather'): provide 5-7 essential words/phrases with short definitions and examples. "
    "Suggest how the student can use these words in everyday speech."
)

EXERCISE_GENERATOR_PROMPT = (
    "Generate short, focused English exercises based on the user's request (e.g., 'present simple exercises', 'vocabulary quiz on animals'). "
    "Specify the exercise type (gap-fill, multiple choice, matching). "
    "Create 5-7 items. "
    "After the user attempts the exercise, provide the correct answers and brief explanations."
)

TEXT_SIMPLIFIER_PROMPT = (
    "The user will provide an English text. Your task is to adapt it to a specific proficiency level (e.g., A2, B1). "
    "Simplify the vocabulary and grammar structures while preserving the main meaning. "
    "Keep sentences short and clear. "
    "After the simplified text, you can optionally add a list of 3-5 key vocabulary words from the original text with simple definitions."
)

INTERVIEW_COACH_PROMPT = (
    "Simulate a job interview in English. "
    "Start by asking the user about the job role they are preparing for. "
    "Ask common interview questions (e.g., 'Tell me about yourself', 'What are your strengths?'). "
    "After their response, provide feedback on the content (clarity, structure) and language (grammar, vocabulary). "
    "Suggest more natural or effective ways to phrase their answers."
)

STUDY_PLAN_PROMPT = (
    "Generate a weekly English learning plan in Markdown, tailored to the user's profile. "
    "Include an 'Overall approach' section with daily/weekly recommendations. "
    "Then create a weekly plan table with columns: Week | Grammar | Vocabulary & Theme | Listening/Reading | Writing/Speaking (Active practice). "
    "Cover the whole timeframe by weeks (e.g., 8–16 weeks depending on timeframe). "
    "Keep items practical, specific, and level-appropriate. "
    "Use clear headings and a table formatted in Markdown. "
    "Write the plan in Russian. "
)

# Telegram token is configured elsewhere (not used directly here)

GOAL, CURRENT_LEVEL, TARGET_LEVEL, TIMEFRAME, PLAN_APPROVAL, SCHEDULE_DAYS, SCHEDULE_TIME, LESSON, WAITING_ANSWER, CONVERSATION_MODE = range(10)

LEVELS = ["A1 (Beginner)", "A2 (Elementary)", "B1 (Intermediate)", "B2 (Upper-Intermediate)", "C1 (Advanced)", "C2 (Proficient)"]
DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

user_data = {}

# Global vocabulary storage
vocabulary_storage = {}


def build_user_profile_prompt(user_id: int) -> str:
    data = user_data.get(user_id, {})
    goal = data.get('goal', 'Общее улучшение английского')
    current_level = data.get('current_level', 'B1 (Intermediate)')
    target_level = data.get('target_level', 'B2 (Upper-Intermediate)')
    timeframe = data.get('timeframe', '6 months')
    days = ", ".join(data.get('schedule_days', [])) if data.get('schedule_days') else 'не указаны'
    time = data.get('schedule_time', 'не указано')
    return (
        "Профиль пользователя:\n"
        f"- Цель: {goal}\n"
        f"- Текущий уровень: {current_level}\n"
        f"- Целевой уровень: {target_level}\n"
        f"- Срок достижения: {timeframe}\n"
        f"- Предпочтительное расписание: дни {days}, время {time}"
    )

def add_words_to_vocabulary(user_id, text):
    """Add unique words longer than 3 characters to user's vocabulary"""
    if user_id not in vocabulary_storage:
        vocabulary_storage[user_id] = set()
    
    # Extract words longer than 3 characters (allow simple contractions/hyphens)
    words = re.findall(r"\b[a-zA-Z][a-zA-Z'-]{3,}\b", text.lower())
    
    # Common words to exclude
    common_words = {
        'this', 'that', 'with', 'have', 'they', 'were', 'been', 'their', 'said', 'each', 'which', 
        'them', 'many', 'some', 'time', 'very', 'when', 'much', 'new', 'now', 'old', 'see', 'him', 
        'two', 'more', 'go', 'no', 'way', 'could', 'my', 'than', 'first', 'water', 'long', 'little', 
        'most', 'after', 'back', 'other', 'many', 'where', 'much', 'take', 'why', 'help', 'put', 
        'years', 'work', 'part', 'number', 'right', 'came', 'same', 'case', 'while', 'here', 'might', 
        'think', 'show', 'large', 'again', 'turn', 'ask', 'went', 'men', 'read', 'need', 'land', 
        'different', 'home', 'move', 'try', 'kind', 'hand', 'picture', 'again', 'change', 'off', 
        'play', 'spell', 'air', 'away', 'animal', 'house', 'point', 'page', 'letter', 'mother', 
        'answer', 'found', 'study', 'still', 'learn', 'should', 'america', 'world'
    }
    
    # Add new words to vocabulary
    new_words = []
    for word in words:
        normalized = word.strip("'")
        if normalized not in common_words and normalized not in vocabulary_storage[user_id]:
            vocabulary_storage[user_id].add(normalized)
            new_words.append(normalized)
    
    return new_words

def check_sentence_structure(text):
    """Check sentence structure and provide feedback"""
    sentences = re.split(r'[.!?]+', text.strip())
    actual_sentences = [s.strip() for s in sentences if s.strip()]
    
    issues = []
    suggestions = []
    
    for sentence in actual_sentences:
        words = sentence.split()
        sentence_lower = sentence.lower()
        
        # Check for very short sentences
        if len(words) < 3:
            issues.append(f"'{sentence}' - too short, needs more words")
            suggestions.append("Try to make complete sentences with subject, verb, and object")
        
        # Check for subject-verb agreement issues
        if re.search(r'\bi\s+(is|are|was|were)', sentence_lower):
            issues.append(f"'{sentence}' - subject-verb agreement issue with 'I'")
            suggestions.append("Use 'I am' or 'I was', not 'I is/are/were'")
        
        # Check for incorrect verb forms with "I"
        if re.search(r'\bi\s+am\s+(study|work|go|play|do)', sentence_lower):
            issues.append(f"'{sentence}' - incorrect verb form after 'I am'")
            suggestions.append("Use 'I study' or 'I am studying', not 'I am study'")
        
        # Check for missing articles before nouns
        if re.search(r'\b(in|at|on)\s+(community|school|work|office|home)\b', sentence_lower):
            if not re.search(r'\b(in|at|on)\s+(the|a|an|my|our|their)\s+', sentence_lower):
                issues.append(f"'{sentence}' - might need an article before noun")
                suggestions.append("Consider adding 'the', 'a', 'an', or 'my' before nouns")
        
        # Check for word order in questions
        if sentence.strip().endswith('?'):
            if not re.search(r'^(what|where|when|why|how|do|does|did|is|are|was|were|can|could|will|would)', sentence_lower):
                issues.append(f"'{sentence}' - question word order might be incorrect")
                suggestions.append("Questions usually start with question words or auxiliary verbs")
        
        # Check for run-on sentences (very long without proper punctuation)
        if len(words) > 20 and ',' not in sentence:
            issues.append(f"'{sentence[:50]}...' - very long sentence, consider breaking it up")
            suggestions.append("Use commas or split long sentences into shorter ones")
        
        # Check for missing capitalization at start
        if sentence and not sentence[0].isupper():
            issues.append(f"'{sentence}' - should start with capital letter")
            suggestions.append("Always start sentences with a capital letter")
        
        # Check for double spaces or formatting issues
        if '  ' in sentence:
            issues.append(f"'{sentence}' - has extra spaces")
            suggestions.append("Use single spaces between words")
    
    if issues:
        feedback = "\n\n🔍 **Sentence structure suggestions:**\n"
        for issue in issues[:3]:  # Show max 3 issues
            feedback += f"• {issue}\n"
        if len(issues) > 3:
            feedback += f"• ... and {len(issues) - 3} more suggestions\n"
        
        feedback += "\n💡 **Tips:**\n"
        for tip in list(set(suggestions))[:2]:  # Show unique tips, max 2
            feedback += f"• {tip}\n"
        
        return feedback
    
    return "\n\n✅ **Good sentence structure!**"

def get_grammar_feedback(text):
    """Get comprehensive grammar and structure feedback"""
    # Always check sentence structure first
    structure_feedback = check_sentence_structure(text)
    
    if not tutor.grammar_checker:
        return structure_feedback
    
    try:
        corrected_text, grammar_feedback = tutor.check_grammar(text)
        
        # Combine both feedbacks
        combined_feedback = ""
        
        # Add grammar feedback without brittle parsing
        if grammar_feedback:
            combined_feedback += "\n\n" + grammar_feedback.strip()
        
        # Always add structure feedback
        if structure_feedback:
            combined_feedback += structure_feedback
        
        return combined_feedback if combined_feedback else structure_feedback
        
    except Exception as e:
        logger.error(f"Grammar feedback error: {e}")
        return structure_feedback

class AIConversationPartner:
    """AI conversation partner using HuggingFace models for natural English practice"""
    
    def __init__(self):
        # Conversation content is generated dynamically by LLM; no static templates.
        pass
    
    async def get_conversation_starter(self, level, topic=None, generator_prompt: str | None = None):
        """Generate conversation starter based on level; use LLM when available, otherwise offline starter."""
        level_key = level.split()[0]

        if llm_client and llm_client.is_available():
            prompt = (
                f"{generator_prompt or DEFAULT_GENERATOR_PROMPT}\n\n"
                f"Task: Propose a short conversation topic and a single friendly starter question for CEFR level {level_key}.\n"
                f"Constraints:\n"
                f"- Topic must be suitable for the level and everyday life (no sensitive content).\n"
                f"- Starter should be 1 sentence, <= 25 words, inviting the student to answer.\n"
                f"Output JSON with keys: topic (string), starter (string).\n"
            )
            if topic:
                prompt += f"\nPreferred topic to consider: {topic}\n"

            # Используем асинхронный вызов
            data = await llm_client.generate_json_async(prompt, max_new_tokens=160, temperature=0.7)
            if data and isinstance(data, dict) and "starter" in data:
                gen_topic = data.get("topic") or topic or "General"
                starter = data["starter"].strip()
                if starter:
                    return starter, gen_topic

        # Fallback to offline starter generation
        topics_by_level = {
            "A1": ["Daily routine", "Food", "Family", "Hobbies"],
            "A2": ["Travel", "School/Work", "Weekend plans", "Favorite places"],
            "B1": ["Technology", "Sports & health", "Movies & books", "Cultural traditions"],
            "B2": ["Education systems", "Work-life balance", "Environmental issues", "Social media"],
            "C1": ["Future of work", "Cultural differences", "Ethics in technology", "Personal development"],
            "C2": ["Globalization", "Sustainability", "Art and society", "Innovation"]
        }
        level_key = level_key if level_key in topics_by_level else "B1"
        chosen_topic = topic or random.choice(topics_by_level[level_key])

        starters = [
            "Let's talk about {t}. What's the first thing that comes to your mind?",
            "I'm curious about your experience with {t}. What do you enjoy most about it?",
            "Thinking about {t}, what is one interesting story you can share?",
            "How does {t} play a role in your daily life?",
            "What are the pros and cons of {t} from your perspective?"
        ]
        if level_key in {"A1", "A2"}:
            starters = [
                "Let's talk about {t}. What do you like about it?",
                "Do you enjoy {t}? Why?",
                "What is your favorite thing about {t}?",
                "How often do you do something related to {t}?"
            ]
        starter = random.choice(starters).format(t=chosen_topic)
        return starter, chosen_topic
    
    async def get_ai_response(self, user_message, level, topic, conversation_history):
        """Get AI response using improved conversation logic"""
        # Always use fallback for now - more reliable and contextual
        return self._get_fallback_response(user_message, topic, conversation_history)
        
        # HuggingFace API disabled temporarily for better user experience
        # if not HF_API_KEY or not requests:
        #     return self._get_fallback_response(user_message, topic, conversation_history)
        
        # try:
        #     level_key = level.split()[0]
        #     
        #     # Build context from recent conversation
        #     context_messages = []
        #     for msg in conversation_history[-4:]:  # Last 2 exchanges
        #         if msg['role'] == 'user':
        #             context_messages.append(f"Student: {msg['content']}")
        #         elif msg['role'] == 'assistant':
        #             context_messages.append(f"Tutor: {msg['content']}")
        #     
        #     context = "\n".join(context_messages)
        #     
        #     # Create a more natural prompt
        #     prompt = f"You are an English conversation tutor. Topic: {topic}\n\n{context}\nStudent: {user_message}\nTutor:"
        #     
        #     headers = {
        #         "Authorization": f"Bearer {HF_API_KEY}",
        #         "Content-Type": "application/json"
        #     }
        #     
        #     payload = {
        #         "inputs": prompt,
        #         "parameters": {
        #             "max_new_tokens": 60,
        #             "temperature": 0.7,
        #             "do_sample": True,
        #             "return_full_text": False,
        #             "pad_token_id": 50256
        #         }
        #     }
        #     
        #     api_url = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium"
        #     
        #     loop = asyncio.get_running_loop()
        #     post = functools.partial(requests.post, api_url, headers=headers, json=payload, timeout=10)
        #     response = await loop.run_in_executor(None, post)
        #     
        #     if response.status_code == 200:
        #         result = response.json()
        #         if isinstance(result, list) and len(result) > 0:
        #             ai_response = result[0].get("generated_text", "").strip()
        #             if ai_response and len(ai_response) > 10:
        #                 # Clean up response
        #                 ai_response = ai_response.replace(prompt, "").strip()
        #                 ai_response = ai_response.split("Student:")[0].strip()
        #                 ai_response = ai_response.split("\n")[0].strip()
        #                 ai_response = ai_response[:120]
        #                 
        #                 if ai_response and not ai_response.startswith("Tutor:"):
        #                     return ai_response
        #         
        #         return self._get_fallback_response(user_message, topic, conversation_history)
        #     
        #     else:
        #         logger.error(f"HuggingFace API error: {response.status_code}")
        #         return self._get_fallback_response(user_message, topic, conversation_history)
        #         
        # except Exception as e:
        #     logger.error(f"HuggingFace API error: {e}")
        #     return self._get_fallback_response(user_message, topic, conversation_history)
    
    def _get_fallback_response(self, user_message, topic, conversation_history):
        """Generate contextual responses based on conversation flow and content analysis"""
        user_lower = user_message.lower()
        user_messages = [msg for msg in conversation_history if msg['role'] == 'user']
        message_count = len(user_messages)
        
        # Get previous AI response for context
        previous_ai_response = ""
        if len(conversation_history) >= 2:
            previous_ai_response = conversation_history[-2].get('content', '').lower()
        
        # Handle confusion or clarification requests
        if any(phrase in user_lower for phrase in [
            "i do not understand", "i don't understand", "what do you mean", 
            "i don't know", "i do not know", "what", "confused", "unclear"
        ]):
            clarification_responses = [
                f"Let me explain better. When we talk about {topic.lower()}, I mean things like traditions, customs, or ways of life. What traditions are important in your country?",
                f"I understand it might be confusing. Let's make it simpler - can you tell me about something you do regularly that's part of your {topic.lower()}?",
                f"No problem! Let's approach this differently. What comes to mind when you think about {topic.lower()}?",
                f"That's okay! Let me ask a more specific question: What's one thing about {topic.lower()} that you find interesting?"
            ]
            return random.choice(clarification_responses)
        
        # Handle questions from user
        if user_message.strip().endswith('?'):
            if "best solution" in previous_ai_response:
                question_responses = [
                    "That's a great question! I was asking about your ideas because everyone has different perspectives. What do you think might work?",
                    "Good point to ask! I'm curious about your thoughts because you might have insights I haven't considered. What's your opinion?",
                    "You're right to ask! I want to hear your perspective first. What solutions come to mind for you?"
                ]
            else:
                question_responses = [
                    f"That's an interesting question about {topic.lower()}! What made you think of that?",
                    "I'd love to discuss that with you. What's your own experience with this?",
                    "Great question! Let me turn it back to you - what do you think about this topic?"
                ]
            return random.choice(question_responses)
        
        # Analyze content for specific topic responses
        topic_responses = self._get_topic_specific_response(user_message, topic, user_lower)
        if topic_responses:
            return topic_responses
        
        # Handle expressions of opinion or experience
        if any(phrase in user_lower for phrase in ["i think", "i believe", "in my opinion", "i feel", "i consider"]):
            opinion_responses = [
                "That's a thoughtful perspective! What experiences led you to think this way?",
                "I appreciate you sharing your opinion. Can you give me an example of what you mean?",
                "That's interesting! How do others around you feel about this?",
                "I see your point. What would you say to someone who disagrees with this view?"
            ]
            return random.choice(opinion_responses)
        
        # Handle personal experiences
        if any(phrase in user_lower for phrase in ["my", "i have", "i do", "i work", "i live", "i study"]):
            personal_responses = [
                "Thanks for sharing that personal detail! How does this experience shape your view of the topic?",
                "That sounds like valuable experience. What have you learned from this?",
                "I appreciate you opening up about that. How does this compare to what others experience?",
                "That's really interesting! What's the most important thing about this for you?"
            ]
            return random.choice(personal_responses)
        
        # Context-aware responses based on conversation flow
        if message_count == 1:
            # First response - acknowledge and dig deeper
            first_responses = [
                f"That's a great start to our conversation about {topic.lower()}! Can you tell me more about your personal experience with this?",
                f"Interesting point about {topic.lower()}! What made you think about this particular aspect?",
                f"I'd love to hear more about your perspective on {topic.lower()}. What's most important to you about this topic?"
            ]
            return random.choice(first_responses)
        
        elif message_count == 2:
            # Second response - build on what they said
            second_responses = [
                "I'm getting a better picture of your thoughts. How does this affect your daily life?",
                "That adds good context to what you said before. What challenges do you face with this?",
                "Thanks for elaborating! What would you like to see change about this situation?"
            ]
            return random.choice(second_responses)
        
        else:
            # Continuing conversation - keep it flowing naturally
            continuing_responses = [
                "That's a valuable insight. How do you think this will develop in the future?",
                "I can see you've thought about this carefully. What advice would you give to others?",
                "That's really thoughtful. What's the most surprising thing you've learned about this?",
                "Interesting perspective! How do you think your views have changed over time?"
            ]
            return random.choice(continuing_responses)
    
    def _get_topic_specific_response(self, user_message, topic, user_lower):
        """Generate topic-specific responses based on content"""
        
        # Culture-specific responses
        if "culture" in topic.lower():
            if any(word in user_lower for word in ["important", "tradition", "custom", "habit", "country", "family"]):
                return random.choice([
                    "Culture really does shape who we are! What traditions from your culture do you value most?",
                    "That's so true about culture being important. How do you maintain your cultural traditions?",
                    "Cultural habits are fascinating! How are your cultural practices different from other countries?",
                    "Family culture is really significant. What cultural values did your family teach you?"
                ])
            
            if any(word in user_lower for word in ["everyday", "daily", "life", "express", "show"]):
                return random.choice([
                    "Daily life is where culture really shows! What's a typical day like for you culturally?",
                    "That's a great way to think about culture - through everyday actions. What cultural practices do you do regularly?",
                    "Culture in daily life is so interesting! How do you express your cultural identity?",
                    "Everyday cultural expressions are meaningful. What cultural habits do you have?"
                ])
        
        # Work-related responses
        if any(word in user_lower for word in ["work", "job", "office", "workplace", "colleague", "boss", "career"]):
            return random.choice([
                "Work culture varies so much between places! What's the work environment like where you are?",
                "Professional life is a big part of culture. How do people interact at your workplace?",
                "Work relationships are interesting culturally. What's considered professional behavior in your culture?",
                "Career culture is important. How do people in your culture view work-life balance?"
            ])
        
        # Education/learning responses  
        if any(word in user_lower for word in ["learn", "study", "education", "school", "university", "knowledge"]):
            return random.choice([
                "Learning is such an important part of culture! How do people in your culture approach education?",
                "Educational culture is fascinating. What's valued most in learning where you're from?",
                "Study habits vary culturally. How do students typically learn in your educational system?",
                "Knowledge sharing is cultural too. How do people pass on knowledge in your community?"
            ])
        
        # No specific topic match
        return None

class VoiceProcessor:
    """Handle voice message processing for speech recognition and TTS"""
    
    def __init__(self):
        self.recognizer = sr.Recognizer() if sr else None
    
    async def process_voice_message(self, voice_file_path):
        """Convert voice message to text"""
        if not self.recognizer or not AudioSegment:
            return None, "Voice processing is not available"
        
        wav_path = None
        try:
            # Convert to WAV format
            audio = AudioSegment.from_file(voice_file_path)
            wav_path = voice_file_path.replace('.ogg', '.wav')
            audio.export(wav_path, format="wav")
            
            # Recognize speech
            if sr:
                with sr.AudioFile(wav_path) as source:
                    audio_data = self.recognizer.record(source)
                    text = self.recognizer.recognize_google(audio_data, language='en-US')
                    return text, None
            else:
                return None, "Speech recognition not available"
                
        except Exception as e:
            if sr and hasattr(sr, 'UnknownValueError') and isinstance(e, sr.UnknownValueError):
                return None, "Sorry, I couldn't understand the audio. Please try speaking more clearly."
            elif sr and hasattr(sr, 'RequestError') and isinstance(e, sr.RequestError):
                return None, f"Speech recognition error: {e}"
            else:
                logger.error(f"Voice processing error: {e}")
                return None, "Error processing voice message"
        finally:
            try:
                if wav_path and os.path.exists(wav_path):
                    os.remove(wav_path)
            except Exception:
                pass
    
    def generate_tts_audio(self, text, language='en'):
        """Generate text-to-speech audio"""
        if not gTTS:
            return None
        
        try:
            tts = gTTS(text=text, lang=language, slow=False)
            audio_buffer = io.BytesIO()
            tts.write_to_fp(audio_buffer)
            audio_buffer.seek(0)
            return audio_buffer
        except Exception as e:
            logger.error(f"TTS generation error: {e}")
            return None

class EnglishTutor:
    def __init__(self):
        self.grammar_checker = None
        self._grammar_checker_initialized = False

    def _initialize_grammar_checker(self):
        """Lazy initialization of grammar checker"""
        if self._grammar_checker_initialized:
            return
        
        self._grammar_checker_initialized = True
        try:
            if pipeline:
                self.grammar_checker = pipeline(
                    "text2text-generation",
                    model="vennify/t5-base-grammar-correction",
                    tokenizer="vennify/t5-base-grammar-correction"
                )
                logger.info("Grammar checker initialized successfully")
            else:
                self.grammar_checker = None
                logger.warning("Transformers pipeline not available")
        except Exception as e:
            logger.error("Failed to initialize grammar checker: %s", e)
            self.grammar_checker = None

    def check_grammar(self, text):
        # Initialize grammar checker on first use
        self._initialize_grammar_checker()
        
        if not self.grammar_checker:
            return text, "⚠️ Grammar checker not available."
            
        try:
            result = self.grammar_checker(
                f"grammar: {text}",
                max_length=256,
                num_beams=5,
                early_stopping=True
            )
            corrected_text = result[0]['generated_text']
            
            # Compare original and corrected text using token diff
            original_words = text.split()
            corrected_words = corrected_text.split()

            changes = []
            sm = difflib.SequenceMatcher(None, original_words, corrected_words)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag == "replace":
                    orig = " ".join(original_words[i1:i2])
                    corr = " ".join(corrected_words[j1:j2])
                    changes.append(f"• '{orig}' → '{corr}'")
                elif tag == "delete":
                    orig = " ".join(original_words[i1:i2])
                    changes.append(f"• Removed '{orig}'")
                elif tag == "insert":
                    corr = " ".join(corrected_words[j1:j2])
                    changes.append(f"• Added '{corr}'")

            if changes:
                feedback = "\n🔧 **Grammar corrections:**\n" + "\n".join(changes[:3])
                if len(changes) > 3:
                    feedback += f"\n• ... and {len(changes) - 3} more corrections"
            else:
                feedback = "\n✅ No grammar errors found!"
            
            return corrected_text, feedback
            
        except Exception as e:
            logger.error(f"Grammar check error: {e}")
            return text, "⚠️ Error during grammar check."

# Initialize components
tutor = EnglishTutor()
ai_partner = AIConversationPartner()
voice_processor = VoiceProcessor()

# Exercise checking functions (keeping existing ones)
def check_gap_filling_answer(user_answer, correct_answers):
    """Check gap filling exercise answers"""
    if not user_answer.strip():
        return False, "❌ Please provide your answers."
    
    user_answers = [ans.strip().lower() for ans in user_answer.split(',')]
    correct_answers = [ans.strip().lower() for ans in correct_answers]
    
    if len(user_answers) != len(correct_answers):
        return False, f"❌ Incorrect number of answers. Expected {len(correct_answers)}, but got {len(user_answers)}."
    
    correct_count = 0
    feedback = []
    
    for i, (user_ans, correct_ans) in enumerate(zip(user_answers, correct_answers)):
        similarity = difflib.SequenceMatcher(None, user_ans, correct_ans).ratio()
        if similarity > 0.8:
            correct_count += 1
            feedback.append(f"✅ Gap {i+1}: Correct!")
        else:
            feedback.append(f"❌ Gap {i+1}: '{user_ans}' instead of '{correct_ans}'")
    
    accuracy = correct_count / len(correct_answers)
    
    if accuracy == 1:
        return True, "🎉 Excellent! All answers are correct!"
    elif accuracy >= 0.7:
        return False, f"📗 Good! {correct_count} out of {len(correct_answers)} correct.\n" + "\n".join(feedback)
    else:
        return False, f"📘 Needs practice! {correct_count} out of {len(correct_answers)} correct.\n" + "\n".join(feedback)

def check_comprehension_answer(user_answer, correct_answers):
    """Check reading comprehension answers"""
    if not user_answer.strip():
        return False, "❌ Please provide your answer."
    
    user_answer_lower = user_answer.lower()
    
    for correct_answer in correct_answers:
        if correct_answer.lower() in user_answer_lower:
            return True, "✅ Correct! You understood the text well."
    
    return False, "❌ Answer is not quite accurate. Try rereading the text."

def check_sentence_answer(user_answer, correct_sentences):
    """Check sentence formation answers with improved word matching"""
    if not user_answer.strip():
        return False, "❌ Please write a sentence."
    
    user_sentence = user_answer.strip()
    
    corrected_text, grammar_feedback = tutor.check_grammar(user_answer)
    
    # Tokenize and normalize words for better matching
    import re
    required_words = set()
    for word in correct_sentences[0].split():
        # Remove punctuation and normalize
        clean_word = re.sub(r'[^\w]', '', word.lower())
        if len(clean_word) > 2:  # Only check meaningful words
            required_words.add(clean_word)
    
    # Tokenize user input similarly
    user_words = set()
    for word in user_sentence.split():
        clean_word = re.sub(r'[^\w]', '', word.lower())
        if len(clean_word) > 2:
            user_words.add(clean_word)
    
    missing_words = required_words - user_words
    
    if not missing_words:
        return True, f"✅ Excellent! Correct sentence.{grammar_feedback}"
    else:
        return False, f"❌ Missing key words: {', '.join(missing_words)}.{grammar_feedback}"

def check_pronunciation_answer(user_answer, correct_answers):
    """Check pronunciation exercise"""
    user_answer_lower = user_answer.strip().lower()
    if user_answer_lower == 'done':
        return True, "🎯 Pronunciation practice completed! Keep practicing!"
    else:
        return False, "🗣️ Please practice pronouncing the words and type 'done' when finished."

def check_writing_answer(user_answer, correct_answers):
    """Check writing exercise with grammar feedback"""
    if not user_answer.strip():
        return False, "❌ Please write your paragraph."
    
    # Check if answer is a navigation command
    navigation_commands = ["🎯 next exercise", "🎯 start lesson", "📊 my statistics", 
                          "📚 my progress", "🏠 main menu", "/start_lesson"]
    
    if user_answer.strip().lower() in [cmd.lower() for cmd in navigation_commands]:
        return False, "❌ Please complete the writing exercise first before navigating."
    
    corrected_text, grammar_feedback = tutor.check_grammar(user_answer)
    
    # Check text length
    word_count = len(user_answer.split())
    if word_count < 20:
        length_feedback = f"\n📝 **Suggestion:** Try to write more. Current: {word_count} words (recommended: 30+ words)."
    elif word_count < 40:
        length_feedback = f"\n📝 **Good length:** {word_count} words."
    else:
        length_feedback = f"\n📝 **Excellent length:** {word_count} words!"
    
    # Check structure
    sentences = re.split(r'[.!?]+', user_answer)
    actual_sentences = [s.strip() for s in sentences if s.strip()]
    
    if len(actual_sentences) >= 2:
        structure_feedback = f"\n📋 **Structure:** Good paragraph with {len(actual_sentences)} sentences."
    else:
        structure_feedback = "\n📋 **Suggestion:** Try to write multiple sentences to form a proper paragraph."
    
    full_feedback = f"✅ **Writing submitted!**{length_feedback}{structure_feedback}{grammar_feedback}"
    
    return True, full_feedback

def check_unavailable_answer(user_answer, correct_answers):
    """Used when LLM generation is unavailable; informs the user instead of checking."""
    return False, (
        "⚠️ Exercise generation is currently unavailable.\n"
        "Please set HF_API_KEY in environment and restart the bot, or try again later."
    )

# Exercise generators (keeping existing ones but adding conversation mode)
def generate_gap_filling(topic, level):
    """Generate varied gap-filling exercise offline."""
    exercises = {
        "A1": [
            {"text": "I _____ breakfast at 8 a.m. My sister _____ tea, but I _____ coffee.", "answers": ["have", "drinks", "prefer"]},
            {"text": "We _____ to the park on Sundays. My dad _____ the guitar and we _____ together.", "answers": ["go", "plays", "sing"]},
        ],
        "A2": [
            {"text": "Last weekend we _____ a picnic. The weather _____ sunny, so we _____ a great time.", "answers": ["had", "was", "had"]},
            {"text": "I _____ a new phone yesterday. It _____ very fast and I _____ it already.", "answers": ["bought", "is", "like"]},
        ],
        "B1": [
            {"text": "If I _____ earlier, I _____ caught the bus, but I _____ too late.", "answers": ["had left", "would have", "was"]},
            {"text": "She _____ working here since 2020 and _____ many projects; now she _____ a team.", "answers": ["has been", "has completed", "leads"]},
        ],
        "B2": [
            {"text": "Despite _____ exhausted, they _____ to finish on time; the result _____ outstanding.", "answers": ["being", "managed", "was"]},
            {"text": "Had I _____ your message, I _____ you back immediately, but my phone _____ off.", "answers": ["seen", "would have called", "was"]},
        ],
    }
    level_key = level.split()[0]
    bank = exercises.get(level_key, exercises["B1"])
    return random.choice(bank)

def generate_reading_comprehension(topic, level):
    """Generate varied short text + one question with acceptable answers."""
    texts = {
        "A1": [
            {
                "text": "Anna has a small dog. She takes it for a walk every morning. After the walk, she eats breakfast and goes to work.",
                "questions": "When does Anna walk her dog?",
                "answers": ["in the morning", "every morning"]
            },
            {
                "text": "Jake likes reading. He goes to the library on Saturdays. He often reads adventure books with his friends.",
                "questions": "Where does Jake go on Saturdays?",
                "answers": ["the library", "to the library"]
            },
        ],
        "A2": [
            {
                "text": "Last month, Peter traveled to Spain. He visited Barcelona and Madrid. He enjoyed the local food and the warm weather.",
                "questions": "Which cities did Peter visit?",
                "answers": ["Barcelona and Madrid", "Madrid and Barcelona"]
            },
            {
                "text": "Nora started a new hobby: photography. She practices on weekends in the park and shares her pictures online.",
                "questions": "When does Nora practice photography?",
                "answers": ["on weekends", "at weekends"]
            },
        ],
        "B1": [
            {
                "text": "Remote work has become more common. Many people save time by avoiding commuting. However, some miss the social aspect of the office.",
                "questions": "What is one advantage mentioned about remote work?",
                "answers": ["saving time", "no commuting", "avoiding commuting"]
            },
            {
                "text": "Learning a language takes regular practice. Short, daily sessions are often more effective than long, rare ones.",
                "questions": "What is considered more effective for learning a language?",
                "answers": ["short daily sessions", "regular short practice"]
            },
        ],
        "B2": [
            {
                "text": "Public transportation can reduce traffic congestion and pollution. Yet, it requires investment and careful planning to be efficient.",
                "questions": "What benefits can public transportation bring?",
                "answers": ["reduce congestion", "reduce pollution", "less traffic and pollution"]
            },
            {
                "text": "Social media platforms influence public opinion. While they connect people, they also spread misinformation quickly.",
                "questions": "What is a risk mentioned about social media?",
                "answers": ["misinformation", "spreading misinformation"]
            },
        ],
    }
    level_key = level.split()[0]
    bank = texts.get(level_key, texts["B1"])
    return random.choice(bank)

def generate_sentence_exercise(topic, level):
    """Generate varied sentence formation sets per level."""
    word_sets = {
    "A1": [
    {"words": ["I", "have", "a", "cat"], "possible_answers": ["I have a cat"]},
    {"words": ["We", "like", "to", "play", "games"], "possible_answers": ["We like to play games"]},
    ],
    "A2": [
    {"words": ["Yesterday", "I", "went", "to", "the", "cinema"], "possible_answers": ["Yesterday I went to the cinema"]},
    {"words": ["She", "didn't", "go", "to", "school", "today"], "possible_answers": ["She didn't go to school today"]},
    ],
    "B1": [
    {"words": ["Although", "it", "was", "raining", "we", "decided", "to", "go", "out"], "possible_answers": ["Although it was raining, we decided to go out"]},
    {"words": ["If", "I", "had", "more", "time", "I", "would", "travel"], "possible_answers": ["If I had more time, I would travel"]},
    ],
    "B2": [
    {"words": ["The", "report", "which", "was", "published", "yesterday", "caused", "a", "debate"], "possible_answers": ["The report which was published yesterday caused a debate"]},
    {"words": ["Having", "finished", "the", "project", "they", "took", "a", "break"], "possible_answers": ["Having finished the project, they took a break"]},
    ],
    }
    level_key = level.split()[0]
    bank = word_sets.get(level_key, word_sets["B1"])
    return random.choice(bank)

def generate_writing_prompt(topic, level):
    """Generate varied writing prompts per level."""
    prompts = {
        "A1": [
            "Describe your daily routine",
            "Write about your favorite food",
            "Describe your family in a few sentences",
        ],
        "A2": [
            "Write about your last vacation",
            "Describe your weekend plans",
            "Write about a place you like in your city",
        ],
        "B1": [
            "Discuss the advantages and disadvantages of social media",
            "Write about a memorable learning experience",
            "Explain how you stay healthy and active",
        ],
        "B2": [
            "Explain your opinion on climate change and possible solutions",
            "Discuss work-life balance in modern life",
            "Should schools focus more on soft skills? Explain.",
        ],
    }
    level_key = level.split()[0]
    bank = prompts.get(level_key, prompts["B1"])
    return random.choice(bank)

def generate_pronunciation_words(topic, level):
    """Generate a small randomized list of words per level."""
    pools = {
        "A1": ["hello", "goodbye", "please", "thank you", "morning", "evening", "family", "friend"],
        "A2": ["weather", "family", "travel", "restaurant", "ticket", "holiday", "airport", "breakfast"],
        "B1": ["environment", "communication", "education", "technology", "decision", "community", "pollution", "influence"],
        "B2": ["responsibility", "opportunity", "characteristic", "development", "efficiency", "generation", "negotiation", "motivation"],
    }
    level_key = level.split()[0]
    base = pools.get(level_key, pools["B1"])
    k = 4 if level_key in {"A1", "A2"} else 4
    return random.sample(base, k)

# Exercise content pools to reduce repetition










# Exercise system (keeping existing structure)
EXERCISE_TEMPLATES = {
    "reading": [
        {
            "type": "text_comprehension",
            "template": "Read the text and answer the question:\n\n{text}\n\nQuestion: {questions}\n\nYour answer:",
                        "check_answer": check_comprehension_answer
        },
        {
            "type": "gap_filling",
            "template": "Fill in the gaps with appropriate words:\n\n{text}\n\nEnter your answers separated by commas:",
                        "check_answer": check_gap_filling_answer
        }
    ],
    "writing": [
        {
            "type": "sentence_formation",
            "template": "Create a sentence using these words: {words}\n\nYour sentence:",
                        "check_answer": check_sentence_answer
        },
        {
            "type": "paragraph_writing",
            "template": "Write a short paragraph about: {topic}\n\nYour paragraph:",
                        "check_answer": check_writing_answer
        }
    ],
    "speaking": [
        {
            "type": "pronunciation",
            "template": "Practice pronouncing these words: {words}\n\nSay them aloud and type 'done' when finished:",
                        "check_answer": check_pronunciation_answer
        }
    ]
}

def get_exercise_instructions(exercise_type, subtype):
    instructions = {
        "reading": {
            "text_comprehension": "📖 Read the text and answer the question",
            "gap_filling": "📝 Fill in the gaps with appropriate words"
        },
        "writing": {
            "sentence_formation": "✍️ Create a sentence using the given words",
            "paragraph_writing": "📝 Write a short paragraph on the topic"
        },
        "speaking": {
            "pronunciation": "🗣️ Practice pronouncing these words"
        }
    }
    return instructions.get(exercise_type, {}).get(subtype, "Complete the exercise")

def generate_exercise_via_llm(subtype: str, level: str, generator_prompt: str | None, preferred_topic: str | None = None) -> dict | None:
    """Ask LLM to generate an exercise for a subtype and return normalized dict or None on failure."""
    if not (llm_client and llm_client.is_available()):
        return None

    level_key = level.split()[0]

    schemas = {
        "text_comprehension": (
            "Create a short reading text and a single comprehension question.",
            "Output JSON: {\"text\": string (60-120 words), \"questions\": string, \"answers\": array of 2-4 acceptable short answers (strings)}."
        ),
        "gap_filling": (
            "Create 1-2 sentences with 3 blanks marked by five underscores (_____) for grammar/vocabulary.",
            "Output JSON: {\"text\": string with blanks, \"answers\": array of correct words in order}."
        ),
        "sentence_formation": (
            "Create a set of 6-10 words that can form exactly one natural sentence.",
            "Output JSON: {\"words\": array of words (shuffled), \"possible_answers\": array with 1-3 valid sentences}."
        ),
        "paragraph_writing": (
            "Propose a concise writing topic for a short paragraph.",
            "Output JSON: {\"topic\": string}."
        ),
        "pronunciation": (
            "Provide a list of 4-6 level-appropriate practice words.",
            "Output JSON: {\"words\": array of words}."
        ),
    }

    if subtype not in schemas:
        return None

    task, schema = schemas[subtype]
    topic_hint = f"Preferred topic: {preferred_topic}." if preferred_topic else ""

    prompt = (
        f"{generator_prompt or DEFAULT_GENERATOR_PROMPT}\n\n"
        f"Task: {task}\n"
        f"Level: CEFR {level_key}. {topic_hint}\n"
        f"Constraints: avoid sensitive content; keep vocabulary and grammar appropriate to level.\n"
        f"{schema}\n"
    )

    data = llm_client.generate_json(prompt, max_new_tokens=320, temperature=0.8)
    if not isinstance(data, dict):
        return None

    # Basic validation per subtype
    try:
        if subtype == "text_comprehension":
            if not (data.get("text") and data.get("questions") and isinstance(data.get("answers"), list)):
                return None
        elif subtype == "gap_filling":
            if not (data.get("text") and isinstance(data.get("answers"), list)):
                return None
        elif subtype == "sentence_formation":
            if not (isinstance(data.get("words"), list) and isinstance(data.get("possible_answers"), list)):
                return None
        elif subtype == "paragraph_writing":
            if not data.get("topic"):
                return None
        elif subtype == "pronunciation":
            if not isinstance(data.get("words"), list):
                return None
        return data
    except Exception:
        return None


def generate_checkable_exercise(user_id):
    """Generate exercise with checking system, avoiding recent repetition; prefers LLM when available."""
    if user_id not in user_data:
        user_data[user_id] = {
            'current_level': 'B1 (Intermediate)',
            'progress': {'completed': 0, 'correct': 0},
            'recent_exercises': [],  # list of (subtype, id)
        }

    data = user_data[user_id]
    level = data.get('current_level', 'B1 (Intermediate)')
    last_subtype = data.get('last_subtype')

    # Choose a subtype different from last_subtype when possible
    candidates = []
    for etype, templates in EXERCISE_TEMPLATES.items():
        for tmpl in templates:
            if tmpl["type"] != last_subtype:
                candidates.append((etype, tmpl))
    if candidates:
        exercise_type, template = random.choice(candidates)
    else:
        # fallback: any template
        etype = random.choice(list(EXERCISE_TEMPLATES.keys()))
        template = random.choice(EXERCISE_TEMPLATES[etype])
        exercise_type = etype

    subtype = template["type"]

    # Try LLM generation first
    base_prompt = data.get('generation_prompt') or DEFAULT_GENERATOR_PROMPT
    combined_prompt = f"{base_prompt}\n\n{build_user_profile_prompt(user_id)}"
    preferred_topic = data.get('current_topic')
    llm_data = generate_exercise_via_llm(subtype, level, combined_prompt, preferred_topic)

    exercise_data = {
        "type": exercise_type,
        "subtype": subtype,
        "check_function": template["check_answer"],
        "instructions": get_exercise_instructions(exercise_type, subtype)
    }

    if llm_data:
        # Build from LLM response
        if subtype == "text_comprehension":
            exercise_data["content"] = template["template"].format(
                text=llm_data["text"], questions=llm_data["questions"], words="", topic=""
            )
            exercise_data["correct_answers"] = llm_data["answers"]
        elif subtype == "gap_filling":
            exercise_data["content"] = template["template"].format(
                text=llm_data["text"], questions="", words="", topic=""
            )
            exercise_data["correct_answers"] = llm_data["answers"]
        elif subtype == "sentence_formation":
            exercise_data["content"] = template["template"].format(
                words=", ".join(llm_data["words"]), text="", questions="", topic=""
            )
            exercise_data["correct_answers"] = llm_data["possible_answers"]
        elif subtype == "paragraph_writing":
            exercise_data["content"] = template["template"].format(
                topic=llm_data["topic"], words="", text="", questions=""
            )
            exercise_data["correct_answers"] = [llm_data["topic"]]
        elif subtype == "pronunciation":
            exercise_data["content"] = template["template"].format(
                words=", ".join(llm_data["words"]), text="", questions="", topic=""
            )
            exercise_data["correct_answers"] = []
        else:
            exercise_data["content"] = template["template"].format(
                topic="General English", words="", text="", questions=""
            )
            exercise_data["correct_answers"] = [""]

        # Update recent trackers
        user_data[user_id]['last_subtype'] = subtype
        recent = user_data[user_id].setdefault('recent_exercises', [])
        recent.append((subtype, f"llm_{subtype}_{random.randint(1000,9999)}"))
        if len(recent) > 8:
            user_data[user_id]['recent_exercises'] = recent[-8:]

        return exercise_data

    # LLM unavailable or failed: build offline exercise from local templates
    topic = data.get('current_topic', 'General English')
    if subtype == "text_comprehension":
        rd = generate_reading_comprehension(topic, level)
        exercise_data["content"] = template["template"].format(
            text=rd["text"], questions=rd["questions"], words="", topic=""
        )
        exercise_data["correct_answers"] = rd["answers"]
    elif subtype == "gap_filling":
        gf = generate_gap_filling(topic, level)
        exercise_data["content"] = template["template"].format(
            text=gf["text"], questions="", words="", topic=""
        )
        exercise_data["correct_answers"] = gf["answers"]
    elif subtype == "sentence_formation":
        se = generate_sentence_exercise(topic, level)
        exercise_data["content"] = template["template"].format(
            words=", ".join(se["words"]), text="", questions="", topic=""
        )
        exercise_data["correct_answers"] = se["possible_answers"]
    elif subtype == "paragraph_writing":
        wp = generate_writing_prompt(topic, level)
        exercise_data["content"] = template["template"].format(
            topic=wp, words="", text="", questions=""
        )
        exercise_data["correct_answers"] = [wp]
    elif subtype == "pronunciation":
        wl = generate_pronunciation_words(topic, level)
        exercise_data["content"] = template["template"].format(
            words=", ".join(wl), text="", questions="", topic=""
        )
        exercise_data["correct_answers"] = []
    else:
        exercise_data["content"] = template["template"].format(
            topic="General English", words="", text="", questions=""
        )
        exercise_data["correct_answers"] = [""]

    # Update recent trackers
    user_data[user_id]['last_subtype'] = subtype
    recent = user_data[user_id].setdefault('recent_exercises', [])
    recent.append((subtype, f"offline_{subtype}_{random.randint(1000,9999)}"))
    if len(recent) > 8:
        user_data[user_id]['recent_exercises'] = recent[-8:]

    return exercise_data

# Bot command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the bot and begin registration"""
    user = update.message.from_user
    
    welcome_text = """
👋 Welcome to your English Learning Assistant!

I'm here to help you improve your English through:
🗣️ AI-powered conversation practice
📚 Interactive exercises and lessons
🎯 Personalized learning plans
📊 Progress tracking
🔊 Voice message support

Let's get started by setting up your learning profile!

What's your main goal for learning English?
"""
    
    keyboard = [
        ["🗣️ Improve speaking skills"],
        ["📖 Better reading comprehension"],
        ["✍️ Writing improvement"],
        ["🎯 General English proficiency"],
        ["💼 Business English"],
        ["🎓 Exam preparation"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    return GOAL

async def set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Set user's learning goal"""
    user = update.message.from_user
    user_data[user.id] = {'goal': update.message.text}
    
    await update.message.reply_text(
        f"Great! Your goal: {update.message.text}\n\n"
        "What's your current English level?",
        reply_markup=ReplyKeyboardMarkup([LEVELS], resize_keyboard=True)
    )
    return CURRENT_LEVEL

async def set_current_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Set user's current level"""
    user = update.message.from_user
    user_data[user.id]['current_level'] = update.message.text
    
    await update.message.reply_text(
        f"Current level: {update.message.text}\n\n"
        "What level would you like to reach?",
        reply_markup=ReplyKeyboardMarkup([LEVELS], resize_keyboard=True)
    )
    return TARGET_LEVEL

async def set_target_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Set user's target level"""
    user = update.message.from_user
    user_data[user.id]['target_level'] = update.message.text
    
    await update.message.reply_text(
        f"Target level: {update.message.text}\n\n"
        "In how many months would you like to reach this level?",
        reply_markup=ReplyKeyboardMarkup([["3 months", "6 months"], ["12 months", "24 months"]], resize_keyboard=True)
    )
    return TIMEFRAME

async def set_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Set learning timeframe"""
    user = update.message.from_user
    user_data[user.id]['timeframe'] = update.message.text
    
    # Generate and show plan (offload blocking generation)
    loop = asyncio.get_running_loop()
    plan = await loop.run_in_executor(None, functools.partial(generate_study_plan, user.id))
    user_data[user.id]['plan'] = plan
    
    plan_text = format_plan(plan)
    
    await update.message.reply_text(
        f"📋 Here's your personalized study plan:\n\n{plan_text}\n\n"
        "Does this plan look good to you?",
        reply_markup=ReplyKeyboardMarkup([["✅ Approve Plan", "❌ Modify Plan"]], resize_keyboard=True),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    return PLAN_APPROVAL

async def handle_plan_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle plan approval and modifications to avoid looping."""
    user = update.message.from_user
    text = (update.message.text or '').strip()

    if text == "✅ Approve Plan":
        await update.message.reply_text(
            "Excellent! Now let's set up your learning schedule.\n\n"
            "Which days of the week would you like to study?",
            reply_markup=ReplyKeyboardMarkup([DAYS_OF_WEEK[:4], DAYS_OF_WEEK[4:]], resize_keyboard=True)
        )
        return SCHEDULE_DAYS

    if text in {"Change goal", "Change Goal"}:
        await update.message.reply_text(
            "What's your main goal for learning English?",
            reply_markup=ReplyKeyboardMarkup([
                ["🗣️ Improve speaking skills"],
                ["📖 Better reading comprehension"],
                ["✍️ Writing improvement"],
                ["🎯 General English proficiency"],
                ["💼 Business English"],
                ["🎓 Exam preparation"]
            ], resize_keyboard=True)
        )
        return GOAL

    if text in {"Change timeframe", "Change Timeframe"}:
        await update.message.reply_text(
            "In how many months would you like to reach this level?",
            reply_markup=ReplyKeyboardMarkup([["3 months", "6 months"], ["12 months", "24 months"]], resize_keyboard=True)
        )
        return TIMEFRAME

    if text in {"Continue with plan", "Continue"}:
        await update.message.reply_text(
            "Great! Let's set up your learning schedule.\n\nWhich days of the week would you like to study?",
            reply_markup=ReplyKeyboardMarkup([DAYS_OF_WEEK[:4], DAYS_OF_WEEK[4:]], resize_keyboard=True)
        )
        return SCHEDULE_DAYS

    # Default: show modification options again
    await update.message.reply_text(
        "Let's adjust your plan. What would you like to change?",
        reply_markup=ReplyKeyboardMarkup([["Change goal", "Change timeframe"], ["Continue with plan"]], resize_keyboard=True)
    )
    return PLAN_APPROVAL

async def set_schedule_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Set study schedule days"""
    user = update.message.from_user
    
    if 'schedule_days' not in user_data[user.id]:
        user_data[user.id]['schedule_days'] = []
    
    selected_day = update.message.text
    if selected_day in DAYS_OF_WEEK:
        if selected_day not in user_data[user.id]['schedule_days']:
            user_data[user.id]['schedule_days'].append(selected_day)
            await update.message.reply_text(f"Added {selected_day}. Select more days or type 'ok'.")
        else:
            await update.message.reply_text(f"{selected_day} already selected.")
    else:
        # Allow user to confirm selection with 'ok'
        if selected_day and selected_day.strip().lower() in {"ok", "okay", "done"}:
            days_text = ", ".join(user_data[user.id]['schedule_days'])
            await update.message.reply_text(
                f"Selected days: {days_text}\n\n"
                "What time would you like to receive lesson reminders?",
                reply_markup=ReplyKeyboardMarkup([["09:00", "12:00"], ["18:00", "20:00"]], resize_keyboard=True)
            )
            return SCHEDULE_TIME
        else:
            await update.message.reply_text("Please select valid days from the keyboard, or type 'ok' when done.")
            return SCHEDULE_DAYS

async def set_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Set reminder time and complete setup"""
    user = update.message.from_user
    user_data[user.id]['schedule_time'] = update.message.text
    
    # Setup reminders if possible
    schedule_days = user_data[user.id].get('schedule_days', [])
    schedule_time = user_data[user.id].get('schedule_time')
    
    await update.message.reply_text(
        f"🎉 Setup complete!\n\n"
        f"📅 Study days: {', '.join(schedule_days)}\n"
        f"⏰ Reminder time: {schedule_time}\n\n"
        "Ready to start learning? Choose an option:",
        reply_markup=ReplyKeyboardMarkup([
            ["🎯 Start Lesson", "💬 AI Conversation"],
            ["📊 My Progress", "🏠 Main Menu"]
        ], resize_keyboard=True)
    )
    return LESSON

async def start_conversation_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start AI conversation mode"""
    user = update.message.from_user
    
    if user.id not in user_data:
        await update.message.reply_text("Please register first using /start")
        return ConversationHandler.END
    
    level = user_data[user.id].get('current_level', 'B1 (Intermediate)')
    
    # Initialize conversation history
    if 'conversation_history' not in user_data[user.id]:
        user_data[user.id]['conversation_history'] = []
    
    # Get conversation starter асинхронно
    base_prompt = user_data[user.id].get('generation_prompt') or DEFAULT_GENERATOR_PROMPT
    combined_prompt = f"{base_prompt}\n\n{build_user_profile_prompt(user.id)}"
    starter_message, topic = await ai_partner.get_conversation_starter(
        level, generator_prompt=combined_prompt
    )
    user_data[user.id]['current_topic'] = topic
    
    await update.message.reply_text(
        f"💬 **AI Conversation Mode**\n\n"
        f"Let's practice English conversation! 🗣️\n"
        f"Topic: {topic}\n\n"
        f"{starter_message}\n\n"
        f"💡 You can send text or voice messages!\n"
        f"Type 'end conversation' to finish.",
        reply_markup=ReplyKeyboardMarkup([
            ["🔚 End Conversation"],
            ["📚 Back to Lessons"]
        ], resize_keyboard=True)
    )
    
    # Add AI message to history
    user_data[user.id]['conversation_history'].append({
        "role": "assistant", 
        "content": starter_message
    })
    
    return CONVERSATION_MODE

async def handle_conversation_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle messages in conversation mode"""
    user = update.message.from_user
    
    if update.message.text and update.message.text.lower() in ['end conversation', '🔚 end conversation']:
        # End conversation and show summary
        history = user_data[user.id].get('conversation_history', [])
        message_count = len([msg for msg in history if msg['role'] == 'user'])
        
        await update.message.reply_text(
            f"🎉 Great conversation practice!\n\n"
            f"📊 Summary:\n"
            f"• Messages exchanged: {message_count}\n"
            f"• Topic: {user_data[user.id].get('current_topic', 'General')}\n\n"
            f"Keep practicing to improve your English! 💪",
            reply_markup=ReplyKeyboardMarkup([
                ["🎯 Start Lesson", "💬 New Conversation"],
                ["📊 My Progress", "🏠 Main Menu"]
            ], resize_keyboard=True)
        )
        return LESSON
    
    if update.message.text and update.message.text == "📚 Back to Lessons":
        return await handle_lesson_navigation(update, context)
    
    # Process user message (text or voice)
    user_message = None
    
    if update.message.voice:
        # Voice processing is under development
        await update.message.reply_text(
            "🎤 Voice message processing is currently under development. "
            "Please use text messages for now. Thank you for your patience!"
        )
        return CONVERSATION_MODE
        
    elif update.message.text:
        user_message = update.message.text
    
    if not user_message:
        await update.message.reply_text("Please send a text or voice message to continue the conversation.")
        return CONVERSATION_MODE
    
    # Add words to vocabulary
    new_words = add_words_to_vocabulary(user.id, user_message)
    
    # Get grammar feedback (offload blocking work)
    loop = asyncio.get_running_loop()
    grammar_feedback = await loop.run_in_executor(None, functools.partial(get_grammar_feedback, user_message))
    
    # Add user message to history
    user_data[user.id]['conversation_history'].append({
        "role": "user",
        "content": user_message
    })
    # Prune history to last 50 messages
    user_data[user.id]['conversation_history'] = user_data[user.id]['conversation_history'][-50:]
    
    # Get AI response
    level = user_data[user.id].get('current_level', 'B1 (Intermediate)')
    topic = user_data[user.id].get('current_topic', 'General')
    history = user_data[user.id]['conversation_history']
    
    ai_response = await ai_partner.get_ai_response(user_message, level, topic, history)
    
    # Add AI response to history
    user_data[user.id]['conversation_history'].append({
        "role": "assistant",
        "content": ai_response
    })
    # Prune history to last 50 messages
    user_data[user.id]['conversation_history'] = user_data[user.id]['conversation_history'][-50:]
    
    # Prepare response with grammar feedback
    response_text = f"🤖 {ai_response}"
    if grammar_feedback:
        response_text += grammar_feedback
    
    # Add vocabulary notification if new words were found
    if new_words:
        vocab_text = f"\n\n📚 **New words added to vocabulary:** {', '.join(new_words[:3])}"
        if len(new_words) > 3:
            vocab_text += f" and {len(new_words) - 3} more"
        response_text += vocab_text
    
    # Send AI response with feedback
    await update.message.reply_text(response_text)
    
    # Optionally send as audio message too (only for shorter responses)
    if gTTS and len(ai_response) < 100:
        try:
            loop = asyncio.get_running_loop()
            audio_buffer = await loop.run_in_executor(None, functools.partial(voice_processor.generate_tts_audio, ai_response))
            if audio_buffer:
                # Use reply_audio for MP3 files from gTTS, not reply_voice
                await update.message.reply_audio(audio=audio_buffer, title="AI Response")
        except Exception as e:
            logger.error(f"TTS error: {e}")
            # Inform user about TTS failure
            await update.message.reply_text("🔊 Audio generation temporarily unavailable.")
    
    return CONVERSATION_MODE

async def start_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start a lesson with exercises"""
    user = update.message.from_user
    
    if user.id not in user_data:
        await update.message.reply_text("Please register first using /start")
        return ConversationHandler.END
    
    # Generate exercise
    exercise = generate_checkable_exercise(user.id)
    user_data[user.id]['current_exercise'] = exercise
    
    exercise_text = f"🎯 {exercise['type'].upper()} EXERCISE\n"
    exercise_text += f"📝 {exercise['instructions']}\n\n"
    exercise_text += f"{exercise['content']}"
    
    await update.message.reply_text(exercise_text)
    
    # Set state to wait for answer
    return WAITING_ANSWER

async def handle_exercise_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's exercise answer"""
    user = update.message.from_user
    user_answer = update.message.text

    # If user sends a navigation command while answering, route to navigation to avoid loops
    navigation_buttons = {
        "🎯 Next Exercise",
        "🎯 Start Lesson",
        "💬 AI Conversation",
        "📊 My Statistics",
        "📚 My Progress",
        "🏠 Main Menu",
        "📚 Back to Lessons",
        "/start_lesson",
    }
    if user_answer in navigation_buttons:
        return await handle_lesson_navigation(update, context)
    
    if user.id not in user_data or 'current_exercise' not in user_data[user.id]:
        await update.message.reply_text("Please start a lesson with /start_lesson first.")
        return LESSON
    
    exercise = user_data[user.id]['current_exercise']
    
    # Check answer (offload potential heavy checks)
    loop = asyncio.get_running_loop()
    is_correct, feedback = await loop.run_in_executor(None, functools.partial(exercise['check_function'], user_answer, exercise['correct_answers']))
    
    # Update progress
    if 'progress' not in user_data[user.id]:
        user_data[user.id]['progress'] = {'completed': 0, 'correct': 0}
    
    user_data[user.id]['progress']['completed'] += 1
    if is_correct:
        user_data[user.id]['progress']['correct'] += 1
    
    # Send feedback
    await update.message.reply_text(feedback)
    
    # Show statistics
    progress = user_data[user.id]['progress']
    accuracy = (progress['correct'] / progress['completed']) * 100 if progress['completed'] > 0 else 0
    
    stats_text = f"\n📊 Your progress: {progress['correct']}/{progress['completed']} correct ({accuracy:.1f}% accuracy)"
    await update.message.reply_text(stats_text)
    
    # Suggest next action
    keyboard = [
        ["🎯 Next Exercise", "💬 AI Conversation"],
        ["📊 My Statistics", "📚 My Progress"],
        ["🏠 Main Menu"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "What would you like to do next?",
        reply_markup=reply_markup
    )
    
    return LESSON

async def handle_lesson_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Navigate lesson menu"""
    text = update.message.text
    user = update.message.from_user
    
    if text == "🎯 Start Lesson" or text == "🎯 Next Exercise":
        return await start_lesson(update, context)
    elif text in {"💬 AI Conversation", "💬 New Conversation"}:
        return await start_conversation_mode(update, context)
    elif text == "📊 My Statistics" or text == "📊 Statistics":
        return await show_stats(update, context)
    elif text == "📚 My Progress":
        return await show_progress(update, context)
    elif text == "📚 Back to Lessons":
        return await start_lesson(update, context)
    elif text == "🏠 Main Menu":
        await update.message.reply_text(
            "Returning to main menu. Use /start_lesson to begin a new lesson.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Please use the buttons to navigate.")
        return LESSON

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics"""
    user_id = update.message.from_user.id
    if user_id not in user_data or 'progress' not in user_data[user_id]:
        await update.message.reply_text("You don't have any statistics yet.")
        return LESSON
    
    progress = user_data[user_id]['progress']
    accuracy = (progress['correct'] / progress['completed']) * 100 if progress['completed'] > 0 else 0
    
    conversation_history = user_data[user_id].get('conversation_history', [])
    conversation_messages = len([msg for msg in conversation_history if msg['role'] == 'user'])
    
    await update.message.reply_text(
        f"📊 Your statistics:\n\n"
        f"✅ Exercises completed: {progress['completed']}\n"
        f"🎯 Correct answers: {progress['correct']}\n"
        f"📈 Accuracy: {accuracy:.1f}%\n"
        f"💬 Conversation messages: {conversation_messages}"
    )
    return LESSON

async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show learning progress"""
    user_id = update.message.from_user.id
    if user_id not in user_data:
        await update.message.reply_text("Please register first using /start")
        return LESSON
    
    progress = user_data[user_id].get('progress', {'completed': 0, 'correct': 0})
    lessons_completed = progress.get('completed', 0)
    correct_answers = progress.get('correct', 0)
    accuracy = (correct_answers / lessons_completed * 100) if lessons_completed > 0 else 0
    
    await update.message.reply_text(
        f"📊 Your learning progress:\n\n"
        f"✅ Completed exercises: {lessons_completed}\n"
        f"🎯 Correct answers: {correct_answers}\n"
        f"📈 Accuracy: {accuracy:.1f}%\n"
        f"🎯 Current level: {user_data[user_id].get('current_level', 'Not defined')}\n"
        f"🎯 Target level: {user_data[user_id].get('target_level', 'Not defined')}"
    )
    return LESSON

async def show_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's study plan (re-generate to ensure weekly LLM plan)."""
    user_id = update.message.from_user.id

    if user_id not in user_data:
        await update.message.reply_text("Please register first using /start")
        return

    # Always regenerate to reflect latest profile and ensure LLM weekly plan (offload blocking generation)
    loop = asyncio.get_running_loop()
    plan = await loop.run_in_executor(None, functools.partial(generate_study_plan, user_id))
    user_data[user_id]['plan'] = plan
    plan_text = format_plan(plan)

    await update.message.reply_text(
        f"📋 <b>Your Study Plan:</b>\n\n{plan_text}",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

async def show_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's learning schedule"""
    user_id = update.message.from_user.id
    
    if user_id not in user_data:
        await update.message.reply_text("Please register first using /start")
        return
    
    schedule_days = user_data[user_id].get('schedule_days', [])
    schedule_time = user_data[user_id].get('schedule_time', 'Not set')
    
    if not schedule_days:
        await update.message.reply_text("You don't have a learning schedule yet. Please complete the setup using /start")
        return
    
    schedule_text = f"📅 **Your Learning Schedule:**\n\n"
    schedule_text += f"📆 Study days: {', '.join(schedule_days)}\n"
    schedule_text += f"⏰ Reminder time: {schedule_time}\n\n"
    
    # Add progress info
    progress = user_data[user_id].get('progress', {'completed': 0, 'correct': 0})
    if progress['completed'] > 0:
        accuracy = (progress['correct'] / progress['completed']) * 100
        schedule_text += f"📊 **Recent Progress:**\n"
        schedule_text += f"✅ Exercises completed: {progress['completed']}\n"
        schedule_text += f"🎯 Accuracy: {accuracy:.1f}%\n"
    
    await update.message.reply_text(schedule_text)

async def show_vocabulary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's vocabulary"""
    user_id = update.message.from_user.id
    
    if user_id not in vocabulary_storage or not vocabulary_storage[user_id]:
        await update.message.reply_text("📚 Your vocabulary is empty. Start conversations or exercises to build your vocabulary!")
        return
    
    words = list(vocabulary_storage[user_id])
    words.sort()  # Sort alphabetically
    
    vocab_text = f"📚 **Your Vocabulary ({len(words)} words):**\n\n"
    
    # Show words in groups of 10
    for i in range(0, min(len(words), 50), 10):  # Show max 50 words
        group = words[i:i+10]
        vocab_text += f"**{i+1}-{i+len(group)}:** {', '.join(group)}\n"
    
    if len(words) > 50:
        vocab_text += f"\n... and {len(words) - 50} more words!"
    
    vocab_text += f"\n\n💡 **Tip:** Keep practicing conversations to learn new words!"
    
    await update.message.reply_text(vocab_text)

async def generator_prompt_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set or show the LLM content generation prompt for this user."""
    user_id = update.message.from_user.id
    args = context.args if hasattr(context, 'args') else []
    if args:
        prompt_text = " ".join(args).strip()
        if user_id not in user_data:
            user_data[user_id] = {}
        user_data[user_id]['generation_prompt'] = prompt_text
        await update.message.reply_text("✅ Content generation prompt saved. Future conversation starters and exercises will use it.")
        return

    current = user_data.get(user_id, {}).get('generation_prompt')
    if current:
        await update.message.reply_text(
            "Your current generator prompt:\n\n" + current + "\n\nUse /generator_prompt <your prompt> to change it."
        )
    else:
        await update.message.reply_text(
            "No custom generator prompt set. Using default.\n\n"
            "Set one with:\n/generator_prompt You are an ESL tutor focusing on business English with short tasks."
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help information"""
    help_text = """
📚 Available commands:

/start - Start working with the bot
/help - Show this help
/conversation - Start AI conversation
/lesson - Start a lesson
/progress - Show your progress
/stats - Show statistics
/plan - Show your study plan
/schedule - Show your learning schedule
/vocabulary - Show your vocabulary
/generator_prompt <prompt> - Set the LLM content generation prompt

🎯 Features:
• AI-powered conversation practice with grammar feedback
• Interactive exercises (LLM-generated when available)
• Voice message support
• Grammar checking
• Progress tracking
• Personalized learning plans
• Vocabulary building
    """
    await update.message.reply_text(help_text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel current conversation"""
    user = update.message.from_user
    logger.info(f"User {user.first_name} canceled the conversation.")
    
    await update.message.reply_text(
        "Bye! I hope we can talk again some day.", reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END

def generate_study_plan(user_id):
    """Generate a detailed weekly study plan using LLM; fallback to static if unavailable."""
    data = user_data[user_id]

    # Base plan meta
    plan = {
        "goal": data.get('goal', ''),
        "current_level": data.get('current_level', ''),
        "target_level": data.get('target_level', ''),
        "timeframe": data.get('timeframe', "6 months"),
    }

    # Try LLM for Markdown weekly plan
    if llm_client and llm_client.is_available():
        timeframe = plan["timeframe"]
        # Rough weeks estimation from timeframe (months * 4)
        import re as _re
        m = _re.search(r"(\d+)", str(timeframe))
        weeks_hint = None
        if m:
            months = int(m.group(1))
            if "month" in str(timeframe).lower():
                weeks_hint = months * 4
        profile = build_user_profile_prompt(user_id)
        base_prompt = user_data[user_id].get('generation_prompt') or DEFAULT_GENERATOR_PROMPT
        prompt = (
            f"{base_prompt}\n\n{profile}\n\n"
            f"{STUDY_PLAN_PROMPT}\n"
            f"Если указаны месяцы, сделай план на ~{weeks_hint or '8-16'} недель. "
            f"Сначала добавь раздел 'Общий подход и рекомендации на весь период', затем таблицу по неделям."
        )
        text = llm_client.generate(prompt, max_new_tokens=900, temperature=0.7)
        if text:
            plan["llm_plan_markdown"] = text
            return plan

    # Fallback static plan if LLM not available: build HTML suitable for Telegram
    timeframe = plan.get("timeframe", "3 months")
    weeks_count = 12
    try:
        import re as _re2
        m2 = _re2.search(r"(\d+)", str(timeframe))
        if m2 and "month" in str(timeframe).lower():
            weeks_count = int(m2.group(1)) * 4
            weeks_count = max(8, min(weeks_count, 24))
    except Exception:
        pass

    grammar_topics = [
        "Повторение основ и диагностика ошибок",
        "Present Simple vs. Present Continuous",
        "Past Simple vs. Present Perfect",
        "Future forms (will / going to / Present Continuous)",
        "Модальные глаголы (can, could, must, have to)",
        "Пассивный залог (Present/Past)",
        "Относительные предложения (who/which/that)",
        "Степени сравнения прилагательных и наречий",
        "Условные предложения (0, 1, 2 тип)",
        "Reported Speech (косвенная речь)",
        "Фразовые глаголы и коллокации",
        "Итоговая неделя: систематизация и практика"
    ]

    vocab_themes = [
        "Путешествия и транспорт",
        "Работа и карьерa",
        "Учёба и навыки",
        "Здоровье и спорт",
        "Технологии и интернет",
        "Культура и традиции",
        "Окружающая среда",
        "Медиа и развлечения",
        "Отношения и общение",
        "Город и инфраструктура",
        "Бизнес и финансы (основы)",
        "Повторение/обобщение"
    ]

    table_lines = []
    table_lines.append("| Неделя | Грамматика | Лексика и тема | Аудирование/Чтение | Письмо/Говорение (активная практика) |")
    table_lines.append("|-------:|------------|----------------|---------------------|--------------------------------------|")
    for w in range(1, weeks_count + 1):
        g = grammar_topics[(w - 1) % len(grammar_topics)]
        v = vocab_themes[(w - 1) % len(vocab_themes)]
        listening = "2 коротких материала (10–15 мин): заметки + 3 ключевые идеи"
        writing = "2 задания: 1 мини‑эссе (120–150 слов) + 1 устный ответ (5–7 предложений)"
        table_lines.append(f"| {w} | {g} | {v} | {listening} | {writing} |")

    html_lines = []
    html_lines.append("<b>Общий подход и рекомендации на весь период</b>")
    html_lines.append("• 4–5 коротких занятий в неделю по 25–35 минут (лучше каждый день понемногу).")
    html_lines.append("• Чередуйте навыки: чтение/аудирование — письмо/говорение — грамматика — лексика.")
    html_lines.append("• В конце недели — мини‑рефлексия: 3 новых слова, 1 грамматическая тема, 1 сильная сторона, 1 зона роста.")
    html_lines.append("• Отслеживайте прогресс в боте: выполняйте упражнения и ведите словарь новых слов.")
    html_lines.append("")
    html_lines.append("<b>План по неделям</b>")
    html_lines.append("<pre>")
    html_lines.extend(table_lines)
    html_lines.append("</pre>")

    plan["llm_plan_html"] = "\n".join(html_lines)
    return plan

def format_plan(plan):
    """Format plan for display in Telegram HTML. Prefer HTML, safely show Markdown if present."""
    # Prefer prebuilt HTML
    if plan.get('llm_plan_html'):
        return plan['llm_plan_html']

    # If only Markdown is available (e.g., from LLM), show it in a pre block, HTML-escaped
    if plan.get('llm_plan_markdown'):
        try:
            return "<pre>" + _html.escape(plan['llm_plan_markdown']) + "</pre>"
        except Exception:
            return plan['llm_plan_markdown']

    # Minimal HTML fallback
    lines = []
    lines.append(f"<b>Цель:</b> {_html.escape(plan.get('goal',''))}")
    lines.append(f"<b>Уровень:</b> {_html.escape(plan.get('current_level',''))} → {_html.escape(plan.get('target_level',''))}")
    lines.append(f"<b>Срок:</b> {_html.escape(plan.get('timeframe',''))}")
    approach = plan.get('learning_approach')
    if approach:
        lines.append(f"<b>Подход:</b> {_html.escape(approach)}")
    features = plan.get('features', [])
    if features:
        lines.append("<b>Особенности:</b>")
        for f in features:
            lines.append("• " + _html.escape(f))
    return "\n".join(lines)

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Send lesson reminder"""
    job = context.job
    user_id = job.data
    
    if user_id in user_data and not user_data[user_id].get('paused', False):
        await context.bot.send_message(
            chat_id=user_id,
            text="📚 Time for your English lesson! Ready to practice? 🎯",
            reply_markup=ReplyKeyboardMarkup([
                ["🎯 Start Lesson", "💬 AI Conversation"],
                ["⏰ Skip Today", "⏸️ Pause Learning"]
            ], resize_keyboard=True)
        )

def main() -> None:
    """Start the bot"""
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is required")
        return
        
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Setup conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_goal)],
            CURRENT_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_current_level)],
            TARGET_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_target_level)],
            TIMEFRAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_timeframe)],
            PLAN_APPROVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_plan_approval)],
            SCHEDULE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_schedule_days)],
            SCHEDULE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_schedule_time)],
            LESSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_lesson_navigation)],
            WAITING_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exercise_answer)],
            CONVERSATION_MODE: [MessageHandler((filters.TEXT | filters.VOICE) & ~filters.COMMAND, handle_conversation_message)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    application.add_handler(conv_handler)
    
    # Add additional command handlers
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("conversation", start_conversation_mode))
    application.add_handler(CommandHandler("lesson", start_lesson))
    application.add_handler(CommandHandler("progress", show_progress))
    application.add_handler(CommandHandler("stats", show_stats))
    application.add_handler(CommandHandler("plan", show_plan_command))
    application.add_handler(CommandHandler("schedule", show_schedule_command))
    application.add_handler(CommandHandler("vocabulary", show_vocabulary_command))
    application.add_handler(CommandHandler("generator_prompt", generator_prompt_command))
    
    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()
