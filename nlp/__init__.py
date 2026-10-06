"""
ISIS NLP Engine
===============
A self-contained, embedding-based semantic skill matching pipeline that runs
alongside (not instead of) the Gemini integration.

Modules:
    preprocessing.py     – text cleaning + phrase splitting for explainability
    embedding_engine.py  – lazy-loaded, cached SentenceTransformer wrapper
    similarity.py        – cosine similarity + confidence scoring (pure numpy)
    skill_matcher.py      – builds/caches the skill embedding knowledge base and
                            performs semantic matching against user activity text

This package has no dependency on Flask or app.py, so it can be imported,
unit-tested, and reasoned about independently of the web layer.
"""
