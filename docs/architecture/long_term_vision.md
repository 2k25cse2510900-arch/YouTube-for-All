# Long-Term Architecture Specification: Content Pillars & AI Systems

> **Status**: Accepted Architecture Roadmap  
> **Project**: A Lesson With AI  
> **Date**: 2026-11-13  

---

## 1. Overview & Strategic Goals

**A Lesson With AI** is evolving to support two complementary content categories designed for high audience retention, intellectual curiosity, and emotional resonance in the YouTube Shorts format (under 60 seconds).

To scale production sustainably while preserving creator voice and factual integrity, the system architecture will decouple research, script synthesis, media generation, and video assembly into autonomous, human-supervised stages.

---

## 2. Content Pillars

### 2.1 Category 1: Anime + Real-World Science
- **Core Concept**: Use popular anime characters, situations, power systems, or memorable plot moments as conceptual hooks, immediately bridging them into genuine real-world science, mathematics, psychology, technology, or history.
- **Exemplar**: *Chronobiology & Stasis Fiction* — Analyzing the neurological plausibility and mathematical reality of maintaining consciousness and counting seconds continuously across vast time horizons in cryogenic stasis.
- **Architectural Rules**:
  1. **Strict Verification**: Every scientific, mathematical, or empirical claim must be cross-verified before inclusion in any script. Hallucinated or speculative science is strictly banned.
  2. **Canon vs. Reality Demarcation**: Explicitly differentiate between fictional story mechanics and verifiable scientific principles.
  3. **High-Impact Pacing**: Hook with the fictional concept in seconds 0–3, pivot to the real-world science in seconds 4–15, deliver the surprising takeaway in seconds 16–45, and conclude with a thought-provoking call to reflection in seconds 46–55.

### 2.2 Category 2: Motivational & Meaningful Storytelling
- **Core Concept**: Original, emotionally evocative short stories exploring timeless psychological and philosophical themes: patience, discipline, ego, quiet perseverance, ambition, compound growth, and self-belief.
- **Exemplar**: The metaphor of the Chinese bamboo tree or root system—spending years developing unseen underground roots before visible exponential surface growth.
- **Architectural Rules**:
  1. **Original Narratives**: While visual treatments or thematic archetypes may be inspired by anime aesthetics (e.g., intense focus, inner dialogue, quiet discipline reminiscent of striving tacticians), the stories and allegories must remain original creative compositions.
  2. **Emotional & Psychological Depth**: Focus on visceral human truths, addressing self-doubt, discipline over motivation, and compound effort.
  3. **Visual Allegory**: Design scripts with visual metaphors that pair seamlessly with 9:16 vertical cinematography.

---

## 3. Future AI Research & Generation Architecture

```
                    ┌───────────────────────────────────┐
                    │      Creator Manual Batches       │
                    │   (10-15 Day High-Quality Scripts) │
                    └─────────────────┬─────────────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │   Approved Script DB   │
                         │    & Style Library     │
                         └────────────┬───────────┘
                                      │
                 ┌────────────────────┴────────────────────┐
                 │ (Few-Shot / Retrieval Context)          │
                 ▼                                         ▼
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│     Gemini Research Engine      │       │     AI Script Generator         │
│  - Anime lore & fact search     │       │  - Dual-category style prompts  │
│  - Scientific claim checking    │──────▶│  - Structure & hook matching    │
│  - Truth & source validation    │       │  - Pacing & duration constraints│
└─────────────────────────────────┘       └────────────────┬────────────────┘
                                                           │
                                                           ▼
                                          ┌─────────────────────────────────┐
                                          │      HUMAN APPROVAL GATE 1      │
                                          │ (Approve / Edit / Reject Script)│
                                          └────────────────┬────────────────┘
                                                           │
                                                           ▼
                                          ┌─────────────────────────────────┐
                                          │   Modular Production Pipeline   │
                                          │  Audio ➔ Visuals ➔ Assembly     │
                                          └────────────────┬────────────────┘
                                                           │
                                                           ▼
                                          ┌─────────────────────────────────┐
                                          │      HUMAN APPROVAL GATE 2      │
                                          │ (Approve / Review Final Video)  │
                                          └────────────────┬────────────────┘
                                                           │
                                                           ▼
                                          ┌─────────────────────────────────┐
                                          │   YouTube Scheduler / Upload    │
                                          └─────────────────────────────────┘
```

### 3.1 Google Gemini API Integration Plan
When entering the AI Research phase, Google's Gemini API will be integrated through a dedicated module (`src/research_engine/`):
- **Fact-Checking & Claim Verification**: Submitting scientific claims through structured multi-source verification prompts to eliminate scientific misinformation.
- **Anime Fact Checking**: Validating character names, arc references, and canonical facts to maintain absolute credibility with anime audiences.
- **Idea & Angle Ideation**: Generating alternative hooks, metaphors, and punchlines for approved themes.
- **Multimodal Visual Asset Generation**: Utilizing supported Gemini image/visual capabilities for concept generation where suitable.
- **Pre-requisite Checks**: Quota availability, response latency, token costs, and safety filter configurations must be audited prior to module activation.

### 3.2 Script Generation & Style Learning Strategy
To ensure generated scripts match the creator's exact voice and tone:
1. **Script Repository & Metadata Tagging**:
   - Manually provided scripts from the initial 10–15 day batches will be categorized (`anime_science` vs. `motivational_story`) and stored with performance annotations.
2. **Retrieval-Augmented Generation (RAG) & Few-Shot Prompting**:
   - Instead of premature model fine-tuning, the script generator will dynamically inject approved exemplar scripts into prompts as style references.
   - This approach ensures immediate adherence to rhythm, sentence structure, hook length, and rhetorical devices without requiring thousands of training samples.
3. **Transition to Fine-Tuning**:
   - Fine-tuning will be evaluated only after amassing a curated dataset of at least 50–100+ approved and published scripts with proven audience retention metrics.
4. **Trigger Condition**:
   - The AI generation system activates automatically as a fallback when the manual script queue falls below a defined buffer (e.g., 3 days remaining).

---

## 4. Non-Negotiable Engineering Rules

1. **Human Approval Throughout**:
   - Gate 1: No AI-generated script enters production without creator sign-off.
   - Gate 2: No assembled video is published to YouTube without creator sign-off.
2. **Absolute Module Decoupling**:
   - Research, script writing, voice synthesis, image generation, video compositing, QA, and YouTube scheduling must remain strictly separate packages with clear interfaces.
3. **No Unverified Claims**:
   - If a scientific fact cannot be independently verified, the script must be rejected or rewritten.
4. **Credential Security**:
   - Zero hardcoding of API keys or Google OAuth secrets. All configurations remain managed via `.env` and local secure stores.
5. **No Speculative Implementation**:
   - Architectural requirements are documented here; implementation of these future modules will commence sequentially in their respective planned phases.
