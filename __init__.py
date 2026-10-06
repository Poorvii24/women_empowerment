"""
ISIS NLP Engine
===============
A self-contained, embedding-based semantic skill matching pipeline that runs
alongside (not instead of) the Gemini integration.

Full pipeline (raw text -> career mapping):
    raw text
      -> preprocessing.clean_text()                  [hygiene]
      -> text_pipeline.tokenize()                    [tokenization]
      -> text_pipeline.remove_stopwords()/lemmatize() [normalization]
      -> text_pipeline.extract_noun_phrases()        [keyphrase candidates]
      -> keyphrase_extractor.extract_keyphrases()     [keyphrase ranking]
      -> feature_representation.tfidf_similarity_to_skills()  [TF-IDF features]
      -> embedding_engine.encode() + similarity.cosine_similarity()  [semantic features]
      -> skill_matcher.analyze_activity_semantic()    [hybrid skill matching]
      -> app.py / services/role_taxonomy.py           [career mapping]

Modules:
    preprocessing.py         – text cleaning + phrase splitting for explainability
    text_pipeline.py         – tokenization, stopword removal, POS tagging,
                                lemmatization, noun-phrase candidate generation
    feature_representation.py– TF-IDF vectorization + cosine similarity ("Converting
                                Text to Features", NLP syllabus Unit III)
    keyphrase_extractor.py   – POS-candidate + TF-IDF-ranked keyphrase extraction
                                (NLP syllabus Unit V)
    embedding_engine.py      – lazy-loaded, cached SentenceTransformer wrapper
    similarity.py            – cosine similarity + confidence scoring (pure numpy)
    skill_matcher.py         – builds/caches the skill knowledge base (embeddings +
                                TF-IDF) and performs hybrid semantic+lexical matching
                                against user activity text

This package has no dependency on Flask or app.py, so it can be imported,
unit-tested, and reasoned about independently of the web layer.
"""
