# Hinglish Voice Engine: Architectural Specification & Guide
## Project: A Lesson With AI
**Version:** 3.0 (Language-Aware Indian Hinglish Architecture)  
**Status:** Implemented & Verified  
**Default Voice:** `hi-IN-MadhurNeural` (Neural Multi-Lingual Hindi Male)  
**Cost Ceiling:** Strict ₹0.00 (Zero-Cost Continuous Production)  
**Sample Rate Standard:** 48,000 Hz Stereo 16-bit PCM WAV / AAC  

---

## 1. System Overview

The **Language-Aware Indian Hinglish Voice Engine** transforms raw Romanized, Devanagari, and mixed Hinglish script narration into expressive, natural, human-like Indian speech. 

Unlike conventional TTS systems that treat all Latin tokens as US English or apply mechanical pauses, the rebuilt engine operates with deep awareness of Indian phonology:
1. **Indian Hindi Phonology**: Native dental stops, retroflex consonants, and correct schwa deletion.
2. **Indian English Phonology**: Replaces American rhotic vowels and broad vowels with authentic Indian English monophthongs (`[eː]`, `[oː]`, `[ɔː]`) and retroflex stops (`[ʈ]`, `[ɖ]`).
3. **Unified Acoustic Space Code-Switching**: Eliminates vocoder language-switching latency, timbre shifts, and pitch jumps by compiling Hindi and English into an aligned Indian phonetic representation.
4. **Syllable-Timed Rhythm**: Preserves distinct syllable durations without American-English vowel swallowing.
5. **Dual-Layer Alignment**: Acoustic models receive the phonetically optimized speech representation, while subtitle generators receive the exact creator-approved script words aligned down to millisecond precision.

---

## 2. Core Architecture Pipeline

```
┌────────────────────────────────────────────────────────────────────────┐
│                      Storyboard Script Narration                       │
│    "Square-Cube Law ke mutaabiq colossal structure par stress padega"  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 1. LanguageAwarePronunciationEngine (`HinglishTextProcessor`)          │
│  - Token Classification: Devanagari, Roman Hindi, English Loanword,    │
│    Technical Term, Number/Unit                                         │
│  - Multiplier & Formula Expansion: "40,000x" -> "40,000 गुना",         │
│    "A ∝ L²" -> "Area proportional to L square"                         │
│  - Authentic Indian English Phonetics:                                 │
│    "Square-Cube Law" -> "स्क्वेयर-क्यूब लॉ", "Colossus" -> "कोलोसस",   │
│    "Volume" -> "वॉल्यूम", "Weight" -> "वेट", "Physics" -> "फ़िज़िक्स"   │
│  - Roman Hindi Transliteration: "jabki" -> "जबकि", "wazan" -> "वज़न"   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. ProsodyController & EmotionController                               │
│  - 9 Delivery Styles: CURIOUS, EDUCATIONAL, EXCITED, SURPRISE,         │
│    SERIOUS, DRAMATIC, EMOTIONAL, CONVERSATIONAL, CALM                  │
│  - Semantic intonation inference (rising question lilts, contrastive   │
│    clause pauses, cadential falling terminal pitch)                    │
│  - Syllable-timed cadence with natural breathing intervals             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. Voice Provider (`EdgeTTSVoiceProvider`)                             │
│  - hi-IN-MadhurNeural neural synthesis in unified phonetic space       │
│  - WordBoundary streaming event capture (100ns precision)              │
│  - Bidirectional boundary alignment back to original script tokens     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 4. AudioContinuityProcessor                                            │
│  - PCM silence trimming (removes dead air, preserves 50ms anti-pop pad)│
│  - Inter-scene natural breathing bridge (220ms cadence)                │
│  - EBU R128 Loudness Normalization (-16.0 LUFS, -1.5 dBFS true peak)   │
│  - Resampled to broadcast standard 48,000 Hz 16-bit PCM WAV            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 5. VoiceQualityChecker                                                 │
│  - Automated acoustic QA: WPM pacing, clipping, silence run ratio      │
│  - Pre-assembly validation gate generating structured VoiceQualityReport│
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Details

### 3.1 PronunciationDictionary (`src/audio_engine/pronunciation_dictionary.py`)
- **Structured Storage**: `src/audio_engine/data/pronunciation_dict.json` holds:
  1. `hindi_roman_to_devanagari`: 250+ Roman Hindi words mapped to canonical Devanagari.
  2. `english_to_indian_phonetics`: 100+ English loanwords, technical concepts, and anime character names mapped to Indian English phonetics.
  3. `devanagari_phonetic_fixes`: Targeted adjustments for neural vocoder acoustic clarity.
  4. `custom_overrides`: Runtime creator overrides.
- **Dedicated Lookups**:
  - `lookup_indian_phonetic(word)`: Retrieves authentic Indian English phonetic representation.
  - `lookup_hindi_devanagari(word)`: Retrieves canonical Devanagari representation.
  - `lookup_compound(phrase)`: Matches multi-word technical units (*e.g.*, *Square-Cube Law*, *The Science of Giants*).

### 3.2 HinglishTextProcessor (`src/audio_engine/hinglish_processor.py`)
- Categorizes tokens via `classify_token` into `LanguageCategory`.
- Expands formulas, exponents, multipliers, and units into natural spoken Indian Hinglish.
- Bridges speech synthesis and subtitle synchronization via `align_boundaries()`.

### 3.3 Prosody & Emotion Controller (`src/audio_engine/prosody.py`)
Supports 9 distinct delivery styles:

| Delivery Style | Rate | Pitch | Clause Pause | Intended Context |
|---|---|---|---|---|
| **`CURIOUS`** | `+4%` | `+4Hz` | 180ms | Opening question hooks (*"Kya 60-meter lamba Colossus...?"*) |
| **`EDUCATIONAL`** | `-1%` | `+0Hz` | 220ms | Scientific scaling explanations & physical laws |
| **`EXCITED`** | `+12%` | `+6Hz` | 140ms | Dynamic high-energy anime hooks and transitions |
| **`SURPRISE`** | `+8%` | `+6Hz` | 150ms | Astonishing facts and dramatic reveals (*"Sochiye agar..."*) |
| **`DRAMATIC`** | `-6%` | `-5Hz` | 280ms | Structural collapse & bone failure climaxes |
| **`SERIOUS`** | `-4%` | `-4Hz` | 240ms | Authoritative warnings & physiological limits |
| **`CONVERSATIONAL`** | `+3%` | `+1Hz` | 170ms | Friendly takeaways, outros, and anime comparisons |
| **`EMOTIONAL`** | `+1%` | `+2Hz` | 200ms | Storytelling and reflective moments |
| **`CALM`** | `-2%` | `-1Hz` | 220ms | Measured, patient instructional pacing |

---

## 4. Empirical Benchmark Suite (`src/audio_engine/benchmark.py`)

A comprehensive 30-sentence benchmark corpus is maintained and continuously tested:
- **Corpus Size**: 30 sentences spanning Devanagari Hindi, Roman Hindi, Indian English, Mixed Hinglish, Pop-Culture, and Inquisitive Hooks.
- **Regression Words**: Evaluates specific target words: `जबकि`, `Colossal`, `Colossus`, `Square-Cube Law`, `Volume`, `Weight`, `Muscles`, `Physics`, `Science`.
- **Pass Rate**: 30/30 (100%) passing automated acoustic QA.
- **Audio Deliverables**: Stored as 48,000 Hz broadcast WAVs in `assets/audio/benchmark_hinglish/bench_*.wav`.
- **Benchmark Report**: Documented in `docs/reports/voice_engine_benchmark_report.md`.
